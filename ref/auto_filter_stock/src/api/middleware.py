"""Middleware configuration for FastAPI application."""

import time
from typing import Callable
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from loguru import logger


def setup_middleware(app: FastAPI):
    """Configure all middleware for the application."""
    
    # Request timing middleware
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next: Callable):
        """Add processing time header to responses."""
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response
    
    # Request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next: Callable):
        """Log incoming requests and responses."""
        start_time = time.time()
        
        # Log request
        logger.info(
            f"Incoming request: {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'}"
        )
        
        # Process request
        response = await call_next(request)
        
        # Log response
        process_time = time.time() - start_time
        logger.info(
            f"Response: {response.status_code} for {request.method} {request.url.path} "
            f"in {process_time:.3f}s"
        )
        
        return response
    
    # GZip compression middleware
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    
    # Security headers middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: Callable):
        """Add security headers to responses."""
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response
    
    # Rate limiting headers (placeholder for actual rate limiting)
    @app.middleware("http")
    async def add_rate_limit_headers(request: Request, call_next: Callable):
        """Add rate limiting headers."""
        response = await call_next(request)
        
        # Add rate limit headers (these would be set by actual rate limiting)
        response.headers["X-RateLimit-Limit"] = "1000"
        response.headers["X-RateLimit-Remaining"] = "999"
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + 3600)
        
        return response


def setup_error_handlers(app: FastAPI):
    """Configure error handlers for the application."""
    
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        """Handle 404 Not Found errors."""
        logger.warning(f"404 error for {request.url.path}")
        return JSONResponse(
            status_code=404,
            content={"error": "Not Found", "message": "The requested resource was not found"}
        )
    
    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc):
        """Handle 500 Internal Server errors."""
        logger.error(f"500 error for {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error", "message": "An internal server error occurred"}
        )