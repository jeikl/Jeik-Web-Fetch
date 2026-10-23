import re
from typing import List, Dict, Tuple, Any, Optional
from bs4 import BeautifulSoup
from ..core.models import OutputFormat

from urllib.parse import urljoin

class ContentTransformer:
    """
    负责将浏览器渲染后的 HTML 按需拆解转换为多样化目标格式：
    - Markdown (高保真代码框还原、表格对齐、层级标题)
    - Clean HTML (仅清洗掉不可见脚本与广告)
    - Raw HTML (原始 DOM 镜像)
    - Text (人类可读纯文本)
    - Links (提取所有超链接结构列表)
    - Metadata (抽取标题、关键词、描述)
    """

    @staticmethod
    def extract_metadata(soup: BeautifulSoup) -> Dict[str, Any]:
        meta = {}
        title = soup.find("title")
        meta["title"] = title.get_text().strip() if title else ""
        
        desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)}) or \
               soup.find("meta", attrs={"property": re.compile(r"og:description", re.I)})
        meta["description"] = desc.get("content", "").strip() if desc else ""

        kw = soup.find("meta", attrs={"name": re.compile(r"keywords", re.I)})
        meta["keywords"] = kw.get("content", "").strip() if kw else ""
        return meta

    @staticmethod
    def extract_links(soup: BeautifulSoup, base_url: Optional[str] = None) -> List[Dict[str, str]]:
        links = []
        for a in soup.find_all("a"):
            href = a.get("href", "").strip()
            text = a.get_text().strip()
            if href:
                full_href = urljoin(base_url, href) if base_url else href
                links.append({"text": text, "href": full_href})
        return links

    @classmethod
    def extract_sidebar_navigation(cls, soup: BeautifulSoup, base_url: Optional[str] = None) -> str:
        """
        高保真提取文档系统（Docusaurus, Mintlify, VitePress, Nextra 等）的侧边栏菜单与超链接：
        - 识别目录分组与接口列表；
        - 将相对路径解析为完整的绝对 HTTP/HTTPS URL；
        - 标准化 HTTP Method 标记 (POST / GET / PUT / DELETE)；
        - 挂载为清晰严谨的 Markdown 目录导航。
        """
        aside = soup.find("aside") or soup.find(class_=lambda c: c and any(k in str(c).lower() for k in ["sidebar", "doc-sidebar", "menu__list", "docs-nav"]))
        if not aside:
            return ""

        all_links = aside.find_all("a")
        if len(all_links) < 2:
            return ""

        grouped_sections = []
        seen_hrefs = set()

        # 1. 优先尝试适配 Docusaurus 风格的分类 (theme-doc-sidebar-item-category)
        docusaurus_cats = aside.find_all(class_=lambda c: c and "theme-doc-sidebar-item-category" in str(c))
        for cat in docusaurus_cats:
            title_el = cat.find(class_=lambda c: c and any(k in str(c) for k in ["menu__list-item-collapsible", "menu__link--sublist", "category"]))
            if not title_el:
                title_el = cat.find(["a", "span", "div", "button"])
            cat_title = title_el.get_text().strip() if title_el else ""
            if not cat_title or len(cat_title) > 30:
                continue

            cat_links = []
            for a in cat.find_all("a"):
                href = a.get("href", "").strip()
                if not href or href.startswith("javascript:"):
                    continue
                full_href = urljoin(base_url, href) if base_url else href
                if full_href in seen_hrefs:
                    continue
                seen_hrefs.add(full_href)
                txt = a.get_text().strip()
                txt = re.sub(r'^(POST|GET|PUT|DELETE|PATCH)([A-Za-z\u4e00-\u9fa5])', r'\1 \2', txt)
                cat_links.append((txt, full_href))
            if cat_links:
                grouped_sections.append((cat_title, cat_links))

        # 2. 如果未命中 Docusaurus 风格，尝试通用按钮/标题分组 (如 MiMo, Mintlify)
        if not grouped_sections:
            category_btns = aside.find_all(lambda el: el.name in ["button", "h3", "h4", "h5", "div"] and 0 < len(el.get_text().strip()) <= 20 and not el.find("a"))
            valid_categories = []
            for btn in category_btns:
                btn_txt = btn.get_text().strip()
                if btn_txt in ["Ctrl", "搜索文档", "搜索", "Search", ""]:
                    continue
                p = btn.parent
                while p and p != aside and len(p.find_all("a")) == 0:
                    p = p.parent
                if p and len(p.find_all("a")) > 0:
                    valid_categories.append((btn_txt, p))

            if valid_categories:
                for cat_title, container in valid_categories:
                    cat_links = []
                    for a in container.find_all("a"):
                        href = a.get("href", "").strip()
                        if not href or href.startswith("javascript:"):
                            continue
                        full_href = urljoin(base_url, href) if base_url else href
                        if full_href in seen_hrefs:
                            continue
                        seen_hrefs.add(full_href)
                        txt = a.get_text().strip()
                        txt = re.sub(r'^(POST|GET|PUT|DELETE|PATCH)([A-Za-z\u4e00-\u9fa5])', r'\1 \2', txt)
                        cat_links.append((txt, full_href))
                    if cat_links:
                        grouped_sections.append((cat_title, cat_links))

        # 3. 收集未分组的剩余链接
        remaining_links = []
        for a in all_links:
            href = a.get("href", "").strip()
            if not href or href.startswith("javascript:"):
                continue
            full_href = urljoin(base_url, href) if base_url else href
            if full_href not in seen_hrefs:
                seen_hrefs.add(full_href)
                txt = a.get_text().strip()
                txt = re.sub(r'^(POST|GET|PUT|DELETE|PATCH)([A-Za-z\u4e00-\u9fa5])', r'\1 \2', txt)
                remaining_links.append((txt, full_href))

        if not grouped_sections and not remaining_links:
            return ""

        md_lines = ["\n\n---\n\n## 📚 关联文档与目录导航 (Sidebar Links)\n"]
        if remaining_links and grouped_sections:
            md_lines.append("\n### 核心接口\n")
            for txt, href in remaining_links:
                md_lines.append(f"- [{txt}]({href})")
        elif remaining_links:
            for txt, href in remaining_links:
                md_lines.append(f"- [{txt}]({href})")

        for cat_title, cat_links in grouped_sections:
            md_lines.append(f"\n### {cat_title}\n")
            for txt, href in cat_links:
                md_lines.append(f"- [{txt}]({href})")

        return "\n".join(md_lines)

    @classmethod
    def extract_pagination(cls, soup: BeautifulSoup, base_url: Optional[str] = None) -> str:
        """提取底部分页 (Previous / Next) 导航"""
        nav = soup.find(class_=lambda c: c and any(k in str(c) for k in ["pagination-nav", "docs-pagination"]))
        if not nav:
            nav = soup.find("nav", attrs={"aria-label": re.compile(r"pagination|pages", re.I)})
        if not nav:
            return ""

        prev_a = nav.find(class_=lambda c: c and "prev" in str(c))
        next_a = nav.find(class_=lambda c: c and "next" in str(c))

        parts = []
        if prev_a and prev_a.get("href"):
            txt = prev_a.get_text().replace("Previous", "").replace("上一页", "").strip() or "Previous"
            href = urljoin(base_url, prev_a["href"]) if base_url else prev_a["href"]
            parts.append(f"**Previous:** [{txt}]({href})")

        if next_a and next_a.get("href"):
            txt = next_a.get_text().replace("Next", "").replace("下一页", "").strip() or "Next"
            href = urljoin(base_url, next_a["href"]) if base_url else next_a["href"]
            parts.append(f"**Next:** [{txt}]({href})")

        if parts:
            return "\n\n---\n\n" + " | ".join(parts) + "\n"
        return ""

    @classmethod
    def transform(
        cls,
        raw_html: str,
        formats: List[OutputFormat],
        only_main_content: bool = True,
        drawers_text: Optional[str] = None,
        base_url: Optional[str] = None,
        include_sidebar: bool = True,
        sidebar_html: Optional[str] = None,
        code_samples: Optional[List[Dict[str, str]]] = None,
        pagination_html: Optional[str] = None
    ) -> Dict[str, Any]:
        result = {}

        if OutputFormat.RAW_HTML in formats:
            result["rawHtml"] = raw_html

        soup = BeautifulSoup(raw_html, "html.parser")
        meta = cls.extract_metadata(soup)
        result["metadata"] = meta

        if OutputFormat.LINKS in formats:
            result["links"] = cls.extract_links(soup, base_url=base_url)

        # 在清洗侧边栏/导航标签前，高保真提取文档站点的目录树与接口超链接
        sidebar_md = ""
        if include_sidebar:
            if sidebar_html:
                sb_soup = BeautifulSoup(sidebar_html, "html.parser")
                sidebar_md = cls.extract_sidebar_navigation(sb_soup, base_url=base_url)
            else:
                sidebar_md = cls.extract_sidebar_navigation(soup, base_url=base_url)

        # 提取底部分页导航 (Previous / Next)
        pagination_md = ""
        if pagination_html:
            p_soup = BeautifulSoup(pagination_html, "html.parser")
            pagination_md = cls.extract_pagination(p_soup, base_url=base_url)
        else:
            pagination_md = cls.extract_pagination(soup, base_url=base_url)

        # 过滤噪音标签
        for tag in soup(["script", "style", "head", "noscript", "svg", "iframe"]):
            tag.decompose()

        if only_main_content:
            for tag in soup(["footer", "nav", "aside"]):
                tag.decompose()

        # 过滤骨架屏与纯 Loading 占位节点 (如 React Suspense Fallback / Spinner / Skeleton)
        for el in list(soup.find_all(True)):
            if getattr(el, "attrs", None) is None:
                continue
            cls_list = el.attrs.get("class", [])
            cls_name = " ".join(cls_list) if isinstance(cls_list, list) else str(cls_list or "")
            if any(k in cls_name.lower() for k in ["loadingring", "loadingspinner", "skeleton-wrapper", "loading-skeleton"]):
                if not el.find(["p", "pre", "code", "table", "h1", "h2", "h3", "h4", "h5", "h6"]):
                    el.decompose()
                    continue
            txt = el.get_text().strip()
            if txt in ["Loading...", "Loading", "加载中...", "正在加载..."]:
                if not el.find(["p", "pre", "code", "table", "h1", "h2", "h3", "h4", "h5", "h6"]):
                    el.decompose()

        # 处理 Monaco Editor 等代码框
        for monaco in soup.find_all(class_=lambda c: c and any(k in str(c) for k in ["monaco-editor", "code-block", "highlight"])):
            lines = []
            for line in monaco.find_all(class_=lambda c: c and "view-line" in str(c)):
                line_str = line.get_text().replace("\xa0", " ").strip()
                if line_str and line_str not in lines:
                    lines.append(line_str)
            if lines:
                code_text = "\n".join(lines)
                pre = soup.new_tag("pre")
                code = soup.new_tag("code")
                code.string = code_text
                pre.append(code)
                monaco.replace_with(pre)
                continue

            raw_code = monaco.get_text().replace("\xa0", " ").strip()
            if raw_code and len(raw_code) > 10:
                pre = soup.new_tag("pre")
                code = soup.new_tag("code")
                code.string = raw_code
                pre.append(code)
                monaco.replace_with(pre)

        if OutputFormat.HTML in formats:
            result["html"] = str(soup)

        if OutputFormat.TEXT in formats:
            result["text"] = re.sub(r"\s+", " ", soup.get_text()).strip()

        if OutputFormat.MARKDOWN in formats:
            # 执行 Markdown 结构化转换
            work_soup = BeautifulSoup(str(soup), "html.parser")

            # 1. 代码块
            for pre in work_soup.find_all("pre"):
                code_text = pre.get_text().replace("\xa0", " ").strip()
                lines = [ln.strip() for ln in code_text.splitlines() if ln.strip()]
                if len(lines) > 2 and lines[0].replace(" ", "") == lines[1].replace(" ", ""):
                    lines = lines[1:]
                clean_code = "\n".join(lines)
                pre.replace_with(f"\n\n```\n{clean_code}\n```\n\n")

            # 2. 格式化 OpenAPI / Swagger 参数列表 (结构化解析，避免字段类型与描述挤在单行)
            for item in work_soup.find_all(class_=lambda c: c and any(k in str(c) for k in ["openapi-schema__list-item", "schema-property"])):
                prop_el = item.find(class_=lambda c: c and "openapi-schema__property" in str(c))
                prop = prop_el.get_text().strip() if prop_el else ""
                type_el = item.find(class_=lambda c: c and "openapi-schema__name" in str(c))
                type_name = type_el.get_text().strip() if type_el else ""
                req_el = item.find(class_=lambda c: c and any(k in str(c).lower() for k in ["required", "nullable"]))
                badge = f" `[{req_el.get_text().strip()}]`" if req_el else ""

                p_texts = [p.get_text().strip() for p in item.find_all("p") if p.get_text().strip()]
                desc_str = "\n  - ".join(p_texts)
                desc_part = f"\n  - {desc_str}" if desc_str else ""
                md_item = f"\n\n- `{prop}` *({type_name})*{badge}{desc_part}\n\n"
                item.replace_with(work_soup.new_string(md_item))

            # 3. 标题
            for i in range(6, 0, -1):
                for h in work_soup.find_all(f"h{i}"):
                    h_text = h.get_text().strip()
                    if h_text:
                        h.replace_with(f"\n\n{'#' * i} {h_text}\n\n")

            # 3. 表格
            for table in work_soup.find_all("table"):
                rows = []
                for tr in table.find_all("tr"):
                    cells = [c.get_text().strip().replace("\n", " ") for c in tr.find_all(["th", "td"])]
                    if cells:
                        rows.append("| " + " | ".join(cells) + " |")
                if rows:
                    col_count = len(rows[0].split("|")) - 2
                    sep = "| " + " | ".join(["---"] * col_count) + " |"
                    table_md = "\n\n" + rows[0] + "\n" + sep + "\n" + "\n".join(rows[1:]) + "\n\n"
                    table.replace_with(table_md)

            # 4. 列表与链接
            for li in work_soup.find_all("li"):
                li_text = li.get_text().strip()
                if li_text:
                    li.replace_with(f"\n- {li_text}")

            for a in work_soup.find_all("a"):
                href = a.get("href", "").strip()
                text = a.get_text().strip()
                if href and text:
                    # 将相对链接自动转换为完整的绝对 HTTP/HTTPS 链接
                    full_href = urljoin(base_url, href) if base_url else href
                    a.replace_with(f"[{text}]({full_href})")

            md_text = work_soup.get_text()
            md_text = re.sub(r"[ \t]+", " ", md_text)
            md_text = re.sub(r"\n\s*\n\s*\n+", "\n\n", md_text)
            # 清除可能残留于文档末尾的孤立 Loading 占位符
            md_text = re.sub(r"(?:\n\s*)+\b(?:Loading\.\.\.|加载中\.\.\.)\s*$", "", md_text, flags=re.I)
            
            # 多语言代码示例挂载
            if code_samples:
                code_lines = ["\n\n---\n\n## 💻 代码示例与多语言 SDK (Code Samples)\n"]
                for s in code_samples:
                    lang = s.get("language", "cURL").strip()
                    code = s.get("code", "").strip()
                    fence = "bash" if lang.upper() in ["CURL", "SHELL", "BASH"] else lang.lower()
                    code_lines.append(f"\n### {lang}\n\n```{fence}\n{code}\n```\n")
                md_text += "\n".join(code_lines)

            # 底部分页导航挂载
            if pagination_md:
                md_text += f"\n\n{pagination_md}"

            # 如果提取到了抽屉/弹窗中的详细规则与细则，高保真挂载在附录章节中
            if drawers_text and drawers_text.strip():
                clean_drawers = re.sub(r"[ \t]+", " ", drawers_text.strip())
                clean_drawers = re.sub(r"\n\s*\n\s*\n+", "\n\n", clean_drawers)
                md_text += f"\n\n---\n\n## 📋 附录：详细活动规则与细则（弹窗/抽屉完整提取）\n\n{clean_drawers}"

            # 挂载文档目录与接口超链接导航
            if sidebar_md:
                md_text += f"\n\n{sidebar_md}"

            result["markdown"] = md_text.strip()

        return result
