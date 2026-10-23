import re
from bs4 import BeautifulSoup

def html_to_markdown(html_content: str, base_url: str = None, include_sidebar: bool = True) -> str:
    """
    将富文本与动态渲染 DOM 转换为优雅、精准的 Markdown：
    1. 彻底清除脚本、样式、追踪器与导航等干扰标签
    2. 原生还原 Monaco / CodeMirror / Prism 等现代前端代码编辑器内容
    3. 标准化表格对齐线与 Markdown 表格语法
    4. 标题、列表、超链接语义化提纯
    5. 自动结构化提取侧边栏关联文档目录与超链接
    """
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "html.parser")

    # 提取侧边栏导航与文档超链接
    sidebar_md = ""
    pagination_md = ""
    if include_sidebar:
        from .transformers.content import ContentTransformer
        sidebar_md = ContentTransformer.extract_sidebar_navigation(soup, base_url=base_url)
        pagination_md = ContentTransformer.extract_pagination(soup, base_url=base_url)

    # 1. 过滤垃圾与噪音标签
    for tag in soup(["script", "style", "head", "noscript", "svg", "iframe", "footer", "nav", "aside"]):
        tag.decompose()

    # 过滤骨架屏与纯 Loading 占位节点
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

    # 2. 识别并提取复杂代码框 (Monaco Editor / CodeMirror / Ace)
    def is_real_code_editor(tag):
        if not tag or not tag.has_attr("class"):
            return False
        classes = tag.get("class", [])
        classes_list = classes if isinstance(classes, list) else str(classes).split()
        for c in classes_list:
            c_low = c.lower()
            if c_low in ["monaco-editor", "codemirror", "ace_editor"] or "monaco-editor" in c_low:
                return True
        return False

    for monaco in soup.find_all(is_real_code_editor):
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

    # 3. 标准代码块转 Markdown 代码围栏
    for pre in soup.find_all("pre"):
        code_text = pre.get_text().replace("\xa0", " ").strip()
        lines = [ln.strip() for ln in code_text.splitlines() if ln.strip()]
        if len(lines) > 2 and lines[0].replace(" ", "") == lines[1].replace(" ", ""):
            lines = lines[1:]
        clean_code = "\n".join(lines)
        pre.replace_with(f"\n\n```\n{clean_code}\n```\n\n")

    # 4. 标题转换 (# ~ ######)
    for i in range(6, 0, -1):
        for h in soup.find_all(f"h{i}"):
            h_text = h.get_text().strip()
            if h_text:
                h.replace_with(f"\n\n{'#' * i} {h_text}\n\n")

    # 5. 表格高保真排版 (计算列数并补齐对齐线)
    for table in soup.find_all("table"):
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

    # 6. 无序列表
    for li in soup.find_all("li"):
        li_text = li.get_text().strip()
        if li_text:
            li.replace_with(f"\n- {li_text}")

    # 7. 超链接
    for a in soup.find_all("a"):
        href = a.get("href", "").strip()
        text = a.get_text().strip()
        if href and text:
            a.replace_with(f"[{text}]({href})")

    # 8. 规整空行与空白符
    text = soup.get_text()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    text = re.sub(r"(?:\n\s*)+\b(?:Loading\.\.\.|加载中\.\.\.)\s*$", "", text, flags=re.I)
    if pagination_md:
        text += f"\n\n{pagination_md}"
    if sidebar_md:
        text += f"\n\n{sidebar_md}"
    return text.strip()
