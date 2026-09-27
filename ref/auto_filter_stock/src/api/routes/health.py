"""Health check endpoints for API monitoring."""

from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from src.api.dependencies import get_services, Services
from src.utils.cookie_manager import get_cookie_manager


router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    timestamp: datetime
    version: str
    services: Dict[str, str]
    details: Dict[str, Any]


class HealthCheck(BaseModel):
    """Health check status model."""
    status: str
    message: str
    timestamp: datetime


@router.get("/", response_model=HealthResponse)
async def health_check(services: Services = Depends(get_services)):
    """Comprehensive health check endpoint."""
    try:
        # Check individual services
        service_status = {}
        
        # Data services
        service_status["data_fetcher"] = "healthy" if services.data_fetcher else "unavailable"
        service_status["data_processor"] = "healthy" if services.data_processor else "unavailable"
        service_status["data_validator"] = "healthy" if services.data_validator else "unavailable"
        
        # Analysis services
        service_status["momentum_calculator"] = "healthy" if services.momentum_calculator else "unavailable"
        service_status["stock_screener"] = "healthy" if services.stock_screener else "unavailable"
        service_status["stock_ranker"] = "healthy" if services.stock_ranker else "unavailable"
        
        # Visualization services
        service_status["chart_generator"] = "healthy" if services.chart_generator else "unavailable"
        service_status["momentum_chart_generator"] = "healthy" if services.momentum_chart_generator else "unavailable"
        service_status["dashboard_generator"] = "healthy" if services.dashboard_generator else "unavailable"
        
        # Cookie configuration status
        cookie_manager = get_cookie_manager()
        cookie_info = cookie_manager.get_cookie_info()
        has_cookie = cookie_info['has_env_cookie'] or (cookie_info['has_cached_cookie'] and not cookie_info['cache_expired'])
        service_status["pywencai_cookie"] = "healthy" if has_cookie else "missing"
        
        # Determine overall status
        unhealthy_services = [k for k, v in service_status.items() if v != "healthy"]
        overall_status = "healthy" if not unhealthy_services else "degraded"
        
        return HealthResponse(
            status=overall_status,
            timestamp=datetime.now().isoformat(),
            version="1.0.0",
            services=service_status,
            details={
                "unhealthy_services": unhealthy_services,
                "service_count": len(service_status),
                "healthy_count": len([v for v in service_status.values() if v == "healthy"]),
                "cookie_status": cookie_info
            }
        )
        
    except Exception as e:
        return HealthResponse(
            status="unhealthy",
            timestamp=datetime.now().isoformat(),
            version="1.0.0",
            services={},
            details={"error": str(e)}
        )


@router.get("/simple", response_model=HealthCheck)
async def simple_health_check():
    """Simple health check endpoint."""
    return HealthCheck(
        status="healthy",
        message="API is running",
        timestamp=datetime.now().isoformat()
    )


@router.get("/ready")
async def readiness_check(services: Services = Depends(get_services)):
    """Readiness check for Kubernetes/Docker."""
    try:
        # Check if critical services are ready
        critical_services = [
            services.data_fetcher,
            services.stock_screener,
            services.chart_generator
        ]
        
        ready = all(service is not None for service in critical_services)
        
        if ready:
            return {"status": "ready", "timestamp": datetime.now().isoformat()}
        else:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "timestamp": datetime.now().isoformat()}
            )
            
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        )


@router.get("/live")
async def liveness_check():
    """Liveness check for Kubernetes/Docker."""
    return {"status": "alive", "timestamp": datetime.now()}


# Aliases for test compatibility
@router.get("/health", response_model=HealthResponse)
async def health_alias(services: Services = Depends(get_services)):
    """Health check endpoint (alias for /)."""
    return await health_check(services)


@router.get("/status", response_model=HealthResponse)
async def status_alias(services: Services = Depends(get_services)):
    """Status check endpoint (alias for /)."""
    return await health_check(services)
