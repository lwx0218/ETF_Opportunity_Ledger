"""Momentum-specific chart generation for trend analysis and visualization."""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

from loguru import logger

from src.config.settings import get_settings
from src.models.momentum_score import MomentumScore, PriceTrend, TrendStrength


@dataclass
class MomentumChartConfig:
    """Configuration for momentum chart generation."""
    width: int = 1200
    height: int = 800
    theme: str = "plotly_white"
    show_trend_line: bool = True
    show_r_squared: bool = True
    show_volatility: bool = True
    trend_periods: List[int] = None
    confidence_bands: bool = True
    
    def __post_init__(self):
        if self.trend_periods is None:
            self.trend_periods = [5, 10, 20, 60]


@dataclass
class MomentumChartResult:
    """Result of momentum chart generation."""
    success: bool
    figure: Optional[go.Figure] = None
    html_content: Optional[str] = None
    json_data: Optional[Dict] = None
    trend_stats: Optional[Dict] = None
    error: Optional[str] = None
    generation_time: float = 0.0


class MomentumChartGenerator:
    """Service for generating momentum analysis charts and trend visualizations."""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger.bind(service="MomentumChartGenerator")
        self.default_config = MomentumChartConfig()
    
    def generate_momentum_trend_chart(
        self,
        stock_symbol: str,
        price_data: List[Dict[str, Any]],
        momentum_score: Optional[MomentumScore] = None,
        title: Optional[str] = None,
        config: Optional[MomentumChartConfig] = None
    ) -> MomentumChartResult:
        """Generate momentum trend analysis chart with linear regression.
        
        Args:
            stock_symbol: Stock symbol (e.g., "000001.SZ")
            price_data: List of price data with 'date', 'close', 'volume'
            momentum_score: Optional pre-calculated momentum score
            title: Chart title
            config: Chart configuration options
            
        Returns:
            MomentumChartResult with generated chart and trend statistics
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        title = title or f"{stock_symbol} Momentum Trend Analysis"
        
        try:
            self.logger.info(f"Generating momentum trend chart for {stock_symbol}")
            
            # Validate input data
            if not price_data:
                return MomentumChartResult(
                    success=False,
                    error="No price data provided",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Prepare data
            df = self._prepare_price_data(price_data)
            if df.empty or len(df) < 10:  # Need minimum data points
                return MomentumChartResult(
                    success=False,
                    error="Insufficient price data for momentum analysis",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Calculate momentum metrics
            momentum_data = self._calculate_momentum_metrics(df, config)
            
            # Create subplots
            fig = make_subplots(
                rows=3, cols=1,
                subplot_titles=('Price & Trend', 'Momentum Indicators', 'Volume'),
                vertical_spacing=0.08,
                row_heights=[0.5, 0.3, 0.2]
            )
            
            # Add price line with trend
            fig.add_trace(
                go.Scatter(
                    x=df['date'],
                    y=df['close'],
                    name='Close Price',
                    line=dict(color='blue', width=2),
                    hovertemplate='<b>%{x}</b><br>Close: ¥%{y:.2f}<extra></extra>'
                ),
                row=1, col=1
            )
            
            # Add trend line if requested
            if config.show_trend_line and momentum_data['trend_line'] is not None:
                fig.add_trace(
                    go.Scatter(
                        x=df['date'],
                        y=momentum_data['trend_line'],
                        name=f"Trend Line (R²={momentum_data['r_squared']:.3f})",
                        line=dict(color='red', width=2, dash='dash'),
                        hovertemplate='<b>Trend</b><br>Value: ¥%{y:.2f}<extra></extra>'
                    ),
                    row=1, col=1
                )
            
            # Add confidence bands if requested
            if config.confidence_bands and momentum_data['upper_band'] is not None:
                # Upper band
                fig.add_trace(
                    go.Scatter(
                        x=df['date'],
                        y=momentum_data['upper_band'],
                        name='Upper Confidence',
                        line=dict(color='rgba(255,0,0,0.3)', width=1),
                        showlegend=False
                    ),
                    row=1, col=1
                )
                
                # Lower band (fill area)
                fig.add_trace(
                    go.Scatter(
                        x=df['date'],
                        y=momentum_data['lower_band'],
                        name='Lower Confidence',
                        line=dict(color='rgba(255,0,0,0.3)', width=1),
                        fill='tonexty',
                        fillcolor='rgba(255,0,0,0.1)',
                        showlegend=False
                    ),
                    row=1, col=1
                )
            
            # Add momentum indicators
            fig.add_trace(
                go.Scatter(
                    x=df['date'],
                    y=momentum_data['momentum'],
                    name='Momentum',
                    line=dict(color='green', width=2),
                    hovertemplate='<b>Momentum</b><br>Value: %{y:.3f}<extra></extra>'
                ),
                row=2, col=1
            )
            
            # Add zero line for momentum
            fig.add_hline(y=0, line_dash="dash", line_color="gray", row=2, col=1)
            
            # Add moving averages of different periods
            colors = ['orange', 'purple', 'brown', 'pink']
            for i, period in enumerate(config.trend_periods):
                if len(df) >= period and f'ma_{period}' in df.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=df['date'],
                            y=df[f'ma_{period}'],
                            name=f'MA{period}',
                            line=dict(color=colors[i % len(colors)], width=1),
                            hovertemplate=f'<b>MA{period}</b><br>Value: ¥%{{y:.2f}}<extra></extra>'
                        ),
                        row=1, col=1
                    )
            
            # Add volume
            if 'volume' in df.columns:
                fig.add_trace(
                    go.Bar(
                        x=df['date'],
                        y=df['volume'],
                        name='Volume',
                        marker_color='lightblue',
                        opacity=0.7
                    ),
                    row=3, col=1
                )
            
            # Update layout
            fig.update_layout(
                title=title,
                xaxis_title='Date',
                yaxis_title='Price (CNY)',
                width=config.width,
                height=config.height,
                template=config.theme,
                showlegend=True,
                hovermode='x unified'
            )
            
            # Update axes
            fig.update_xaxes(rangeslider_visible=False)
            fig.update_yaxes(title_text="Momentum", row=2, col=1)
            fig.update_yaxes(title_text="Volume", row=3, col=1)
            
            # Add trend annotations
            if momentum_score:
                trend_color = "green" if momentum_score.price_trend == PriceTrend.UP else "red"
                fig.add_annotation(
                    text=f"Trend: {momentum_score.price_trend}<br>"
                         f"Strength: {momentum_score.trend_strength}<br>"
                         f"Score: {momentum_score.momentum_score:.1f}",
                    xref="paper", yref="paper",
                    x=0.02, y=0.98,
                    showarrow=False,
                    bgcolor="white",
                    bordercolor=trend_color,
                    borderwidth=2
                )
            
            # Generate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            # Prepare trend statistics
            trend_stats = {
                'r_squared': momentum_data['r_squared'],
                'trend_slope': momentum_data['trend_slope'],
                'volatility': momentum_data['volatility'],
                'trend_direction': momentum_data['trend_direction'],
                'data_points': len(df),
                'trend_period': momentum_data['trend_period']
            }
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"Momentum trend chart generated for {stock_symbol} in {generation_time:.3f}s")
            
            return MomentumChartResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                trend_stats=trend_stats,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating momentum trend chart for {stock_symbol}: {e}")
            return MomentumChartResult(
                success=False,
                error=f"Momentum chart generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def generate_momentum_comparison_chart(
        self,
        momentum_scores: List[MomentumScore],
        title: Optional[str] = None,
        config: Optional[MomentumChartConfig] = None
    ) -> MomentumChartResult:
        """Generate comparison chart for multiple momentum scores.
        
        Args:
            momentum_scores: List of momentum scores to compare
            title: Chart title
            config: Chart configuration
            
        Returns:
            MomentumChartResult with comparison chart
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        title = title or "Momentum Score Comparison"
        
        try:
            self.logger.info(f"Generating momentum comparison chart for {len(momentum_scores)} stocks")
            
            if not momentum_scores:
                return MomentumChartResult(
                    success=False,
                    error="No momentum scores provided",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Prepare data
            df = self._prepare_momentum_data(momentum_scores)
            if df.empty:
                return MomentumChartResult(
                    success=False,
                    error="Invalid momentum data",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Create subplots
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=('Momentum Scores', 'R-squared Values', 'Trend Slopes', 'Score Distribution'),
                vertical_spacing=0.12,
                horizontal_spacing=0.1
            )
            
            # 1. Momentum scores bar chart
            colors = ['green' if score > 50 else 'red' for score in df['momentum_score']]
            fig.add_trace(
                go.Bar(
                    x=df['stock_symbol'],
                    y=df['momentum_score'],
                    name='Momentum Score',
                    marker_color=colors,
                    text=df['momentum_score'].round(1),
                    textposition='auto'
                ),
                row=1, col=1
            )
            
            # 2. R-squared scatter plot
            fig.add_trace(
                go.Scatter(
                    x=df['momentum_score'],
                    y=df['r_squared'],
                    mode='markers',
                    name='R-squared vs Score',
                    marker=dict(
                        size=10,
                        color=df['momentum_score'],
                        colorscale='RdYlGn',
                        showscale=True,
                        colorbar=dict(title="Score")
                    ),
                    text=df['stock_symbol'],
                    hovertemplate='<b>%{text}</b><br>Score: %{x:.1f}<br>R²: %{y:.3f}<extra></extra>'
                ),
                row=1, col=2
            )
            
            # 3. Trend slopes
            slope_colors = ['green' if slope > 0 else 'red' for slope in df['trend_slope']]
            fig.add_trace(
                go.Bar(
                    x=df['stock_symbol'],
                    y=df['trend_slope'],
                    name='Trend Slope',
                    marker_color=slope_colors,
                    text=df['trend_slope'].round(4),
                    textposition='auto'
                ),
                row=2, col=1
            )
            
            # 4. Score distribution histogram
            fig.add_trace(
                go.Histogram(
                    x=df['momentum_score'],
                    name='Score Distribution',
                    nbinsx=10,
                    marker_color='lightblue'
                ),
                row=2, col=2
            )
            
            # Add reference lines
            fig.add_hline(y=50, line_dash="dash", line_color="gray", row=1, col=1)
            fig.add_vline(x=50, line_dash="dash", line_color="gray", row=1, col=2)
            fig.add_hline(y=0, line_dash="dash", line_color="gray", row=2, col=1)
            
            # Update layout
            fig.update_layout(
                title=title,
                width=config.width,
                height=config.height,
                template=config.theme,
                showlegend=False
            )
            
            # Update axes
            fig.update_xaxes(title_text="Stock Symbol", row=1, col=1)
            fig.update_yaxes(title_text="Momentum Score", row=1, col=1)
            fig.update_xaxes(title_text="Momentum Score", row=1, col=2)
            fig.update_yaxes(title_text="R-squared", row=1, col=2)
            fig.update_xaxes(title_text="Stock Symbol", row=2, col=1)
            fig.update_yaxes(title_text="Trend Slope", row=2, col=1)
            fig.update_xaxes(title_text="Momentum Score", row=2, col=2)
            fig.update_yaxes(title_text="Count", row=2, col=2)
            
            # Generate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            # Prepare statistics
            trend_stats = {
                'mean_score': df['momentum_score'].mean(),
                'std_score': df['momentum_score'].std(),
                'mean_r_squared': df['r_squared'].mean(),
                'mean_slope': df['trend_slope'].mean(),
                'up_trend_count': (df['trend_slope'] > 0).sum(),
                'down_trend_count': (df['trend_slope'] <= 0).sum(),
                'strong_correlation_count': (df['r_squared'] >= 0.7).sum()
            }
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"Momentum comparison chart generated in {generation_time:.3f}s")
            
            return MomentumChartResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                trend_stats=trend_stats,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating momentum comparison chart: {e}")
            return MomentumChartResult(
                success=False,
                error=f"Momentum comparison chart generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def generate_momentum_heatmap(
        self,
        momentum_scores: List[MomentumScore],
        title: Optional[str] = None,
        config: Optional[MomentumChartConfig] = None
    ) -> MomentumChartResult:
        """Generate heatmap showing momentum patterns across stocks and time periods.
        
        Args:
            momentum_scores: List of momentum scores
            title: Chart title
            config: Chart configuration
            
        Returns:
            MomentumChartResult with heatmap
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        title = title or "Momentum Analysis Heatmap"
        
        try:
            self.logger.info("Generating momentum heatmap")
            
            if not momentum_scores:
                return MomentumChartResult(
                    success=False,
                    error="No momentum scores provided",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Prepare heatmap data
            heatmap_data = self._prepare_heatmap_data(momentum_scores)
            if heatmap_data.empty:
                return MomentumChartResult(
                    success=False,
                    error="Insufficient data for heatmap",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Create figure
            fig = go.Figure(data=go.Heatmap(
                z=heatmap_data.values,
                x=heatmap_data.columns,
                y=heatmap_data.index,
                colorscale='RdYlGn',
                zmid=50,
                hoverongaps=False,
                colorbar=dict(title="Momentum Score")
            ))
            
            # Update layout
            fig.update_layout(
                title=title,
                xaxis_title='Metrics',
                yaxis_title='Stock Symbol',
                width=config.width,
                height=max(400, len(heatmap_data) * 30),  # Dynamic height
                template=config.theme
            )
            
            # Generate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"Momentum heatmap generated in {generation_time:.3f}s")
            
            return MomentumChartResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating momentum heatmap: {e}")
            return MomentumChartResult(
                success=False,
                error=f"Momentum heatmap generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def _prepare_price_data(self, price_data: List[Dict[str, Any]]) -> pd.DataFrame:
        """Prepare price data for momentum analysis."""
        try:
            df = pd.DataFrame(price_data)
            
            if df.empty:
                return pd.DataFrame()
            
            # Ensure required columns
            required_cols = ['date', 'close']
            if not all(col in df.columns for col in required_cols):
                return pd.DataFrame()
            
            # Convert date
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            
            # Ensure numeric
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            df = df.dropna(subset=['close', 'date'])
            
            # Add moving averages
            for period in [5, 10, 20, 60]:
                if len(df) >= period:
                    df[f'ma_{period}'] = df['close'].rolling(window=period).mean()
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error preparing price data: {e}")
            return pd.DataFrame()
    
    def _calculate_momentum_metrics(self, df: pd.DataFrame, config: MomentumChartConfig) -> Dict:
        """Calculate momentum metrics including trend line and statistics."""
        try:
            # Prepare data for linear regression
            x_values = np.arange(len(df)).reshape(-1, 1)
            y_values = df['close'].values
            
            # Fit linear regression
            model = LinearRegression()
            model.fit(x_values, y_values)
            
            # Calculate trend line
            trend_line = model.predict(x_values)
            r_squared = model.score(x_values, y_values)
            trend_slope = model.coef_[0]
            
            # Calculate confidence bands (simplified)
            residuals = y_values - trend_line
            std_residuals = np.std(residuals)
            upper_band = trend_line + 1.96 * std_residuals
            lower_band = trend_line - 1.96 * std_residuals
            
            # Calculate momentum (rate of change)
            momentum = df['close'].pct_change(periods=5) * 100  # 5-day rate of change
            
            # Calculate volatility
            volatility = df['close'].pct_change().rolling(window=20).std() * np.sqrt(252) * 100
            
            # Determine trend direction
            trend_direction = "Upward" if trend_slope > 0 else "Downward"
            
            return {
                'trend_line': trend_line,
                'r_squared': r_squared,
                'trend_slope': trend_slope,
                'upper_band': upper_band if config.confidence_bands else None,
                'lower_band': lower_band if config.confidence_bands else None,
                'momentum': momentum,
                'volatility': volatility,
                'trend_direction': trend_direction,
                'trend_period': len(df)
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating momentum metrics: {e}")
            return {
                'trend_line': None,
                'r_squared': 0.0,
                'trend_slope': 0.0,
                'upper_band': None,
                'lower_band': None,
                'momentum': pd.Series(),
                'volatility': pd.Series(),
                'trend_direction': "Unknown",
                'trend_period': len(df)
            }
    
    def _prepare_momentum_data(self, momentum_scores: List[MomentumScore]) -> pd.DataFrame:
        """Prepare momentum data for charting."""
        try:
            if not momentum_scores:
                return pd.DataFrame()
            
            data = []
            for score in momentum_scores:
                data.append({
                    'stock_symbol': score.stock_symbol,
                    'momentum_score': score.momentum_score,
                    'r_squared': score.r_squared,
                    'trend_slope': score.trend_slope,
                    'price_trend': str(score.price_trend),
                    'trend_strength': str(score.trend_strength),
                    'calculation_date': score.calculation_date
                })
            
            df = pd.DataFrame(data)
            
            if df.empty:
                return pd.DataFrame()
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error preparing momentum data: {e}")
            return pd.DataFrame()
    
    def _prepare_heatmap_data(self, momentum_scores: List[MomentumScore]) -> pd.DataFrame:
        """Prepare data for momentum heatmap."""
        try:
            df = self._prepare_momentum_data(momentum_scores)
            
            if df.empty:
                return pd.DataFrame()
            
            # Create pivot table for heatmap
            heatmap_data = df[['stock_symbol', 'momentum_score', 'r_squared', 'trend_slope']].copy()
            
            # Normalize trend_slope to 0-100 scale for better visualization
            heatmap_data['trend_slope_normalized'] = (
                (heatmap_data['trend_slope'] - heatmap_data['trend_slope'].min()) /
                (heatmap_data['trend_slope'].max() - heatmap_data['trend_slope'].min()) * 100
            ).fillna(0)
            
            # Set stock symbol as index
            heatmap_data = heatmap_data.set_index('stock_symbol')
            
            return heatmap_data
            
        except Exception as e:
            self.logger.error(f"Error preparing heatmap data: {e}")
            return pd.DataFrame()
    
    def save_chart(
        self,
        chart_result: MomentumChartResult,
        output_path: str,
        format: str = 'html'
    ) -> bool:
        """Save momentum chart to file."""
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
            
            self.logger.info(f"Momentum chart saved to {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving momentum chart to {output_path}: {e}")
            return False
    
    async def generate_momentum_trend_chart_async(
        self,
        stock_symbol: str,
        price_data: List[Dict[str, Any]],
        momentum_score: Optional[MomentumScore] = None,
        title: Optional[str] = None,
        config: Optional[MomentumChartConfig] = None
    ) -> MomentumChartResult:
        """Async version of momentum trend chart generation."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.generate_momentum_trend_chart,
            stock_symbol,
            price_data,
            momentum_score,
            title,
            config
        )