"""UserSession model for performance tracking and monitoring."""

from datetime import datetime
from typing import Optional
from enum import Enum
import json

from pydantic import BaseModel, Field, validator


class CompletionStatus(str, Enum):
    """Status of session completion."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class UserSession(BaseModel):
    """Represents user interaction sessions for performance monitoring.
    
    Attributes:
        session_id: Unique session identifier
        user_count: Number of concurrent users during session
        request_timestamp: When request was initiated
        response_time: Total response time in seconds
        endpoint: API endpoint accessed
        request_params: JSON string of request parameters
        completion_status: Success/failure status
        memory_usage: Peak memory usage in MB
        cpu_usage: Average CPU usage percentage
    """
    
    session_id: str = Field(..., description="Unique session identifier")
    user_count: int = Field(
        default=1,
        ge=1,
        le=1000,
        description="Number of concurrent users during session"
    )
    request_timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When request was initiated"
    )
    response_time: Optional[float] = Field(
        None,
        ge=0.0,
        description="Total response time in seconds"
    )
    endpoint: str = Field(..., description="API endpoint accessed")
    request_params: str = Field(
        default="{}",
        description="JSON string of request parameters"
    )
    completion_status: CompletionStatus = Field(
        default=CompletionStatus.PENDING,
        description="Success/failure status"
    )
    memory_usage: Optional[int] = Field(
        None,
        ge=0,
        description="Peak memory usage in MB"
    )
    cpu_usage: Optional[float] = Field(
        None,
        ge=0.0,
        le=100.0,
        description="Average CPU usage percentage"
    )
    
    @validator("session_id")
    def validate_session_id(cls, v):
        """Validate session ID format."""
        if len(v) < 10:
            raise ValueError("Session ID must be at least 10 characters")
        return v
    
    @validator("request_params")
    def validate_request_params(cls, v):
        """Validate request params is valid JSON."""
        try:
            json.loads(v)
        except json.JSONDecodeError:
            raise ValueError("request_params must be valid JSON string")
        return v
    
    @validator("response_time")
    def validate_response_time(cls, v):
        """Validate response time is reasonable."""
        if v is not None and v > 3600:  # 1 hour
            raise ValueError(f"Response time {v}s exceeds reasonable limit")
        return v
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "session_id": "test-session-123",
                "user_count": 5,
                "request_timestamp": "2025-10-07T10:30:00Z",
                "response_time": 45.2,
                "endpoint": "/api/screening/run",
                "request_params": '{"volume_top_n": 100, "heat_top_n": 100}',
                "completion_status": "SUCCESS",
                "memory_usage": 256,
                "cpu_usage": 45.5
            }
        }
    
    def start_processing(self) -> None:
        """Mark session as processing."""
        self.completion_status = CompletionStatus.PROCESSING
    
    def mark_success(self, response_time: float) -> None:
        """Mark session as successful.
        
        Args:
            response_time: Total response time in seconds
        """
        self.completion_status = CompletionStatus.SUCCESS
        self.response_time = response_time
    
    def mark_failed(self, response_time: Optional[float] = None) -> None:
        """Mark session as failed.
        
        Args:
            response_time: Total response time in seconds
        """
        self.completion_status = CompletionStatus.FAILED
        if response_time is not None:
            self.response_time = response_time
    
    def mark_timeout(self, response_time: float) -> None:
        """Mark session as timed out.
        
        Args:
            response_time: Total response time in seconds
        """
        self.completion_status = CompletionStatus.TIMEOUT
        self.response_time = response_time
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time since request started.
        
        Returns:
            Elapsed time in seconds
        """
        return (datetime.now() - self.request_timestamp).total_seconds()
    
    def is_within_sla(self, sla_seconds: float = 300.0) -> bool:
        """Check if session is within SLA.
        
        Args:
            sla_seconds: SLA threshold in seconds (default: 5 minutes)
            
        Returns:
            True if response time is within SLA
        """
        if self.response_time is None:
            return self.get_elapsed_time() <= sla_seconds
        return self.response_time <= sla_seconds
    
    def is_memory_efficient(self, threshold_mb: int = 2048) -> bool:
        """Check if memory usage is within threshold.
        
        Args:
            threshold_mb: Memory threshold in MB (default: 2GB)
            
        Returns:
            True if memory usage is below threshold
        """
        if self.memory_usage is None:
            return True
        return self.memory_usage <= threshold_mb
    
    def is_cpu_efficient(self, threshold_percent: float = 80.0) -> bool:
        """Check if CPU usage is within threshold.
        
        Args:
            threshold_percent: CPU threshold percentage
            
        Returns:
            True if CPU usage is below threshold
        """
        if self.cpu_usage is None:
            return True
        return self.cpu_usage <= threshold_percent
    
    def meets_performance_targets(self) -> bool:
        """Check if session meets all performance targets.
        
        Returns:
            True if all targets are met
        """
        return (
            self.is_within_sla() and
            self.is_memory_efficient() and
            self.is_cpu_efficient()
        )
    
    def get_params_dict(self) -> dict:
        """Get request parameters as dictionary.
        
        Returns:
            Dictionary of request parameters
        """
        return json.loads(self.request_params)
    
    def get_performance_summary(self) -> dict:
        """Get performance summary.
        
        Returns:
            Dictionary with performance metrics
        """
        return {
            "session_id": self.session_id,
            "endpoint": self.endpoint,
            "response_time": self.response_time,
            "memory_usage": self.memory_usage,
            "cpu_usage": self.cpu_usage,
            "completion_status": self.completion_status,
            "within_sla": self.is_within_sla(),
            "memory_efficient": self.is_memory_efficient(),
            "cpu_efficient": self.is_cpu_efficient()
        }
    
    def to_dict(self):
        """Convert to dictionary."""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: dict) -> "UserSession":
        """Create UserSession instance from dictionary."""
        return cls(**data)
    
    @classmethod
    def create_session(
        cls,
        session_id: str,
        endpoint: str,
        request_params: dict,
        user_count: int = 1
    ) -> "UserSession":
        """Create a new user session.
        
        Args:
            session_id: Unique session identifier
            endpoint: API endpoint
            request_params: Request parameters
            user_count: Number of concurrent users
            
        Returns:
            UserSession instance
        """
        return cls(
            session_id=session_id,
            endpoint=endpoint,
            request_params=json.dumps(request_params),
            user_count=user_count
        )

