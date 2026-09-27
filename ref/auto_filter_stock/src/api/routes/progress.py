"""Progress tracking routes."""

import csv
import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import Dict, Any, List
from src.api.dependencies import get_services
from src.api.dependencies import Services

router = APIRouter()


@router.get("/latest")
async def get_latest_progress(
    services: Services = Depends(get_services)
) -> Dict[str, Any]:
    """Get the latest screening progress (most recent session)."""
    # Get the most recent session from the screener
    latest_session = services.stock_screener.get_latest_session()
    
    if not latest_session:
        return {
            "session_id": None,
            "status": "no_session",
            "stage": "",
            "total_progress": 0,
            "message": "没有活跃的筛选任务"
        }
    
    # Get progress for the latest session
    progress = services.stock_screener.get_progress(latest_session)
    
    return {
        "session_id": latest_session,
        "status": progress.get("status", "unknown"),
        "stage": progress.get("stage", ""),
        "stage_progress": progress.get("stage_progress", 0),
        "total_progress": progress.get("total_progress", 0),
        "message": progress.get("message", ""),
        "current_stocks": progress.get("current_stocks", 0),
        "total_stocks": progress.get("total_stocks", 0),
        "start_time": progress.get("start_time"),
        "estimated_remaining": progress.get("estimated_remaining", 0),
        "current_data_source": progress.get("current_data_source", ""),
        "data_sources_completed": progress.get("data_sources_completed", []),
        "data_sources_pending": progress.get("data_sources_pending", []),
        "current_stock_symbol": progress.get("current_stock_symbol", ""),
        "stage_details": progress.get("stage_details", {})
    }


@router.get("/progress/{session_id}")
async def get_progress(
    session_id: str,
    services: Services = Depends(get_services)
) -> Dict[str, Any]:
    """Get screening progress for a session."""
    # Get progress from the screener service
    progress = services.stock_screener.get_progress(session_id)
    
    return {
        "session_id": session_id,
        "status": progress.get("status", "unknown"),
        "stage": progress.get("stage", ""),
        "stage_progress": progress.get("stage_progress", 0),
        "total_progress": progress.get("total_progress", 0),
        "message": progress.get("message", ""),
        "current_stocks": progress.get("current_stocks", 0),
        "total_stocks": progress.get("total_stocks", 0),
        "start_time": progress.get("start_time"),
        "estimated_remaining": progress.get("estimated_remaining", 0),
        "current_data_source": progress.get("current_data_source", ""),
        "data_sources_completed": progress.get("data_sources_completed", []),
        "data_sources_pending": progress.get("data_sources_pending", []),
        "current_stock_symbol": progress.get("current_stock_symbol", ""),
        "stage_details": progress.get("stage_details", {})
    }


@router.get("/download/latest")
async def download_latest_results(
    services: Services = Depends(get_services)
) -> StreamingResponse:
    """Download the latest screening results as CSV."""
    import pandas as pd
    from pathlib import Path
    
    results_dir = Path(__file__).parent.parent.parent.parent / "results"
    
    # Find the most recent final ranking file
    final_ranking_files = list(results_dir.glob("*_stage5_final_ranking_top_stocks.csv"))
    if not final_ranking_files:
        raise HTTPException(status_code=404, detail="No screening results found")
    
    # Get the most recent file
    latest_file = max(final_ranking_files, key=lambda x: x.stat().st_mtime)
    session_id = latest_file.stem.replace("_stage5_final_ranking_top_stocks", "")
    
    # Redirect to the session-specific download
    return await download_results(session_id, services)


