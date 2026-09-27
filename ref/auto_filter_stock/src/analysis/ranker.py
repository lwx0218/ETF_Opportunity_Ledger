"""Stock ranking service for final scoring and ranking based on multiple criteria."""

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import json

from loguru import logger

from src.config.settings import get_settings
from src.config.parameters import ScreeningParams
from src.models.stock import Stock
from src.models.trading_volume import TradingVolume
from src.models.market_heat import MarketHeat
from src.models.momentum_score import MomentumScore
from src.models.screening_result import ScreeningResult


@dataclass
class RankingWeights:
    """Weights for different ranking criteria."""
    volume_weight: float = 0.25
    heat_weight: float = 0.25
    momentum_weight: float = 0.35
    quality_weight: float = 0.15
    
    def validate(self) -> bool:
        """Validate that weights sum to 1.0."""
        total = (self.volume_weight + self.heat_weight + 
                self.momentum_weight + self.quality_weight)
        return abs(total - 1.0) < 0.001
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary."""
        return {
            "volume_weight": self.volume_weight,
            "heat_weight": self.heat_weight,
            "momentum_weight": self.momentum_weight,
            "quality_weight": self.quality_weight
        }


@dataclass
class RankingResult:
    """Result of stock ranking operation."""
    success: bool
    ranked_stocks: List[ScreeningResult]
    ranking_methodology: str
    weights_used: RankingWeights
    processing_time: float
    error: Optional[str] = None


@dataclass
class StockMetrics:
    """Comprehensive metrics for a single stock."""
    symbol: str
    name: str
    volume_rank: Optional[int]
    volume_score: float
    heat_rank: Optional[int]
    heat_score: float
    momentum_score: float
    momentum_rank: Optional[int]
    quality_score: float
    combined_score: float
    final_rank: int
    # Raw data objects for detailed export
    volume_data: Optional[TradingVolume] = None
    heat_data: Optional[MarketHeat] = None
    momentum_data: Optional[MomentumScore] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "name": self.name,
            "volume_rank": self.volume_rank,
            "volume_score": self.volume_score,
            "heat_rank": self.heat_rank,
            "heat_score": self.heat_score,
            "momentum_score": self.momentum_score,
            "momentum_rank": self.momentum_rank,
            "quality_score": self.quality_score,
            "combined_score": self.combined_score,
            "final_rank": self.final_rank
        }


class StockRanker:
    """Service for ranking stocks based on multiple criteria with configurable weights."""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger.bind(service="StockRanker")
        
        # Default ranking weights
        self.default_weights = RankingWeights()
        
        # Quality thresholds
        self.min_momentum_r_squared = 0.3
        self.min_volume_threshold = 1000000  # 1M shares
        self.min_heat_score = 10.0
    
    def rank_stocks(
        self,
        stocks: List[Stock],
        trading_volumes: List[TradingVolume],
        market_heats: List[MarketHeat],
        momentum_scores: List[MomentumScore],
        top_n: int = 10,
        weights: Optional[RankingWeights] = None,
        ranking_date: Optional[date] = None
    ) -> RankingResult:
        """Rank stocks based on multiple criteria with configurable weights.
        
        Args:
            stocks: List of stock basic information
            trading_volumes: List of trading volume data
            market_heats: List of market heat data
            momentum_scores: List of momentum scores
            top_n: Number of top stocks to return
            weights: Custom ranking weights (uses defaults if None)
            ranking_date: Date for ranking (defaults to today)
            
        Returns:
            RankingResult with ranked stocks and methodology
        """
        start_time = datetime.now()
        
        if ranking_date is None:
            ranking_date = date.today()
            
        weights = weights or self.default_weights
        
        if not weights.validate():
            return RankingResult(
                success=False,
                ranked_stocks=[],
                ranking_methodology="",
                weights_used=weights,
                processing_time=(datetime.now() - start_time).total_seconds(),
                error="Invalid weights: must sum to 1.0"
            )
        
        self.logger.info(
            f"Ranking {len(stocks)} stocks with weights: {weights.to_dict()}"
        )
        
        try:
            # Build comprehensive metrics for each stock
            stock_metrics = self._build_stock_metrics(
                stocks, trading_volumes, market_heats, momentum_scores
            )
            
            if not stock_metrics:
                return RankingResult(
                    success=False,
                    ranked_stocks=[],
                    ranking_methodology="",
                    weights_used=weights,
                    processing_time=(datetime.now() - start_time).total_seconds(),
                    error="No valid stock metrics could be calculated"
                )
            
            # Calculate combined scores
            scored_stocks = self._calculate_combined_scores(stock_metrics, weights)
            
            # Sort by combined score (descending) and then by stock symbol (ascending) for stable sorting
            # This ensures consistent results when stocks have the same score
            ranked_stocks = sorted(scored_stocks, key=lambda x: (-x.combined_score, x.symbol))
            
            # Select top N stocks
            top_stocks = ranked_stocks[:top_n]
            
            # Convert to ScreeningResult objects
            screening_results = [
                self._create_screening_result(stock, rank + 1, weights, ranking_date)
                for rank, stock in enumerate(top_stocks)
            ]
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            # Create methodology description
            methodology = self._create_methodology_description(weights, top_n)
            
            self.logger.info(
                f"Stock ranking completed: {len(screening_results)} stocks ranked "
                f"in {processing_time:.3f}s"
            )
            
            return RankingResult(
                success=True,
                ranked_stocks=screening_results,
                ranking_methodology=methodology,
                weights_used=weights,
                processing_time=processing_time
            )
            
        except Exception as e:
            self.logger.error(f"Stock ranking failed: {e}")
            return RankingResult(
                success=False,
                ranked_stocks=[],
                ranking_methodology="",
                weights_used=weights,
                processing_time=(datetime.now() - start_time).total_seconds(),
                error=f"Ranking error: {str(e)}"
            )
    
    def _build_stock_metrics(
        self,
        stocks: List[Stock],
        trading_volumes: List[TradingVolume],
        market_heats: List[MarketHeat],
        momentum_scores: List[MomentumScore]
    ) -> List[StockMetrics]:
        """Build comprehensive metrics for each stock."""
        # Create lookup dictionaries
        stock_dict = {stock.symbol: stock for stock in stocks}
        volume_dict = {vol.stock_symbol: vol for vol in trading_volumes}
        heat_dict = {heat.stock_symbol: heat for heat in market_heats}
        momentum_dict = {ms.stock_symbol: ms for ms in momentum_scores}
        
        # Find common stocks across all data types
        all_symbols = set(stock_dict.keys())
        volume_symbols = set(volume_dict.keys())
        heat_symbols = set(heat_dict.keys())
        momentum_symbols = set(momentum_dict.keys())
        
        # Use intersection for most reliable results
        common_symbols = all_symbols.intersection(volume_symbols, heat_symbols, momentum_symbols)
        
        if not common_symbols:
            # Fall back to stocks with at least momentum scores
            common_symbols = momentum_symbols
            self.logger.warning("Using momentum-only stocks for ranking due to incomplete data")
        
        stock_metrics = []
        
        for symbol in common_symbols:
            try:
                stock = stock_dict.get(symbol)
                volume = volume_dict.get(symbol)
                heat = heat_dict.get(symbol)
                momentum = momentum_dict.get(symbol)
                
                # Calculate individual scores (0-100 scale)
                volume_score = self._calculate_volume_score(volume)
                heat_score = self._calculate_heat_score(heat)
                momentum_score_value = self._calculate_momentum_score(momentum)
                quality_score = self._calculate_quality_score(stock, momentum)
                
                # Get ranks where available
                volume_rank = volume.raw_volume_rank if volume and volume.raw_volume_rank else None
                heat_rank = heat.raw_heat_rank if heat and heat.raw_heat_rank else None
                momentum_rank = None  # Will be set during final ranking
                
                metrics = StockMetrics(
                    symbol=symbol,
                    name=stock.name if stock else symbol,
                    volume_rank=volume_rank,
                    volume_score=volume_score,
                    heat_rank=heat_rank,
                    heat_score=heat_score,
                    momentum_score=momentum_score_value,
                    momentum_rank=momentum_rank,
                    quality_score=quality_score,
                    combined_score=0.0,  # Will be calculated later
                    final_rank=0,  # Will be set later
                    volume_data=volume,
                    heat_data=heat,
                    momentum_data=momentum
                )
                
                stock_metrics.append(metrics)
                
            except Exception as e:
                self.logger.warning(f"Failed to build metrics for {symbol}: {e}")
                continue
        
        self.logger.info(f"Built metrics for {len(stock_metrics)} stocks")
        return stock_metrics
    
    def _calculate_volume_score(self, volume: Optional[TradingVolume]) -> float:
        """Calculate volume score (0-100 scale)."""
        if not volume:
            return 50.0  # Neutral score for missing data
        
        # Use normalized volume if available, otherwise use percentile
        if volume.normalized_volume is not None:
            return volume.normalized_volume * 100
        elif volume.volume_percentile is not None:
            return volume.volume_percentile
        else:
            # Fallback: basic volume-based scoring
            if volume.volume >= self.min_volume_threshold * 10:
                return 90.0
            elif volume.volume >= self.min_volume_threshold * 5:
                return 70.0
            elif volume.volume >= self.min_volume_threshold:
                return 50.0
            else:
                return 30.0
    
    def _calculate_heat_score(self, heat: Optional[MarketHeat]) -> float:
        """Calculate heat score (0-100 scale)."""
        if not heat:
            return 50.0  # Neutral score for missing data
        
        # Use normalized heat if available, otherwise use percentile
        if heat.normalized_heat is not None:
            return heat.normalized_heat * 100
        elif heat.heat_percentile is not None:
            return heat.heat_percentile
        else:
            # Fallback: basic heat-based scoring
            if heat.heat_score >= 80.0:
                return 90.0
            elif heat.heat_score >= 60.0:
                return 70.0
            elif heat.heat_score >= self.min_heat_score:
                return 50.0
            else:
                return 30.0
    
    def _calculate_momentum_score(self, momentum: Optional[MomentumScore]) -> float:
        """Calculate momentum score (0-100 scale)."""
        if not momentum:
            return 50.0  # Neutral score for missing data
        
        # Check if calculation is reliable
        if momentum.calculation_status != "COMPLETED" and momentum.calculation_status != "VALIDATED":
            return 30.0  # Low score for unreliable calculations
        
        # Use momentum score directly, but normalize if needed
        raw_score = abs(momentum.momentum_score)
        normalized_score = min(raw_score / 100, 100)  # Cap at 100
        
        # Adjust based on R-squared reliability
        reliability_factor = momentum.r_squared
        adjusted_score = normalized_score * reliability_factor
        
        return min(adjusted_score, 100.0)
    
    def _calculate_quality_score(self, stock: Optional[Stock], momentum: Optional[MomentumScore]) -> float:
        """Calculate quality score based on stock fundamentals and momentum reliability."""
        quality_factors = []
        
        # Stock fundamentals quality
        if stock:
            # Market cap quality (larger companies are generally more stable)
            if stock.market_cap >= 100_000_000_000:  # 100B+
                quality_factors.append(95.0)
            elif stock.market_cap >= 10_000_000_000:  # 10B+
                quality_factors.append(80.0)
            elif stock.market_cap >= 1_000_000_000:   # 1B+
                quality_factors.append(65.0)
            else:
                quality_factors.append(40.0)
            
            # Price stability (lower volatility is better)
            if abs(stock.price_change_percent) <= 5.0:
                quality_factors.append(85.0)
            elif abs(stock.price_change_percent) <= 10.0:
                quality_factors.append(70.0)
            else:
                quality_factors.append(50.0)
        
        # Momentum reliability quality
        if momentum:
            # R-squared quality
            if momentum.r_squared >= 0.7:
                quality_factors.append(95.0)
            elif momentum.r_squared >= 0.5:
                quality_factors.append(75.0)
            elif momentum.r_squared >= self.min_momentum_r_squared:
                quality_factors.append(55.0)
            else:
                quality_factors.append(25.0)
            
            # Calculation status quality
            if momentum.calculation_status == "VALIDATED":
                quality_factors.append(90.0)
            elif momentum.calculation_status == "COMPLETED":
                quality_factors.append(70.0)
            else:
                quality_factors.append(30.0)
        
        # Return average of quality factors, or neutral score if no factors
        return sum(quality_factors) / len(quality_factors) if quality_factors else 50.0
    
    def _calculate_combined_scores(
        self, 
        stock_metrics: List[StockMetrics], 
        weights: RankingWeights
    ) -> List[StockMetrics]:
        """Calculate combined scores using weighted averaging."""
        for metrics in stock_metrics:
            combined_score = (
                weights.volume_weight * metrics.volume_score +
                weights.heat_weight * metrics.heat_score +
                weights.momentum_weight * metrics.momentum_score +
                weights.quality_weight * metrics.quality_score
            )
            metrics.combined_score = combined_score
        
        return stock_metrics
    
    def _create_screening_result(
        self,
        metrics: StockMetrics,
        final_rank: int,
        weights: RankingWeights,
        ranking_date: date
    ) -> ScreeningResult:
        """Create ScreeningResult object from stock metrics."""
        # Create selection criteria
        criteria_dict = {
            "ranking_weights": weights.to_dict(),
            "ranking_date": ranking_date.isoformat(),
            "methodology": "multi_criteria_weighted_ranking"
        }
        
        # Extract detailed information from raw data
        volume_amount = metrics.volume_data.volume if metrics.volume_data else None
        heat_score_val = metrics.heat_data.heat_score if metrics.heat_data else None
        momentum_score_val = metrics.momentum_data.score if metrics.momentum_data else None
        trend_slope = metrics.momentum_data.trend_slope if metrics.momentum_data else None
        r_squared = metrics.momentum_data.r_squared if metrics.momentum_data else None
        trend_strength = metrics.momentum_data.trend_strength if metrics.momentum_data else None
        price_trend = metrics.momentum_data.price_trend if metrics.momentum_data else None
        
        return ScreeningResult(
            stock_symbol=metrics.symbol,
            stock_name=metrics.name,
            screening_date=ranking_date,
            volume_rank=metrics.volume_rank,
            heat_rank=metrics.heat_rank,
            momentum_rank=metrics.momentum_rank,
            combined_score=metrics.combined_score,
            final_ranking=final_rank,
            selection_criteria=json.dumps(criteria_dict),
            is_selected=True,
            volume_amount=volume_amount,
            heat_score=heat_score_val,
            momentum_score=momentum_score_val,
            trend_slope=trend_slope,
            r_squared=r_squared,
            trend_strength=trend_strength,
            price_trend=price_trend
        )
    
    def _create_methodology_description(self, weights: RankingWeights, top_n: int) -> str:
        """Create description of ranking methodology."""
        return (
            f"Multi-criteria weighted ranking using volume ({weights.volume_weight:.0%}), "
            f"heat ({weights.heat_weight:.0%}), momentum ({weights.momentum_weight:.0%}), "
            f"and quality ({weights.quality_weight:.0%}) factors. "
            f"Top {top_n} stocks selected based on combined scores."
        )
    
    def get_ranking_weights_presets(self) -> Dict[str, RankingWeights]:
        """Get predefined ranking weight presets."""
        return {
            "balanced": RankingWeights(0.25, 0.25, 0.35, 0.15),
            "momentum_focused": RankingWeights(0.15, 0.15, 0.55, 0.15),
            "volume_focused": RankingWeights(0.45, 0.15, 0.25, 0.15),
            "heat_focused": RankingWeights(0.15, 0.45, 0.25, 0.15),
            "quality_focused": RankingWeights(0.20, 0.20, 0.30, 0.30),
            "conservative": RankingWeights(0.30, 0.30, 0.25, 0.15),
            "aggressive": RankingWeights(0.10, 0.10, 0.60, 0.20)
        }
    
    def analyze_ranking_sensitivity(
        self,
        stock_metrics: List[StockMetrics],
        base_weights: RankingWeights,
        weight_variations: List[Tuple[str, RankingWeights]]
    ) -> Dict[str, Any]:
        """Analyze how rankings change with different weight configurations.
        
        Args:
            stock_metrics: Base stock metrics
            base_weights: Base/reference weights
            weight_variations: List of (name, weights) tuples to test
            
        Returns:
            Sensitivity analysis results
        """
        start_time = datetime.now()
        
        # Calculate base ranking with stable sorting
        base_scored = self._calculate_combined_scores(stock_metrics.copy(), base_weights)
        base_ranking = {m.symbol: i + 1 for i, m in enumerate(sorted(base_scored, key=lambda x: (-x.combined_score, x.symbol)))}
        
        # Test variations
        variations = {}
        for name, weights in weight_variations:
            try:
                varied_scored = self._calculate_combined_scores(stock_metrics.copy(), weights)
                varied_ranking = {m.symbol: i + 1 for i, m in enumerate(sorted(varied_scored, key=lambda x: (-x.combined_score, x.symbol)))}
                
                # Calculate ranking changes
                ranking_changes = {}
                for symbol in base_ranking:
                    base_rank = base_ranking[symbol]
                    varied_rank = varied_ranking.get(symbol, len(stock_metrics) + 1)
                    ranking_changes[symbol] = base_rank - varied_rank  # Positive means improved ranking
                
                variations[name] = {
                    "weights": weights.to_dict(),
                    "ranking": varied_ranking,
                    "ranking_changes": ranking_changes,
                    "top_stocks": list(varied_ranking.keys())[:10]
                }
                
            except Exception as e:
                self.logger.warning(f"Sensitivity analysis failed for {name}: {e}")
                continue
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return {
            "base_weights": base_weights.to_dict(),
            "base_ranking": base_ranking,
            "variations": variations,
            "analysis_time": processing_time,
            "stock_count": len(stock_metrics)
        }
    
    def generate_ranking_report(
        self,
        ranking_result: RankingResult,
        include_detailed_metrics: bool = True
    ) -> Dict[str, Any]:
        """Generate comprehensive ranking report.
        
        Args:
            ranking_result: Result from rank_stocks operation
            include_detailed_metrics: Whether to include detailed metrics breakdown
            
        Returns:
            Comprehensive ranking report
        """
        if not ranking_result.success:
            return {
                "success": False,
                "error": ranking_result.error,
                "generated_at": datetime.now().isoformat()
            }
        
        report = {
            "success": True,
            "generated_at": datetime.now().isoformat(),
            "methodology": ranking_result.ranking_methodology,
            "weights_used": ranking_result.weights_used.to_dict(),
            "processing_time": ranking_result.processing_time,
            "summary": {
                "total_stocks_ranked": len(ranking_result.ranked_stocks),
                "top_stock_score": ranking_result.ranked_stocks[0].combined_score if ranking_result.ranked_stocks else 0,
                "average_score": sum(sr.combined_score for sr in ranking_result.ranked_stocks) / len(ranking_result.ranked_stocks) if ranking_result.ranked_stocks else 0,
                "score_range": {
                    "min": min(sr.combined_score for sr in ranking_result.ranked_stocks) if ranking_result.ranked_stocks else 0,
                    "max": max(sr.combined_score for sr in ranking_result.ranked_stocks) if ranking_result.ranked_stocks else 0
                }
            },
            "top_stocks": []
        }
        
        # Add top stocks with details
        for i, screening_result in enumerate(ranking_result.ranked_stocks[:20]):  # Top 20
            stock_info = {
                "rank": i + 1,
                "symbol": screening_result.stock_symbol,
                "combined_score": screening_result.combined_score,
                "volume_rank": screening_result.volume_rank,
                "heat_rank": screening_result.heat_rank,
                "momentum_rank": screening_result.momentum_rank
            }
            
            if include_detailed_metrics:
                # Try to parse criteria for detailed metrics
                try:
                    criteria = json.loads(screening_result.selection_criteria)
                    stock_info["detailed_metrics"] = criteria
                except:
                    pass
            
            report["top_stocks"].append(stock_info)
        
        return report
    
    async def rank_stocks_async(
        self,
        stocks: List[Stock],
        trading_volumes: List[TradingVolume],
        market_heats: List[MarketHeat],
        momentum_scores: List[MomentumScore],
        top_n: int = 10,
        weights: Optional[RankingWeights] = None,
        ranking_date: Optional[date] = None
    ) -> RankingResult:
        """Async version of stock ranking."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.rank_stocks,
            stocks,
            trading_volumes,
            market_heats,
            momentum_scores,
            top_n,
            weights,
            ranking_date
        )