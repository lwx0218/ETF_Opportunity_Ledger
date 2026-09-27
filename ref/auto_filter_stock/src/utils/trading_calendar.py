"""Trading calendar utilities for working with stock market trading days."""

from datetime import date, datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def get_previous_trading_day(target_date: Optional[date] = None) -> date:
    """获取指定日期的上一个交易日。
    
    Args:
        target_date: 目标日期，如果为None则使用今天
        
    Returns:
        上一个交易日的日期
        
    Note:
        简化版本，仅考虑周末，不考虑节假日
        实际应用中可以接入专业的交易日历API
    """
    if target_date is None:
        target_date = date.today()
    
    # 从目标日期前一天开始查找
    prev_day = target_date - timedelta(days=1)
    
    # 跳过周末（周六=5, 周日=6）
    while prev_day.weekday() >= 5:
        prev_day -= timedelta(days=1)
    
    logger.debug(f"Previous trading day for {target_date}: {prev_day}")
    return prev_day


def is_trading_day(check_date: date) -> bool:
    """检查指定日期是否为交易日。
    
    Args:
        check_date: 要检查的日期
        
    Returns:
        如果是交易日返回True，否则返回False
        
    Note:
        简化版本，仅考虑周末，不考虑节假日
    """
    # 周一到周五为交易日（weekday: 0-4）
    return check_date.weekday() < 5


def get_trading_days_between(start_date: date, end_date: date) -> int:
    """计算两个日期之间的交易日数量。
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        
    Returns:
        交易日数量
    """
    if start_date > end_date:
        return 0
    
    trading_days = 0
    current_date = start_date
    
    while current_date <= end_date:
        if is_trading_day(current_date):
            trading_days += 1
        current_date += timedelta(days=1)
    
    return trading_days


def format_date_for_query(target_date: date) -> str:
    """将日期格式化为查询字符串。
    
    Args:
        target_date: 目标日期
        
    Returns:
        格式化的日期字符串
    """
    return target_date.strftime("%Y-%m-%d")


def parse_date_input(date_input: str) -> Optional[date]:
    """解析用户输入的日期字符串。
    
    Args:
        date_input: 用户输入的日期字符串
        
    Returns:
        解析后的日期对象，如果解析失败返回None
        
    支持的格式:
        - YYYY-MM-DD (2025-10-09)
        - YYYY/MM/DD (2025/10/09)
        - MM-DD (10-09, 默认当年)
        - MM/DD (10/09, 默认当年)
    """
    if not date_input or not date_input.strip():
        return None
    
    date_input = date_input.strip()
    current_year = datetime.now().year
    
    # 尝试不同的日期格式
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d", 
        "%m-%d",
        "%m/%d"
    ]
    
    for fmt in formats:
        try:
            if fmt in ["%m-%d", "%m/%d"]:
                # 对于没有年份的格式，添加当前年份
                parsed_date = datetime.strptime(date_input, fmt).replace(year=current_year).date()
            else:
                parsed_date = datetime.strptime(date_input, fmt).date()
            
            logger.debug(f"Successfully parsed '{date_input}' as {parsed_date}")
            return parsed_date
            
        except ValueError:
            continue
    
    logger.warning(f"Failed to parse date input: '{date_input}'")
    return None