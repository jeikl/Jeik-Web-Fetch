import os
import re
import tempfile
from typing import Optional, Dict

class StorageManager:
    """
    统一本地存储管理：
    - 支持保存到系统级临时目录（带前缀，自动隔离）
    - 支持保存到用户自定义的工程产物目录
    - 自动根据 URL 生成规范友好的安全文件名
    """
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir

    def _sanitize_filename(self, url: str) -> str:
        # 去掉协议，替换非法字符为下划线
        cleaned = re.sub(r"^https?://", "", url)
        cleaned = re.sub(r"[^\w\.-]", "_", cleaned)
        return cleaned[:80].strip("_") or "page"

    def get_target_dir(self, custom_dir: Optional[str] = None) -> str:
        if custom_dir:
            os.makedirs(custom_dir, exist_ok=True)
            return custom_dir
        if self.base_dir:
            os.makedirs(self.base_dir, exist_ok=True)
            return self.base_dir
        
        # 默认使用系统临时目录中的专用隔离文件夹
        tmp = os.path.join(tempfile.gettempdir(), "jeik_fetch_artifacts")
        os.makedirs(tmp, exist_ok=True)
        return tmp

    def save_content(self, url: str, content: str, ext: str, custom_dir: Optional[str] = None) -> str:
        target_dir = self.get_target_dir(custom_dir)
        base_name = self._sanitize_filename(url)
        ext = ext.lstrip(".")
        filename = f"{base_name}.{ext}"
        filepath = os.path.join(target_dir, filename)

        # 存在同名则追加时间戳
        if os.path.exists(filepath):
            import time
            filepath = os.path.join(target_dir, f"{base_name}_{int(time.time()*1000)}.{ext}")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

# 全局默认存储实例
default_storage = StorageManager()
