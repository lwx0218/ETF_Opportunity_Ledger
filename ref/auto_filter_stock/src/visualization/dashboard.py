"""Dashboard generator for comprehensive stock screening visualization."""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import pandas as pd
import json

from loguru import logger

from src.config.settings import get_settings
from src.config.parameters import ScreeningParams
from src.models.screening_result import ScreeningResult
from src.models.momentum_score import MomentumScore
from src.visualization.charts import ChartGenerator, ChartConfig, ChartResult
from src.visualization.momentum_charts import MomentumChartGenerator, MomentumChartConfig, MomentumChartResult


@dataclass
class DashboardConfig:
    """Configuration for dashboard generation."""
    width: int = 1400
    height: int = 1000
    theme: str = "plotly_white"
    show_summary: bool = True
    show_charts: bool = True
    show_statistics: bool = True
    layout_type: str = "grid"  # "grid", "tabs", "single"
    include_momentum: bool = True
    include_volume: bool = True
    include_heat: bool = True
    max_stocks_display: int = 20


@dataclass
class DashboardResult:
    """Result of dashboard generation."""
    success: bool
    figure: Optional[go.Figure] = None
    html_content: Optional[str] = None
    json_data: Optional[Dict] = None
    summary_stats: Optional[Dict] = None
    error: Optional[str] = None
    generation_time: float = 0.0


