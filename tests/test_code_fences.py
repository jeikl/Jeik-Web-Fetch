"""代码块保真回归：Prism/Shiki 逐行 span、缩进、空行、语言标注。

历史问题：
- 逐行高亮的 `<pre>` 里行与行之间没有换行文本节点，`get_text()` 会把整段代码拼成一行
  （DeepSeek 文档的 curl/Python 示例就是这样被压扁的）；
- 旧实现逐行 `.strip()`，把缩进也一并吃掉；
- 无 `language-*` 标注时 fence 没有语言信息（ai-x / opencode / 阿里云等站点常见）。
"""

from jeik_web_fetch.core.models import OutputFormat
from jeik_web_fetch.transformers.content import (
    ContentTransformer,
    _normalize_sample_code,
    infer_code_language,
)


def _markdown(html: str) -> str:
    result = ContentTransformer.transform(
        html,
        formats=[OutputFormat.MARKDOWN],
        only_main_content=False,
    )
    return result["markdown"]


def test_prism_line_spans_keep_newlines():
    html = (
        "<html><body><main><pre class='prism-code language-json'>"
        "<div class='codeBlockLines'>"
        "<span class='token-line'>{&quot;a&quot;: 1,</span>"
        "<span class='token-line'> &quot;b&quot;: 2}</span>"
        "</div></pre></main></body></html>"
    )

    markdown = _markdown(html)

    assert '```json\n{"a": 1,\n "b": 2}\n```' in markdown


def test_indentation_and_blank_lines_are_preserved():
    html = (
        "<html><body><main><pre><code>"
        "def f():\n    if True:\n\n        return 1\n"
        "</code></pre></main></body></html>"
    )

    markdown = _markdown(html)
    body = markdown.split("```")[1]

    assert "    if True:" in body, "缩进被吃掉了"
    assert "\n\n        return 1" in body, "空行被吃掉了"


def test_language_class_wins_over_inference():
    html = (
        "<html><body><main><pre><code class='language-python'>"
        "curl is only mentioned in a comment\n"
        "</code></pre></main></body></html>"
    )

    assert "```python" in _markdown(html)


def test_language_inference_is_conservative():
    assert infer_code_language('curl https://x -H "a: b"') == "bash"
    assert infer_code_language('{"ok": true}') == "json"
    assert infer_code_language("from openai import OpenAI\nclient = OpenAI()") == "python"
    assert infer_code_language("import os") == "python"
    assert infer_code_language("<html><body></body></html>") == "html"
    assert infer_code_language("The quick brown fox") == ""


def test_empty_pre_is_dropped():
    markdown = _markdown("<html><body><main><pre>   </pre><p>hello</p></main></body></html>")
    assert "```" not in markdown
    assert "hello" in markdown


def test_container_line_class_does_not_flatten_the_block():
    """`code-block-lines` 是容器，不是行：DeepSeek OpenAPI 示例曾被它拍成一行。"""
    html = """
    <html><body><main>
    <pre class="prism-code language-bash openapi-explorer__code-block">
      <code class="openapi-explorer__code-block-lines openapi-explorer__code-block-lines-numbering">
        <span class="token-line openapi-explorer__code-block-code-line">
          <span class="openapi-explorer__code-block-code-line-number"></span>
          <span class="openapi-explorer__code-block-code-line-content"><span class="token plain">curl https://x \\</span></span><br>
        </span>
        <span class="token-line openapi-explorer__code-block-code-line">
          <span class="openapi-explorer__code-block-code-line-number"></span>
          <span class="openapi-explorer__code-block-code-line-content"><span class="token plain">  --header 'a: b'</span></span><br>
        </span>
      </code>
    </pre>
    </main></body></html>
    """

    markdown = _markdown(html)

    assert "curl https://x \\\n  --header 'a: b'" in markdown


def test_sample_code_extra_blank_lines_are_collapsed():
    doubled = "# comment\n\n\tcurl https://x \\\n\n  --header 'a: b'\n\n}"
    normalized = _normalize_sample_code(doubled)
    assert "\n\n" not in normalized
    assert "\tcurl https://x" in normalized


def test_sample_code_keeps_real_blank_lines():
    code = "def f():\n    a = 1\n\n    return a"
    assert "\n\n" in _normalize_sample_code(code)
