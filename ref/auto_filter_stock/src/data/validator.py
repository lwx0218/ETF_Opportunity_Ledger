"""Data validator service for validating stock data against business rules."""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from loguru import logger

from src.models.stock import Stock
from src.models.trading_volume import TradingVolume, VolumeState
from src.models.market_heat import MarketHeat, HeatState
from src.models.momentum_score import MomentumScore, CalculationStatus
from src.config.settings import get_settings


class ValidationLevel(str, Enum):
    """Validation severity levels."""
    STRICT = "STRICT"      # Reject on any validation failure
    MODERATE = "MODERATE"  # Allow some minor issues
    LENIENT = "LENIENT"    # Allow most issues with warnings


class ValidationResult:
    """Result of data validation."""
    
    def __init__(self, is_valid: bool = True):
        self.is_valid = is_valid
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
        self.validation_time = 0.0
        self.records_validated = 0
        
    def add_error(self, message: str) -> None:
        """Add validation error."""
        self.is_valid = False
        self.errors.append(message)
        
    def add_warning(self, message: str) -> None:
        """Add validation warning."""
        self.warnings.append(message)
        
    def add_info(self, message: str) -> None:
        """Add validation info."""
        self.info.append(message)
        
    def merge(self, other: 'ValidationResult') -> None:
        """Merge another validation result into this one."""
        self.is_valid = self.is_valid and other.is_valid
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.info.extend(other.info)
        self.records_validated += other.records_validated
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'is_valid': self.is_valid,
            'errors': self.errors,
            'warnings': self.warnings,
            'info': self.info,
            'validation_time': self.validation_time,
            'records_validated': self.records_validated
        }


