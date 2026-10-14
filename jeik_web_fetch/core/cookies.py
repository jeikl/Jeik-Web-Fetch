import os
import re
import json
import time
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any, Union

class CookieHelper:
    """
    通用 Cookie 解析与适配工具：
    - 支持直接 Cookie 字符串 ("name=value; foo=bar")
    - 支持字典格式 ({"name": "value"})
    - 支持标准 Cookie 对象列表 ([{"name": "...", "value": "..."}])
    - 支持从 Netscape cookies.txt 或 JSON 文件中读取
    - 提供适配 HTTP 请求头 (Cookie Header) 与 Chrome CDP (Network.setCookies) 的转换方法
    """

    @staticmethod
    def parse_cookie_string(raw_str: str) -> List[Dict[str, Any]]:
        """解析类似 'key1=val1; key2=val2' 的 Cookie 字符串"""
        cookies = []
        if not raw_str or not raw_str.strip():
            return cookies

        # 兼容以 Cookie: 开头的完整 header 行
        if raw_str.lower().startswith("cookie:"):
            raw_str = raw_str[7:].strip()

        # 支持分号或换行符分隔
        parts = re.split(r"[;\r\n]+", raw_str)
        for part in parts:
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, val = part.split("=", 1)
            name = name.strip()
            val = val.strip()
            if name:
                cookies.append({
                    "name": name,
                    "value": val,
                    "path": "/",
                })
        return cookies

    @staticmethod
    def parse_netscape_cookies(content: str) -> List[Dict[str, Any]]:
        """
        解析标准的 Netscape / Curl cookies.txt 格式：
        domain, flag, path, secure, expiration, name, value
        """
        cookies = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) >= 7:
                domain, flag, path, secure, expires, name, value = fields[:7]
                cookie_dict = {
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": domain.strip(),
                    "path": path.strip() or "/",
                    "secure": secure.strip().upper() == "TRUE",
                }
                try:
                    exp_val = float(expires.strip())
                    if exp_val > 0:
                        cookie_dict["expires"] = exp_val
                except ValueError:
                    pass
                cookies.append(cookie_dict)
            elif "=" in line:
                # 容错：有些文件中直接放了 key=val
                cookies.extend(CookieHelper.parse_cookie_string(line))
        return cookies

    @classmethod
    def load_from_file(cls, file_path: Union[str, Path]) -> List[Dict[str, Any]]:
        """从文件 (JSON 或 Netscape txt) 中加载 Cookie"""
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Cookie 文件未找到: {path}")

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1", errors="replace")

        trimmed = content.strip()
        # 尝试作为 JSON 加载
        if trimmed.startswith("[") or trimmed.startswith("{"):
            try:
                data = json.loads(trimmed)
                if isinstance(data, list):
                    return cls.normalize_cookies(data)
                elif isinstance(data, dict):
                    # 如果顶层是字典，可能是 {"cookies": [...]} 或直接是 {name: val}
                    if "cookies" in data and isinstance(data["cookies"], list):
                        return cls.normalize_cookies(data["cookies"])
                    return cls.normalize_cookies(data)
            except Exception:
                pass

        # 尝试作为 Netscape txt 或标准键值字符串解析
        return cls.parse_netscape_cookies(content)

    @classmethod
    def normalize_cookies(
        cls,
        raw: Any,
        target_url: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        核心归一化适配器：
        将任意格式（字符串、文件路径、字典、对象列表）统一转换为标准 Cookie 字典列表。
        """
        if not raw:
            return []

        # 1. 如果是文件路径（字符串且存在该文件）
        if isinstance(raw, (str, Path)):
            raw_str = str(raw).strip()
            # 只有当它是一个实际存在的有效路径，且不包含分号等 cookie 格式特征时当作文件读取
            if "\n" not in raw_str and ";" not in raw_str and len(raw_str) < 512:
                try:
                    p = Path(raw_str).expanduser()
                    if p.is_file():
                        return cls.load_from_file(p)
                except Exception:
                    pass
            # 否则作为 cookie 字符串解析
            return cls.parse_cookie_string(raw_str)

        # 2. 如果是字典格式 {"key": "value"}
        if isinstance(raw, dict):
            # 检查是否嵌套了 cookies 键
            if "cookies" in raw and isinstance(raw["cookies"], list):
                return cls.normalize_cookies(raw["cookies"], target_url=target_url)
            cookies = []
            for k, v in raw.items():
                if isinstance(v, dict):
                    item = dict(v)
                    item.setdefault("name", k)
                    cookies.append(item)
                else:
                    cookies.append({
                        "name": str(k).strip(),
                        "value": str(v).strip(),
                        "path": "/",
                    })
            return cls.normalize_cookies(cookies, target_url=target_url)

        # 3. 如果是列表格式
        if isinstance(raw, list):
            cookies = []
            default_domain = None
            if target_url:
                try:
                    default_domain = urlparse(target_url).hostname
                except Exception:
                    pass

            for item in raw:
                if isinstance(item, dict):
                    c = {
                        "name": str(item.get("name", "")).strip(),
                        "value": str(item.get("value", "")).strip(),
                        "path": str(item.get("path", "/")).strip() or "/",
                    }
                    if not c["name"]:
                        continue
                    if "domain" in item and item["domain"]:
                        c["domain"] = str(item["domain"]).strip()
                    elif default_domain:
                        c["domain"] = default_domain

                    if "secure" in item:
                        c["secure"] = bool(item["secure"])
                    if "httpOnly" in item:
                        c["httpOnly"] = bool(item["httpOnly"])
                    if "sameSite" in item and item["sameSite"]:
                        c["sameSite"] = str(item["sameSite"])
                    if "expires" in item and item["expires"]:
                        try:
                            c["expires"] = float(item["expires"])
                        except (ValueError, TypeError):
                            pass
                    cookies.append(c)
                elif isinstance(item, str):
                    cookies.extend(cls.parse_cookie_string(item))
            return cookies

        return []

    @staticmethod
    def to_cookie_header(cookies: List[Dict[str, Any]]) -> str:
        """
        转换为 HTTP 请求头 'Cookie: ...' 所需的纯字符串形式
        例如: 'sessionid=123; token=abc'
        """
        pairs = []
        for c in cookies:
            name = c.get("name")
            value = c.get("value")
            if name:
                pairs.append(f"{name}={value or ''}")
        return "; ".join(pairs)

    @staticmethod
    def to_cdp_cookies(cookies: List[Dict[str, Any]], target_url: str) -> List[Dict[str, Any]]:
        """
        转换为符合 Chrome DevTools Protocol (CDP) Network.setCookies 规范的参数结构
        """
        parsed = urlparse(target_url)
        hostname = parsed.hostname or ""
        cdp_list = []

        for c in cookies:
            name = c.get("name")
            if not name:
                continue
            item = {
                "name": name,
                "value": c.get("value", ""),
                "url": target_url,
                "path": c.get("path") or "/",
            }
            domain = c.get("domain") or hostname
            if domain:
                item["domain"] = domain
            if "secure" in c:
                item["secure"] = bool(c["secure"])
            if "httpOnly" in c:
                item["httpOnly"] = bool(c["httpOnly"])
            if "sameSite" in c and c["sameSite"]:
                item["sameSite"] = c["sameSite"]
            if "expires" in c:
                item["expires"] = c["expires"]

            cdp_list.append(item)
        return cdp_list


class CookieStore:
    """
    域名级持久化 Cookie 管理器 (Domain-level Cookie Persistence)：
    - 存储于用户全局主目录 ~/.jeik/cookies/{domain}.json
    - 支持按域名自动级联检索匹配（如访问 a.b.com 会逐级匹配 a.b.com -> b.com）
    - 提供 CLI 命令行 `jeik cookie set/list/delete` 存储维护支持
    """
    def __init__(self, storage_dir: Optional[Union[str, Path]] = None):
        if storage_dir:
            self.base_dir = Path(storage_dir).expanduser().resolve()
        else:
            self.base_dir = Path.home() / ".jeik" / "cookies"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_domain(self, domain: str) -> str:
        """清洗域名字符串作为安全文件名"""
        d = domain.strip().lower()
        d = re.sub(r"^https?://", "", d)
        d = d.split(":")[0].split("/")[0]
        d = re.sub(r"[^\w\.-]", "_", d)
        return d.strip("._")

    def save_for_domain(self, domain: str, raw_cookies: Any) -> Path:
        """保存指定域名的持久化登录态 Cookie"""
        clean_domain = self._sanitize_domain(domain)
        if not clean_domain:
            raise ValueError(f"无效的域名: {domain}")

        cookies = CookieHelper.normalize_cookies(raw_cookies, target_url=f"https://{clean_domain}")
        out_file = self.base_dir / f"{clean_domain}.json"
        
        payload = {
            "domain": clean_domain,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(cookies),
            "cookies": cookies
        }
        out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return out_file

    def get_for_url_or_domain(self, url_or_domain: str) -> List[Dict[str, Any]]:
        """
        根据 URL 或域名级联查找匹配的持久化 Cookie：
        例如输入 'https://pan.baidu.com/disk/home'：
        1. 尝试 pan.baidu.com.json
        2. 尝试 baidu.com.json
        """
        clean = self._sanitize_domain(url_or_domain)
        if not clean:
            return []

        # 构造级联候选域名列表
        parts = clean.split(".")
        candidates = []
        for i in range(len(parts) - 1):
            cand = ".".join(parts[i:])
            candidates.append(cand)

        for cand in candidates:
            file_path = self.base_dir / f"{cand}.json"
            if file_path.is_file():
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and "cookies" in data:
                        return data["cookies"]
                    elif isinstance(data, list):
                        return data
                except Exception:
                    continue
        return []

    def list_all(self) -> List[Dict[str, Any]]:
        """列出所有已保存登录态的域名及信息"""
        result = []
        if not self.base_dir.exists():
            return result

        for f in sorted(self.base_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                domain = data.get("domain", f.stem)
                count = len(data.get("cookies", []))
                updated_at = data.get("updated_at", "unknown")
                result.append({
                    "domain": domain,
                    "count": count,
                    "updated_at": updated_at,
                    "file": str(f.resolve())
                })
            except Exception:
                continue
        return result

    def delete_for_domain(self, domain: str) -> bool:
        """删除指定域名的持久化登录态"""
        clean_domain = self._sanitize_domain(domain)
        file_path = self.base_dir / f"{clean_domain}.json"
        if file_path.is_file():
            file_path.unlink()
            return True
        return False

# 全局默认持久化实例
default_cookie_store = CookieStore()
