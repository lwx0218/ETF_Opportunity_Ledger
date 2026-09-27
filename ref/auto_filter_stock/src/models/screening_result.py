"""ScreeningResult model for final screening output."""

from datetime import date
from typing import Optional
import json

from pydantic import BaseModel, Field, validator


class ScreeningResult(BaseModel):
    """Represents the final screening result combining all metrics.
    
    Attributes:
        id: Auto-incrementing identifier
        stock_symbol: Reference to Stock.symbol
        stock_name: Stock name for display
        screening_date: Date of screening execution
        volume_rank: Final ranking by trading volume
        heat_rank: Final ranking by market heat
        momentum_rank: Final ranking by momentum score
        combined_score: Weighted combination of all metrics
        final_ranking: Overall screening result ranking (1-10)
        selection_criteria: JSON string of parameters used
        is_selected: Whether stock made it to top 10
        volume_amount: Trading volume amount
        heat_score: Market heat score
        momentum_score: Momentum score value
        trend_slope: Momentum trend slope
        r_squared: Momentum R-squared value
        trend_strength: Trend strength description
        price_trend: Price trend description
    """
    
    id: Optional[int] = Field(None, description="Auto-incrementing identifier")
    stock_symbol: str = Field(..., description="Reference to Stock.symbol")
    stock_name: Optional[str] = Field(None, description="Stock name")
    screening_date: date = Field(..., description="Date of screening execution")
    volume_rank: Optional[int] = Field(
        None,
        ge=1,
        description="Final ranking by trading volume"
    )
    heat_rank: Optional[int] = Field(
        None,
        ge=1,
        description="Final ranking by market heat"
    )
    momentum_rank: Optional[int] = Field(
        None,
        ge=1,
        description="Final ranking by momentum score"
    )
    combined_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Weighted combination of all metrics"
    )
    final_ranking: int = Field(
        ...,
        ge=1,
        le=100,
        description="Overall screening result ranking"
    )
    selection_criteria: str = Field(
        ...,
        description="JSON string of parameters used"
    )
    is_selected: bool = Field(
        default=False,
        description="Whether stock made it to top selection"
    )
    # Additional detailed fields for CSV export
    volume_amount: Optional[float] = Field(None, description="Trading volume amount")
    heat_score: Optional[float] = Field(None, description="Market heat score")
    momentum_score: Optional[float] = Field(None, description="Momentum score")
    trend_slope: Optional[float] = Field(None, description="Trend slope")
    r_squared: Optional[float] = Field(None, description="R-squared value")
    trend_strength: Optional[str] = Field(None, description="Trend strength")
    price_trend: Optional[str] = Field(None, description="Price trend")
    
    @validator("selection_criteria")
    def validate_selection_criteria(cls, v):
        """Validate selection criteria is valid JSON."""
        try:
            json.loads(v)
        except json.JSONDecodeError:
            raise ValueError("selection_criteria must be valid JSON string")
        return v
    
    @validator("combined_score")
    def validate_combined_score(cls, v):
        """Validate combined score is between 0 and 100."""
        if not (0.0 <= v <= 100.0):
            raise ValueError(f"Combined score must be between 0 and 100, got {v}")
        return v
    
    @validator("is_selected", always=True)
    def determine_selection(cls, v, values):
        """Determine if stock is selected based on ranking."""
        if v is not None:
            return v
        
        if "final_ranking" in values:
            # Get the top_n from selection_criteria if available
            if "selection_criteria" in values:
                try:
                    criteria = json.loads(values["selection_criteria"])
                    top_n = criteria.get("final_top_n", 10)
                    return values["final_ranking"] <= top_n
                except:
                    pass
            
            # Default to top 10
            return values["final_ranking"] <= 10
        
        return False
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            date: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "stock_symbol": "000001.SZ",
                "screening_date": "2025-10-07",
                "volume_rank": 15,
                "heat_rank": 23,
                "momentum_rank": 8,
                "combined_score": 85.2,
                "final_ranking": 3,
                "selection_criteria": '{"volume_top_n": 100, "heat_top_n": 100, "momentum_days": 25, "final_top_n": 10}',
                "is_selected": True
            }
        }
    
    @classmethod
    def calculate_combined_score(
        cls,
        volume_rank: Optional[int],
        heat_rank: Optional[int],
        momentum_score: float,
        total_stocks: int,
        volume_weight: float = 0.4,
        heat_weight: float = 0.3,
        momentum_weight: float = 0.3
    ) -> float:
        """Calculate combined score from individual metrics.
        
        Args:
            volume_rank: Rank by volume (lower is better)
            heat_rank: Rank by heat (lower is better)
            momentum_score: Momentum score (higher is better)
            total_stocks: Total number of stocks in pool
            volume_weight: Weight for volume component (default: 0.4)
            heat_weight: Weight for heat component (default: 0.3)
            momentum_weight: Weight for momentum component (default: 0.3)
            
        Returns:
            Combined score (0-100)
        """
        # Validate weights sum to 1.0
        total_weight = volume_weight + heat_weight + momentum_weight
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")
        
        score = 0.0
        
        # Convert ranks to percentile scores (higher is better)
        if volume_rank is not None:
            volume_percentile = ((total_stocks - volume_rank) / total_stocks) * 100
            score += volume_weight * volume_percentile
        
        if heat_rank is not None:
            heat_percentile = ((total_stocks - heat_rank) / total_stocks) * 100
            score += heat_weight * heat_percentile
        
        # Normalize momentum score to 0-100 scale
        # Assuming momentum_score is already scaled appropriately
        normalized_momentum = min(max(momentum_score, 0), 100)
        score += momentum_weight * normalized_momentum
        
        return min(max(score, 0.0), 100.0)
    
    def get_criteria_dict(self) -> dict:
        """Get selection criteria as dictionary.
        
        Returns:
            Dictionary of selection criteria
        """
        return json.loads(self.selection_criteria)
    
    def get_rank_summary(self) -> dict:
        """Get summary of all rankings.
        
        Returns:
            Dictionary with rank information
        """
        return {
            "volume_rank": self.volume_rank,
            "heat_rank": self.heat_rank,
            "momentum_rank": self.momentum_rank,
            "final_ranking": self.final_ranking,
            "combined_score": self.combined_score
        }
    
    def is_top_performer(self, threshold: int = 5) -> bool:
        """Check if stock is a top performer.
        
        Args:
            threshold: Ranking threshold
            
        Returns:
            True if final ranking is within threshold
        """
        return self.final_ranking <= threshold
    
    def to_dict(self):
        """Convert to dictionary."""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: dict) -> "ScreeningResult":
        """Create ScreeningResult instance from dictionary."""
        return cls(**data)

