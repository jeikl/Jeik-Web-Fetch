import re
from urllib.parse import urlparse

class PageRouter:
    """
    智能页面路由决策器 (Tiered Fetch Router):
    - 快速判断页面是属于传统服务端渲染 (SSR / 静态)，还是动态单页应用 (SPA / 重度反爬)
    - 静态页面走 0.5s 极速 HTTP 抓取，耗时缩减 80%！
    - 命中 SPA / 反爬 / 静态提取失败时，自愈升级为完整无头浏览器深度探索
    """

    # 1. 明确已知是服务端直出 (SSR) 的高频极速站点白名单
    FAST_SSR_DOMAINS = {
        "github.com",
        "raw.githubusercontent.com",
        "gist.github.com",
        "news.ycombinator.com",
        "wikipedia.org",
        "stackoverflow.com",
        "reddit.com",
        "v2ex.com",
        "huggingface.co",
        "arxiv.org",
        "medium.com",
        "dev.to",
        "pypi.org",
        "crates.io",
        "npmjs.com",
    }

    # 2. 明确已知是重度前端客户端渲染 (SPA / 现代微前端 / 动态反爬) 的站点黑名单
    SPA_DOMAINS = {
        "open.dingtalk.com",
        "dingtalk.com",
        "docs.volcengine.com",
        "volcengine.com",
        "aliyun.com",
        "zhuanlan.zhihu.com",
        "zhihu.com",
        "feishu.cn",
        "larksuite.com",
        "notion.so",
        "notion.site",
        "xiaohongshu.com",
    }

    @classmethod
    def prefer_fast_fetch(cls, url: str) -> bool:
        """如果域名在 SSR 白名单中，优先尝试极速流"""
        try:
            domain = urlparse(url).netloc.lower()
            # 匹配二级域名
            for white in cls.FAST_SSR_DOMAINS:
                if domain == white or domain.endswith("." + white):
                    return True
        except Exception:
            pass
        return False

    @classmethod
    def is_known_spa(cls, url: str) -> bool:
        """如果域名在已知 SPA 库中，直接走无头渲染流"""
        try:
            domain = urlparse(url).netloc.lower()
            for spa in cls.SPA_DOMAINS:
                if domain == spa or domain.endswith("." + spa):
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def is_spa_skeleton(html: str) -> bool:
        """
        启发式算法：检测抓取到的 HTML 是否只是一个空壳/骨架屏 (Skeleton)
        - 文本极少但充满了 <div id="root">, <div id="app">, <script>
        - 包含明确的现代 SPA 挂载标记
        """
        if not html:
            return True

        # 如果含有典型的 SPA 挂载点且正文极短
        has_spa_mount = bool(re.search(r'<div\s+id=["\'](?:root|app|__next|__nuxt)["\']\s*>\s*</div>', html, re.I))
        
        # 移除标签后统计纯文字
        clean_text = re.sub(r'<[^>]+>', ' ', html)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        # 纯文本少于 400 字符且有大量脚本
        if len(clean_text) < 400 and (has_spa_mount or "<script" in html.lower()):
            return True

        # 如果返回的是知乎/Cloudflare 等特征风控异常
        if "您当前请求存在异常" in clean_text or "Just a moment..." in clean_text or "Attention Required" in clean_text:
            return True

        return False
