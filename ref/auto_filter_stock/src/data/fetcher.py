"""Data fetcher service for acquiring stock data from pywencai and mairui."""

import asyncio
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import pandas as pd
import pywencai
import requests
from loguru import logger

from src.config.settings import get_settings
from src.models.stock import Stock
from src.models.trading_volume import TradingVolume
from src.models.market_heat import MarketHeat
from src.models.error_log import ErrorLog
from src.utils.cookie_manager import get_cookie_manager
from src.utils.trading_calendar import get_previous_trading_day, format_date_for_query


@dataclass
class FetchResult:
    """Result of data fetching operation."""
    success: bool
    data: Optional[Dict[str, List]] = None
    error: Optional[str] = None
    retry_count: int = 0
    fetch_time: float = 0.0


class DataFetcher:
    """Service for fetching stock data from pywencai with retry logic."""
    
    def __init__(self):
        self.settings = get_settings()
        self.retry_attempts = self.settings.pywencai_retry_attempts
        self.timeout = self.settings.pywencai_timeout
        self.rate_limit_delay = 60 / self.settings.pywencai_rate_limit  # seconds between requests
        self._last_request_time = 0.0
        
        # 使用Cookie管理器自动获取Cookie
        cookie_manager = get_cookie_manager()
        self.cookie = cookie_manager.get_cookie()
        
        # Mairui API配置
        self.mairui_licence = self.settings.mairui_licence
        self.mairui_base_url = self.settings.mairui_base_url
        self.mairui_timeout = self.settings.mairui_timeout
        
        # Log cookie status (don't log the actual cookie for security)
        if self.cookie:
            logger.info("Pywencai cookie loaded successfully")
        else:
            logger.error("Pywencai cookie not found!")
            logger.error("=" * 60)
            logger.error("请配置同花顺问财Cookie以获取数据：")
            logger.error("方法1: 运行 ./setup_cookie.sh 配置Cookie")
            logger.error("方法2: 设置环境变量 PYWENCAI_COOKIE=你的cookie")
            logger.error("方法3: 查看 COOKIE_SETUP.md 获取详细教程")
            logger.error("=" * 60)
        
        # Log Mairui status
        if self.mairui_licence:
            logger.info("Mairui licence configured successfully")
        
    def _rate_limit(self) -> None:
        """Apply rate limiting to respect API limits."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        
        if time_since_last < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - time_since_last
            logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f}s")
            time.sleep(sleep_time)
        
        self._last_request_time = time.time()
    
    def _fetch_volume_query(self, query: str):
        """执行成交量查询"""
        return pywencai.get(
            query=query,
            cookie=self.cookie,
            log=False
        )
    
    def _fetch_heat_query(self, query: str):
        """执行热度查询"""
        return pywencai.get(
            query=query,
            cookie=self.cookie,
            log=False
        )
    
    def _execute_with_retry(
        self, 
        func, 
        *args, 
        **kwargs
    ) -> Tuple[Optional[any], int, Optional[str]]:
        """Execute function with exponential backoff retry logic."""
        last_error = None
        
        for attempt in range(self.retry_attempts):
            try:
                self._rate_limit()
                result = func(*args, **kwargs)
                
                if result is not None:
                    logger.debug(f"Successfully executed {func.__name__} on attempt {attempt + 1}")
                    return result, attempt, None
                    
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {last_error}")
                
                if attempt < self.retry_attempts - 1:
                    # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                    backoff_time = 2 ** attempt
                    logger.debug(f"Retrying in {backoff_time}s...")
                    time.sleep(backoff_time)
        
        logger.error(f"All {self.retry_attempts} attempts failed for {func.__name__}")
        return None, self.retry_attempts, last_error
    
    def fetch_trading_volume_data(
        self, 
        top_n: int = 100,
        date_filter: Optional[date] = None
    ) -> FetchResult:
        """Fetch top stocks by trading volume."""
        start_time = time.time()
        
        if date_filter is None:
            date_filter = date.today()
        
        # 获取上一个交易日作为数据基准日期
        previous_trading_day = get_previous_trading_day(date_filter)
        logger.info(f"Fetching top {top_n} stocks by trading volume for {date_filter} (based on {previous_trading_day} data)")
        
        def _fetch_volume():
            """Internal function to fetch volume data."""
            # 尝试多种查询格式
            queries = [
                f"今日成交额排名前{top_n}的股票",
                f"成交额排名前{top_n}的股票",
                f"{top_n}只成交额最大的股票"
            ]
            
            result = None
            for query in queries:
                try:
                    logger.debug(f"Trying query: {query}")
                    result = pywencai.get(
                        query=query,
                        cookie=self.cookie,
                        log=False
                    )
                    
                    if result is not None and not result.empty:
                        logger.info(f"Successfully got data with query: {query}")
                        break
                    else:
                        logger.warning(f"No data returned for volume query: {query}")
                        result = None
                        
                except Exception as e:
                    logger.warning(f"Query '{query}' failed: {e}")
                    result = None
                    continue
            
            if result is None or result.empty:
                logger.error("All volume queries failed or returned no data")
                return None
            
            # Log the actual columns returned
            logger.info(f"Returned columns: {list(result.columns)}")
            logger.info(f"First row data: {result.iloc[0].to_dict() if len(result) > 0 else 'No data'}")
                
            # Process the DataFrame result
            volume_data = []
            for _, row in result.iterrows():
                try:
                    # Extract stock symbol and name
                    stock_symbol = row.get('股票代码', '')
                    if not stock_symbol:
                        continue
                    
                    # Extract stock name (try multiple possible column names)
                    stock_name = row.get('股票简称', row.get('股票名称', row.get('名称', stock_symbol)))
                        
                    # Normalize symbol format (ensure .SZ or .SH suffix)
                    if not stock_symbol.endswith(('.SZ', '.SH', '.SS')):
                        # Default to .SZ if no exchange suffix
                        stock_symbol = f"{stock_symbol}.SZ"
                    
                    # Try multiple column names for volume/turnover
                    # First try exact match, then try pattern matching for dated columns
                    volume = 0
                    volume_col_name = None
                    if '成交额' in row:
                        volume = row.get('成交额', 0)
                        volume_col_name = '成交额'
                    else:
                        # Try to find any column that starts with '成交额['
                        for col_name in row.keys():
                            if col_name.startswith('成交额[') or col_name.startswith('成交额（'):
                                volume = row.get(col_name, 0)
                                volume_col_name = col_name
                                break
                    
                    logger.info(f"Stock {stock_symbol}: volume_col={volume_col_name}, raw_value={volume}, type={type(volume)}")
                    
                    # Handle empty, None, or zero values
                    if volume is None or volume == 0 or volume == '' or volume == '0':
                        logger.info(f"Skipping {stock_symbol}: invalid volume value")
                        continue
                    
                    # Try to convert to number
                    try:
                        volume_num = float(str(volume).replace(',', ''))
                        if volume_num == 0:
                            logger.info(f"Skipping {stock_symbol}: volume is zero")
                            continue
                    except (ValueError, TypeError) as e:
                        logger.info(f"Skipping {stock_symbol}: cannot convert volume '{volume}' to number: {e}")
                        continue
                        
                    volume_data.append({
                        'stock_symbol': stock_symbol,
                        'stock_name': stock_name,
                        'date': date_filter,
                        'volume': int(volume_num),
                        'turnover': float(volume_num),
                        'raw_data': row.to_dict()  # Store raw data for debugging
                    })
                    
                except Exception as e:
                    logger.warning(f"Error processing volume row: {e}")
                    continue
            
            logger.info(f"Successfully fetched {len(volume_data)} volume records")
            return volume_data
        
        # Execute with retry logic
        volume_data, retry_count, error_msg = self._execute_with_retry(_fetch_volume)
        
        fetch_time = time.time() - start_time
        
        if volume_data is not None:
            return FetchResult(
                success=True,
                data={'volume_data': volume_data},
                retry_count=retry_count,
                fetch_time=fetch_time
            )
        else:
            return FetchResult(
                success=False,
                error=error_msg or "Failed to fetch volume data",
                retry_count=retry_count,
                fetch_time=fetch_time
            )
    
    def fetch_market_heat_data(
        self, 
        top_n: int = 100,
        date_filter: Optional[date] = None
    ) -> FetchResult:
        """Fetch top stocks by market heat/attention."""
        start_time = time.time()
        
        if date_filter is None:
            date_filter = date.today()
        
        # 获取上一个交易日作为数据基准日期
        previous_trading_day = get_previous_trading_day(date_filter)
        logger.info(f"Fetching top {top_n} stocks by market heat for {date_filter} (based on {previous_trading_day} data)")
        
        def _fetch_heat():
            """Internal function to fetch heat data."""
            # 尝试多种查询格式
            queries = [
                f"今日热度排名前{top_n}的股票",
                f"热度排名前{top_n}的股票",
                f"{top_n}只最热门的股票",
                f"关注度排名前{top_n}的股票"
            ]
            
            result = None
            for query in queries:
                try:
                    logger.debug(f"Trying heat query: {query}")
                    result = pywencai.get(
                        query=query,
                        cookie=self.cookie,
                        log=False
                    )
                    
                    if result is not None and not result.empty:
                        logger.info(f"Successfully got heat data with query: {query}")
                        break
                    else:
                        logger.warning(f"No data returned for heat query: {query}")
                        result = None
                        
                except Exception as e:
                    logger.warning(f"Heat query '{query}' failed: {e}")
                    result = None
                    continue
            
            if result is None or result.empty:
                logger.error("All heat queries failed or returned no data")
                return None
                
            # Process the DataFrame result
            heat_data = []
            for _, row in result.iterrows():
                try:
                    # Extract stock symbol and name
                    stock_symbol = row.get('股票代码', '')
                    if not stock_symbol:
                        continue
                    
                    # Extract stock name (try multiple possible column names)
                    stock_name = row.get('股票简称', row.get('股票名称', row.get('名称', stock_symbol)))
                        
                    # Normalize symbol format
                    if not stock_symbol.endswith(('.SZ', '.SH', '.SS')):
                        stock_symbol = f"{stock_symbol}.SZ"
                    
                    # Try multiple column names for heat score
                    heat_score = 0
                    
                    # First try exact column names
                    for col_name in ['热度', '关注度', '人气值', '热度值']:
                        if col_name in row:
                            heat_score = row.get(col_name, 0)
                            break
                    
                    # If not found, try columns with date patterns like '个股热度[20251009]'
                    if heat_score == 0:
                        for col_name in row.keys():
                            if '热度[' in col_name or '关注度[' in col_name or '人气[' in col_name:
                                heat_score = row.get(col_name, 0)
                                if heat_score != 0:
                                    logger.debug(f"Found heat data in column: {col_name}")
                                    break
                    
                    if heat_score == 0:
                        logger.debug(f"No heat data found for {stock_symbol}, available columns: {list(row.keys())}")
                        continue
                        
                    heat_data.append({
                        'stock_symbol': stock_symbol,
                        'stock_name': stock_name,
                        'date': date_filter,
                        'heat_score': float(heat_score),
                        'attention_index': float(heat_score),  # Use same value for now
                        'raw_data': row.to_dict()
                    })
                    
                except Exception as e:
                    logger.warning(f"Error processing heat row: {e}")
                    continue
            
            logger.info(f"Successfully fetched {len(heat_data)} heat records")
            return heat_data
        
        # Execute with retry logic
        heat_data, retry_count, error_msg = self._execute_with_retry(_fetch_heat)
        
        fetch_time = time.time() - start_time
        
        if heat_data is not None:
            return FetchResult(
                success=True,
                data={'heat_data': heat_data},
                retry_count=retry_count,
                fetch_time=fetch_time
            )
        else:
            return FetchResult(
                success=False,
                error=error_msg or "Failed to fetch heat data",
                retry_count=retry_count,
                fetch_time=fetch_time
            )
    
    def fetch_historical_prices(
        self, 
        symbol: str,
        days: int = 60
    ) -> FetchResult:
        """Fetch historical price data for a stock using akshare."""
        start_time = time.time()
        
        def _fetch_prices():
            """Internal function to fetch price data using mairui API."""
            try:
                # 构建mairui API URL
                # API格式: http://api.mairuiapi.com/hsstock/history/{股票代码}/d/n{licence}?lt=条数
                # d=日线, n=不复权
                url = f"{self.mairui_base_url}/hsstock/history/{symbol}/d/f{self.mairui_licence}"
                
                # 计算需要获取的天数（考虑周末和节假日，多取一些）
                extra_days = int(days * 1.5)  # 多取50%以确保有足够交易日
                
                logger.debug(f"Fetching price data for {symbol} from mairui API (requesting {extra_days} days)")
                
                # 调用mairui API
                response = requests.get(url, params={'lt': extra_days}, timeout=self.mairui_timeout)
                
                if response.status_code != 200:
                    logger.error(f"Mairui API returned status {response.status_code}: {response.text}")
                    return None
                
                data = response.json()
                
                if not isinstance(data, list) or len(data) == 0:
                    logger.warning(f"No price data returned for {symbol} from mairui")
                    return None
                
                # 处理mairui返回的数据
                # 字段: t(时间), o(开盘), h(最高), l(最低), c(收盘), v(成交量), a(成交额), pc(前收盘), sf(停牌)
                price_data = []
                for item in data:
                    try:
                        # 解析日期，mairui返回格式为 "2025-10-09 00:00:00"
                        price_date = datetime.strptime(item['t'].split()[0], '%Y-%m-%d').date()
                        
                        price_data.append({
                            'date': price_date,
                            'close': float(item['c']),
                            'open': float(item['o']),
                            'high': float(item['h']),
                            'low': float(item['l']),
                            'volume': float(item['v']),
                            'symbol': symbol
                        })
                    except Exception as e:
                        logger.debug(f"Error processing price data for {symbol}: {e}")
                        continue
                
                # 按日期排序
                price_data.sort(key=lambda x: x['date'])
                
                # 只保留最近的days天数据
                if len(price_data) > days:
                    price_data = price_data[-days:]
                
                logger.info(f"Successfully fetched {len(price_data)} price records for {symbol} using mairui")
                return price_data
                
            except Exception as e:
                logger.error(f"Error fetching price data for {symbol} using mairui: {e}")
                return None
        
        # Execute with retry logic
        price_data, retry_count, error_msg = self._execute_with_retry(_fetch_prices)
        
        fetch_time = time.time() - start_time
        
        if price_data is not None:
            return FetchResult(
                success=True,
                data={'price_data': price_data},
                retry_count=retry_count,
                fetch_time=fetch_time
            )
        else:
            return FetchResult(
                success=False,
                error=error_msg or f"Failed to fetch price data for {symbol}",
                retry_count=retry_count,
                fetch_time=fetch_time
            )