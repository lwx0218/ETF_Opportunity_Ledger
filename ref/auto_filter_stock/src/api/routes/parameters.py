"""Parameters management API endpoints."""

from typing import Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.config.parameters import ScreeningParams

router = APIRouter()

# In-memory storage for current parameters (in production, use database/cache)
_current_parameters = ScreeningParams()


class ParametersResponse(BaseModel):
    """Response model for parameters."""
    volume_top_n: int
    heat_top_n: int
    intersection_top_n: int
    momentum_days: int
    final_top_n: int
    use_cache: bool


class ParametersUpdateRequest(BaseModel):
    """Request model for updating parameters."""
    volume_top_n: Optional[int] = Field(None, ge=10, le=500)
    heat_top_n: Optional[int] = Field(None, ge=10, le=500)
    intersection_top_n: Optional[int] = Field(None, ge=10, le=100)
    momentum_days: Optional[int] = Field(None, ge=5, le=60)
    final_top_n: Optional[int] = Field(None, ge=5, le=50)
    use_cache: Optional[bool] = None


@router.get("/", response_model=ParametersResponse)
async def get_parameters():
    """Get current screening parameters."""
    global _current_parameters
    return ParametersResponse(
        volume_top_n=_current_parameters.volume_top_n,
        heat_top_n=_current_parameters.heat_top_n,
        intersection_top_n=_current_parameters.intersection_top_n,
        momentum_days=_current_parameters.momentum_days,
        final_top_n=_current_parameters.final_top_n,
        use_cache=_current_parameters.use_cache
    )


@router.put("/", response_model=ParametersResponse)
async def update_parameters(request: ParametersUpdateRequest):
    """Update screening parameters."""
    global _current_parameters
    
    try:
        # Create updated parameters
        updated_params = ScreeningParams(
            volume_top_n=request.volume_top_n if request.volume_top_n is not None else _current_parameters.volume_top_n,
            heat_top_n=request.heat_top_n if request.heat_top_n is not None else _current_parameters.heat_top_n,
            intersection_top_n=request.intersection_top_n if request.intersection_top_n is not None else _current_parameters.intersection_top_n,
            momentum_days=request.momentum_days if request.momentum_days is not None else _current_parameters.momentum_days,
            final_top_n=request.final_top_n if request.final_top_n is not None else _current_parameters.final_top_n,
            use_cache=request.use_cache if request.use_cache is not None else _current_parameters.use_cache
        )
        
        # Validate that final_top_n doesn't exceed the intersection size
        max_intersection = min(updated_params.volume_top_n, updated_params.heat_top_n)
        if updated_params.final_top_n > max_intersection:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"final_top_n ({updated_params.final_top_n}) cannot exceed the minimum of volume_top_n and heat_top_n ({max_intersection})"
            )
        
        # Update global parameters
        _current_parameters = updated_params
        
        return ParametersResponse(
            volume_top_n=_current_parameters.volume_top_n,
            heat_top_n=_current_parameters.heat_top_n,
            intersection_top_n=_current_parameters.intersection_top_n,
            momentum_days=_current_parameters.momentum_days,
            final_top_n=_current_parameters.final_top_n,
            use_cache=_current_parameters.use_cache
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid parameters: {str(e)}"
        )


@router.get("/default", response_model=ParametersResponse)
async def get_default_parameters():
    """Get default screening parameters."""
    default_params = ScreeningParams()
    return ParametersResponse(
        volume_top_n=default_params.volume_top_n,
        heat_top_n=default_params.heat_top_n,
        intersection_top_n=default_params.intersection_top_n,
        momentum_days=default_params.momentum_days,
        final_top_n=default_params.final_top_n,
        use_cache=default_params.use_cache
    )


@router.post("/reset", response_model=ParametersResponse)
async def reset_parameters():
    """Reset parameters to default values."""
    global _current_parameters
    _current_parameters = ScreeningParams()
    
    return ParametersResponse(
        volume_top_n=_current_parameters.volume_top_n,
        heat_top_n=_current_parameters.heat_top_n,
        intersection_top_n=_current_parameters.intersection_top_n,
        momentum_days=_current_parameters.momentum_days,
        final_top_n=_current_parameters.final_top_n,
        use_cache=_current_parameters.use_cache
    )

