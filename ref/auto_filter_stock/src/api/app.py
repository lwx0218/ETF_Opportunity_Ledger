"""Main FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse
from contextlib import asynccontextmanager
import asyncio
import os

from src.config.settings import get_settings
from src.utils.logging import setup_logging
from .middleware import setup_middleware
from .routes import screening, charts, health, progress, parameters
from .dependencies import Services


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    settings = get_settings()
    setup_logging(settings.log_level)
    
    # Initialize services
    services = Services()
    await services.initialize()
    app.state.services = services
    
    yield
    
    # Shutdown
    await services.shutdown()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title="Auto Filter Stock API",
        description="Stock screening and analysis API with visualization capabilities",
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan
    )
    
    # Setup CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Setup custom middleware
    setup_middleware(app)
    
    # Root endpoint - serve visualization directly
    @app.get("/")
    async def root():
        static_path = os.path.join(os.getcwd(), "static", "index.html")
        if os.path.exists(static_path):
            return FileResponse(static_path)
        else:
            return {"message": "Visualization not found"}
    
    # Mount static files
    app.mount("/static", StaticFiles(directory="static"), name="static")
    
    # Include routers with both /api/ and /api/v1/ prefixes for backward compatibility
    # Primary routes (for tests and spec compliance)
    app.include_router(health.router, prefix="/api/system", tags=["system"])
    app.include_router(screening.router, prefix="/api/screening", tags=["screening"])
    app.include_router(charts.router, prefix="/api/stocks", tags=["stocks"])
    app.include_router(progress.router, prefix="/api/progress", tags=["progress"])
    app.include_router(parameters.router, prefix="/api/parameters", tags=["parameters"])

    # Legacy v1 routes (for backward compatibility)
    app.include_router(health.router, prefix="/api/v1/health", tags=["health-v1"])
    app.include_router(screening.router, prefix="/api/v1/screening", tags=["screening-v1"])
    app.include_router(charts.router, prefix="/api/v1/charts", tags=["charts-v1"])
    app.include_router(progress.router, prefix="/api/v1/progress", tags=["progress-v1"])

    @app.get("/api/v1")
    async def api_info():
        return {
            "name": "Auto Filter Stock API",
            "version": "1.0.0",
            "endpoints": {
                "health": "/api/system",
                "screening": "/api/screening",
                "charts": "/api/stocks",
                "docs": "/docs" if settings.debug else None
            }
        }
    
    return app


# Create the app instance for uvicorn
app = create_app()