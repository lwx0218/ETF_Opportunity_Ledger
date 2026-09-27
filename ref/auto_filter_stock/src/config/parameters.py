"""Parameter validation and management for stock screening."""

from typing import Dict, Any
from pydantic import BaseModel, Field, field_validator


class ScreeningParams(BaseModel):
    """Screening parameters with validation."""

    volume_top_n: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Number of top volume stocks to consider"
    )
    heat_top_n: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Number of top heat stocks to consider"
    )
    intersection_top_n: int = Field(
        default=30,
        ge=10,
        le=100,
        description="Number of top stocks to select after intersection for momentum analysis (从综合优质股中筛选，避免遗漏动量强的股票)"
    )
    momentum_days: int = Field(
        default=25,
        ge=5,
        le=60,
        description="Number of days for momentum calculation"
    )
    final_top_n: int = Field(
        default=10,
        ge=5,
        le=30,
        description="Number of final stocks to select"
    )
    use_cache: bool = Field(
        default=True,
        description="Whether to use cached data if available"
    )

    @field_validator('momentum_days')
    def validate_momentum_days(cls, v):
        """Validate momentum days are reasonable."""
        if v < 5 or v > 60:
            raise ValueError('Momentum days must be between 5 and 60')
        return v

    @field_validator('final_top_n')
    def validate_final_top_n(cls, v, info):
        """Ensure final selection is reasonable compared to filters."""
        data = info.data
        volume_top = data.get('volume_top_n', 100)
        heat_top = data.get('heat_top_n', 100)
        min_pool = min(volume_top, heat_top)
        
        if v > min_pool:
            raise ValueError(f'Final top N ({v}) cannot exceed minimum filter size ({min_pool})')
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScreeningParams':
        """Create from dictionary."""
        return cls(**data)


class ParameterRanges(BaseModel):
    """Valid parameter ranges for UI configuration."""

    volume_top_n: Dict[str, int] = {
        "min": 10,
        "max": 500,
        "default": 100
    }
    heat_top_n: Dict[str, int] = {
        "min": 10,
        "max": 500,
        "default": 100
    }
    intersection_top_n: Dict[str, int] = {
        "min": 10,
        "max": 100,
        "default": 30
    }
    momentum_days: Dict[str, int] = {
        "min": 5,
        "max": 60,
        "default": 25
    }
    final_top_n: Dict[str, int] = {
        "min": 5,
        "max": 30,
        "default": 10
    }

    def get_ranges(self) -> Dict[str, Dict[str, int]]:
        """Get all parameter ranges."""
        return self.dict()