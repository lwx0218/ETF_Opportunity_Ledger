"""Configuration management for the stock screening system."""

from functools import lru_cache
from typing import List

from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Environment
    environment: str = Field(default="development", env="ENVIRONMENT")
    debug: bool = Field(default=True, env="DEBUG")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    # API Configuration
    api_host: str = Field(default="0.0.0.0", env="API_HOST")
    api_port: int = Field(default=8000, env="API_PORT")
    api_reload: bool = Field(default=True, env="API_RELOAD")

    # Data Source Configuration
    pywencai_rate_limit: int = Field(default=100, env="PYWENCAI_RATE_LIMIT")
    pywencai_retry_attempts: int = Field(default=3, env="PYWENCAI_RETRY_ATTEMPTS")
    pywencai_timeout: int = Field(default=30, env="PYWENCAI_TIMEOUT")
    pywencai_cookie: str = Field(default="", env="PYWENCAI_COOKIE")  # 同花顺问财Cookie
    
    # Akshare Configuration
    # Akshare是免费开源的数据接口，无需配置API密钥

    # Cache Configuration
    redis_host: str = Field(default="localhost", env="REDIS_HOST")
    redis_port: int = Field(default=6379, env="REDIS_PORT")
    redis_db: int = Field(default=0, env="REDIS_DB")
    cache_ttl: int = Field(default=300, env="CACHE_TTL")  # 5 minutes

    # Performance Configuration
    max_concurrent_users: int = Field(default=100, env="MAX_CONCURRENT_USERS")
    response_time_limit: int = Field(default=300, env="RESPONSE_TIME_LIMIT")  # 5 minutes
    memory_limit: int = Field(default=2048, env="MEMORY_LIMIT")  # 2GB

    # Security Configuration
    cors_origins: List[str] = Field(
        default=["*"],  # 允许所有来源（开发环境），生产环境应通过env指定具体域名
        env="CORS_ORIGINS"
    )
    api_rate_limit: int = Field(default=100, env="API_RATE_LIMIT")
    api_rate_window: int = Field(default=60, env="API_RATE_WINDOW")

    # Database Configuration
    database_url: str = Field(
        default="sqlite:///./stock_screening.db",
        env="DATABASE_URL"
    )

    # Logging Configuration
    log_file: str = Field(default="logs/stock_screening.log", env="LOG_FILE")
    log_rotation: str = Field(default="1 day", env="LOG_ROTATION")
    log_retention: str = Field(default="30 days", env="LOG_RETENTION")

    # Screening Default Parameters
    screening_defaults: dict = {
        "volume_top_n": 100,
        "heat_top_n": 100,
        "intersection_top_n": 30,  # 交集后加权排名取前30，避免遗漏动量强但综合排名靠后的股票
        "momentum_days": 25,
        "final_top_n": 10,
        "use_cache": True,
    }

    @validator("cors_origins", pre=True)
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.strip("[]").split(",")]
        return v

    @validator("log_level")
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}")
        return v.upper()

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()