"""Logging configuration using loguru."""

import sys
from pathlib import Path
from loguru import logger

from src.config.settings import settings


def setup_logging(log_level: str = None):
    """Configure structured logging with loguru."""
    
    # Use provided log level or default from settings
    effective_log_level = log_level or settings.log_level
    
    # Remove default handler
    logger.remove()
    
    # Console logging
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        level=effective_log_level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )
    
    # File logging
    log_file = Path(settings.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    logger.add(
        settings.log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
               "{name}:{function}:{line} - {message}",
        level=effective_log_level,
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        compression="zip",
        serialize=False,  # JSON format for structured logging
        backtrace=True,
        diagnose=True,
    )
    
    # Error logging to separate file
    logger.add(
        settings.log_file.replace(".log", "_errors.log"),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
               "{name}:{function}:{line} - {message}",
        level="ERROR",
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        compression="zip",
        backtrace=True,
        diagnose=True,
    )
    
    return logger


# Setup logging on import
logger = setup_logging()