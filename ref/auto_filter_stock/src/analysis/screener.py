"""Stock screening service for multi-stage filtering based on volume, heat, and momentum."""

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass
import threading
import time
import pandas as pd
from pathlib import Path

from loguru import logger

from src.config.settings import get_settings
from src.config.parameters import ScreeningParams
from src.models.stock import Stock
from src.models.trading_volume import TradingVolume, VolumeState
from src.models.market_heat import MarketHeat, HeatState
from src.models.momentum_score import MomentumScore, CalculationStatus
from src.models.screening_result import ScreeningResult
from src.data.fetcher import DataFetcher
from src.data.processor import DataProcessor
from src.data.validator import DataValidator, ValidationLevel
from src.analysis.momentum import MomentumCalculator


@dataclass
class ScreeningStage:
    """Represents a single screening stage."""
    name: str
    description: str
    stocks_passed: int
    stocks_filtered: int
    processing_time: float


@dataclass
class ScreeningProcessResult:
    """Complete screening result with all stages."""
    success: bool
    session_id: str
    screening_date: date
    parameters: ScreeningParams
    stages: List[ScreeningStage]
    final_results: List[ScreeningResult]
    total_processing_time: float
    error: Optional[str] = None


class StockScreener:
    """Multi-stage stock screener using volume, heat, and momentum filters."""
    
    def __init__(
        self,
        data_fetcher: Optional[DataFetcher] = None,
        data_processor: Optional[DataProcessor] = None,
        data_validator: Optional[DataValidator] = None,
        momentum_calculator: Optional[MomentumCalculator] = None
    ):
        self.settings = get_settings()
        self.logger = logger.bind(service="StockScreener")
        
        # Initialize services
        self.data_fetcher = data_fetcher or DataFetcher()
        self.data_processor = data_processor or DataProcessor()
        self.data_validator = data_validator or DataValidator(ValidationLevel.MODERATE)
        self.momentum_calculator = momentum_calculator or MomentumCalculator()
        
        # Progress tracking
        self._progress_lock = threading.Lock()
        self._progress_data: Dict[str, Dict[str, Any]] = {}
        
        self.stages = []
        
        # Results directory for saving intermediate CSV files
        self.results_dir = Path(__file__).parent.parent.parent / "results"
        self.results_dir.mkdir(exist_ok=True)
    
    def _update_progress(
        self, 
        session_id: str, 
        status: str, 
        stage: str, 
        stage_progress: int = 0,
        total_progress: int = 0,
        message: str = "",
        current_stocks: int = 0,
        total_stocks: int = 0,
        current_data_source: str = "",
        current_stock_symbol: str = "",
        data_sources_completed: List[str] = None,
        data_sources_pending: List[str] = None,
        stage_details: Dict[str, Any] = None
    ):
        """Update progress for a session."""
        with self._progress_lock:
            if session_id not in self._progress_data:
                self._progress_data[session_id] = {
                    "start_time": time.time(),
                    "status": "starting",
                    "stage": "",
                    "stage_progress": 0,
                    "total_progress": 0,
                    "message": "",
                    "current_stocks": 0,
                    "total_stocks": 0,
                    "current_data_source": "",
                    "current_stock_symbol": "",
                    "data_sources_completed": [],
                    "data_sources_pending": [],
                    "stage_details": {},
                    "final_results": [],
                    "summary": {}
                }
            
            update_data = {
                "status": status,
                "stage": stage,
                "stage_progress": stage_progress,
                "total_progress": total_progress,
                "message": message,
                "current_stocks": current_stocks,
                "total_stocks": total_stocks,
                "last_update": time.time()
            }
            
            # Add detailed progress information if provided
            if current_data_source:
                update_data["current_data_source"] = current_data_source
            if current_stock_symbol:
                update_data["current_stock_symbol"] = current_stock_symbol
            if data_sources_completed is not None:
                update_data["data_sources_completed"] = data_sources_completed
            if data_sources_pending is not None:
                update_data["data_sources_pending"] = data_sources_pending
            if stage_details is not None:
                update_data["stage_details"] = stage_details
            
            self._progress_data[session_id].update(update_data)
    
    def get_screening_results(self, session_id: str) -> Dict[str, Any]:
        """Get screening results for a session."""
        with self._progress_lock:
            if session_id not in self._progress_data:
                return None
            
            progress = self._progress_data[session_id]
            summary = progress.get("summary", {})
            final_results = progress.get("final_results", [])
            
            # Convert ScreeningResult objects to dicts for JSON serialization
            results_list = []
            for result in final_results:
                if hasattr(result, 'dict'):
                    results_list.append(result.dict())
                elif isinstance(result, dict):
                    results_list.append(result)
                else:
                    # Fallback: convert to dict manually
                    results_list.append({
                        "stock_symbol": getattr(result, 'stock_symbol', ''),
                        "stock_name": getattr(result, 'stock_name', ''),
                        "final_ranking": getattr(result, 'final_ranking', 0),
                        "combined_score": getattr(result, 'combined_score', 0),
                        "volume_rank": getattr(result, 'volume_rank', 0),
                        "heat_rank": getattr(result, 'heat_rank', 0),
                        "momentum_rank": getattr(result, 'momentum_rank', 0),
                        "volume_amount": getattr(result, 'volume_amount', 0),
                        "heat_score": getattr(result, 'heat_score', 0),
                        "momentum_score": getattr(result, 'momentum_score', 0),
                        "trend_slope": getattr(result, 'trend_slope', 0),
                        "r_squared": getattr(result, 'r_squared', 0),
                        "trend_strength": getattr(result, 'trend_strength', ''),
                        "price_trend": getattr(result, 'price_trend', ''),
                        "is_selected": getattr(result, 'is_selected', True)
                    })
            
            # Return flattened structure matching frontend expectations
            return {
                "session_id": session_id,
                "screening_date": summary.get("screening_date", ""),
                "total_stocks_processed": summary.get("total_stocks_processed", summary.get("total_stocks", 0)),
                "total_stocks_selected": summary.get("total_stocks_selected", summary.get("selected_stocks", len(results_list))),
                "processing_time": summary.get("processing_time", 0),
                "results": results_list,
                "status": progress.get("status", "unknown")
            }
    
    def get_progress(self, session_id: str) -> Dict[str, Any]:
        """Get progress for a session."""
        with self._progress_lock:
            if session_id not in self._progress_data:
                return {"status": "not_found"}
            
            progress = self._progress_data[session_id].copy()
            
            # Calculate estimated remaining time
            if progress.get("start_time") and progress["status"] == "running":
                elapsed = time.time() - progress["start_time"]
                if progress["total_progress"] > 0:
                    estimated_total = elapsed / (progress["total_progress"] / 100)
                    progress["estimated_remaining"] = max(0, estimated_total - elapsed)
                else:
                    progress["estimated_remaining"] = 0
            else:
                progress["estimated_remaining"] = 0
            
            return progress
    
    def get_latest_session(self) -> Optional[str]:
        """Get the most recent session ID."""
        with self._progress_lock:
            if not self._progress_data:
                return None
            
            # Find the session with the most recent last_update or start_time
            latest_session = None
            latest_time = 0
            
            for session_id, progress in self._progress_data.items():
                session_time = progress.get("last_update", progress.get("start_time", 0))
                if session_time > latest_time:
                    latest_time = session_time
                    latest_session = session_id
            
            return latest_session
    
    def _save_stage_results(
        self,
        session_id: str,
        stage_name: str,
        data: List[Dict[str, Any]],
        filename_suffix: str = ""
    ):
        """保存每个阶段的结果到CSV文件
        
        Args:
            session_id: 会话ID
            stage_name: 阶段名称
            data: 要保存的数据列表
            filename_suffix: 文件名后缀（可选）
        """
        try:
            if not data:
                self.logger.warning(f"No data to save for {stage_name}")
                return
            
            # 创建文件名：session_id_stage_name_suffix.csv
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{session_id}_{stage_name}{filename_suffix}.csv"
            filepath = self.results_dir / filename
            
            # 转换为DataFrame并保存
            df = pd.DataFrame(data)
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
            
            self.logger.info(f"Saved {len(data)} records to {filepath}")
            
        except Exception as e:
            self.logger.error(f"Error saving stage results for {stage_name}: {e}")
    
    def screen_stocks(
        self,
        params: ScreeningParams,
        session_id: str,
        screening_date: Optional[date] = None
    ) -> ScreeningProcessResult:
        """Perform complete multi-stage stock screening.
        
        Args:
            params: Screening parameters
            session_id: Unique session identifier
            screening_date: Date for screening (defaults to today)
            
        Returns:
            Complete screening result with all stages
        """
        start_time = datetime.now()
        
        if screening_date is None:
            screening_date = date.today()
            
        self.logger.info(
            f"Starting stock screening for session {session_id} on {screening_date} "
            f"with parameters: {params.to_dict()}"
        )
        
        try:
            self.stages = []
            
            # Initialize progress tracking
            self._update_progress(session_id, "running", "初始化", 0, 0, "开始股票筛选流程...")
            
            # Stage 1: Fetch volume data
            stage1_result = self._stage1_fetch_volume_data(params, screening_date, session_id)
            if not stage1_result["success"]:
                return self._create_error_result(
                    session_id, screening_date, params, stage1_result["error"]
                )
            
            volume_data = stage1_result["data"]
            
            # Stage 2: Fetch heat data
            stage2_result = self._stage2_fetch_heat_data(params, screening_date, session_id)
            if not stage2_result["success"]:
                return self._create_error_result(
                    session_id, screening_date, params, stage2_result["error"]
                )
            
            heat_data = stage2_result["data"]
            
            # Stage 3: Find intersection of top volume and heat stocks
            self._update_progress(session_id, "running", "寻找交集", 0, 35, "正在寻找成交额和热度的交集股票...")
            
            stage3_result = self._stage3_find_intersection(volume_data, heat_data, params, session_id)
            if not stage3_result["success"]:
                return self._create_error_result(
                    session_id, screening_date, params, stage3_result["error"]
                )
            
            intersection_stocks = stage3_result["stocks"]
            
            # Stage 4: Calculate momentum for intersection stocks
            # Stage 4: Calculate momentum
            self._update_progress(
                session_id, "running", "计算动量", 0, 70, 
                f"正在计算{len(intersection_stocks)}只股票的动量评分...",
                current_data_source="momentum_calculation",
                data_sources_completed=["trading_volume", "market_heat", "intersection"],
                data_sources_pending=["historical_prices", "momentum_calculation", "ranking", "final_validation"]
            )
            stage4_result = self._stage4_calculate_momentum(intersection_stocks, params, screening_date, session_id)
            if not stage4_result["success"]:
                return self._create_error_result(
                    session_id, screening_date, params, stage4_result["error"]
                )
            
            momentum_scores = stage4_result["momentum_scores"]
            
            # Stage 5: Final ranking and selection
            # Stage 5: Final ranking
            self._update_progress(
                session_id, "running", "最终排名", 0, 90, 
                "正在进行最终排名和评分...",
                current_data_source="ranking",
                data_sources_completed=["trading_volume", "market_heat", "intersection", "historical_prices", "momentum_calculation"],
                data_sources_pending=["ranking", "final_validation"]
            )
            stage5_result = self._stage5_final_ranking(momentum_scores, params, session_id, volume_data, heat_data)
            if not stage5_result["success"]:
                return self._create_error_result(
                    session_id, screening_date, params, stage5_result["error"]
                )
            
            final_results = stage5_result["final_results"]
            
            # Save results to progress data for CSV download
            # Calculate total stocks processed from stages
            total_processed = 0
            if self.stages:
                # Get the count from the first stage (volume data fetch)
                total_processed = self.stages[0].stocks_passed + self.stages[0].stocks_filtered
            
            with self._progress_lock:
                if session_id in self._progress_data:
                    self._progress_data[session_id]["final_results"] = final_results
                    self._progress_data[session_id]["summary"] = {
                        "screening_date": screening_date.strftime("%Y-%m-%d"),
                        "total_stocks": len(final_results),
                        "selected_stocks": len([r for r in final_results if r.is_selected]),
                        "total_stocks_processed": total_processed,
                        "total_stocks_selected": len(final_results),
                        "processing_time": (datetime.now() - start_time).total_seconds(),
                        "parameters": params.dict() if hasattr(params, 'dict') else str(params)
                    }
            
            total_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(
                f"Stock screening completed for session {session_id}: "
                f"{len(final_results)} stocks selected in {total_time:.2f}s"
            )
            
            # Update final progress
            self._update_progress(
                session_id, "completed", "完成", 100, 100, 
                f"筛选完成！共找到{len(final_results)}只强势股",
                current_data_source="final_validation",
                data_sources_completed=["trading_volume", "market_heat", "intersection", "historical_prices", "momentum_calculation", "ranking", "final_validation"],
                data_sources_pending=[]
            )
            
            return ScreeningProcessResult(
                success=True,
                session_id=session_id,
                screening_date=screening_date,
                parameters=params,
                stages=self.stages,
                final_results=final_results,
                total_processing_time=total_time
            )
            
        except Exception as e:
            self.logger.error(f"Stock screening failed for session {session_id}: {e}")
            return self._create_error_result(
                session_id, screening_date, params, f"Screening error: {str(e)}"
            )
    
    def _stage1_fetch_volume_data(
        self, 
        params: ScreeningParams, 
        screening_date: date,
        session_id: str
    ) -> Dict[str, Any]:
        """Stage 1: Fetch top stocks by trading volume."""
        stage_start = datetime.now()
        self.logger.info(f"Stage 1: Fetching top {params.volume_top_n} stocks by volume")
        
        try:
            self._update_progress(session_id, "running", "获取成交额数据", 0, 5, "正在从同花顺获取成交额数据...")
            
            # Fetch volume data
            fetch_result = self.data_fetcher.fetch_trading_volume_data(
                top_n=params.volume_top_n,
                date_filter=screening_date
            )
            
            if not fetch_result.success:
                return {"success": False, "error": fetch_result.error}
            
            self._update_progress(session_id, "running", "获取成交额数据", 50, 15, "正在处理成交量数据...")
            
            # Process volume data
            volume_data = fetch_result.data.get('volume_data', [])
            process_result = self.data_processor.process_volume_data(volume_data)
            
            if not process_result.success:
                return {"success": False, "error": process_result.error}
            
            trading_volumes = process_result.processed_data.get('trading_volumes', [])
            
            # Validate processed data
            validation_result = self.data_validator.validate_volume_data(trading_volumes)
            if not validation_result.is_valid and validation_result.errors:
                self.logger.warning(f"Volume data validation issues: {validation_result.errors}")
            
            stage_time = (datetime.now() - stage_start).total_seconds()
            
            stage = ScreeningStage(
                name="Volume Data Fetching",
                description=f"Fetched and processed top {len(trading_volumes)} stocks by trading volume",
                stocks_passed=len(trading_volumes),
                stocks_filtered=0,  # First stage, no filtering yet
                processing_time=stage_time
            )
            self.stages.append(stage)
            
            # 保存成交量数据到CSV
            volume_csv_data = []
            for idx, vol in enumerate(trading_volumes, 1):
                volume_csv_data.append({
                    '排名': idx,
                    '股票代码': vol.stock_symbol,
                    '股票名称': getattr(vol, 'stock_name', vol.stock_symbol),  # 使用stock_symbol作为后备
                    '成交量': vol.volume,
                    '成交额': vol.turnover,
                    '原始排名': vol.raw_volume_rank if vol.raw_volume_rank else idx,
                    '状态': vol.state.value if vol.state else 'unknown',
                    '数据日期': vol.date.isoformat() if vol.date else ''
                })
            self._save_stage_results(session_id, "stage1_volume", volume_csv_data, "_top100")
            
            return {"success": True, "data": trading_volumes}
            
        except Exception as e:
            self.logger.error(f"Stage 1 failed: {e}")
            return {"success": False, "error": f"Volume data fetch failed: {str(e)}"}
    
    def _stage2_fetch_heat_data(
        self, 
        params: ScreeningParams, 
        screening_date: date,
        session_id: str
    ) -> Dict[str, Any]:
        """Stage 2: Fetch top stocks by market heat."""
        stage_start = datetime.now()
        self.logger.info(f"Stage 2: Fetching top {params.heat_top_n} stocks by heat")
        
        try:
            self._update_progress(session_id, "running", "获取热度数据", 0, 20, "正在从同花顺获取市场热度数据...")
            
            # Fetch heat data
            fetch_result = self.data_fetcher.fetch_market_heat_data(
                top_n=params.heat_top_n,
                date_filter=screening_date
            )
            
            if not fetch_result.success:
                return {"success": False, "error": fetch_result.error}
            
            self._update_progress(session_id, "running", "获取热度数据", 50, 30, "正在处理市场热度数据...")
            
            # Process heat data
            heat_data = fetch_result.data.get('heat_data', [])
            process_result = self.data_processor.process_heat_data(heat_data)
            
            if not process_result.success:
                return {"success": False, "error": process_result.error}
            
            market_heats = process_result.processed_data.get('market_heats', [])
            
            # Validate processed data
            validation_result = self.data_validator.validate_heat_data(market_heats)
            if not validation_result.is_valid and validation_result.errors:
                self.logger.warning(f"Heat data validation issues: {validation_result.errors}")
            
            stage_time = (datetime.now() - stage_start).total_seconds()
            
            stage = ScreeningStage(
                name="Heat Data Fetching",
                description=f"Fetched and processed top {len(market_heats)} stocks by market heat",
                stocks_passed=len(market_heats),
                stocks_filtered=0,  # No filtering in this stage
                processing_time=stage_time
            )
            self.stages.append(stage)
            
            # 保存热度数据到CSV
            heat_csv_data = []
            for idx, heat in enumerate(market_heats, 1):
                heat_csv_data.append({
                    '排名': idx,
                    '股票代码': heat.stock_symbol,
                    '股票名称': getattr(heat, 'stock_name', heat.stock_symbol),  # 使用stock_symbol作为后备
                    '热度值': heat.heat_score,
                    '关注指数': heat.attention_index,
                    '原始排名': heat.raw_heat_rank if heat.raw_heat_rank else idx,
                    '状态': heat.state.value if heat.state else 'unknown',
                    '数据日期': heat.date.isoformat() if heat.date else ''
                })
            self._save_stage_results(session_id, "stage2_heat", heat_csv_data, "_top100")
            
            return {"success": True, "data": market_heats}
            
        except Exception as e:
            self.logger.error(f"Stage 2 failed: {e}")
            return {"success": False, "error": f"Heat data fetch failed: {str(e)}"}
    
    def _stage3_find_intersection(
        self,
        volume_data: List[TradingVolume],
        heat_data: List[MarketHeat],
        params: ScreeningParams,
        session_id: str
    ) -> Dict[str, Any]:
        """Stage 3: Find intersection of top volume and heat stocks."""
        stage_start = datetime.now()
        self.logger.info("Stage 3: Finding intersection of volume and heat leaders")
        
        try:
            # Combine volume and heat data
            combined_volumes, combined_heats = self.data_processor.combine_volume_and_heat_data(
                volume_data, heat_data, min_intersection=5
            )
            
            if not combined_volumes:
                return {
                    "success": False, 
                    "error": "No stocks found in volume-heat intersection. Consider adjusting parameters."
                }
            
            # Get unique stock symbols from intersection
            intersection_symbols = list({
                vol.stock_symbol for vol in combined_volumes
            }.intersection({
                heat.stock_symbol for heat in combined_heats
            }))
            
            self.logger.info(f"Found {len(intersection_symbols)} stocks in volume-heat intersection")
            
            # 数据已在process阶段标准化，直接计算加权组合分数 (成交额权重0.5, 热度权重0.5)
            combined_scores = self.data_processor.calculate_combined_scores(
                combined_volumes, combined_heats,
                volume_weight=0.5, heat_weight=0.5
            )
            
            # 按加权分数排序，取前 intersection_top_n 只
            top_scored_stocks = self.data_processor.get_top_stocks_by_combined_score(
                combined_scores, top_n=params.intersection_top_n
            )
            
            # 提取前N只股票的代码
            final_symbols = [symbol for symbol, score in top_scored_stocks]
            
            self.logger.info(f"Selected top {len(final_symbols)} stocks after weighted ranking")
            
            stage_time = (datetime.now() - stage_start).total_seconds()
            stocks_filtered = len(intersection_symbols) - len(final_symbols)
            
            stage = ScreeningStage(
                name="Volume-Heat Intersection + Weighted Ranking",
                description=f"Found {len(intersection_symbols)} stocks in intersection, selected top {len(final_symbols)} by weighted score",
                stocks_passed=len(final_symbols),
                stocks_filtered=stocks_filtered,
                processing_time=stage_time
            )
            self.stages.append(stage)
            
            # 保存交集和加权排名数据到CSV
            # 创建字典方便查找
            volume_dict = {v.stock_symbol: v for v in combined_volumes}
            heat_dict = {h.stock_symbol: h for h in combined_heats}
            score_dict = {symbol: score for symbol, score in top_scored_stocks}
            
            intersection_csv_data = []
            for symbol in final_symbols:
                vol = volume_dict.get(symbol)
                heat = heat_dict.get(symbol)
                
                # 尝试从不同来源获取股票名称
                stock_name = symbol  # 默认使用股票代码
                if vol:
                    stock_name = getattr(vol, 'stock_name', symbol)
                elif heat:
                    stock_name = getattr(heat, 'stock_name', symbol)
                
                intersection_csv_data.append({
                    '股票代码': symbol,
                    '股票名称': stock_name,
                    '成交量': vol.volume if vol else 0,
                    '成交额': vol.turnover if vol else 0,
                    '成交额标准化': f"{vol.normalized_volume:.4f}" if vol and vol.normalized_volume else "N/A",
                    '热度值': heat.heat_score if heat else 0,
                    '关注指数': heat.attention_index if heat else 0,
                    '热度标准化': f"{heat.normalized_heat:.4f}" if heat and heat.normalized_heat else "N/A",
                    '加权组合分数': f"{score_dict.get(symbol, 0):.4f}",
                    '通过原因': '加权排名前30'
                })
            self._save_stage_results(session_id, "stage3_intersection", intersection_csv_data, "_filtered")
            
            return {"success": True, "stocks": final_symbols}
            
        except Exception as e:
            self.logger.error(f"Stage 3 failed: {e}")
            return {"success": False, "error": f"Intersection calculation failed: {str(e)}"}
    
    def _stage4_calculate_momentum(
        self, 
        stock_symbols: List[str], 
        params: ScreeningParams, 
        screening_date: date,
        session_id: str
    ) -> Dict[str, Any]:
        """Stage 4: Calculate momentum for intersection stocks."""
        stage_start = datetime.now()
        self.logger.info(f"Stage 4: Calculating momentum for {len(stock_symbols)} stocks")
        
        try:
            momentum_scores = []
            failed_symbols = []
            
            # 批量并发获取所有股票的历史价格(大幅提速)
            import concurrent.futures
            import threading
            
            self._update_progress(
                session_id, "running", "获取历史价格", 0, 45, 
                f"正在并发获取{len(stock_symbols)}只股票的历史价格...",
                0, len(stock_symbols),
                current_data_source="historical_prices"
            )
            
            price_data_dict = {}
            fetch_lock = threading.Lock()
            completed_count = [0]  # 使用列表以便在闭包中修改
            
            def fetch_single_stock(symbol):
                """获取单只股票的历史价格"""
                try:
                    price_result = self.data_fetcher.fetch_historical_prices(
                        symbol=symbol,
                        days=params.momentum_days + 10
                    )
                    
                    with fetch_lock:
                        completed_count[0] += 1
                        current_count = completed_count[0]
                        
                        if price_result.success:
                            price_data_dict[symbol] = price_result.data.get('price_data', [])
                        else:
                            self.logger.warning(f"Failed to fetch price data for {symbol}: {price_result.error}")
                            failed_symbols.append(symbol)
                        
                        # 更新进度
                        stage_progress = int(current_count / len(stock_symbols) * 100)
                        total_progress = 45 + int(current_count / len(stock_symbols) * 20)  # 45% -> 65%
                        self._update_progress(
                            session_id, "running", "获取历史价格", stage_progress, total_progress, 
                            f"已获取 {current_count}/{len(stock_symbols)} 只股票的历史价格",
                            current_count, len(stock_symbols),
                            current_data_source="historical_prices",
                            current_stock_symbol=symbol
                        )
                    
                    return True
                        
                except Exception as e:
                    self.logger.error(f"Error fetching price data for {symbol}: {e}")
                    with fetch_lock:
                        failed_symbols.append(symbol)
                    return False
            
            # 使用线程池并发获取（最多10个线程同时执行）
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(fetch_single_stock, symbol) for symbol in stock_symbols]
                # 等待所有任务完成
                concurrent.futures.wait(futures)
            
            # 计算动量(这部分很快)
            for i, symbol in enumerate(price_data_dict.keys()):
                # Update progress for each stock - progress from 65% to 90%
                stage_progress = int((i / len(price_data_dict)) * 100)
                total_progress = 65 + int((i / len(price_data_dict)) * 25)  # 65% -> 90%
                self._update_progress(
                    session_id, "running", "计算动量", stage_progress, total_progress, 
                    f"正在计算 {symbol} 的动量评分... ({i+1}/{len(price_data_dict)})",
                    i, len(price_data_dict),
                    current_data_source="momentum_calculation",
                    current_stock_symbol=symbol
                )
                
                try:
                    price_data = price_data_dict[symbol]
                    
                    # Calculate momentum
                    momentum_result = self.momentum_calculator.calculate_momentum(
                        stock_symbol=symbol,
                        price_data=price_data,
                        period_days=params.momentum_days,
                        calculation_date=screening_date
                    )
                    
                    if momentum_result.success and momentum_result.momentum_score:
                        # Only include stocks with reliable momentum calculations
                        if momentum_result.momentum_score.r_squared >= 0.3:
                            momentum_scores.append(momentum_result.momentum_score)
                        else:
                            self.logger.warning(f"Low R-squared for {symbol}: {momentum_result.momentum_score.r_squared}")
                            failed_symbols.append(symbol)
                    else:
                        self.logger.warning(f"Momentum calculation failed for {symbol}: {momentum_result.error}")
                        failed_symbols.append(symbol)
                        
                except Exception as e:
                    self.logger.error(f"Momentum calculation error for {symbol}: {e}")
                    failed_symbols.append(symbol)
            
            if not momentum_scores:
                return {
                    "success": False,
                    "error": "No reliable momentum scores calculated. Check data quality and parameters."
                }
            
            stage_time = (datetime.now() - stage_start).total_seconds()
            
            stage = ScreeningStage(
                name="Momentum Calculation",
                description=f"Calculated reliable momentum for {len(momentum_scores)} stocks",
                stocks_passed=len(momentum_scores),
                stocks_filtered=len(failed_symbols),
                processing_time=stage_time
            )
            self.stages.append(stage)
            
            # 保存动量数据到CSV
            momentum_csv_data = []
            # 按动量得分排序
            sorted_momentum = sorted(momentum_scores, key=lambda x: x.momentum_score, reverse=True)
            for idx, m in enumerate(sorted_momentum, 1):
                # 安全获取枚举值
                trend_strength = m.trend_strength
                if hasattr(trend_strength, 'value'):
                    trend_strength = trend_strength.value
                elif trend_strength is not None:
                    trend_strength = str(trend_strength)
                else:
                    trend_strength = 'unknown'
                
                price_trend = m.price_trend
                if hasattr(price_trend, 'value'):
                    price_trend = price_trend.value
                elif price_trend is not None:
                    price_trend = str(price_trend)
                else:
                    price_trend = 'unknown'
                
                calculation_status = m.calculation_status if m.calculation_status else 'unknown'
                if hasattr(calculation_status, 'value'):
                    calculation_status = calculation_status.value
                
                momentum_csv_data.append({
                    '排名': idx,
                    '股票代码': m.stock_symbol,
                    '动量得分': m.momentum_score,
                    '趋势斜率': m.trend_slope,
                    'R平方值': m.r_squared,
                    '趋势强度': trend_strength,
                    '价格趋势': price_trend,
                    '计算状态': calculation_status,
                    '计算日期': m.calculation_date.isoformat() if m.calculation_date else ''
                })
            self._save_stage_results(session_id, "stage4_momentum", momentum_csv_data, "_calculated")
            
            return {"success": True, "momentum_scores": momentum_scores}
            
        except Exception as e:
            self.logger.error(f"Stage 4 failed: {e}")
            return {"success": False, "error": f"Momentum calculation failed: {str(e)}"}
    
    def _stage5_final_ranking(
        self,
        momentum_scores: List[MomentumScore],
        params: ScreeningParams,
        session_id: str,
        volume_data: List[TradingVolume] = None,
        heat_data: List[MarketHeat] = None
    ) -> Dict[str, Any]:
        """Stage 5: Final ranking and selection based on momentum scores."""
        stage_start = datetime.now()
        self.logger.info(f"Stage 5: Final ranking of {len(momentum_scores)} stocks")
        
        try:
            # Create lookup dictionaries for volume and heat data
            volume_dict = {v.stock_symbol: v for v in (volume_data or [])}
            heat_dict = {h.stock_symbol: h for h in (heat_data or [])}
            
            # Sort by momentum score (higher is better)
            sorted_scores = sorted(momentum_scores, key=lambda x: x.momentum_score, reverse=True)
            
            # Select top stocks based on final_top_n parameter
            top_scores = sorted_scores[:params.final_top_n]
            
            # Create final screening results
            final_results = []
            for rank, momentum_score in enumerate(top_scores, 1):
                screening_result = self._create_screening_result(
                    momentum_score=momentum_score,
                    final_ranking=rank,
                    parameters=params,
                    volume_data=volume_dict.get(momentum_score.stock_symbol),
                    heat_data=heat_dict.get(momentum_score.stock_symbol)
                )
                final_results.append(screening_result)
            
            stage_time = (datetime.now() - stage_start).total_seconds()
            
            stage = ScreeningStage(
                name="Final Ranking",
                description=f"Selected top {len(final_results)} stocks by momentum score",
                stocks_passed=len(final_results),
                stocks_filtered=len(sorted_scores) - len(final_results),
                processing_time=stage_time
            )
            self.stages.append(stage)
            
            # 保存最终排名数据到CSV
            final_csv_data = []
            for result in final_results:
                final_csv_data.append({
                    '最终排名': result.final_ranking,
                    '股票代码': result.stock_symbol,
                    '股票名称': result.stock_name,
                    '成交量排名': result.volume_rank,
                    '成交额': result.volume_amount,
                    '热度排名': result.heat_rank,
                    '热度得分': result.heat_score,
                    '动量排名': result.momentum_rank,
                    '动量得分': result.momentum_score,
                    '趋势斜率': result.trend_slope,
                    'R平方值': result.r_squared,
                    '趋势强度': result.trend_strength,
                    '价格趋势': result.price_trend,
                    '综合得分': result.combined_score,
                    '筛选日期': result.screening_date.isoformat() if result.screening_date else ''
                })
            self._save_stage_results(session_id, "stage5_final_ranking", final_csv_data, "_top_stocks")
            
            return {"success": True, "final_results": final_results}
            
        except Exception as e:
            self.logger.error(f"Stage 5 failed: {e}")
            return {"success": False, "error": f"Final ranking failed: {str(e)}"}
    
    def _create_screening_result(
        self,
        momentum_score: MomentumScore,
        final_ranking: int,
        parameters: ScreeningParams,
        volume_data: TradingVolume = None,
        heat_data: MarketHeat = None
    ) -> ScreeningResult:
        """Create final screening result from momentum score."""
        # Create combined score based on momentum score and quality
        # Weight: 70% momentum score, 30% R-squared (trend reliability)
        normalized_momentum = min(abs(momentum_score.momentum_score) / 100, 100)
        reliability_score = momentum_score.r_squared * 100
        combined_score = 0.7 * normalized_momentum + 0.3 * reliability_score
        
        # Create selection criteria JSON
        import json
        criteria_dict = {
            "volume_top_n": parameters.volume_top_n,
            "heat_top_n": parameters.heat_top_n,
            "momentum_days": parameters.momentum_days,
            "final_top_n": parameters.final_top_n
        }
        
        # Extract detailed data from volume, heat, and momentum objects
        volume_amount = volume_data.volume if volume_data else None
        volume_rank = volume_data.raw_volume_rank if volume_data and volume_data.raw_volume_rank else None
        
        heat_score_val = heat_data.heat_score if heat_data else None
        heat_rank = heat_data.raw_heat_rank if heat_data and heat_data.raw_heat_rank else None
        
        # Get stock name from volume or heat data
        stock_name = None
        if volume_data and hasattr(volume_data, 'stock_name'):
            stock_name = volume_data.stock_name
        elif heat_data and hasattr(heat_data, 'stock_name'):
            stock_name = heat_data.stock_name
        else:
            # Fallback to symbol if name not available
            stock_name = momentum_score.stock_symbol
        
        return ScreeningResult(
            stock_symbol=momentum_score.stock_symbol,
            stock_name=stock_name,
            screening_date=momentum_score.calculation_date,
            volume_rank=volume_rank,
            heat_rank=heat_rank,
            momentum_rank=final_ranking,
            combined_score=combined_score,
            final_ranking=final_ranking,
            selection_criteria=json.dumps(criteria_dict),
            is_selected=True,
            volume_amount=volume_amount,
            heat_score=heat_score_val,
            momentum_score=momentum_score.momentum_score,
            trend_slope=momentum_score.trend_slope,
            r_squared=momentum_score.r_squared,
            trend_strength=momentum_score.trend_strength,
            price_trend=momentum_score.price_trend
        )
    
    def _create_error_result(
        self,
        session_id: str,
        screening_date: date,
        params: ScreeningParams,
        error_message: str
    ) -> ScreeningProcessResult:
        """Create error screening result."""
        return ScreeningProcessResult(
            success=False,
            session_id=session_id,
            screening_date=screening_date,
            parameters=params,
            stages=self.stages,
            final_results=[],
            total_processing_time=0.0,
            error=error_message
        )
    
    def get_screening_statistics(self) -> Dict[str, Any]:
        """Get statistics about the screening process."""
        if not self.stages:
            return {"status": "no_screening_performed"}
        
        total_stocks_processed = sum(stage.stocks_passed + stage.stocks_filtered for stage in self.stages)
        total_stocks_selected = self.stages[-1].stocks_passed if self.stages else 0
        total_filtering_rate = (
            sum(stage.stocks_filtered for stage in self.stages) / total_stocks_processed * 100
            if total_stocks_processed > 0 else 0
        )
        
        return {
            "total_stocks_processed": total_stocks_processed,
            "total_stocks_selected": total_stocks_selected,
            "overall_filtering_rate": total_filtering_rate,
            "number_of_stages": len(self.stages),
            "total_processing_time": sum(stage.processing_time for stage in self.stages),
            "stage_details": [
                {
                    "name": stage.name,
                    "stocks_passed": stage.stocks_passed,
                    "stocks_filtered": stage.stocks_filtered,
                    "processing_time": stage.processing_time
                }
                for stage in self.stages
            ]
        }
    
    async def screen_stocks_async(
        self,
        params: ScreeningParams,
        session_id: str,
        screening_date: Optional[date] = None
    ) -> ScreeningProcessResult:
        """Async version of stock screening."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.screen_stocks,
            params,
            session_id,
            screening_date
        )