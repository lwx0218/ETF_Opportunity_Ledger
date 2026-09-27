"""Screening API endpoints."""

from datetime import date
from typing import List, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field

from src.api.dependencies import get_stock_screener, get_dashboard_generator, get_services, Services
from src.analysis.screener import StockScreener
from src.visualization.dashboard import DashboardGenerator
from src.config.parameters import ScreeningParams
from src.models.screening_result import ScreeningResult

logger = logging.getLogger(__name__)


router = APIRouter()


class ScreeningRequest(BaseModel):
    """Request model for stock screening."""
    volume_top_n: int = Field(default=100, ge=10, le=500, description="Top N stocks by volume")
    heat_top_n: int = Field(default=100, ge=10, le=500, description="Top N stocks by market heat")
    intersection_top_n: int = Field(default=30, ge=10, le=100, description="Top N stocks after intersection by weighted score")
    momentum_days: int = Field(default=25, ge=5, le=60, description="Momentum calculation period in days")
    final_top_n: int = Field(default=10, ge=5, le=50, description="Final number of stocks to select")
    use_cache: bool = Field(default=True, description="Whether to use cached data")
    screening_date: Optional[date] = Field(default=None, description="Date for screening (defaults to today)")


class ScreeningResponse(BaseModel):
    """Response model for stock screening."""
    success: bool
    session_id: str
    screening_date: date
    parameters: dict
    total_stocks_processed: int
    total_stocks_selected: int
    processing_time: float
    stages: List[dict]
    results: List[dict]
    error: Optional[str] = None


class ScreeningStatus(BaseModel):
    """Status model for screening operations."""
    session_id: str
    status: str  # "pending", "processing", "completed", "failed"
    progress: float  # 0-100
    current_stage: str
    results_ready: bool
    error: Optional[str] = None


@router.post("/screen", response_model=ScreeningResponse)
async def screen_stocks(
    request: ScreeningRequest,
    screener: StockScreener = Depends(get_stock_screener)
):
    """Perform stock screening based on volume, heat, and momentum criteria (synchronous with progress tracking)."""
    try:
        # Convert request to ScreeningParams
        params = ScreeningParams(
            volume_top_n=request.volume_top_n,
            heat_top_n=request.heat_top_n,
            intersection_top_n=request.intersection_top_n,
            momentum_days=request.momentum_days,
            final_top_n=request.final_top_n,
            use_cache=request.use_cache
        )
        
        # Generate unique session ID
        import uuid
        session_id = str(uuid.uuid4())
        
        # 同步执行筛选（screener内部会更新进度）
        result = screener.screen_stocks(
            params=params,
            session_id=session_id,
            screening_date=request.screening_date
        )
        
        if not result.success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Screening failed: {result.error}"
            )
        
        # Convert results to response format
        screening_results = []
        for screening_result in result.final_results:
            screening_results.append({
                "stock_symbol": screening_result.stock_symbol,
                "stock_name": screening_result.stock_name,
                "screening_date": screening_result.screening_date,
                "volume_rank": screening_result.volume_rank,
                "heat_rank": screening_result.heat_rank,
                "momentum_rank": screening_result.momentum_rank,
                "combined_score": screening_result.combined_score,
                "final_ranking": screening_result.final_ranking,
                "is_selected": screening_result.is_selected
            })
        
        return ScreeningResponse(
            success=result.success,
            session_id=result.session_id,
            screening_date=result.screening_date,
            parameters=result.parameters.to_dict(),
            total_stocks_processed=sum(stage.stocks_passed + stage.stocks_filtered for stage in result.stages),
            total_stocks_selected=len(result.final_results),
            processing_time=result.total_processing_time,
            stages=[
                {
                    "name": stage.name,
                    "description": stage.description,
                    "stocks_passed": stage.stocks_passed,
                    "stocks_filtered": stage.stocks_filtered,
                    "processing_time": stage.processing_time
                }
                for stage in result.stages
            ],
            results=screening_results,
            error=result.error
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during screening: {str(e)}"
        )


