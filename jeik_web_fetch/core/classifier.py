import re
from typing import Tuple

class ContentQualityClassifier:
    """
    通用内容质量与特征分析器 (Content Quality & SPA Classifier):
    - 完全抛弃任何生硬的域名黑白名单，从根源上治本！
    - 基于“文本密度 (Text Density)”、“脚本/标签比”和“语义结构启发式”
    - 毫秒级对任意未知 URL 的首次 HTTP 响应做出精确裁决：
        1. 质量充足且结构完备 -> 直接秒级输出 Markdown
        2. 属于空壳骨架屏 / 脚本占绝对主导 / 触发状态异常 -> 自动自愈切换无头浏览器
    """

    # 常见反爬拦截关键词特征（触发直接切无头）
    CHALLENGE_KEYWORDS = [
        "captcha",
        "turnstile",
        "challenge-platform",
        "just a moment",
        "attention required",
        "cloudflare",
        "您当前请求存在异常",
        "访问被拒绝",
        "安全验证",
        "滑动验证",
        "robot",
        "shield",
    ]

    # 常见 SPA 挂载节点标记 (React, Vue, Angular, Next, Nuxt)
    SPA_MOUNT_PATTERNS = [
        r'<div\s+id=["\'](?:root|app|__next|__nuxt|main-app)["\']\s*>\s*</div>',
        r'<div\s+id=["\'](?:root|app|__next|__nuxt)["\']\s*>\s*<!--',
        r'<div\s+class=["\'](?:loading-skeleton|skeleton-wrapper)["\']',
    ]

    @classmethod
    def evaluate_html(cls, html: str, status_code: int = 200) -> Tuple[bool, str]:
        """
        评估 HTML 的有效正文价值：
        返回: (is_valid, reason)
        - is_valid=True: 静态 HTML 正文充沛且结构健康，直接转 Markdown 秒出；
        - is_valid=False: 判定为 SPA 骨架、被拦截或无有效文本，需升级至无头浏览器。
        """
        if status_code != 200:
            return False, f"HTTP status {status_code}"

        if not html or len(html) < 200:
            return False, "HTML response too small"

        # 1. 检查是否存在明显的反爬风控页面特征
        lower_html = html.lower()
        for kw in cls.CHALLENGE_KEYWORDS:
            if kw in lower_html:
                # 检查是否为误报（如果正文很长，可能只是文章在讨论验证码）
                if len(html) < 5000:
                    return False, f"Anti-bot challenge keyword detected: {kw}"

        # 2. 剥离不可见节点 (<script>, <style>, <noscript>) 评估真实有效正文
        body_without_code = re.sub(r'<(script|style|noscript|svg|iframe)[^>]*>[\s\S]*?</\1>', '', html, flags=re.I)
        plain_text = re.sub(r'<[^>]+>', ' ', body_without_code)
        plain_text = re.sub(r'\s+', ' ', plain_text).strip()
        plain_len = len(plain_text)

        # 3. 统计关键特征
        # SPA 骨架屏检测（例如钉钉 290KB 的静态 HTML 里只有 11 个可见字符）
        if plain_len < 100:
            return False, f"Almost zero visible text ({plain_len} chars), clearly an SPA skeleton"

        for pat in cls.SPA_MOUNT_PATTERNS:
            if re.search(pat, html, re.I) and plain_len < 600:
                return False, f"SPA mount point found with low initial text ({plain_len} chars)"

        # 4. 文本密度比 (Text-to-Tag Ratio)
        # 正常文章/GitHub/维基百科的纯文本至少有数千字符，且有丰富的标题和段落结构
        has_headings = bool(re.search(r'<h[1-6][^>]*>', body_without_code, re.I))
        has_paragraphs = bool(re.search(r'<p[^>]*>', body_without_code, re.I))
        has_articles = bool(re.search(r'<(article|main)[^>]*>', body_without_code, re.I))

        # 如果至少有 800 字以上的实质内容，且包含基础的标题或段落，认定为高价值静态页面
        if plain_len >= 800 and (has_headings or has_paragraphs or has_articles):
            return True, f"Rich semantic content ({plain_len} chars) with valid structure"

        # 对于介于 100~800 之间的短文本，如果脚本极多（>10 个 script 标签），大概率是前端客户端渲染
        script_count = len(re.findall(r'<script', html, re.I))
        if script_count >= 8 and plain_len < 500:
            return False, f"Script heavy ({script_count} scripts) but very low text ({plain_len} chars)"

        # 默认：文本量充沛则信任静态，过少则保险走无头
        if plain_len >= 500:
            return True, f"Adequate plain text ({plain_len} chars)"

        return False, f"Marginal content ({plain_len} chars), fallback to headless"
