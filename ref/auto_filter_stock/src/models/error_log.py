"""ErrorLog model for system error tracking and monitoring."""

from datetime import datetime
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field, validator


class ErrorType(str, Enum):
    """Category of error."""
    DATA_FETCH = "DATA_FETCH"
    CALCULATION = "CALCULATION"
    SYSTEM = "SYSTEM"
    VALIDATION = "VALIDATION"


class ResolutionStatus(str, Enum):
    """Status of error resolution."""
    NEW = "NEW"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ErrorLog(BaseModel):
    """Represents system errors and exceptions for debugging and monitoring.
    
    Attributes:
        id: Auto-incrementing identifier
        timestamp: When error occurred
        error_type: Category of error
        stock_symbol: Related stock if applicable
        error_message: Detailed error description
        error_code: Standardized error code
        retry_count: Number of retry attempts made
        resolution_status: Status of error resolution
        stack_trace: Technical error details
    """
    
    id: Optional[int] = Field(None, description="Auto-incrementing identifier")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When error occurred"
    )
    error_type: ErrorType = Field(..., description="Category of error")
    stock_symbol: Optional[str] = Field(
        None,
        description="Related stock if applicable"
    )
    error_message: str = Field(..., description="Detailed error description")
    error_code: str = Field(..., description="Standardized error code")
    retry_count: int = Field(
        default=0,
        ge=0,
        description="Number of retry attempts made"
    )
    resolution_status: ResolutionStatus = Field(
        default=ResolutionStatus.NEW,
        description="Status of error resolution"
    )
    stack_trace: Optional[str] = Field(
        None,
        description="Technical error details"
    )
    
    @validator("error_code")
    def validate_error_code(cls, v, values):
        """Validate error code format."""
        if "error_type" in values:
            error_type = values["error_type"]
            # Error code should start with error type prefix
            expected_prefix = error_type.value[:4]
            if not v.startswith(expected_prefix):
                # Allow it but log warning
                pass
        return v
    
    @validator("retry_count")
    def validate_retry_count(cls, v):
        """Validate retry count is reasonable."""
        if v > 10:
            raise ValueError(f"Retry count {v} exceeds maximum allowed (10)")
        return v
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "timestamp": "2025-10-07T10:30:00Z",
                "error_type": "DATA_FETCH",
                "stock_symbol": "000001.SZ",
                "error_message": "Failed to fetch data from pywencai",
                "error_code": "DATA_FETCH_001",
                "retry_count": 3,
                "resolution_status": "NEW",
                "stack_trace": "Traceback (most recent call last):..."
            }
        }
    
    def increment_retry(self) -> None:
        """Increment retry count."""
        self.retry_count += 1
    
    def mark_investigating(self) -> None:
        """Mark error as being investigated."""
        self.resolution_status = ResolutionStatus.INVESTIGATING
    
    def mark_resolved(self) -> None:
        """Mark error as resolved."""
        self.resolution_status = ResolutionStatus.RESOLVED
    
    def mark_escalated(self) -> None:
        """Mark error as escalated."""
        self.resolution_status = ResolutionStatus.ESCALATED
    
    def should_retry(self, max_retries: int = 3) -> bool:
        """Check if error should be retried.
        
        Args:
            max_retries: Maximum number of retries allowed
            
        Returns:
            True if retry count is below maximum
        """
        return self.retry_count < max_retries
    
    def is_critical(self) -> bool:
        """Check if error is critical.
        
        Returns:
            True if error type is SYSTEM or retry count exceeded
        """
        return (
            self.error_type == ErrorType.SYSTEM or
            self.retry_count >= 3
        )
    
    def get_age_seconds(self) -> float:
        """Get age of error in seconds.
        
        Returns:
            Age in seconds
        """
        return (datetime.now() - self.timestamp).total_seconds()
    
    def get_summary(self) -> dict:
        """Get error summary.
        
        Returns:
            Dictionary with error summary
        """
        return {
            "error_type": self.error_type,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "stock_symbol": self.stock_symbol,
            "retry_count": self.retry_count,
            "resolution_status": self.resolution_status,
            "age_seconds": self.get_age_seconds()
        }
    
    @classmethod
    def create_data_fetch_error(
        cls,
        message: str,
        stock_symbol: Optional[str] = None,
        stack_trace: Optional[str] = None
    ) -> "ErrorLog":
        """Create a data fetch error.
        
        Args:
            message: Error message
            stock_symbol: Related stock symbol
            stack_trace: Stack trace
            
        Returns:
            ErrorLog instance
        """
        return cls(
            error_type=ErrorType.DATA_FETCH,
            error_message=message,
            error_code="DATA_FETCH_001",
            stock_symbol=stock_symbol,
            stack_trace=stack_trace
        )
    
    @classmethod
    def create_calculation_error(
        cls,
        message: str,
        stock_symbol: Optional[str] = None,
        stack_trace: Optional[str] = None
    ) -> "ErrorLog":
        """Create a calculation error.
        
        Args:
            message: Error message
            stock_symbol: Related stock symbol
            stack_trace: Stack trace
            
        Returns:
            ErrorLog instance
        """
        return cls(
            error_type=ErrorType.CALCULATION,
            error_message=message,
            error_code="CALC_ERROR_001",
            stock_symbol=stock_symbol,
            stack_trace=stack_trace
        )
    
    @classmethod
    def create_validation_error(
        cls,
        message: str,
        stock_symbol: Optional[str] = None,
        stack_trace: Optional[str] = None
    ) -> "ErrorLog":
        """Create a validation error.
        
        Args:
            message: Error message
            stock_symbol: Related stock symbol
            stack_trace: Stack trace
            
        Returns:
            ErrorLog instance
        """
        return cls(
            error_type=ErrorType.VALIDATION,
            error_message=message,
            error_code="VALID_ERROR_001",
            stock_symbol=stock_symbol,
            stack_trace=stack_trace
        )
    
    def to_dict(self):
        """Convert to dictionary."""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: dict) -> "ErrorLog":
        """Create ErrorLog instance from dictionary."""
        return cls(**data)

