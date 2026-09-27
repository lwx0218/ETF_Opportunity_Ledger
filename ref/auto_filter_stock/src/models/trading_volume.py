"""TradingVolume model for daily trading volume data."""

from datetime import date as date_type
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class VolumeState(str, Enum):
    """State of trading volume data processing."""
    NEW = "NEW"
    PROCESSED = "PROCESSED"
    RANKED = "RANKED"


class TradingVolume(BaseModel):
    """Represents daily trading volume data for volume-based screening.
    
    Attributes:
        id: Auto-incrementing identifier
        stock_symbol: Reference to Stock.symbol
        stock_name: Stock name (optional)
        date: Trading date
        volume: Number of shares traded
        turnover: Trading value in CNY
        raw_volume_rank: Rank among all stocks by volume
        normalized_volume: Min-Max normalized score (0-1)
        volume_percentile: Percentile ranking (0-100)
        state: Processing state
    """
    
    id: Optional[int] = Field(None, description="Auto-incrementing identifier")
    stock_symbol: str = Field(..., description="Reference to Stock.symbol")
    stock_name: Optional[str] = Field(None, description="Stock name")
    date: date_type = Field(..., description="Trading date")
    volume: int = Field(..., gt=0, description="Number of shares traded")
    turnover: float = Field(..., gt=0, description="Trading value in CNY")
    raw_volume_rank: Optional[int] = Field(
        None, 
        ge=1, 
        description="Rank among all stocks by volume"
    )
    normalized_volume: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Min-Max normalized score (0-1)"
    )
    volume_percentile: Optional[float] = Field(
        None,
        ge=0.0,
        le=100.0,
        description="Percentile ranking (0-100)"
    )
    state: VolumeState = Field(
        default=VolumeState.NEW,
        description="Processing state"
    )
    
    @field_validator("turnover")
    def validate_turnover_consistency(cls, v, info):
        """Validate turnover is consistent with volume."""
        volume = info.data.get("volume")
        if volume is not None:
            # Turnover should be reasonable relative to volume
            # Assuming average price per share is between 1 and 1000 CNY
            min_turnover = volume * 0.1  # Very low price
            max_turnover = volume * 10000  # Very high price
            
            if not (min_turnover <= v <= max_turnover):
                raise ValueError(
                    f"Turnover {v} seems inconsistent with volume {volume}"
                )
        return v
    
    @field_validator("normalized_volume")
    def validate_normalized_volume(cls, v):
        """Validate normalized volume is between 0 and 1."""
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"Normalized volume must be between 0 and 1, got {v}")
        return v
    
    model_config = {
        "use_enum_values": True,
        "json_schema_extra": {
            "example": {
                "stock_symbol": "000001.SZ",
                "date": "2025-10-07",
                "volume": 1234567,
                "turnover": 15234567.89,
                "raw_volume_rank": 15,
                "normalized_volume": 0.85,
                "volume_percentile": 92.5,
                "state": "RANKED"
            }
        }
    }
    
    def normalize(self, min_volume: float, max_volume: float) -> None:
        """Apply Min-Max normalization to volume.
        
        Args:
            min_volume: Minimum volume in the dataset
            max_volume: Maximum volume in the dataset
        """
        if max_volume == min_volume:
            self.normalized_volume = 1.0
        else:
            self.normalized_volume = (
                (self.volume - min_volume) / (max_volume - min_volume)
            )
        self.state = VolumeState.PROCESSED
    
    def set_rank(self, rank: int, total_stocks: int) -> None:
        """Set ranking information.
        
        Args:
            rank: Rank among all stocks (1-based)
            total_stocks: Total number of stocks
        """
        self.raw_volume_rank = rank
        self.volume_percentile = ((total_stocks - rank) / total_stocks) * 100
        self.state = VolumeState.RANKED
    
    def is_processed(self) -> bool:
        """Check if volume data has been processed."""
        return self.state in [VolumeState.PROCESSED, VolumeState.RANKED]
    
    def is_ranked(self) -> bool:
        """Check if volume data has been ranked."""
        return self.state == VolumeState.RANKED
    
    def to_dict(self):
        """Convert to dictionary."""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: dict) -> "TradingVolume":
        """Create TradingVolume instance from dictionary."""
        return cls(**data)

