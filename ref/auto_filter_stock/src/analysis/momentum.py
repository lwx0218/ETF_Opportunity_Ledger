"""Momentum calculation service using linear regression for trend analysis."""

import numpy as np
import pandas as pd
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

from loguru import logger

from src.config.settings import get_settings
from src.models.momentum_score import MomentumScore, PriceTrend, TrendStrength, CalculationStatus


@dataclass
class MomentumResult:
    """Result of momentum calculation."""
    success: bool
    momentum_score: Optional[MomentumScore] = None
    error: Optional[str] = None
    calculation_time: float = 0.0
    data_points_used: int = 0


@dataclass
class PriceDataPoint:
    """Single price data point for momentum calculation."""
    date: date
    close_price: float
    volume: int
    
    def is_valid(self) -> bool:
        """Check if data point is valid for calculation."""
        return (self.close_price > 0 and 
                self.volume >= 0 and 
                isinstance(self.date, date))


class MomentumCalculator:
    """Service for calculating stock momentum using linear regression."""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger.bind(service="MomentumCalculator")
        
        # Default configuration
        self.min_data_points = 10  # Minimum data points required
        self.max_data_points = 60  # Maximum data points to use
        self.min_r_squared = 0.3   # Minimum R-squared for reliable trend
        
    def calculate_momentum(
        self,
        stock_symbol: str,
        price_data: List[Dict[str, Any]],
        period_days: int = 25,
        calculation_date: Optional[date] = None
    ) -> MomentumResult:
        """Calculate momentum score for a single stock.
        
        Args:
            stock_symbol: Stock symbol (e.g., "000001.SZ")
            price_data: List of price data points with 'date', 'close', 'volume'
            period_days: Number of days for momentum calculation
            calculation_date: Date of calculation (defaults to today)
            
        Returns:
            MomentumResult with calculated momentum score or error
        """
        start_time = datetime.now()
        
        if calculation_date is None:
            calculation_date = date.today()
            
        self.logger.info(f"Calculating momentum for {stock_symbol} over {period_days} days")
        
        try:
            # Validate input data
            validation_result = self._validate_price_data(price_data, period_days)
            if not validation_result["is_valid"]:
                return MomentumResult(
                    success=False,
                    error=validation_result["error"],
                    calculation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Filter and prepare data
            prepared_data = self._prepare_price_data(price_data, period_days, calculation_date)
            if not prepared_data:
                return MomentumResult(
                    success=False,
                    error="Insufficient valid price data after filtering",
                    calculation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Perform linear regression
            regression_result = self._perform_linear_regression(prepared_data)
            if not regression_result["success"]:
                return MomentumResult(
                    success=False,
                    error=regression_result["error"],
                    calculation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Create momentum score
            momentum_score = self._create_momentum_score(
                stock_symbol=stock_symbol,
                calculation_date=calculation_date,
                period_days=period_days,
                regression_result=regression_result,
                data_points_used=len(prepared_data)
            )
            
            calculation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(
                f"Momentum calculation completed for {stock_symbol}: "
                f"trend_slope={regression_result['slope']:.4f}, "
                f"r_squared={regression_result['r_squared']:.3f}, "
                f"score={momentum_score.momentum_score:.2f}, "
                f"time={calculation_time:.3f}s"
            )
            
            return MomentumResult(
                success=True,
                momentum_score=momentum_score,
                calculation_time=calculation_time,
                data_points_used=len(prepared_data)
            )
            
        except Exception as e:
            self.logger.error(f"Error calculating momentum for {stock_symbol}: {e}")
            return MomentumResult(
                success=False,
                error=f"Calculation error: {str(e)}",
                calculation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def _validate_price_data(
        self, 
        price_data: List[Dict[str, Any]], 
        period_days: int
    ) -> Dict[str, Any]:
        """Validate price data for momentum calculation."""
        if not price_data:
            return {"is_valid": False, "error": "No price data provided"}
        
        if len(price_data) < self.min_data_points:
            return {
                "is_valid": False, 
                "error": f"Insufficient data points: {len(price_data)} < {self.min_data_points}"
            }
        
        if period_days < 5 or period_days > 60:
            return {
                "is_valid": False,
                "error": f"Invalid period_days: {period_days}. Must be between 5 and 60"
            }
        
        return {"is_valid": True, "error": None}
    
    def _prepare_price_data(
        self,
        price_data: List[Dict[str, Any]],
        period_days: int,
        calculation_date: date
    ) -> List[PriceDataPoint]:
        """Prepare and filter price data for calculation."""
        # Convert to PriceDataPoint objects and validate
        valid_data = []
        for data_point in price_data:
            try:
                # Extract required fields
                data_date = data_point.get('date')
                close_price = float(data_point.get('close', 0))
                volume = int(data_point.get('volume', 0))
                
                # Handle different date formats
                if isinstance(data_date, str):
                    data_date = datetime.fromisoformat(data_date).date()
                elif isinstance(data_date, datetime):
                    data_date = data_date.date()
                
                price_point = PriceDataPoint(
                    date=data_date,
                    close_price=close_price,
                    volume=volume
                )
                
                if price_point.is_valid():
                    valid_data.append(price_point)
                    
            except (ValueError, TypeError, KeyError) as e:
                self.logger.warning(f"Skipping invalid data point: {e}")
                continue
        
        # Sort by date and filter by period
        valid_data.sort(key=lambda x: x.date)
        
        # Filter to recent data within the specified period
        start_date = calculation_date - timedelta(days=period_days + 5)  # Buffer for market days
        filtered_data = [
            point for point in valid_data 
            if start_date <= point.date <= calculation_date
        ]
        
        # Limit to most recent data points if too many
        if len(filtered_data) > self.max_data_points:
            filtered_data = filtered_data[-self.max_data_points:]
        
        self.logger.debug(
            f"Prepared {len(filtered_data)} price data points from {len(price_data)} raw points"
        )
        
        return filtered_data
    
    def _perform_linear_regression(
        self, 
        price_data: List[PriceDataPoint]
    ) -> Dict[str, Any]:
        """Perform linear regression on price data."""
        if len(price_data) < self.min_data_points:
            return {
                "success": False,
                "error": f"Insufficient data points for regression: {len(price_data)} < {self.min_data_points}"
            }
        
        try:
            # Prepare data for regression
            # Use day indices as X values (0, 1, 2, ..., n-1)
            X = np.arange(len(price_data)).reshape(-1, 1)
            y = np.array([point.close_price for point in price_data])
            
            # Perform linear regression
            model = LinearRegression()
            model.fit(X, y)
            
            # Get regression results
            slope = model.coef_[0]
            intercept = model.intercept_
            
            # Calculate R-squared
            y_pred = model.predict(X)
            r_squared = r2_score(y, y_pred)
            
            # Calculate additional metrics
            price_volatility = np.std(y)
            avg_volume = np.mean([point.volume for point in price_data])
            
            # Calculate trend confidence based on R-squared and data points
            trend_confidence = self._calculate_trend_confidence(r_squared, len(price_data))
            
            self.logger.debug(
                f"Linear regression results: slope={slope:.6f}, "
                f"r_squared={r_squared:.4f}, confidence={trend_confidence:.3f}"
            )
            
            return {
                "success": True,
                "slope": slope,
                "intercept": intercept,
                "r_squared": r_squared,
                "price_volatility": price_volatility,
                "avg_volume": avg_volume,
                "trend_confidence": trend_confidence,
                "model": model
            }
            
        except Exception as e:
            self.logger.error(f"Linear regression failed: {e}")
            return {
                "success": False,
                "error": f"Regression error: {str(e)}"
            }
    
    def _calculate_trend_confidence(
        self, 
        r_squared: float, 
        data_points: int
    ) -> float:
        """Calculate trend confidence based on R-squared and data quality."""
        # Base confidence from R-squared
        base_confidence = r_squared
        
        # Adjust for data quantity (more points = higher confidence)
        quantity_factor = min(data_points / 20, 1.0)  # Normalize to 20+ points = full confidence
        
        # Combine factors (weighted average)
        confidence = (0.7 * base_confidence) + (0.3 * quantity_factor)
        
        return min(confidence, 1.0)
    
    def _create_momentum_score(
        self,
        stock_symbol: str,
        calculation_date: date,
        period_days: int,
        regression_result: Dict[str, Any],
        data_points_used: int
    ) -> MomentumScore:
        """Create MomentumScore object from regression results."""
        slope = regression_result["slope"]
        r_squared = regression_result["r_squared"]
        
        # Calculate momentum score
        # Formula: (trend_slope * r_squared * price_volatility_factor) * scaling_factor
        price_volatility_factor = min(regression_result["price_volatility"] / 10, 2.0)  # Cap at 2x
        base_score = slope * r_squared * price_volatility_factor
        
        # Scale for better ranking differentiation (0-100 range typical)
        momentum_score_value = base_score * 10000
        
        # Determine trend direction and strength
        price_trend = self._determine_price_trend(slope, r_squared)
        trend_strength = self._determine_trend_strength(r_squared)
        
        # Set calculation status based on quality
        if r_squared < 0.3:
            status = CalculationStatus.FAILED
        elif r_squared < 0.5:
            status = CalculationStatus.COMPLETED
        else:
            status = CalculationStatus.VALIDATED
        
        return MomentumScore(
            stock_symbol=stock_symbol,
            calculation_date=calculation_date,
            period_days=period_days,
            trend_slope=slope,
            r_squared=r_squared,
            momentum_score=momentum_score_value,
            price_trend=price_trend,
            trend_strength=trend_strength,
            calculation_status=status
        )
    
    def _determine_price_trend(self, slope: float, r_squared: float) -> PriceTrend:
        """Determine price trend direction from slope and R-squared."""
        # Require minimum R-squared for reliable trend determination
        if r_squared < self.min_r_squared:
            return PriceTrend.FLAT
        
        if slope > 0:
            return PriceTrend.UP
        elif slope < 0:
            return PriceTrend.DOWN
        else:
            return PriceTrend.FLAT
    
    def _determine_trend_strength(self, r_squared: float) -> TrendStrength:
        """Determine trend strength from R-squared."""
        if r_squared >= 0.7:
            return TrendStrength.STRONG
        elif r_squared >= 0.4:
            return TrendStrength.MODERATE
        else:
            return TrendStrength.WEAK
    
    def calculate_momentum_batch(
        self,
        stock_data: Dict[str, List[Dict[str, Any]]],
        period_days: int = 25
    ) -> Dict[str, MomentumResult]:
        """Calculate momentum for multiple stocks in batch.
        
        Args:
            stock_data: Dict mapping stock symbols to their price data
            period_days: Number of days for momentum calculation
            
        Returns:
            Dict mapping stock symbols to their momentum results
        """
        self.logger.info(f"Calculating momentum for {len(stock_data)} stocks")
        
        results = {}
        for symbol, price_data in stock_data.items():
            try:
                result = self.calculate_momentum(
                    stock_symbol=symbol,
                    price_data=price_data,
                    period_days=period_days
                )
                results[symbol] = result
                
            except Exception as e:
                self.logger.error(f"Batch calculation failed for {symbol}: {e}")
                results[symbol] = MomentumResult(
                    success=False,
                    error=f"Batch calculation error: {str(e)}"
                )
        
        self.logger.info(f"Batch momentum calculation completed for {len(results)} stocks")
        return results
    
    def get_momentum_quality_assessment(
        self, 
        momentum_score: MomentumScore
    ) -> Dict[str, Any]:
        """Get detailed quality assessment of momentum calculation.
        
        Args:
            momentum_score: Calculated momentum score
            
        Returns:
            Quality assessment with recommendations
        """
        assessment = {
            "quality_score": momentum_score.get_quality_score(),
            "is_reliable": momentum_score.is_reliable(),
            "trend_reliability": "HIGH" if momentum_score.r_squared >= 0.7 else 
                               "MEDIUM" if momentum_score.r_squared >= 0.4 else "LOW",
            "recommendations": []
        }
        
        # Add specific recommendations
        if momentum_score.r_squared < 0.3:
            assessment["recommendations"].append(
                "Low R-squared indicates weak trend reliability. Consider using shorter period or different stock."
            )
        
        if abs(momentum_score.trend_slope) > 0.1:
            assessment["recommendations"].append(
                "Extreme trend slope detected. Verify data quality and market conditions."
            )
        
        if momentum_score.calculation_status == CalculationStatus.FAILED:
            assessment["recommendations"].append(
                "Calculation failed due to insufficient data quality. Try with more historical data."
            )
        
        if not assessment["recommendations"]:
            assessment["recommendations"].append("Momentum calculation appears reliable for decision making.")
        
        return assessment
    
    async def calculate_momentum_async(
        self,
        stock_symbol: str,
        price_data: List[Dict[str, Any]],
        period_days: int = 25,
        calculation_date: Optional[date] = None
    ) -> MomentumResult:
        """Async version of momentum calculation."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.calculate_momentum,
            stock_symbol,
            price_data,
            period_days,
            calculation_date
        )
    
    async def calculate_momentum_batch_async(
        self,
        stock_data: Dict[str, List[Dict[str, Any]]],
        period_days: int = 25
    ) -> Dict[str, MomentumResult]:
        """Async version of batch momentum calculation."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.calculate_momentum_batch,
            stock_data,
            period_days
        )