@router.get("/download/{session_id}")
async def download_results(
    session_id: str,
    services: Services = Depends(get_services)
) -> StreamingResponse:
    """Download screening results as CSV with detailed screening process data."""
    # Get the screening results from memory
    results = services.stock_screener.get_screening_results(session_id)
    
    # If not in memory, try to load from results folder (in case of server restart)
    if not results or not results.get("results"):
        import pandas as pd
        from pathlib import Path
        
        results_dir = Path(__file__).parent.parent.parent.parent / "results"
        final_ranking_file = results_dir / f"{session_id}_stage5_final_ranking_top_stocks.csv"
        
        if final_ranking_file.exists():
            # Load from CSV file
            df = pd.read_csv(final_ranking_file)
            screening_results = df.to_dict('records')
            results = {
                "session_id": session_id,
                "results": screening_results,
                "screening_date": df['筛选日期'].iloc[0] if '筛选日期' in df.columns and len(df) > 0 else ""
            }
        else:
            raise HTTPException(status_code=404, detail="No results found for this session")
    
    screening_results = results["results"]
    
    # Create CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write enhanced header with screening process details
    writer.writerow([
        "股票代码",
        "股票名称", 
        "最终排名",
        "综合评分",
        "成交量数据",
        "成交量排名",
        "市场热度",
        "热度排名",
        "动量得分",
        "动量排名",
        "趋势斜率",
        "R平方值",
        "趋势强度",
        "价格趋势",
        "是否选中",
        "筛选时间"
    ])
    
    # Write data rows with detailed information
    for idx, result in enumerate(screening_results, 1):
        # Convert to dict if Pydantic model
        if hasattr(result, 'dict'):
            result_data = result.dict()
        elif isinstance(result, dict):
            result_data = result
        else:
            result_data = result.__dict__
        
        # Get values - support both English keys (from memory) and Chinese keys (from CSV file)
        stock_symbol = result_data.get("stock_symbol") or result_data.get("股票代码", "")
        stock_name = result_data.get("stock_name") or result_data.get("股票名称", "")
        final_ranking = result_data.get("final_ranking") or result_data.get("最终排名", idx)
        combined_score = result_data.get("combined_score") or result_data.get("综合得分", 0.0)
        
        volume_amount = result_data.get("volume_amount") or result_data.get("成交额", 0.0)
        volume_rank = result_data.get("volume_rank") or result_data.get("成交量排名", 0)
        
        heat_score = result_data.get("heat_score") or result_data.get("热度得分", 0.0)
        heat_rank = result_data.get("heat_rank") or result_data.get("热度排名", 0)
        
        momentum_score = result_data.get("momentum_score") or result_data.get("动量得分", 0.0)
        momentum_rank = result_data.get("momentum_rank") or result_data.get("动量排名", 0)
        trend_slope = result_data.get("trend_slope") or result_data.get("趋势斜率", 0.0)
        r_squared = result_data.get("r_squared") or result_data.get("R平方值", 0.0)
        trend_strength = result_data.get("trend_strength") or result_data.get("趋势强度", "")
        price_trend = result_data.get("price_trend") or result_data.get("价格趋势", "")
        
        is_selected = result_data.get("is_selected", True)
        
        # Date - support both English and Chinese keys
        screening_date = result_data.get("screening_date") or result_data.get("筛选日期", "")
        if screening_date and hasattr(screening_date, 'strftime'):
            screening_date = screening_date.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(screening_date, str):
            screening_date = screening_date  # Already a string from CSV
        else:
            screening_date = ""
        
        writer.writerow([
            stock_symbol,
            stock_name,
            final_ranking,
            f"{combined_score:.2f}" if combined_score else "0.00",
            f"{volume_amount:.2f}" if volume_amount else "0.00",
            volume_rank if volume_rank else "0",
            f"{heat_score:.2f}" if heat_score else "0.00",
            heat_rank if heat_rank else "0",
            f"{momentum_score:.2f}" if momentum_score else "0.00",
            momentum_rank if momentum_rank else "0",
            f"{trend_slope:.4f}" if trend_slope else "0.0000",
            f"{r_squared:.4f}" if r_squared else "0.0000",
            trend_strength if trend_strength else "",
            price_trend if price_trend else "",
            "是" if is_selected else "否",
            screening_date
        ])
    
    # Prepare CSV content
    output.seek(0)
    csv_content = output.getvalue()
    output.close()
    
    # Create filename with timestamp
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screening_results_detailed_{timestamp}.csv"
    
    return StreamingResponse(
        io.BytesIO(csv_content.encode('utf-8-sig')),  # UTF-8 with BOM for Excel compatibility
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/download/stage/{session_id}/{stage}")
async def download_stage_file(
    session_id: str,
    stage: str,
    services: Services = Depends(get_services)
) -> StreamingResponse:
    """下载指定阶段的CSV文件。"""
    from pathlib import Path
    from loguru import logger
    
    # 阶段文件名映射
    stage_file_mapping = {
        'stage1': f"{session_id}_stage1_volume_top100.csv",
        'stage2': f"{session_id}_stage2_heat_top100.csv",
        'stage3': f"{session_id}_stage3_intersection_filtered.csv",
        'stage4': f"{session_id}_stage4_momentum_calculated.csv",
        'stage5': f"{session_id}_stage5_final_ranking_top_stocks.csv",
    }
    
    if stage not in stage_file_mapping:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {stage}")
    
    # 查找文件
    results_dir = Path(__file__).parent.parent.parent.parent / "results"
    file_path = results_dir / stage_file_mapping[stage]
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Stage file not found: {stage}")
    
    # 读取文件内容
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return StreamingResponse(
            iter([content.encode('utf-8-sig')]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={stage_file_mapping[stage]}"
            }
        )
    except Exception as e:
        logger.error(f"Error reading stage file {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")
