import re
from typing import List, Dict, Tuple, Any, Optional
from bs4 import BeautifulSoup
from ..core.models import OutputFormat

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
    def extract_links(soup: BeautifulSoup) -> List[Dict[str, str]]:
        links = []
        for a in soup.find_all("a"):
            href = a.get("href", "").strip()
            text = a.get_text().strip()
            if href:
                links.append({"text": text, "href": href})
        return links

    @classmethod
    def transform(
        cls,
        raw_html: str,
        formats: List[OutputFormat],
        only_main_content: bool = True,
        drawers_text: Optional[str] = None
    ) -> Dict[str, Any]:
        result = {}

        if OutputFormat.RAW_HTML in formats:
            result["rawHtml"] = raw_html

        soup = BeautifulSoup(raw_html, "html.parser")
        meta = cls.extract_metadata(soup)
        result["metadata"] = meta

        if OutputFormat.LINKS in formats:
            result["links"] = cls.extract_links(soup)

        # 过滤噪音标签
        for tag in soup(["script", "style", "head", "noscript", "svg", "iframe"]):
            tag.decompose()

        if only_main_content:
            for tag in soup(["footer", "nav", "aside"]):
                tag.decompose()

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

            # 2. 标题
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
                    a.replace_with(f"[{text}]({href})")

            md_text = work_soup.get_text()
            md_text = re.sub(r"[ \t]+", " ", md_text)
            md_text = re.sub(r"\n\s*\n\s*\n+", "\n\n", md_text)
            
            # 如果提取到了抽屉/弹窗中的详细规则与细则，高保真挂载在附录章节中
            if drawers_text and drawers_text.strip():
                clean_drawers = re.sub(r"[ \t]+", " ", drawers_text.strip())
                clean_drawers = re.sub(r"\n\s*\n\s*\n+", "\n\n", clean_drawers)
                md_text += f"\n\n---\n\n## 📋 附录：详细活动规则与细则（弹窗/抽屉完整提取）\n\n{clean_drawers}"

            result["markdown"] = md_text.strip()

        return result
