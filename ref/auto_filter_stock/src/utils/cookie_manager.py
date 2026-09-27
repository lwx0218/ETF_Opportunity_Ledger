"""Cookie管理器 - 用于管理同花顺问财的Cookie"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict
from loguru import logger


class CookieManager:
    """管理pywencai API所需的Cookie"""
    
    def __init__(self, cookie_file: str = ".cookie_cache.json"):
        """初始化Cookie管理器
        
        Args:
            cookie_file: Cookie缓存文件路径
        """
        self.cookie_file = Path(__file__).parent.parent.parent / cookie_file
        self._cookie: Optional[str] = None
        self._cookie_expiry: Optional[datetime] = None
        
    def get_cookie(self) -> Optional[str]:
        """获取有效的Cookie
        
        Returns:
            有效的Cookie字符串，如果无法获取则返回None
        """
        # 1. 尝试从settings读取（从.env文件加载）
        try:
            from src.config.settings import get_settings
            settings = get_settings()
            if settings.pywencai_cookie:
                logger.info("Using cookie from settings (.env file)")
                return settings.pywencai_cookie
        except Exception as e:
            logger.debug(f"Failed to load cookie from settings: {e}")
        
        # 2. 尝试从环境变量读取
        env_cookie = os.getenv('PYWENCAI_COOKIE', '').strip()
        if env_cookie:
            logger.info("Using cookie from environment variable")
            return env_cookie
        
        # 3. 尝试从缓存文件读取
        cached_cookie = self._load_from_cache()
        if cached_cookie:
            logger.info("Using cookie from cache file")
            return cached_cookie
        
        # 4. 都没有，返回None并记录警告
        logger.warning("No valid cookie found. Please configure PYWENCAI_COOKIE")
        logger.warning("Run './setup_cookie.sh' or see COOKIE_SETUP.md for instructions")
        return None
    
    def _load_from_cache(self) -> Optional[str]:
        """从缓存文件加载Cookie
        
        Returns:
            缓存的Cookie字符串，如果缓存无效则返回None
        """
        if not self.cookie_file.exists():
            return None
        
        try:
            with open(self.cookie_file, 'r') as f:
                cache_data = json.load(f)
            
            cookie = cache_data.get('cookie')
            expiry_str = cache_data.get('expiry')
            
            if not cookie or not expiry_str:
                return None
            
            # 检查是否过期
            expiry = datetime.fromisoformat(expiry_str)
            if datetime.now() >= expiry:
                logger.warning("Cached cookie has expired")
                return None
            
            return cookie
            
        except Exception as e:
            logger.warning(f"Failed to load cookie from cache: {e}")
            return None
    
    def save_cookie(self, cookie: str, days_valid: int = 7):
        """保存Cookie到缓存文件
        
        Args:
            cookie: Cookie字符串
            days_valid: Cookie有效天数
        """
        try:
            cache_data = {
                'cookie': cookie,
                'expiry': (datetime.now() + timedelta(days=days_valid)).isoformat(),
                'saved_at': datetime.now().isoformat()
            }
            
            with open(self.cookie_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            logger.info(f"Cookie saved to cache (valid for {days_valid} days)")
            
        except Exception as e:
            logger.error(f"Failed to save cookie to cache: {e}")
    
    def clear_cache(self):
        """清除缓存的Cookie"""
        if self.cookie_file.exists():
            try:
                self.cookie_file.unlink()
                logger.info("Cookie cache cleared")
            except Exception as e:
                logger.error(f"Failed to clear cookie cache: {e}")
    
    def validate_cookie(self, cookie: str) -> bool:
        """验证Cookie格式是否正确
        
        Args:
            cookie: 要验证的Cookie字符串
            
        Returns:
            Cookie格式是否有效
        """
        if not cookie or len(cookie) < 10:
            return False
        
        # 基本格式检查：应该包含等号和分号
        if '=' not in cookie:
            return False
        
        # 检查是否包含常见的cookie字段
        common_fields = ['v=', 'PHPSESSID=', 'userid=']
        has_valid_field = any(field in cookie for field in common_fields)
        
        return has_valid_field
    
    def get_cookie_info(self) -> Dict:
        """获取当前Cookie的信息
        
        Returns:
            包含Cookie状态信息的字典
        """
        # 检查是否有cookie（从settings或环境变量）
        has_cookie = False
        try:
            from src.config.settings import get_settings
            settings = get_settings()
            has_cookie = bool(settings.pywencai_cookie)
        except Exception:
            pass
        
        if not has_cookie:
            has_cookie = bool(os.getenv('PYWENCAI_COOKIE'))
        
        info = {
            'has_env_cookie': has_cookie,
            'has_cached_cookie': False,
            'cache_expired': False,
            'cache_file_exists': self.cookie_file.exists()
        }
        
        if self.cookie_file.exists():
            try:
                with open(self.cookie_file, 'r') as f:
                    cache_data = json.load(f)
                
                info['has_cached_cookie'] = True
                
                expiry_str = cache_data.get('expiry')
                if expiry_str:
                    expiry = datetime.fromisoformat(expiry_str)
                    info['cache_expired'] = datetime.now() >= expiry
                    info['cache_expiry'] = expiry_str
                    
            except Exception as e:
                logger.debug(f"Error reading cookie info: {e}")
        
        return info


# 全局单例
_cookie_manager = None

def get_cookie_manager() -> CookieManager:
    """获取Cookie管理器单例"""
    global _cookie_manager
    if _cookie_manager is None:
        _cookie_manager = CookieManager()
    return _cookie_manager