class DataValidator:
    """Service for validating stock data against business rules."""
    
    def __init__(self, validation_level: ValidationLevel = ValidationLevel.MODERATE):
        self.settings = get_settings()
        self.validation_level = validation_level
        self.logger = logger.bind(service="DataValidator")
        
        # Business rule thresholds
        self.min_volume_threshold = 1_000_000  # Minimum 1M shares
        self.max_price_change_threshold = 0.20  # 20% daily change limit
        self.min_market_cap = 1_000_000_000  # Minimum 1B CNY market cap
        self.max_days_old = 7  # Maximum days for data to be considered current
        
    def validate_stock_data(
        self, 
        stocks: List[Stock]
    ) -> ValidationResult:
        """Validate stock basic data.
        
        Args:
            stocks: List of Stock objects to validate
            
        Returns:
            ValidationResult with validation outcomes
        """
        start_time = datetime.now()
        result = ValidationResult()
        
        if not stocks:
            result.add_warning("No stock data to validate")
            result.validation_time = 0.0
            result.records_validated = 0
            return result
        
        self.logger.info(f"Validating {len(stocks)} stock records")
        
        for i, stock in enumerate(stocks):
            try:
                stock_result = self._validate_single_stock(stock)
                result.merge(stock_result)
                
            except Exception as e:
                result.add_error(f"Error validating stock {i}: {str(e)}")
                self.logger.error(f"Error validating stock {i}: {e}")
        
        validation_time = (datetime.now() - start_time).total_seconds()
        result.validation_time = validation_time
        result.records_validated = len(stocks)
        
        self.logger.info(
            f"Stock validation completed: {result.records_validated} records, "
            f"Valid: {result.is_valid}, Errors: {len(result.errors)}, "
            f"Warnings: {len(result.warnings)}"
        )
        
        return result
    
    def _validate_single_stock(self, stock: Stock) -> ValidationResult:
        """Validate a single stock object."""
        result = ValidationResult()
        
        # Validate symbol format
        if not stock.symbol or len(stock.symbol) < 6:
            result.add_error(f"Invalid stock symbol format: {stock.symbol}")
            return result
        
        # Validate price data
        if stock.current_price <= 0:
            result.add_error(f"Invalid current price for {stock.symbol}: {stock.current_price}")
            
        if stock.previous_close <= 0:
            result.add_warning(f"Invalid previous close for {stock.symbol}: {stock.previous_close}")
            
        # Validate price change consistency
        expected_change = stock.current_price - stock.previous_close
        if abs(stock.price_change - expected_change) > 0.01:
            if self.validation_level == ValidationLevel.STRICT:
                result.add_error(
                    f"Price change inconsistency for {stock.symbol}: "
                    f"reported {stock.price_change}, calculated {expected_change}"
                )
            else:
                result.add_warning(
                    f"Price change inconsistency for {stock.symbol}: "
                    f"reported {stock.price_change}, calculated {expected_change}"
                )
        
        # Validate price change percentage
        if stock.previous_close > 0:
            expected_percent = (stock.price_change / stock.previous_close) * 100
            if abs(stock.price_change_percent - expected_percent) > 0.1:
                if self.validation_level == ValidationLevel.STRICT:
                    result.add_error(
                        f"Price change percent inconsistency for {stock.symbol}: "
                        f"reported {stock.price_change_percent}, calculated {expected_percent}"
                    )
                else:
                    result.add_warning(
                        f"Price change percent inconsistency for {stock.symbol}: "
                        f"reported {stock.price_change_percent}, calculated {expected_percent}"
                    )
        
        # Validate extreme price movements
        if abs(stock.price_change_percent) > self.max_price_change_threshold * 100:
            result.add_warning(
                f"Extreme price movement for {stock.symbol}: "
                f"{stock.price_change_percent:.2f}%"
            )
        
        # Validate market cap
        if stock.market_cap < self.min_market_cap:
            result.add_warning(
                f"Low market cap for {stock.symbol}: "
                f"{stock.market_cap:,.0f} CNY"
            )
        
        # Validate data freshness
        if not self._is_data_fresh(stock.last_updated):
            result.add_warning(
                f"Stale data for {stock.symbol}: "
                f"last updated {stock.last_updated}"
            )
        
        # Validate sector
        if not stock.sector or stock.sector == "Unknown":
            result.add_info(f"Missing sector information for {stock.symbol}")
        
        return result
    
    def validate_volume_data(
        self, 
        trading_volumes: List[TradingVolume]
    ) -> ValidationResult:
        """Validate trading volume data.
        
        Args:
            trading_volumes: List of TradingVolume objects to validate
            
        Returns:
            ValidationResult with validation outcomes
        """
        start_time = datetime.now()
        result = ValidationResult()
        
        if not trading_volumes:
            result.add_warning("No volume data to validate")
            result.validation_time = 0.0
            result.records_validated = 0
            return result
        
        self.logger.info(f"Validating {len(trading_volumes)} volume records")
        
        total_volume = 0
        for i, tv in enumerate(trading_volumes):
            try:
                volume_result = self._validate_single_volume(tv)
                result.merge(volume_result)
                
                # Aggregate statistics
                total_volume += tv.volume
                
            except Exception as e:
                result.add_error(f"Error validating volume record {i}: {str(e)}")
                self.logger.error(f"Error validating volume record {i}: {e}")
        
        # Validate aggregate statistics
        if trading_volumes:
            avg_volume = total_volume / len(trading_volumes)
            if avg_volume < self.min_volume_threshold:
                result.add_warning(
                    f"Low average volume across all stocks: {avg_volume:,.0f}"
                )
        
        validation_time = (datetime.now() - start_time).total_seconds()
        result.validation_time = validation_time
        result.records_validated = len(trading_volumes)
        
        self.logger.info(
            f"Volume validation completed: {result.records_validated} records, "
            f"Valid: {result.is_valid}, Errors: {len(result.errors)}, "
            f"Warnings: {len(result.warnings)}"
        )
        
        return result
    
    def _validate_single_volume(self, tv: TradingVolume) -> ValidationResult:
        """Validate a single TradingVolume object."""
        result = ValidationResult()
        
        # Validate basic fields
        if not tv.stock_symbol:
            result.add_error("Missing stock symbol in volume data")
            return result
        
        if tv.volume <= 0:
            result.add_error(f"Invalid volume for {tv.stock_symbol}: {tv.volume}")
            
        if tv.turnover < 0:
            result.add_error(f"Invalid turnover for {tv.stock_symbol}: {tv.turnover}")
        
        # Validate turnover consistency with volume
        if tv.volume > 0 and tv.turnover > 0:
            # Calculate implied price per share
            implied_price = tv.turnover / tv.volume
            
            # Reasonable price range: 0.1 to 10000 CNY per share
            if implied_price < 0.1 or implied_price > 10000:
                result.add_warning(
                    f"Unusual implied price per share for {tv.stock_symbol}: "
                    f"{implied_price:.2f} CNY"
                )
        
        # Validate low volume
        if tv.volume < self.min_volume_threshold:
            result.add_warning(
                f"Low trading volume for {tv.stock_symbol}: {tv.volume:,.0f}"
            )
        
        # Validate normalization state
        if tv.normalized_volume is not None:
            if not (0.0 <= tv.normalized_volume <= 1.0):
                result.add_error(
                    f"Invalid normalized volume for {tv.stock_symbol}: "
                    f"{tv.normalized_volume}"
                )
        else:
            result.add_info(f"Volume not normalized for {tv.stock_symbol}")
        
        # Validate data freshness
        if not self._is_data_fresh(tv.date):
            result.add_warning(
                f"Stale volume data for {tv.stock_symbol}: "
                f"date {tv.date}"
            )
        
        return result
    
    def validate_heat_data(
        self, 
        market_heats: List[MarketHeat]
    ) -> ValidationResult:
        """Validate market heat data.
        
        Args:
            market_heats: List of MarketHeat objects to validate
            
        Returns:
            ValidationResult with validation outcomes
        """
        start_time = datetime.now()
        result = ValidationResult()
        
        if not market_heats:
            result.add_warning("No heat data to validate")
            result.validation_time = 0.0
            result.records_validated = 0
            return result
        
        self.logger.info(f"Validating {len(market_heats)} heat records")
        
        for i, mh in enumerate(market_heats):
            try:
                heat_result = self._validate_single_heat(mh)
                result.merge(heat_result)
                
            except Exception as e:
                result.add_error(f"Error validating heat record {i}: {str(e)}")
                self.logger.error(f"Error validating heat record {i}: {e}")
        
        validation_time = (datetime.now() - start_time).total_seconds()
        result.validation_time = validation_time
        result.records_validated = len(market_heats)
        
        self.logger.info(
            f"Heat validation completed: {result.records_validated} records, "
            f"Valid: {result.is_valid}, Errors: {len(result.errors)}, "
            f"Warnings: {len(result.warnings)}"
        )
        
        return result
    
    def _validate_single_heat(self, mh: MarketHeat) -> ValidationResult:
        """Validate a single MarketHeat object."""
        result = ValidationResult()
        
        # Validate basic fields
        if not mh.stock_symbol:
            result.add_error("Missing stock symbol in heat data")
            return result
        
        if mh.heat_score < 0:
            result.add_error(f"Invalid heat score for {mh.stock_symbol}: {mh.heat_score}")
            
        if mh.attention_index < 0:
            result.add_error(f"Invalid attention index for {mh.stock_symbol}: {mh.attention_index}")
        
        # Validate consistency between heat score and attention index
        if mh.heat_score == 0 and mh.attention_index > 0:
            result.add_warning(
                f"Zero heat score but positive attention index for {mh.stock_symbol}"
            )
        
        # Validate normalization state
        if mh.normalized_heat is not None:
            if not (0.0 <= mh.normalized_heat <= 1.0):
                result.add_error(
                    f"Invalid normalized heat for {mh.stock_symbol}: "
                    f"{mh.normalized_heat}"
                )
        else:
            result.add_info(f"Heat not normalized for {mh.stock_symbol}")
        
        # Validate data freshness
        if not self._is_data_fresh(mh.date):
            result.add_warning(
                f"Stale heat data for {mh.stock_symbol}: "
                f"date {mh.date}"
            )
        
        return result
    
    def validate_momentum_data(
        self, 
        momentum_scores: List[MomentumScore]
    ) -> ValidationResult:
        """Validate momentum score data.
        
        Args:
            momentum_scores: List of MomentumScore objects to validate
            
        Returns:
            ValidationResult with validation outcomes
        """
        start_time = datetime.now()
        result = ValidationResult()
        
        if not momentum_scores:
            result.add_warning("No momentum data to validate")
            result.validation_time = 0.0
            result.records_validated = 0
            return result
        
        self.logger.info(f"Validating {len(momentum_scores)} momentum records")
        
        for i, ms in enumerate(momentum_scores):
            try:
                momentum_result = self._validate_single_momentum(ms)
                result.merge(momentum_result)
                
            except Exception as e:
                result.add_error(f"Error validating momentum record {i}: {str(e)}")
                self.logger.error(f"Error validating momentum record {i}: {e}")
        
        validation_time = (datetime.now() - start_time).total_seconds()
        result.validation_time = validation_time
        result.records_validated = len(momentum_scores)
        
        self.logger.info(
            f"Momentum validation completed: {result.records_validated} records, "
            f"Valid: {result.is_valid}, Errors: {len(result.errors)}, "
            f"Warnings: {len(result.warnings)}"
        )
        
        return result
    
    def _validate_single_momentum(self, ms: MomentumScore) -> ValidationResult:
        """Validate a single MomentumScore object."""
        result = ValidationResult()
        
        # Validate basic fields
        if not ms.stock_symbol:
            result.add_error("Missing stock symbol in momentum data")
            return result
        
        # Validate R-squared
        if not (0.0 <= ms.r_squared <= 1.0):
            result.add_error(f"Invalid R-squared for {ms.stock_symbol}: {ms.r_squared}")
        
        # Validate R-squared quality thresholds
        if ms.r_squared < 0.3:
            result.add_warning(
                f"Low R-squared for {ms.stock_symbol}: {ms.r_squared:.3f} "
                f"(weak trend reliability)"
            )
        elif ms.r_squared > 0.9:
            result.add_info(
                f"High R-squared for {ms.stock_symbol}: {ms.r_squared:.3f} "
                f"(strong trend reliability)"
            )
        
        # Validate trend slope reasonableness
        if abs(ms.trend_slope) > 1.0:
            result.add_warning(
                f"Extreme trend slope for {ms.stock_symbol}: {ms.trend_slope:.4f}"
            )
        
        # Validate calculation status
        if ms.calculation_status == CalculationStatus.FAILED:
            result.add_error(f"Momentum calculation failed for {ms.stock_symbol}")
        elif ms.calculation_status != CalculationStatus.COMPLETED:
            result.add_warning(
                f"Momentum calculation not completed for {ms.stock_symbol}: "
                f"{ms.calculation_status}"
            )
        
        # Validate data freshness
        if not self._is_data_fresh(ms.calculation_date):
            result.add_warning(
                f"Stale momentum data for {ms.stock_symbol}: "
                f"calculated on {ms.calculation_date}"
            )
        
        return result
    
    def validate_combined_data_consistency(
        self,
        stocks: List[Stock],
        trading_volumes: List[TradingVolume],
        market_heats: List[MarketHeat]
    ) -> ValidationResult:
        """Validate consistency across different data types.
        
        Args:
            stocks: List of Stock objects
            trading_volumes: List of TradingVolume objects
            market_heats: List of MarketHeat objects
            
        Returns:
            ValidationResult with consistency validation outcomes
        """
        start_time = datetime.now()
        result = ValidationResult()
        
        self.logger.info("Validating data consistency across data types")
        
        # Create symbol sets
        stock_symbols = {s.symbol for s in stocks}
        volume_symbols = {tv.stock_symbol for tv in trading_volumes}
        heat_symbols = {mh.stock_symbol for mh in market_heats}
        
        # Check symbol consistency
        all_symbols = stock_symbols.union(volume_symbols).union(heat_symbols)
        
        # Stocks without volume data
        stocks_without_volume = stock_symbols - volume_symbols
        if stocks_without_volume:
            result.add_warning(
                f"{len(stocks_without_volume)} stocks have no volume data: "
                f"{list(stocks_without_volume)[:5]}..."
            )
        
        # Stocks without heat data
        stocks_without_heat = stock_symbols - heat_symbols
        if stocks_without_heat:
            result.add_warning(
                f"{len(stocks_without_heat)} stocks have no heat data: "
                f"{list(stocks_without_heat)[:5]}..."
            )
        
        # Volume data without stock info
        volume_without_stocks = volume_symbols - stock_symbols
        if volume_without_stocks:
            result.add_info(
                f"{len(volume_without_stocks)} volume records for unknown stocks"
            )
        
        # Heat data without stock info
        heat_without_stocks = heat_symbols - stock_symbols
        if heat_without_stocks:
            result.add_info(
                f"{len(heat_without_stocks)} heat records for unknown stocks"
            )
        
        validation_time = (datetime.now() - start_time).total_seconds()
        result.validation_time = validation_time
        result.records_validated = len(all_symbols)
        
        self.logger.info(
            f"Consistency validation completed: {result.records_validated} unique symbols, "
            f"Valid: {result.is_valid}, Errors: {len(result.errors)}, "
            f"Warnings: {len(result.warnings)}"
        )
        
        return result
    
    def _is_data_fresh(self, data_date: date) -> bool:
        """Check if data is fresh enough to use.
        
        Args:
            data_date: Date of the data
            
        Returns:
            True if data is fresh, False otherwise
        """
        if isinstance(data_date, datetime):
            data_date = data_date.date()
        elif isinstance(data_date, str):
            try:
                data_date = datetime.fromisoformat(data_date).date()
            except:
                return False
        
        if not isinstance(data_date, date):
            return False
        
        days_old = (date.today() - data_date).days
        return days_old <= self.max_days_old
    
    def set_validation_level(self, level: ValidationLevel) -> None:
        """Update validation level."""
        self.validation_level = level
        self.logger.info(f"Validation level set to {level}")
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """Get summary of validation configuration."""
        return {
            'validation_level': self.validation_level,
            'min_volume_threshold': self.min_volume_threshold,
            'max_price_change_threshold': self.max_price_change_threshold,
            'min_market_cap': self.min_market_cap,
            'max_days_old': self.max_days_old
        }
    
    async def validate_stock_data_async(
        self, 
        stocks: List[Stock]
    ) -> ValidationResult:
        """Async version of validate_stock_data."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.validate_stock_data, stocks)
    
    async def validate_volume_data_async(
        self, 
        trading_volumes: List[TradingVolume]
    ) -> ValidationResult:
        """Async version of validate_volume_data."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.validate_volume_data, trading_volumes)
    
    async def validate_heat_data_async(
        self, 
        market_heats: List[MarketHeat]
    ) -> ValidationResult:
        """Async version of validate_heat_data."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.validate_heat_data, market_heats)
    
    async def validate_momentum_data_async(
        self, 
        momentum_scores: List[MomentumScore]
    ) -> ValidationResult:
        """Async version of validate_momentum_data."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.validate_momentum_data, momentum_scores)