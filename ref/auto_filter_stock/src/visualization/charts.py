"""Chart generation service for K-line charts and technical analysis visualization."""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import pandas as pd
import numpy as np

from loguru import logger

from src.config.settings import get_settings
from src.models.stock import Stock
from src.models.trading_volume import TradingVolume
from src.models.momentum_score import MomentumScore


@dataclass
class ChartConfig:
    """Configuration for chart generation."""
    width: int = 1200
    height: int = 800
    theme: str = "plotly_white"
    show_volume: bool = True
    show_ma: bool = True
    ma_periods: List[int] = None
    show_indicators: bool = True
    
    def __post_init__(self):
        if self.ma_periods is None:
            self.ma_periods = [5, 10, 20]


@dataclass
class ChartResult:
    """Result of chart generation."""
    success: bool
    figure: Optional[go.Figure] = None
    html_content: Optional[str] = None
    json_data: Optional[Dict] = None
    error: Optional[str] = None
    generation_time: float = 0.0


class ChartGenerator:
    """Service for generating K-line charts and technical analysis visualizations."""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger.bind(service="ChartGenerator")
        self.default_config = ChartConfig()
    
    def generate_kline_chart(
        self,
        stock_symbol: str,
        price_data: List[Dict[str, Any]],
        volume_data: Optional[List[TradingVolume]] = None,
        title: Optional[str] = None,
        config: Optional[ChartConfig] = None
    ) -> ChartResult:
        """Generate K-line (candlestick) chart with volume and technical indicators.
        
        Args:
            stock_symbol: Stock symbol (e.g., "000001.SZ")
            price_data: List of price data with 'date', 'open', 'high', 'low', 'close', 'volume'
            volume_data: Optional volume data for volume subplot
            title: Chart title
            config: Chart configuration options
            
        Returns:
            ChartResult with generated chart or error information
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        title = title or f"{stock_symbol} K-Line Chart"
        
        try:
            self.logger.info(f"Generating K-line chart for {stock_symbol}")
            
            # Validate input data
            if not price_data:
                return ChartResult(
                    success=False,
                    error="No price data provided",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Prepare data for plotting
            df = self._prepare_price_data(price_data)
            if df.empty:
                return ChartResult(
                    success=False,
                    error="Invalid or insufficient price data",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Create subplots
            rows = 2 if config.show_volume else 1
            row_heights = [0.7, 0.3] if config.show_volume else [1.0]
            
            fig = make_subplots(
                rows=rows, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                subplot_titles=('Price', 'Volume') if config.show_volume else None,
                row_heights=row_heights
            )
            
            # Add candlestick chart
            fig.add_trace(
                go.Candlestick(
                    x=df['date'],
                    open=df['open'],
                    high=df['high'],
                    low=df['low'],
                    close=df['close'],
                    name="K-Line",
                    increasing_line_color='red',
                    decreasing_line_color='green',
                    increasing_fillcolor='red',
                    decreasing_fillcolor='green'
                ),
                row=1, col=1
            )
            
            # Add moving averages if requested
            if config.show_ma:
                for period in config.ma_periods:
                    if len(df) >= period:
                        ma_col = f'ma_{period}'
                        df[ma_col] = df['close'].rolling(window=period).mean()
                        fig.add_trace(
                            go.Scatter(
                                x=df['date'],
                                y=df[ma_col],
                                name=f'MA{period}',
                                line=dict(width=1)
                            ),
                            row=1, col=1
                        )
            
            # Add volume subplot if requested
            if config.show_volume and 'volume' in df.columns:
                fig.add_trace(
                    go.Bar(
                        x=df['date'],
                        y=df['volume'],
                        name='Volume',
                        marker_color='lightblue'
                    ),
                    row=2, col=1
                )
            
            # Update layout
            fig.update_layout(
                title=title,
                xaxis_title='Date',
                yaxis_title='Price (CNY)',
                xaxis_rangeslider_visible=False,
                width=config.width,
                height=config.height,
                template=config.theme,
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            
            # Update x-axis for better date formatting
            fig.update_xaxes(
                rangeslider_visible=False,
                rangeselector=dict(
                    buttons=list([
                        dict(count=7, label="1w", step="day", stepmode="backward"),
                        dict(count=1, label="1m", step="month", stepmode="backward"),
                        dict(count=3, label="3m", step="month", stepmode="backward"),
                        dict(count=6, label="6m", step="month", stepmode="backward"),
                        dict(step="all")
                    ])
                )
            )
            
            # Generate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"K-line chart generated for {stock_symbol} in {generation_time:.3f}s")
            
            return ChartResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating K-line chart for {stock_symbol}: {e}")
            return ChartResult(
                success=False,
                error=f"Chart generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def generate_volume_chart(
        self,
        stock_symbol: str,
        volume_data: List[TradingVolume],
        title: Optional[str] = None,
        config: Optional[ChartConfig] = None
    ) -> ChartResult:
        """Generate volume analysis chart.
        
        Args:
            stock_symbol: Stock symbol
            volume_data: List of trading volume data
            title: Chart title
            config: Chart configuration
            
        Returns:
            ChartResult with generated volume chart
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        title = title or f"{stock_symbol} Volume Analysis"
        
        try:
            self.logger.info(f"Generating volume chart for {stock_symbol}")
            
            if not volume_data:
                return ChartResult(
                    success=False,
                    error="No volume data provided",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Prepare data
            df = self._prepare_volume_data(volume_data)
            if df.empty:
                return ChartResult(
                    success=False,
                    error="Invalid volume data",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Create figure
            fig = go.Figure()
            
            # Add volume bars
            fig.add_trace(
                go.Bar(
                    x=df['date'],
                    y=df['volume'],
                    name='Trading Volume',
                    marker_color='lightblue',
                    opacity=0.7
                )
            )
            
            # Add volume moving average
            if len(df) >= 5:
                df['volume_ma5'] = df['volume'].rolling(window=5).mean()
                fig.add_trace(
                    go.Scatter(
                        x=df['date'],
                        y=df['volume_ma5'],
                        name='Volume MA5',
                        line=dict(color='red', width=2)
                    )
                )
            
            # Add turnover if available
            if 'turnover' in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df['date'],
                        y=df['turnover'],
                        name='Turnover',
                        line=dict(color='green', width=2),
                        yaxis='y2'
                    )
                )
                
                # Add secondary y-axis for turnover
                fig.update_layout(
                    yaxis2=dict(
                        title="Turnover (CNY)",
                        overlaying="y",
                        side="right"
                    )
                )
            
            # Update layout
            fig.update_layout(
                title=title,
                xaxis_title='Date',
                yaxis_title='Volume (Shares)',
                width=config.width,
                height=config.height,
                template=config.theme,
                showlegend=True
            )
            
            # Generate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"Volume chart generated for {stock_symbol} in {generation_time:.3f}s")
            
            return ChartResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating volume chart for {stock_symbol}: {e}")
            return ChartResult(
                success=False,
                error=f"Volume chart generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def generate_comparison_chart(
        self,
        stock_symbols: List[str],
        price_data_dict: Dict[str, List[Dict[str, Any]]],
        metric: str = 'close',
        title: Optional[str] = None,
        config: Optional[ChartConfig] = None
    ) -> ChartResult:
        """Generate comparison chart for multiple stocks.
        
        Args:
            stock_symbols: List of stock symbols to compare
            price_data_dict: Dictionary mapping symbols to price data
            metric: Metric to compare ('close', 'volume', 'change_pct')
            title: Chart title
            config: Chart configuration
            
        Returns:
            ChartResult with generated comparison chart
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        title = title or f"Stock Comparison - {metric.upper()}"
        
        try:
            self.logger.info(f"Generating comparison chart for {len(stock_symbols)} stocks")
            
            if not stock_symbols or not price_data_dict:
                return ChartResult(
                    success=False,
                    error="No stock data provided",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Create figure
            fig = go.Figure()
            
            # Add trace for each stock
            colors = ['red', 'blue', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
            
            for i, symbol in enumerate(stock_symbols):
                if symbol not in price_data_dict:
                    continue
                    
                price_data = price_data_dict[symbol]
                if not price_data:
                    continue
                
                # Prepare data
                df = self._prepare_price_data(price_data)
                if df.empty:
                    continue
                
                # Get metric values
                if metric == 'change_pct':
                    values = df['close'].pct_change() * 100
                    yaxis_title = 'Change (%)'
                elif metric == 'volume':
                    values = df['volume']
                    yaxis_title = 'Volume'
                else:  # close price
                    values = df['close']
                    yaxis_title = 'Price (CNY)'
                
                # Add trace
                fig.add_trace(
                    go.Scatter(
                        x=df['date'],
                        y=values,
                        name=symbol,
                        line=dict(color=colors[i % len(colors)], width=2)
                    )
                )
            
            # Update layout
            fig.update_layout(
                title=title,
                xaxis_title='Date',
                yaxis_title=yaxis_title,
                width=config.width,
                height=config.height,
                template=config.theme,
                showlegend=True
            )
            
            # Generate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"Comparison chart generated in {generation_time:.3f}s")
            
            return ChartResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating comparison chart: {e}")
            return ChartResult(
                success=False,
                error=f"Comparison chart generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def generate_heatmap(
        self,
        data: pd.DataFrame,
        title: Optional[str] = None,
        config: Optional[ChartConfig] = None
    ) -> ChartResult:
        """Generate heatmap for correlation or ranking visualization.
        
        Args:
            data: DataFrame with values for heatmap
            title: Chart title
            config: Chart configuration
            
        Returns:
            ChartResult with generated heatmap
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        title = title or "Data Heatmap"
        
        try:
            self.logger.info("Generating heatmap")
            
            if data.empty:
                return ChartResult(
                    success=False,
                    error="No data provided for heatmap",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Create heatmap
            fig = go.Figure(data=go.Heatmap(
                z=data.values,
                x=data.columns,
                y=data.index,
                colorscale='RdYlBu_r',
                hoverongaps=False
            ))
            
            # Update layout
            fig.update_layout(
                title=title,
                width=config.width,
                height=config.height,
                template=config.theme
            )
            
            # Generate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"Heatmap generated in {generation_time:.3f}s")
            
            return ChartResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating heatmap: {e}")
            return ChartResult(
                success=False,
                error=f"Heatmap generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def generate_ranking_chart(
        self,
        ranking_data: List[Dict[str, Any]],
        title: Optional[str] = None,
        config: Optional[ChartConfig] = None
    ) -> ChartResult:
        """Generate ranking visualization chart.
        
        Args:
            ranking_data: List of ranking data with 'symbol', 'score', 'rank', etc.
            title: Chart title
            config: Chart configuration
            
        Returns:
            ChartResult with generated ranking chart
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        title = title or "Stock Ranking Analysis"
        
        try:
            self.logger.info("Generating ranking chart")
            
            if not ranking_data:
                return ChartResult(
                    success=False,
                    error="No ranking data provided",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Prepare data
            df = pd.DataFrame(ranking_data)
            if df.empty:
                return ChartResult(
                    success=False,
                    error="Invalid ranking data",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Sort by rank
            df = df.sort_values('rank')
            
            # Create subplots
            fig = make_subplots(
                rows=2, cols=1,
                subplot_titles=('Combined Scores', 'Component Breakdown'),
                vertical_spacing=0.1,
                row_heights=[0.6, 0.4]
            )
            
            # Add main score bars
            fig.add_trace(
                go.Bar(
                    x=df['symbol'],
                    y=df['combined_score'],
                    name='Combined Score',
                    marker_color='lightblue',
                    text=df['combined_score'].round(1),
                    textposition='auto'
                ),
                row=1, col=1
            )
            
            # Add component breakdown if available
            if 'volume_score' in df.columns and 'momentum_score' in df.columns:
                fig.add_trace(
                    go.Bar(
                        x=df['symbol'],
                        y=df['volume_score'],
                        name='Volume Score',
                        marker_color='lightgreen'
                    ),
                    row=2, col=1
                )
                
                fig.add_trace(
                    go.Bar(
                        x=df['symbol'],
                        y=df['momentum_score'],
                        name='Momentum Score',
                        marker_color='lightcoral'
                    ),
                    row=2, col=1
                )
            
            # Update layout
            fig.update_layout(
                title=title,
                xaxis_title='Stock Symbol',
                yaxis_title='Score',
                width=config.width,
                height=config.height,
                template=config.theme,
                showlegend=True,
                barmode='group'
            )
            
            # Generate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"Ranking chart generated in {generation_time:.3f}s")
            
            return ChartResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating ranking chart: {e}")
            return ChartResult(
                success=False,
                error=f"Ranking chart generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def _prepare_price_data(self, price_data: List[Dict[str, Any]]) -> pd.DataFrame:
        """Prepare price data for charting."""
        try:
            # Convert to DataFrame
            df = pd.DataFrame(price_data)
            
            if df.empty:
                return pd.DataFrame()
            
            # Ensure required columns exist
            required_cols = ['date', 'open', 'high', 'low', 'close']
            if not all(col in df.columns for col in required_cols):
                self.logger.warning(f"Missing required columns. Available: {df.columns.tolist()}")
                return pd.DataFrame()
            
            # Convert date column
            df['date'] = pd.to_datetime(df['date'])
            
            # Sort by date
            df = df.sort_values('date')
            
            # Ensure numeric columns are properly typed
            numeric_cols = ['open', 'high', 'low', 'close']
            if 'volume' in df.columns:
                numeric_cols.append('volume')
            if 'turnover' in df.columns:
                numeric_cols.append('turnover')
            
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Remove rows with invalid data
            df = df.dropna(subset=['date', 'open', 'high', 'low', 'close'])
            
            # Remove rows with zero or negative prices
            df = df[
                (df['open'] > 0) & (df['high'] > 0) & 
                (df['low'] > 0) & (df['close'] > 0)
            ]
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error preparing price data: {e}")
            return pd.DataFrame()
    
    def _prepare_volume_data(self, volume_data: List[TradingVolume]) -> pd.DataFrame:
        """Prepare volume data for charting."""
        try:
            # Convert to DataFrame
            data = []
            for vol in volume_data:
                data.append({
                    'date': vol.date,
                    'volume': vol.volume,
                    'turnover': vol.turnover
                })
            
            df = pd.DataFrame(data)
            
            if df.empty:
                return pd.DataFrame()
            
            # Convert date column
            df['date'] = pd.to_datetime(df['date'])
            
            # Sort by date
            df = df.sort_values('date')
            
            # Ensure numeric columns are properly typed
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
            if 'turnover' in df.columns:
                df['turnover'] = pd.to_numeric(df['turnover'], errors='coerce')
            
            # Remove rows with invalid data
            df = df.dropna(subset=['date', 'volume'])
            
            # Remove rows with zero or negative volume
            df = df[df['volume'] > 0]
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error preparing volume data: {e}")
            return pd.DataFrame()
    
    def generate_interactive_chart(
        self,
        stock_symbol: str,
        price_data: List[Dict[str, Any]],
        config: Optional[ChartConfig] = None
    ) -> ChartResult:
        """Generate interactive chart with advanced features.
        
        Args:
            stock_symbol: Stock symbol
            price_data: Price data
            config: Chart configuration
            
        Returns:
            ChartResult with interactive chart
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        
        try:
            # Generate basic K-line chart
            result = self.generate_kline_chart(
                stock_symbol=stock_symbol,
                price_data=price_data,
                title=f"{stock_symbol} Interactive Chart",
                config=config
            )
            
            if not result.success:
                return result
            
            # Add interactive features
            fig = result.figure
            
            # Add trend lines
            df = self._prepare_price_data(price_data)
            if not df.empty and len(df) >= 20:
                # Add support and resistance lines (simplified)
                recent_high = df['high'].tail(10).max()
                recent_low = df['low'].tail(10).min()
                
                fig.add_hline(
                    y=recent_high,
                    line_dash="dash",
                    line_color="red",
                    annotation_text="Resistance"
                )
                
                fig.add_hline(
                    y=recent_low,
                    line_dash="dash",
                    line_color="green",
                    annotation_text="Support"
                )
            
            # Update with enhanced interactivity
            fig.update_layout(
                hovermode='x unified',
                spikedistance=-1,
                xaxis=dict(
                    spikethickness=2,
                    spikedash="dot",
                    spikecolor="#999999",
                    spikemode="across"
                )
            )
            
            # Regenerate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            return ChartResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating interactive chart: {e}")
            return ChartResult(
                success=False,
                error=f"Interactive chart generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def save_chart(
        self,
        chart_result: ChartResult,
        output_path: str,
        format: str = 'html'
    ) -> bool:
        """Save chart to file.
        
        Args:
            chart_result: ChartResult from generation
            output_path: Output file path
            format: Output format ('html', 'png', 'jpeg', 'json')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not chart_result.success:
                self.logger.error("Cannot save unsuccessful chart result")
                return False
            
            if format == 'html' and chart_result.html_content:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(chart_result.html_content)
            elif format in ['png', 'jpeg'] and chart_result.figure:
                chart_result.figure.write_image(output_path, format=format)
            elif format == 'json' and chart_result.json_data:
                import json
                import numpy as np
                
                # Convert numpy arrays to lists for JSON serialization
                def convert_numpy(obj):
                    if isinstance(obj, np.ndarray):
                        return obj.tolist()
                    elif isinstance(obj, (np.integer, np.floating)):
                        return obj.item()
                    elif isinstance(obj, dict):
                        return {k: convert_numpy(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [convert_numpy(item) for item in obj]
                    return obj
                
                serializable_data = convert_numpy(chart_result.json_data)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(serializable_data, f, ensure_ascii=False, indent=2)
            else:
                self.logger.error(f"Unsupported format or missing data: {format}")
                return False
            
            self.logger.info(f"Chart saved to {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving chart to {output_path}: {e}")
            return False
    
    async def generate_kline_chart_async(
        self,
        stock_symbol: str,
        price_data: List[Dict[str, Any]],
        volume_data: Optional[List[TradingVolume]] = None,
        title: Optional[str] = None,
        config: Optional[ChartConfig] = None
    ) -> ChartResult:
        """Async version of K-line chart generation."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.generate_kline_chart,
            stock_symbol,
            price_data,
            volume_data,
            title,
            config
        )
    
    async def generate_comparison_chart_async(
        self,
        stock_symbols: List[str],
        price_data_dict: Dict[str, List[Dict[str, Any]]],
        metric: str = 'close',
        title: Optional[str] = None,
        config: Optional[ChartConfig] = None
    ) -> ChartResult:
        """Async version of comparison chart generation."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.generate_comparison_chart,
            stock_symbols,
            price_data_dict,
            metric,
            title,
            config
        )