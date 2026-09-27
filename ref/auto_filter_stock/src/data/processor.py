"""Data processor service for normalizing and processing stock data."""

import statistics
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from loguru import logger

from src.models.trading_volume import TradingVolume, VolumeState
from src.models.market_heat import MarketHeat, HeatState
from src.models.stock import Stock


@dataclass
class ProcessingResult:
    """Result of data processing operation."""
    success: bool
    processed_data: Optional[Dict[str, List]] = None
    error: Optional[str] = None
    processing_time: float = 0.0
    records_processed: int = 0


class DataProcessor:
    """Service for processing and normalizing stock data."""
    
    def __init__(self):
        self.logger = logger.bind(service="DataProcessor")
    
    def process_volume_data(
        self, 
        volume_data: List[Dict[str, Any]]
    ) -> ProcessingResult:
        """Process raw volume data and create TradingVolume models.
        
        Args:
            volume_data: Raw volume data from fetcher
            
        Returns:
            ProcessingResult with processed TradingVolume objects
        """
        start_time = datetime.now()
        
        if not volume_data:
            return ProcessingResult(
                success=True,
                processed_data={'trading_volumes': []},
                processing_time=0.0,
                records_processed=0
            )
        
        try:
            self.logger.info(f"Processing {len(volume_data)} volume records")
            
            # Create TradingVolume objects from raw data
            trading_volumes = []
            for data in volume_data:
                try:
                    trading_volume = TradingVolume(
                        stock_symbol=data['stock_symbol'],
                        stock_name=data.get('stock_name'),
                        date=data['date'],
                        volume=data['volume'],
                        turnover=data['turnover']
                    )
                    trading_volumes.append(trading_volume)
                    
                except Exception as e:
                    self.logger.warning(f"Error creating TradingVolume from data {data}: {e}")
                    continue
            
            self.logger.info(f"Successfully created {len(trading_volumes)} TradingVolume objects")
            
            # Apply Min-Max normalization
            normalized_volumes = self._normalize_volumes(trading_volumes)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return ProcessingResult(
                success=True,
                processed_data={'trading_volumes': normalized_volumes},
                processing_time=processing_time,
                records_processed=len(normalized_volumes)
            )
            
        except Exception as e:
            self.logger.error(f"Error processing volume data: {e}")
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return ProcessingResult(
                success=False,
                error=f"Failed to process volume data: {str(e)}",
                processing_time=processing_time,
                records_processed=0
            )
    
    def process_heat_data(
        self, 
        heat_data: List[Dict[str, Any]]
    ) -> ProcessingResult:
        """Process raw heat data and create MarketHeat models.
        
        Args:
            heat_data: Raw heat data from fetcher
            
        Returns:
            ProcessingResult with processed MarketHeat objects
        """
        start_time = datetime.now()
        
        if not heat_data:
            return ProcessingResult(
                success=True,
                processed_data={'market_heats': []},
                processing_time=0.0,
                records_processed=0
            )
        
        try:
            self.logger.info(f"Processing {len(heat_data)} heat records")
            
            # Create MarketHeat objects from raw data
            market_heats = []
            for data in heat_data:
                try:
                    market_heat = MarketHeat(
                        stock_symbol=data['stock_symbol'],
                        stock_name=data.get('stock_name'),
                        date=data['date'],
                        heat_score=data['heat_score'],
                        attention_index=data['attention_index']
                    )
                    market_heats.append(market_heat)
                    
                except Exception as e:
                    self.logger.warning(f"Error creating MarketHeat from data {data}: {e}")
                    continue
            
            self.logger.info(f"Successfully created {len(market_heats)} MarketHeat objects")
            
            # Apply Min-Max normalization
            normalized_heats = self._normalize_heats(market_heats)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return ProcessingResult(
                success=True,
                processed_data={'market_heats': normalized_heats},
                processing_time=processing_time,
                records_processed=len(normalized_heats)
            )
            
        except Exception as e:
            self.logger.error(f"Error processing heat data: {e}")
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return ProcessingResult(
                success=False,
                error=f"Failed to process heat data: {str(e)}",
                processing_time=processing_time,
                records_processed=0
            )
    
    def process_stock_details(
        self, 
        stock_details: List[Dict[str, Any]]
    ) -> ProcessingResult:
        """Process raw stock detail data and create Stock models.
        
        Args:
            stock_details: Raw stock detail data from fetcher
            
        Returns:
            ProcessingResult with processed Stock objects
        """
        start_time = datetime.now()
        
        if not stock_details:
            return ProcessingResult(
                success=True,
                processed_data={'stocks': []},
                processing_time=0.0,
                records_processed=0
            )
        
        try:
            self.logger.info(f"Processing {len(stock_details)} stock detail records")
            
            # Create Stock objects from raw data
            stocks = []
            for data in stock_details:
                try:
                    stock = Stock(
                        symbol=data['symbol'],
                        name=data['name'],
                        current_price=data['current_price'],
                        previous_close=data['previous_close'],
                        price_change=data['price_change'],
                        price_change_percent=data['price_change_percent'],
                        market_cap=data['market_cap'],
                        sector=data['sector']
                    )
                    stocks.append(stock)
                    
                except Exception as e:
                    self.logger.warning(f"Error creating Stock from data {data}: {e}")
                    continue
            
            self.logger.info(f"Successfully created {len(stocks)} Stock objects")
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return ProcessingResult(
                success=True,
                processed_data={'stocks': stocks},
                processing_time=processing_time,
                records_processed=len(stocks)
            )
            
        except Exception as e:
            self.logger.error(f"Error processing stock details: {e}")
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return ProcessingResult(
                success=False,
                error=f"Failed to process stock details: {str(e)}",
                processing_time=processing_time,
                records_processed=0
            )
    
    def _normalize_volumes(
        self, 
        trading_volumes: List[TradingVolume]
    ) -> List[TradingVolume]:
        """Apply Min-Max normalization to trading volumes.
        
        Args:
            trading_volumes: List of TradingVolume objects
            
        Returns:
            List of TradingVolume objects with normalized values
        """
        if not trading_volumes:
            return trading_volumes
        
        try:
            # Extract volumes for normalization
            volumes = [tv.volume for tv in trading_volumes]
            
            if len(volumes) < 2:
                # Can't normalize with less than 2 values
                for tv in trading_volumes:
                    tv.normalized_volume = 1.0
                    tv.state = VolumeState.PROCESSED
                return trading_volumes
            
            min_volume = min(volumes)
            max_volume = max(volumes)
            
            if min_volume == max_volume:
                # All volumes are the same
                for tv in trading_volumes:
                    tv.normalized_volume = 1.0
                    tv.state = VolumeState.PROCESSED
            else:
                # Apply Min-Max normalization
                for tv in trading_volumes:
                    tv.normalize(min_volume, max_volume)
            
            # Set rankings
            self._set_volume_rankings(trading_volumes)
            
            self.logger.info(f"Normalized {len(trading_volumes)} volume records")
            return trading_volumes
            
        except Exception as e:
            self.logger.error(f"Error normalizing volumes: {e}")
            # Set default values on error
            for tv in trading_volumes:
                tv.normalized_volume = 0.5  # Default middle value
                tv.state = VolumeState.PROCESSED
            return trading_volumes
    
    def _normalize_heats(
        self, 
        market_heats: List[MarketHeat]
    ) -> List[MarketHeat]:
        """Apply Min-Max normalization to market heat scores.
        
        Args:
            market_heats: List of MarketHeat objects
            
        Returns:
            List of MarketHeat objects with normalized values
        """
        if not market_heats:
            return market_heats
        
        try:
            # Extract heat scores for normalization
            heat_scores = [mh.heat_score for mh in market_heats]
            
            if len(heat_scores) < 2:
                # Can't normalize with less than 2 values
                for mh in market_heats:
                    mh.normalized_heat = 1.0
                    mh.state = HeatState.PROCESSED
                return market_heats
            
            min_heat = min(heat_scores)
            max_heat = max(heat_scores)
            
            if min_heat == max_heat:
                # All heat scores are the same
                for mh in market_heats:
                    mh.normalized_heat = 1.0
                    mh.state = HeatState.PROCESSED
            else:
                # Apply Min-Max normalization
                for mh in market_heats:
                    mh.normalize(min_heat, max_heat)
            
            # Set rankings
            self._set_heat_rankings(market_heats)
            
            self.logger.info(f"Normalized {len(market_heats)} heat records")
            return market_heats
            
        except Exception as e:
            self.logger.error(f"Error normalizing heats: {e}")
            # Set default values on error
            for mh in market_heats:
                mh.normalized_heat = 0.5  # Default middle value
                mh.state = HeatState.PROCESSED
            return market_heats
    
    def _set_volume_rankings(
        self, 
        trading_volumes: List[TradingVolume]
    ) -> None:
        """Set rankings for trading volumes (higher volume = better rank).
        
        Args:
            trading_volumes: List of TradingVolume objects
        """
        if not trading_volumes:
            return
        
        # Sort by volume descending (higher volume = better rank)
        sorted_volumes = sorted(
            trading_volumes, 
            key=lambda x: x.volume, 
            reverse=True
        )
        
        total_stocks = len(sorted_volumes)
        
        for rank, tv in enumerate(sorted_volumes, 1):
            tv.set_rank(rank, total_stocks)
    
    def _set_heat_rankings(
        self, 
        market_heats: List[MarketHeat]
    ) -> None:
        """Set rankings for market heat (higher heat = better rank).
        
        Args:
            market_heats: List of MarketHeat objects
        """
        if not market_heats:
            return
        
        # Sort by heat score descending (higher heat = better rank)
        sorted_heats = sorted(
            market_heats, 
            key=lambda x: x.heat_score, 
            reverse=True
        )
        
        total_stocks = len(sorted_heats)
        
        for rank, mh in enumerate(sorted_heats, 1):
            mh.set_rank(rank, total_stocks)
    
    def combine_volume_and_heat_data(
        self, 
        trading_volumes: List[TradingVolume],
        market_heats: List[MarketHeat],
        min_intersection: int = 10
    ) -> Tuple[List[TradingVolume], List[MarketHeat]]:
        """Find intersection of top volume and heat stocks.
        
        Args:
            trading_volumes: List of TradingVolume objects
            market_heats: List of MarketHeat objects
            min_intersection: Minimum number of stocks required in intersection
            
        Returns:
            Tuple of (volume_stocks, heat_stocks) that appear in both lists
        """
        if not trading_volumes or not market_heats:
            return [], []
        
        # Create sets of stock symbols for efficient lookup
        volume_symbols = {tv.stock_symbol for tv in trading_volumes}
        heat_symbols = {mh.stock_symbol for mh in market_heats}
        
        # Find intersection
        intersection_symbols = volume_symbols.intersection(heat_symbols)
        
        self.logger.info(f"Found {len(intersection_symbols)} stocks in volume-heat intersection")
        
        if len(intersection_symbols) < min_intersection:
            self.logger.warning(
                f"Intersection size {len(intersection_symbols)} is less than minimum {min_intersection}. "
                "Consider adjusting filtering parameters."
            )
        
        # Filter lists to intersection
        filtered_volumes = [tv for tv in trading_volumes if tv.stock_symbol in intersection_symbols]
        filtered_heats = [mh for mh in market_heats if mh.stock_symbol in intersection_symbols]
        
        self.logger.info(
            f"Filtered to {len(filtered_volumes)} volume records and {len(filtered_heats)} heat records"
        )
        
        return filtered_volumes, filtered_heats
    
    def calculate_combined_scores(
        self, 
        trading_volumes: List[TradingVolume],
        market_heats: List[MarketHeat],
        volume_weight: float = 0.5,
        heat_weight: float = 0.5
    ) -> Dict[str, float]:
        """Calculate combined scores from volume and heat data.
        
        Args:
            trading_volumes: List of TradingVolume objects (must be normalized)
            market_heats: List of MarketHeat objects (must be normalized)
            volume_weight: Weight for volume component
            heat_weight: Weight for heat component
            
        Returns:
            Dictionary mapping stock symbols to combined scores
        """
        if abs(volume_weight + heat_weight - 1.0) > 0.01:
            raise ValueError("Volume and heat weights must sum to 1.0")
        
        # Create lookup dictionaries
        volume_dict = {tv.stock_symbol: tv for tv in trading_volumes}
        heat_dict = {mh.stock_symbol: mh for mh in market_heats}
        
        # Find common stocks
        common_symbols = set(volume_dict.keys()).intersection(set(heat_dict.keys()))
        
        combined_scores = {}
        
        for symbol in common_symbols:
            tv = volume_dict[symbol]
            mh = heat_dict[symbol]
            
            # Use normalized values, fallback to raw values if not normalized
            volume_score = tv.normalized_volume if tv.normalized_volume is not None else 0.5
            heat_score = mh.normalized_heat if mh.normalized_heat is not None else 0.5
            
            # Calculate weighted combined score
            combined_score = (volume_weight * volume_score) + (heat_weight * heat_score)
            combined_scores[symbol] = combined_score
        
        self.logger.info(f"Calculated combined scores for {len(combined_scores)} stocks")
        return combined_scores
    
    def get_top_stocks_by_combined_score(
        self, 
        combined_scores: Dict[str, float],
        top_n: int = 30
    ) -> List[Tuple[str, float]]:
        """Get top stocks by combined score.
        
        Args:
            combined_scores: Dictionary of stock symbols to scores
            top_n: Number of top stocks to return
            
        Returns:
            List of tuples (symbol, score) sorted by score descending
        """
        if not combined_scores:
            return []
        
        # Sort by score descending
        sorted_stocks = sorted(
            combined_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        # Return top N
        top_stocks = sorted_stocks[:top_n]
        
        self.logger.info(f"Selected top {len(top_stocks)} stocks by combined score")
        return top_stocks
    
    async def process_volume_data_async(
        self, 
        volume_data: List[Dict[str, Any]]
    ) -> ProcessingResult:
        """Async version of process_volume_data."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.process_volume_data, volume_data)
    
    async def process_heat_data_async(
        self, 
        heat_data: List[Dict[str, Any]]
    ) -> ProcessingResult:
        """Async version of process_heat_data."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.process_heat_data, heat_data)
    
    async def process_stock_details_async(
        self, 
        stock_details: List[Dict[str, Any]]
    ) -> ProcessingResult:
        """Async version of process_stock_details."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.process_stock_details, stock_details)