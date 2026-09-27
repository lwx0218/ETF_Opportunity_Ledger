"""Stock model representing a tradable security."""

from datetime import datetime
from typing import Optional
import re

from pydantic import BaseModel, Field, field_validator


class Stock(BaseModel):
    """Represents a tradable security in the market.
    
    Attributes:
        symbol: Stock symbol/code (e.g., "000001.SZ")
        name: Company name (e.g., "平安银行")
        current_price: Latest trading price
        previous_close: Previous day's closing price
        price_change: Price change amount
        price_change_percent: Price change percentage
        market_cap: Total market capitalization
        sector: Industry sector classification
        last_updated: Timestamp of last data update
    """
    
    symbol: str = Field(..., description="Stock symbol/code")
    name: str = Field(..., description="Company name")
    current_price: float = Field(..., gt=0, description="Latest trading price")
    previous_close: float = Field(..., gt=0, description="Previous day's closing price")
    price_change: float = Field(..., description="Price change amount")
    price_change_percent: float = Field(
        ..., 
        ge=-20.0, 
        le=20.0, 
        description="Price change percentage"
    )
    market_cap: float = Field(..., gt=0, description="Total market capitalization")
    sector: str = Field(..., description="Industry sector classification")
    last_updated: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp of last data update"
    )
    
    @field_validator("symbol")
    def validate_symbol(cls, v):
        """Validate stock symbol format."""
        pattern = r"^[0-9]{6}\.(SZ|SH|SS)$"
        if not re.match(pattern, v):
            raise ValueError(
                f"Invalid stock symbol format: {v}. "
                "Expected format: XXXXXX.SZ or XXXXXX.SH"
            )
        return v
    
    @field_validator("price_change")
    def validate_price_change(cls, v, info):
        """Validate price change is consistent with current and previous prices."""
        current_price = info.data.get("current_price")
        previous_close = info.data.get("previous_close")
        if current_price is not None and previous_close is not None:
            expected_change = current_price - previous_close
            if abs(v - expected_change) > 0.01:  # Allow small floating point errors
                raise ValueError(
                    f"Price change {v} is inconsistent with "
                    f"current_price {current_price} and "
                    f"previous_close {previous_close}"
                )
        return v
    
    @field_validator("price_change_percent")
    def validate_price_change_percent(cls, v, info):
        """Validate price change percentage is consistent with prices."""
        current_price = info.data.get("current_price")
        previous_close = info.data.get("previous_close")
        if current_price is not None and previous_close is not None:
            expected_percent = (
                (current_price - previous_close) 
                / previous_close 
                * 100
            )
            if abs(v - expected_percent) > 0.1:  # Allow small rounding errors
                raise ValueError(
                    f"Price change percent {v}% is inconsistent with "
                    f"calculated value {expected_percent:.2f}%"
                )
        return v
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "symbol": "000001.SZ",
                "name": "平安银行",
                "current_price": 12.34,
                "previous_close": 12.10,
                "price_change": 0.24,
                "price_change_percent": 1.98,
                "market_cap": 250000000000,
                "sector": "银行",
                "last_updated": "2025-10-07T10:30:00Z"
            }
        }
    }
    
    def is_active(self) -> bool:
        """Check if stock is actively trading."""
        # Stock is considered active if updated within last trading day
        time_diff = datetime.now() - self.last_updated
        return time_diff.total_seconds() < 86400  # 24 hours
    
    def get_price_direction(self) -> str:
        """Get price movement direction."""
        if self.price_change > 0:
            return "UP"
        elif self.price_change < 0:
            return "DOWN"
        else:
            return "FLAT"
    
    def to_dict(self):
        """Convert to dictionary."""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: dict) -> "Stock":
        """Create Stock instance from dictionary."""
        return cls(**data)

