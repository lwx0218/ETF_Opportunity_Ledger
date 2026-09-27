"""Main entry point for the Auto Filter Stock API."""

import uvicorn
from src.api.app import create_app
from src.config.settings import get_settings

# Create app instance for uvicorn
app = create_app()

def main():
    """Run the FastAPI application."""
    settings = get_settings()
    
    if settings.api_reload:
        # Use import string for reload mode
        uvicorn.run(
            "main:app",
            host=settings.api_host,
            port=settings.api_port,
            reload=settings.api_reload,
            log_level=settings.log_level.lower()
        )
    else:
        # Use app instance for production
        uvicorn.run(
            app,
            host=settings.api_host,
            port=settings.api_port,
            reload=False,
            log_level=settings.log_level.lower()
        )

if __name__ == "__main__":
    main()
