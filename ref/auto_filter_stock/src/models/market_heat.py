"""MarketHeat model for market attention/heat data."""

from datetime import date as date_type
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class HeatState(str, Enum):
    """State of market heat data processing."""
    NEW = "NEW"
    PROCESSED = "PROCESSED"
    RANKED = "RANKED"


class MarketHeat(BaseModel):
    """Represents market attention/heat data for popularity-based screening.
    
    Attributes:
        id: Auto-incrementing identifier
        stock_symbol: Reference to Stock.symbol
        stock_name: Stock name (optional)
        date: Trading date
        heat_score: Raw heat score from data source
        attention_index: Market attention index
        raw_heat_rank: Rank among all stocks by heat
        normalized_heat: Min-Max normalized score (0-1)
        heat_percentile: Percentile ranking (0-100)
        state: Processing state
    """
    
    id: Optional[int] = Field(None, description="Auto-incrementing identifier")
    stock_symbol: str = Field(..., description="Reference to Stock.symbol")
    stock_name: Optional[str] = Field(None, description="Stock name")
    date: date_type = Field(..., description="Trading date")
    heat_score: float = Field(..., ge=0, description="Raw heat score from data source")
    attention_index: float = Field(..., ge=0, description="Market attention index")
    raw_heat_rank: Optional[int] = Field(
        None,
        ge=1,
        description="Rank among all stocks by heat"
    )
    normalized_heat: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Min-Max normalized score (0-1)"
    )
    heat_percentile: Optional[float] = Field(
        None,
        ge=0.0,
        le=100.0,
        description="Percentile ranking (0-100)"
    )
    state: HeatState = Field(
        default=HeatState.NEW,
        description="Processing state"
    )
    
    @field_validator("attention_index")
    def validate_attention_index(cls, v, info):
        """Validate attention index is proportional to heat score."""
        heat_score = info.data.get("heat_score")
        if heat_score is not None:
            # Attention index should be reasonably related to heat score
            # Allow for some variation but not completely unrelated
            if v > 0 and heat_score == 0:
                raise ValueError(
                    "Attention index cannot be positive when heat score is zero"
                )
        return v
    
    @field_validator("normalized_heat")
    def validate_normalized_heat(cls, v):
        """Validate normalized heat is between 0 and 1."""
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"Normalized heat must be between 0 and 1, got {v}")
        return v
    
    model_config = {
        "use_enum_values": True,
        "json_schema_extra": {
            "example": {
                "stock_symbol": "000001.SZ",
                "date": "2025-10-07",
                "heat_score": 75.5,
                "attention_index": 82.3,
                "raw_heat_rank": 23,
                "normalized_heat": 0.77,
                "heat_percentile": 88.2,
                "state": "RANKED"
            }
        }
    }
    
    def normalize(self, min_heat: float, max_heat: float) -> None:
        """Apply Min-Max normalization to heat score.
        
        Args:
            min_heat: Minimum heat score in the dataset
            max_heat: Maximum heat score in the dataset
        """
        if max_heat == min_heat:
            self.normalized_heat = 1.0
        else:
            self.normalized_heat = (
                (self.heat_score - min_heat) / (max_heat - min_heat)
            )
        self.state = HeatState.PROCESSED
    
    def set_rank(self, rank: int, total_stocks: int) -> None:
        """Set ranking information.
        
        Args:
            rank: Rank among all stocks (1-based)
            total_stocks: Total number of stocks
        """
        self.raw_heat_rank = rank
        self.heat_percentile = ((total_stocks - rank) / total_stocks) * 100
        self.state = HeatState.RANKED
    
    def is_processed(self) -> bool:
        """Check if heat data has been processed."""
        return self.state in [HeatState.PROCESSED, HeatState.RANKED]
    
    def is_ranked(self) -> bool:
        """Check if heat data has been ranked."""
        return self.state == HeatState.RANKED
    
    def to_dict(self):
        """Convert to dictionary."""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: dict) -> "MarketHeat":
        """Create MarketHeat instance from dictionary."""
        return cls(**data)

