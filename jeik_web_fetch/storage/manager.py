import os
import re
import time
import tempfile
from pathlib import Path
from typing import Optional, Dict

class StorageManager:
    """
    统一本地存储管理：
    - 默认落地到执行当前工作目录下的 `.jeik/fetches/`
    - 自动根据 URL 生成规范、安全、易辨识的文件名（带精确时间戳）
    - 永远返回绝对路径（Absolute Path），防止任何 Agent 发生工作目录偏移与相对路径混淆
    """
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir

    def _sanitize_filename(self, url: str) -> str:
        # 去掉 http/https 协议前缀
        cleaned = re.sub(r"^https?://", "", url)
        # 将路径分隔符或特殊字符替换为单下划线
        cleaned = re.sub(r"[^\w\.-]", "_", cleaned)
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned[:90] or "document"

    def get_target_dir(self, custom_dir: Optional[str] = None) -> str:
        if custom_dir:
            p = Path(custom_dir).resolve()
            p.mkdir(parents=True, exist_ok=True)
            return str(p)
        if self.base_dir:
            p = Path(self.base_dir).resolve()
            p.mkdir(parents=True, exist_ok=True)
            return str(p)
        
        # 默认：当前运行目录下的 .jeik/fetches
        p = Path.cwd().resolve() / ".jeik" / "fetches"
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    def save_content(self, url: str, content: str, ext: str, custom_dir: Optional[str] = None) -> str:
        target_dir = Path(self.get_target_dir(custom_dir))
        base_name = self._sanitize_filename(url)
        ext = ext.lstrip(".")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{base_name}_{timestamp}.{ext}"
        filepath = (target_dir / filename).resolve()

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        # 始终返回绝对路径
        return str(filepath)

# 全局默认存储实例
default_storage = StorageManager()
