"""MomentumScore model for technical momentum analysis."""

from datetime import date as date_type
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class CalculationStatus(str, Enum):
    """Status of momentum calculation."""
    PENDING = "PENDING"
    CALCULATING = "CALCULATING"
    COMPLETED = "COMPLETED"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"


class PriceTrend(str, Enum):
    """Price trend direction."""
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class TrendStrength(str, Enum):
    """Qualitative trend strength."""
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


class MomentumScore(BaseModel):
    """Represents technical momentum analysis results for trend-based screening.
    
    Attributes:
        id: Auto-incrementing identifier
        stock_symbol: Reference to Stock.symbol
        calculation_date: Date of momentum calculation
        period_days: Analysis period (default: 25)
        trend_slope: Linear regression slope coefficient
        r_squared: Coefficient of determination (0-1)
        momentum_score: Computed momentum ranking score
        price_trend: Trend direction ("UP", "DOWN", "FLAT")
        trend_strength: Qualitative strength ("STRONG", "MODERATE", "WEAK")
        calculation_status: Status of calculation
    """
    
    id: Optional[int] = Field(None, description="Auto-incrementing identifier")
    stock_symbol: str = Field(..., description="Reference to Stock.symbol")
    calculation_date: date_type = Field(..., description="Date of momentum calculation")
    period_days: int = Field(
        default=25,
        ge=10,
        le=60,
        description="Analysis period"
    )
    trend_slope: float = Field(..., description="Linear regression slope coefficient")
    r_squared: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Coefficient of determination (0-1)"
    )
    momentum_score: float = Field(..., description="Computed momentum ranking score")
    price_trend: PriceTrend = Field(..., description="Trend direction")
    trend_strength: TrendStrength = Field(..., description="Qualitative strength")
    calculation_status: CalculationStatus = Field(
        default=CalculationStatus.PENDING,
        description="Status of calculation"
    )
    
    @field_validator("trend_slope")
    def validate_trend_slope(cls, v):
        """Validate trend slope is a finite number."""
        if not (-1000 <= v <= 1000):  # Reasonable bounds
            raise ValueError(f"Trend slope {v} is outside reasonable bounds")
        return v
    
    @field_validator("r_squared")
    def validate_r_squared(cls, v):
        """Validate R-squared is between 0 and 1."""
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"R-squared must be between 0 and 1, got {v}")
        return v
    
    @field_validator("price_trend", mode="before")
    def determine_price_trend(cls, v, info):
        """Determine price trend from slope and R-squared."""
        if v is not None:
            return v
        
        trend_slope = info.data.get("trend_slope")
        r_squared = info.data.get("r_squared")
        if trend_slope is not None and r_squared is not None:
            if trend_slope > 0 and r_squared > 0.3:
                return PriceTrend.UP
            elif trend_slope < 0 and r_squared > 0.3:
                return PriceTrend.DOWN
            else:
                return PriceTrend.FLAT
        
        return PriceTrend.FLAT
    
    @field_validator("trend_strength", mode="before")
    def determine_trend_strength(cls, v, info):
        """Determine trend strength from R-squared."""
        if v is not None:
            return v
        
        r_squared = info.data.get("r_squared")
        if r_squared is not None:
            if r_squared >= 0.7:
                return TrendStrength.STRONG
            elif r_squared >= 0.4:
                return TrendStrength.MODERATE
            else:
                return TrendStrength.WEAK
        
        return TrendStrength.WEAK
    
    @field_validator("momentum_score", mode="before")
    def calculate_momentum_score(cls, v, info):
        """Calculate momentum score from slope and R-squared."""
        if v is not None:
            return v
        
        trend_slope = info.data.get("trend_slope")
        r_squared = info.data.get("r_squared")
        if trend_slope is not None and r_squared is not None:
            # Momentum Score = (trend_slope * r_squared) * 10000
            # Scale up for better ranking differentiation
            score = trend_slope * r_squared * 10000
            return score
        
        return 0.0
    
    model_config = {
        "use_enum_values": True,
        "json_schema_extra": {
            "example": {
                "stock_symbol": "000001.SZ",
                "calculation_date": "2025-10-07",
                "period_days": 25,
                "trend_slope": 0.0125,
                "r_squared": 0.78,
                "momentum_score": 97.5,
                "price_trend": "UP",
                "trend_strength": "STRONG",
                "calculation_status": "COMPLETED"
            }
        }
    }
    
    def is_uptrend(self) -> bool:
        """Check if stock is in uptrend."""
        return self.price_trend == PriceTrend.UP
    
    def is_strong_trend(self) -> bool:
        """Check if trend is strong."""
        return self.trend_strength == TrendStrength.STRONG
    
    def is_reliable(self, min_r_squared: float = 0.5) -> bool:
        """Check if momentum calculation is reliable.
        
        Args:
            min_r_squared: Minimum R-squared threshold
            
        Returns:
            True if R-squared is above threshold
        """
        return self.r_squared >= min_r_squared
    
    def get_quality_score(self) -> float:
        """Get quality score combining trend and reliability.
        
        Returns:
            Quality score (0-100)
        """
        # Weight: 70% momentum score, 30% R-squared reliability
        normalized_momentum = min(abs(self.momentum_score) / 100, 100)
        reliability = self.r_squared * 100
        
        return 0.7 * normalized_momentum + 0.3 * reliability
    
    def to_dict(self):
        """Convert to dictionary."""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: dict) -> "MomentumScore":
        """Create MomentumScore instance from dictionary."""
        return cls(**data)