class DashboardGenerator:
    """Service for generating comprehensive stock screening dashboards."""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger.bind(service="DashboardGenerator")
        self.chart_generator = ChartGenerator()
        self.momentum_generator = MomentumChartGenerator()
        self.default_config = DashboardConfig()
    
    def generate_screening_dashboard(
        self,
        screening_results: List[ScreeningResult],
        params: Optional[ScreeningParams] = None,
        title: Optional[str] = None,
        config: Optional[DashboardConfig] = None
    ) -> DashboardResult:
        """Generate comprehensive dashboard for screening results.
        
        Args:
            screening_results: List of screening results to visualize
            params: Screening parameters used (optional)
            title: Dashboard title
            config: Dashboard configuration
            
        Returns:
            DashboardResult with generated dashboard
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        title = title or "Stock Screening Dashboard"
        
        try:
            self.logger.info(f"Generating screening dashboard for {len(screening_results)} results")
            
            if not screening_results:
                return DashboardResult(
                    success=False,
                    error="No screening results provided",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Generate summary statistics
            summary_stats = self._generate_summary_stats(screening_results, params)
            
            # Create dashboard layout based on configuration
            if config.layout_type == "grid":
                fig = self._create_grid_dashboard(screening_results, summary_stats, config, title)
            elif config.layout_type == "tabs":
                fig = self._create_tabbed_dashboard(screening_results, summary_stats, config, title)
            else:
                fig = self._create_single_dashboard(screening_results, summary_stats, config, title)
            
            if fig is None:
                return DashboardResult(
                    success=False,
                    error="Failed to create dashboard layout",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Generate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"Screening dashboard generated in {generation_time:.3f}s")
            
            return DashboardResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                summary_stats=summary_stats,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating screening dashboard: {e}")
            return DashboardResult(
                success=False,
                error=f"Dashboard generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def generate_real_time_dashboard(
        self,
        top_stocks: List[Dict[str, Any]],
        market_metrics: Dict[str, Any],
        title: Optional[str] = None,
        config: Optional[DashboardConfig] = None
    ) -> DashboardResult:
        """Generate real-time monitoring dashboard.
        
        Args:
            top_stocks: Current top performing stocks
            market_metrics: Overall market metrics and indicators
            title: Dashboard title
            config: Dashboard configuration
            
        Returns:
            DashboardResult with real-time dashboard
        """
        start_time = datetime.now()
        
        config = config or self.default_config
        title = title or "Real-Time Market Dashboard"
        
        try:
            self.logger.info("Generating real-time dashboard")
            
            if not top_stocks:
                return DashboardResult(
                    success=False,
                    error="No stock data provided",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Create real-time dashboard
            fig = self._create_realtime_dashboard(top_stocks, market_metrics, config, title)
            
            if fig is None:
                return DashboardResult(
                    success=False,
                    error="Failed to create real-time dashboard",
                    generation_time=(datetime.now() - start_time).total_seconds()
                )
            
            # Generate outputs
            html_content = fig.to_html(include_plotlyjs='cdn')
            json_data = fig.to_dict()
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"Real-time dashboard generated in {generation_time:.3f}s")
            
            return DashboardResult(
                success=True,
                figure=fig,
                html_content=html_content,
                json_data=json_data,
                generation_time=generation_time
            )
            
        except Exception as e:
            self.logger.error(f"Error generating real-time dashboard: {e}")
            return DashboardResult(
                success=False,
                error=f"Real-time dashboard generation error: {str(e)}",
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    def _create_grid_dashboard(
        self,
        screening_results: List[ScreeningResult],
        summary_stats: Dict[str, Any],
        config: DashboardConfig,
        title: str
    ) -> Optional[go.Figure]:
        """Create grid-based dashboard layout."""
        try:
            # Calculate grid dimensions
            num_stocks = min(len(screening_results), config.max_stocks_display)
            
            # Create subplots with summary + top stocks
            rows = 3
            cols = 2
            
            fig = make_subplots(
                rows=rows, cols=cols,
                subplot_titles=(
                    'Screening Summary', 'Top 10 Stocks',
                    'Score Distribution', 'Ranking Analysis',
                    'Market Overview', 'Performance Metrics'
                ),
                specs=[
                    [{"type": "indicator"}, {"type": "bar"}],
                    [{"type": "histogram"}, {"type": "scatter"}],
                    [{"type": "table"}, {"type": "bar"}]
                ],
                vertical_spacing=0.1,
                horizontal_spacing=0.1
            )
            
            # 1. Summary indicators
            self._add_summary_indicators(fig, summary_stats, row=1, col=1)
            
            # 2. Top stocks bar chart
            self._add_top_stocks_chart(fig, screening_results[:10], row=1, col=2)
            
            # 3. Score distribution histogram
            self._add_score_distribution(fig, screening_results, row=2, col=1)
            
            # 4. Ranking scatter plot
            self._add_ranking_scatter(fig, screening_results, row=2, col=2)
            
            # 5. Market overview table
            self._add_market_overview_table(fig, screening_results, row=3, col=1)
            
            # 6. Performance metrics
            self._add_performance_metrics(fig, screening_results, row=3, col=2)
            
            # Update layout
            fig.update_layout(
                title=title,
                width=config.width,
                height=config.height,
                template=config.theme,
                showlegend=True
            )
            
            return fig
            
        except Exception as e:
            self.logger.error(f"Error creating grid dashboard: {e}")
            return None
    
    def _create_tabbed_dashboard(
        self,
        screening_results: List[ScreeningResult],
        summary_stats: Dict[str, Any],
        config: DashboardConfig,
        title: str
    ) -> Optional[go.Figure]:
        """Create tabbed dashboard layout (simplified for single HTML output)."""
        # For HTML output, we'll use a comprehensive single layout
        return self._create_grid_dashboard(screening_results, summary_stats, config, title)
    
    def _create_single_dashboard(
        self,
        screening_results: List[ScreeningResult],
        summary_stats: Dict[str, Any],
        config: DashboardConfig,
        title: str
    ) -> Optional[go.Figure]:
        """Create single comprehensive dashboard."""
        try:
            # Create a comprehensive single figure
            fig = go.Figure()
            
            # Add main ranking chart
            top_stocks = screening_results[:config.max_stocks_display]
            
            fig.add_trace(go.Bar(
                x=[result.stock_symbol for result in top_stocks],
                y=[result.combined_score for result in top_stocks],
                name='Combined Score',
                marker_color='lightblue',
                text=[f"{result.combined_score:.1f}" for result in top_stocks],
                textposition='auto'
            ))
            
            # Update layout with comprehensive information
            fig.update_layout(
                title=title,
                xaxis_title='Stock Symbol',
                yaxis_title='Combined Score',
                width=config.width,
                height=config.height,
                template=config.theme,
                showlegend=True,
                annotations=[
                    dict(
                        text=f"Total Stocks: {summary_stats.get('total_stocks', 0)}<br>"
                             f"Average Score: {summary_stats.get('avg_score', 0):.1f}<br>"
                             f"Top Score: {summary_stats.get('max_score', 0):.1f}",
                        xref="paper", yref="paper",
                        x=0.02, y=0.98,
                        showarrow=False,
                        bgcolor="rgba(255,255,255,0.8)",
                        bordercolor="black",
                        borderwidth=1
                    )
                ]
            )
            
            return fig
            
        except Exception as e:
            self.logger.error(f"Error creating single dashboard: {e}")
            return None
    
    def _create_realtime_dashboard(
        self,
        top_stocks: List[Dict[str, Any]],
        market_metrics: Dict[str, Any],
        config: DashboardConfig,
        title: str
    ) -> Optional[go.Figure]:
        """Create real-time monitoring dashboard."""
        try:
            # Create 2x2 grid for real-time data
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=(
                    'Top Performing Stocks', 'Market Heat Index',
                    'Volume Leaders', 'Momentum Leaders'
                ),
                specs=[
                    [{"type": "bar"}, {"type": "indicator"}],
                    [{"type": "bar"}, {"type": "bar"}]
                ]
            )
            
            # Top performing stocks
            if top_stocks:
                symbols = [stock['symbol'] for stock in top_stocks[:10]]
                scores = [stock.get('score', 0) for stock in top_stocks[:10]]
                
                fig.add_trace(go.Bar(
                    x=symbols,
                    y=scores,
                    name='Performance Score',
                    marker_color='green'
                ), row=1, col=1)
            
            # Market heat indicator
            heat_index = market_metrics.get('heat_index', 50)
            fig.add_trace(go.Indicator(
                mode="gauge+number",
                value=heat_index,
                title={'text': "Market Heat"},
                gauge={'axis': {'range': [None, 100]},
                       'bar': {'color': "darkgreen"},
                       'steps': [
                           {'range': [0, 50], 'color': "lightgray"},
                           {'range': [50, 80], 'color': "yellow"},
                           {'range': [80, 100], 'color': "red"}],
                       'threshold': {'line': {'color': "red", 'width': 4},
                                    'thickness': 0.75, 'value': 90}}
            ), row=1, col=2)
            
            # Volume leaders
            volume_data = market_metrics.get('volume_leaders', [])
            if volume_data:
                vol_symbols = [stock['symbol'] for stock in volume_data[:10]]
                volumes = [stock.get('volume', 0) for stock in volume_data[:10]]
                
                fig.add_trace(go.Bar(
                    x=vol_symbols,
                    y=volumes,
                    name='Trading Volume',
                    marker_color='blue'
                ), row=2, col=1)
            
            # Momentum leaders
            momentum_data = market_metrics.get('momentum_leaders', [])
            if momentum_data:
                mom_symbols = [stock['symbol'] for stock in momentum_data[:10]]
                momentum_scores = [stock.get('momentum_score', 0) for stock in momentum_data[:10]]
                
                fig.add_trace(go.Bar(
                    x=mom_symbols,
                    y=momentum_scores,
                    name='Momentum Score',
                    marker_color='orange'
                ), row=2, col=2)
            
            # Update layout
            fig.update_layout(
                title=title,
                width=config.width,
                height=config.height,
                template=config.theme,
                showlegend=False
            )
            
            return fig
            
        except Exception as e:
            self.logger.error(f"Error creating real-time dashboard: {e}")
            return None
    
    def _generate_summary_stats(self, screening_results: List[ScreeningResult], params: Optional[ScreeningParams]) -> Dict[str, Any]:
        """Generate summary statistics for screening results."""
        try:
            if not screening_results:
                return {}
            
            scores = [result.combined_score for result in screening_results]
            
            stats = {
                'total_stocks': len(screening_results),
                'avg_score': sum(scores) / len(scores),
                'max_score': max(scores),
                'min_score': min(scores),
                'std_score': pd.Series(scores).std(),
                'top_performers': len([s for s in scores if s >= 80]),
                'selected_stocks': len([r for r in screening_results if r.is_selected])
            }
            
            # Add parameter information if available
            if params:
                stats['parameters'] = {
                    'volume_top_n': params.volume_top_n,
                    'heat_top_n': params.heat_top_n,
                    'momentum_days': params.momentum_days,
                    'final_top_n': params.final_top_n
                }
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error generating summary statistics: {e}")
            return {}
    
    def _add_summary_indicators(self, fig: go.Figure, summary_stats: Dict[str, Any], row: int, col: int):
        """Add summary indicator widgets."""
        try:
            # Total stocks indicator
            fig.add_trace(go.Indicator(
                mode="number",
                value=summary_stats.get('total_stocks', 0),
                title={'text': "Total Stocks"},
                domain={'x': [0, 0.3], 'y': [0.7, 1]}
            ), row=row, col=col)
            
            # Average score indicator
            fig.add_trace(go.Indicator(
                mode="number+gauge",
                value=summary_stats.get('avg_score', 0),
                title={'text': "Avg Score"},
                gauge={'axis': {'range': [None, 100]},
                       'bar': {'color': "darkblue"},
                       'steps': [
                           {'range': [0, 50], 'color': "lightgray"},
                           {'range': [50, 80], 'color': "yellow"}],
                       'threshold': {'line': {'color': "red", 'width': 4},
                                    'thickness': 0.75, 'value': 80}},
                domain={'x': [0.35, 1], 'y': [0.7, 1]}
            ), row=row, col=col)
            
            # Selected stocks indicator
            fig.add_trace(go.Indicator(
                mode="number",
                value=summary_stats.get('selected_stocks', 0),
                title={'text': "Selected"},
                domain={'x': [0, 0.3], 'y': [0, 0.3]}
            ), row=row, col=col)
            
            # Top performers indicator
            fig.add_trace(go.Indicator(
                mode="number",
                value=summary_stats.get('top_performers', 0),
                title={'text': "Top Performers"},
                domain={'x': [0.35, 0.65], 'y': [0, 0.3]}
            ), row=row, col=col)
            
        except Exception as e:
            self.logger.error(f"Error adding summary indicators: {e}")
    
    def _add_top_stocks_chart(self, fig: go.Figure, screening_results: List[ScreeningResult], row: int, col: int):
        """Add top stocks bar chart."""
        try:
            symbols = [result.stock_symbol for result in screening_results]
            scores = [result.combined_score for result in screening_results]
            
            fig.add_trace(go.Bar(
                x=symbols,
                y=scores,
                name='Combined Score',
                marker_color='lightblue',
                text=[f"{score:.1f}" for score in scores],
                textposition='auto'
            ), row=row, col=col)
            
            fig.update_xaxes(title_text="Stock Symbol", row=row, col=col)
            fig.update_yaxes(title_text="Combined Score", row=row, col=col)
            
        except Exception as e:
            self.logger.error(f"Error adding top stocks chart: {e}")
    
    def _add_score_distribution(self, fig: go.Figure, screening_results: List[ScreeningResult], row: int, col: int):
        """Add score distribution histogram."""
        try:
            scores = [result.combined_score for result in screening_results]
            
            fig.add_trace(go.Histogram(
                x=scores,
                name='Score Distribution',
                nbinsx=10,
                marker_color='lightgreen'
            ), row=row, col=col)
            
            fig.update_xaxes(title_text="Combined Score", row=row, col=col)
            fig.update_yaxes(title_text="Count", row=row, col=col)
            
        except Exception as e:
            self.logger.error(f"Error adding score distribution: {e}")
    
    def _add_ranking_scatter(self, fig: go.Figure, screening_results: List[ScreeningResult], row: int, col: int):
        """Add ranking scatter plot."""
        try:
            rankings = [result.final_ranking for result in screening_results]
            scores = [result.combined_score for result in screening_results]
            symbols = [result.stock_symbol for result in screening_results]
            
            fig.add_trace(go.Scatter(
                x=rankings,
                y=scores,
                mode='markers+text',
                name='Ranking vs Score',
                marker=dict(
                    size=10,
                    color=scores,
                    colorscale='RdYlBu_r',
                    showscale=True
                ),
                text=symbols,
                textposition="top center"
            ), row=row, col=col)
            
            fig.update_xaxes(title_text="Final Ranking", row=row, col=col)
            fig.update_yaxes(title_text="Combined Score", row=row, col=col)
            
        except Exception as e:
            self.logger.error(f"Error adding ranking scatter: {e}")
    
    def _add_market_overview_table(self, fig: go.Figure, screening_results: List[ScreeningResult], row: int, col: int):
        """Add market overview table."""
        try:
            # Prepare table data
            header_values = ['Rank', 'Symbol', 'Score', 'Momentum', 'Volume', 'Heat']
            
            cell_values = [
                [str(result.final_ranking) for result in screening_results[:10]],
                [result.stock_symbol for result in screening_results[:10]],
                [f"{result.combined_score:.1f}" for result in screening_results[:10]],
                [str(result.momentum_rank) if result.momentum_rank else "N/A" for result in screening_results[:10]],
                [str(result.volume_rank) if result.volume_rank else "N/A" for result in screening_results[:10]],
                [str(result.heat_rank) if result.heat_rank else "N/A" for result in screening_results[:10]]
            ]
            
            fig.add_trace(go.Table(
                header=dict(values=header_values,
                           fill_color='lightblue',
                           align='center'),
                cells=dict(values=cell_values,
                          fill_color='white',
                          align='center')
            ), row=row, col=col)
            
        except Exception as e:
            self.logger.error(f"Error adding market overview table: {e}")
    
    def _add_performance_metrics(self, fig: go.Figure, screening_results: List[ScreeningResult], row: int, col: int):
        """Add performance metrics chart."""
        try:
            # Calculate performance metrics
            selected_stocks = [r for r in screening_results if r.is_selected]
            
            metrics = {
                'Selected': len(selected_stocks),
                'Top 10': len([r for r in screening_results if r.final_ranking <= 10]),
                'Score > 80': len([r for r in screening_results if r.combined_score >= 80]),
                'High Momentum': len([r for r in screening_results if r.momentum_rank and r.momentum_rank <= 20])
            }
            
            fig.add_trace(go.Bar(
                x=list(metrics.keys()),
                y=list(metrics.values()),
                name='Performance Metrics',
                marker_color=['green', 'blue', 'orange', 'red']
            ), row=row, col=col)
            
            fig.update_xaxes(title_text="Metric Type", row=row, col=col)
            fig.update_yaxes(title_text="Count", row=row, col=col)
            
        except Exception as e:
            self.logger.error(f"Error adding performance metrics: {e}")
    
    def save_dashboard(
        self,
        dashboard_result: DashboardResult,
        output_path: str,
        format: str = 'html'
    ) -> bool:
        """Save dashboard to file.
        
        Args:
            dashboard_result: DashboardResult from generation
            output_path: Output file path
            format: Output format ('html', 'png', 'jpeg', 'json')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not dashboard_result.success:
                self.logger.error("Cannot save unsuccessful dashboard result")
                return False
            
            if format == 'html' and dashboard_result.html_content:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(dashboard_result.html_content)
            elif format in ['png', 'jpeg'] and dashboard_result.figure:
                dashboard_result.figure.write_image(output_path, format=format)
            elif format == 'json' and dashboard_result.json_data:
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
                
                serializable_data = convert_numpy(dashboard_result.json_data)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(serializable_data, f, ensure_ascii=False, indent=2)
            else:
                self.logger.error(f"Unsupported format or missing data: {format}")
                return False
            
            self.logger.info(f"Dashboard saved to {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving dashboard to {output_path}: {e}")
            return False
    
    async def generate_screening_dashboard_async(
        self,
        screening_results: List[ScreeningResult],
        params: Optional[ScreeningParams] = None,
        title: Optional[str] = None,
        config: Optional[DashboardConfig] = None
    ) -> DashboardResult:
        """Async version of screening dashboard generation."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.generate_screening_dashboard,
            screening_results,
            params,
            title,
            config
        )