@router.post("/screen/async", response_model=dict)
async def screen_stocks_async(
    request: ScreeningRequest,
    background_tasks: BackgroundTasks,
    screener: StockScreener = Depends(get_stock_screener)
):
    """Start asynchronous stock screening operation."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    try:
        # Convert request to ScreeningParams
        params = ScreeningParams(
            volume_top_n=request.volume_top_n,
            heat_top_n=request.heat_top_n,
            intersection_top_n=request.intersection_top_n,
            momentum_days=request.momentum_days,
            final_top_n=request.final_top_n,
            use_cache=request.use_cache
        )
        
        # Generate unique session ID
        import uuid
        session_id = str(uuid.uuid4())
        
        # Run screening in a separate thread to avoid blocking
        def run_screening():
            try:
                result = screener.screen_stocks(
                    params=params,
                    session_id=session_id,
                    screening_date=request.screening_date
                )
                # Store result in cache/session (implementation needed)
                logger.info(f"Async screening completed for session {session_id}")
            except Exception as e:
                logger.error(f"Async screening failed for session {session_id}: {e}")
                # Update progress to failed state
                screener._update_progress(
                    session_id, "failed", "失败", 0, 0, f"筛选失败: {str(e)}"
                )
        
        # Start the screening task in a background thread
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.run_in_executor(executor, run_screening)
        
        return {
            "success": True,
            "session_id": session_id,
            "message": "Screening operation started",
            "status_endpoint": f"/api/v1/screening/status/{session_id}"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start async screening: {str(e)}"
        )


@router.get("/status/{session_id}", response_model=ScreeningStatus)
async def get_screening_status(
    session_id: str
):
    """Get status of screening operation."""
    # This would typically check a cache or database
    # For now, return a mock status
    return ScreeningStatus(
        session_id=session_id,
        status="completed",
        progress=100.0,
        current_stage="Final Ranking",
        results_ready=True,
        error=None
    )


@router.get("/results/{session_id}")
async def get_screening_results(
    session_id: str,
    screener: StockScreener = Depends(get_stock_screener)
):
    """Get screening results by session ID."""
    try:
        # 从 screener 获取结果
        results = screener.get_screening_results(session_id)
        
        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到会话 {session_id} 的筛选结果"
            )
        
        return results
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取结果失败: {str(e)}"
        )


@router.get("/recent", response_model=List[ScreeningResponse])
async def get_recent_screenings(
    limit: int = 10,
    offset: int = 0
):
    """Get recent screening operations."""
    # This would typically query a database
    # For now, return empty list
    return []


# Alias endpoints for test compatibility
@router.post("/run", response_model=dict, status_code=status.HTTP_202_ACCEPTED)
async def run_screening_alias(
    request: ScreeningRequest,
    background_tasks: BackgroundTasks,
    screener: StockScreener = Depends(get_stock_screener)
):
    """Start screening operation (alias for /screen/async)."""
    return await screen_stocks_async(request, background_tasks, screener)


@router.post("/dashboard/{session_id}")
async def generate_screening_dashboard(
    session_id: str,
    dashboard_gen: DashboardGenerator = Depends(get_dashboard_generator),
    screener: StockScreener = Depends(get_stock_screener)
):
    """Generate dashboard for screening results."""
    try:
        # This would typically retrieve results from cache/database
        # For now, generate a mock dashboard
        import uuid
        from datetime import date
        from src.models.screening_result import ScreeningResult
        
        # Mock screening results
        mock_results = [
            ScreeningResult(
                stock_symbol=f"00000{i+1:03d}.SZ",
                screening_date=date.today(),
                volume_rank=i+1,
                heat_rank=i+2,
                momentum_rank=i+1,
                combined_score=85.0 - i * 3.0,
                final_ranking=i+1,
                selection_criteria='{"volume_top_n": 100, "heat_top_n": 100, "momentum_days": 25, "final_top_n": 10}',
                is_selected=i < 10
            )
            for i in range(15)
        ]
        
        # Generate dashboard
        dashboard_result = dashboard_gen.generate_screening_dashboard(
            screening_results=mock_results,
            title=f"Screening Dashboard - {session_id}"
        )
        
        if not dashboard_result.success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Dashboard generation failed: {dashboard_result.error}"
            )
        
        return {
            "success": True,
            "session_id": session_id,
            "dashboard_html": dashboard_result.html_content,
            "summary_stats": dashboard_result.summary_stats,
            "generation_time": dashboard_result.generation_time
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dashboard generation error: {str(e)}"
        )


@router.get("/parameters/default")
async def get_default_parameters():
    """Get default screening parameters."""
    default_params = ScreeningParams()
    return default_params.to_dict()


@router.get("/parameters/validate")
async def validate_parameters(
    volume_top_n: int = 100,
    heat_top_n: int = 100,
    momentum_days: int = 25,
    final_top_n: int = 10
):
    """Validate screening parameters."""
    try:
        params = ScreeningParams(
            volume_top_n=volume_top_n,
            heat_top_n=heat_top_n,
            momentum_days=momentum_days,
            final_top_n=final_top_n
        )
        
        return {
            "valid": True,
            "parameters": params.to_dict(),
            "recommendations": [
                "Consider increasing volume_top_n for broader market coverage",
                "Momentum days between 20-30 typically work well",
                "Final_top_n should be between 5-20 for manageable results"
            ]
        }
        
    except ValueError as e:
        return {
            "valid": False,
            "error": str(e),
            "recommendations": []
        }


@router.get("/historical_prices/{stock_symbol}")
async def get_historical_prices(
    stock_symbol: str,
    days: int = 30,
    services: Services = Depends(get_services)
):
    """获取股票的真实历史价格数据用于绘制K线图。"""
    try:
        logger.info(f"Fetching historical prices for {stock_symbol}, days={days}")
        
        # 使用同步方法但在线程池中运行以避免阻塞
        import asyncio
        result = await asyncio.to_thread(
            services.data_fetcher.fetch_historical_prices,
            symbol=stock_symbol,
            days=days + 10  # 多获取一些以确保有足够数据
        )
        
        logger.info(f"Fetch result for {stock_symbol}: success={result.success}")
        
        if not result.success:
            error_msg = f"无法获取 {stock_symbol} 的历史价格数据: {result.error}"
            logger.warning(error_msg)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg
            )
        
        price_data = result.data.get('price_data', [])
        logger.info(f"Price data count for {stock_symbol}: {len(price_data)}")
        
        if not price_data:
            error_msg = f"未找到 {stock_symbol} 的历史价格数据"
            logger.warning(error_msg)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg
            )
        
        # 格式化数据供前端使用
        formatted_data = []
        for i, price_point in enumerate(price_data[-days:]):  # 只返回需要的天数
            try:
                # 处理字典或对象两种格式
                if isinstance(price_point, dict):
                    formatted_data.append({
                        "date": str(price_point.get('date', '')),
                        "close": float(price_point.get('close', 0)),
                        "open": float(price_point.get('open', price_point.get('close', 0))),
                        "high": float(price_point.get('high', price_point.get('close', 0))),
                        "low": float(price_point.get('low', price_point.get('close', 0))),
                        "volume": float(price_point.get('volume', 0))
                    })
                else:
                    # 对象格式
                    formatted_data.append({
                        "date": price_point.date.isoformat() if hasattr(price_point.date, 'isoformat') else str(price_point.date),
                        "close": float(price_point.close),
                        "open": float(price_point.open) if hasattr(price_point, 'open') else float(price_point.close),
                        "high": float(price_point.high) if hasattr(price_point, 'high') else float(price_point.close),
                        "low": float(price_point.low) if hasattr(price_point, 'low') else float(price_point.close),
                        "volume": float(price_point.volume) if hasattr(price_point, 'volume') else 0
                    })
            except Exception as e:
                logger.error(f"Error formatting price point {i} for {stock_symbol}: {e}")
                # Skip this price point and continue
                continue
        
        if not formatted_data:
            error_msg = f"格式化 {stock_symbol} 价格数据失败"
            logger.error(error_msg)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_msg
            )
        
        logger.info(f"Successfully formatted {len(formatted_data)} price points for {stock_symbol}")
        
        return {
            "success": True,
            "stock_symbol": stock_symbol,
            "data": formatted_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error fetching historical prices for {stock_symbol}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史价格失败: {str(e)}"
        )