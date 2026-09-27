"""Dependency injection and service management."""

from typing import Optional
from fastapi import Depends, HTTPException, status
from loguru import logger

from src.config.settings import Settings, get_settings
from src.data.fetcher import DataFetcher
from src.data.processor import DataProcessor
from src.data.validator import DataValidator, ValidationLevel
from src.analysis.momentum import MomentumCalculator
from src.analysis.screener import StockScreener
from src.analysis.ranker import StockRanker
from src.visualization.charts import ChartGenerator
from src.visualization.momentum_charts import MomentumChartGenerator
from src.visualization.dashboard import DashboardGenerator


class Services:
    """Container for all application services."""
    
    def __init__(self):
        self.data_fetcher: Optional[DataFetcher] = None
        self.data_processor: Optional[DataProcessor] = None
        self.data_validator: Optional[DataValidator] = None
        self.momentum_calculator: Optional[MomentumCalculator] = None
        self.stock_screener: Optional[StockScreener] = None
        self.stock_ranker: Optional[StockRanker] = None
        self.chart_generator: Optional[ChartGenerator] = None
        self.momentum_chart_generator: Optional[MomentumChartGenerator] = None
        self.dashboard_generator: Optional[DashboardGenerator] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize all services."""
        if self._initialized:
            return
        
        try:
            logger.info("Initializing application services...")
            
            # Data services
            self.data_fetcher = DataFetcher()
            self.data_processor = DataProcessor()
            self.data_validator = DataValidator(ValidationLevel.MODERATE)
            
            # Analysis services
            self.momentum_calculator = MomentumCalculator()
            self.stock_screener = StockScreener(
                data_fetcher=self.data_fetcher,
                data_processor=self.data_processor,
                data_validator=self.data_validator,
                momentum_calculator=self.momentum_calculator
            )
            self.stock_ranker = StockRanker()
            
            # Visualization services
            self.chart_generator = ChartGenerator()
            self.momentum_chart_generator = MomentumChartGenerator()
            self.dashboard_generator = DashboardGenerator()
            
            self._initialized = True
            logger.info("Application services initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize services: {e}")
            raise
    
    async def shutdown(self):
        """Shutdown all services and cleanup resources."""
        if not self._initialized:
            return
        
        try:
            logger.info("Shutting down application services...")
            
            # Cleanup resources if needed
            # Add any cleanup logic for services that require it
            
            self._initialized = False
            logger.info("Application services shut down successfully")
            
        except Exception as e:
            logger.error(f"Error during service shutdown: {e}")
            raise


# Global services instance
_services: Optional[Services] = None


async def get_services() -> Services:
    """Get application services (FastAPI dependency)."""
    global _services
    
    if _services is None:
        _services = Services()
        await _services.initialize()
    
    if not _services._initialized:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Services not initialized"
        )
    
    return _services


# Convenience dependencies for specific services
async def get_data_fetcher(services: Services = Depends(get_services)) -> DataFetcher:
    """Get data fetcher service."""
    if services.data_fetcher is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Data fetcher service not available"
        )
    return services.data_fetcher


async def get_stock_screener(services: Services = Depends(get_services)) -> StockScreener:
    """Get stock screener service."""
    if services.stock_screener is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stock screener service not available"
        )
    return services.stock_screener


async def get_chart_generator(services: Services = Depends(get_services)) -> ChartGenerator:
    """Get chart generator service."""
    if services.chart_generator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart generator service not available"
        )
    return services.chart_generator


async def get_momentum_chart_generator(services: Services = Depends(get_services)) -> MomentumChartGenerator:
    """Get momentum chart generator service."""
    if services.momentum_chart_generator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Momentum chart generator service not available"
        )
    return services.momentum_chart_generator


async def get_dashboard_generator(services: Services = Depends(get_services)) -> DashboardGenerator:
    """Get dashboard generator service."""
    if services.dashboard_generator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard generator service not available"
        )
    return services.dashboard_generator