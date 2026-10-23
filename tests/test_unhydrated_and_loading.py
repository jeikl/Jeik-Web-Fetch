import pytest
from jeik_web_fetch.core.classifier import ContentQualityClassifier
from jeik_web_fetch.transformers.content import ContentTransformer
from jeik_web_fetch.converter import html_to_markdown
from jeik_web_fetch.core.models import OutputFormat

def test_unhydrated_component_classifier():
    # 模拟 Partial SSR 架构：正文虽然很长，但包含了未渲染的 React Suspense / OpenAPI 面板
    mock_html = """
    <html>
    <body>
    <main>
        <h1>API Documentation Overview</h1>
        <p>This is a comprehensive documentation page describing endpoints, headers, and authentication.</p>
        <p>It contains numerous paragraphs and structured content that easily exceeds eight hundred characters in total plain text length.</p>
        <p>Here are more details about authorization tokens, rate limits, error codes, and pagination schemes.</p>
        <p>And additional sentences to make sure it surpasses the threshold for static validation easily without ambiguity.</p>
        <div class="col col--5 openapi-right-panel__container">
            <div>Loading...</div>
        </div>
    </main>
    </body>
    </html>
    """
    is_valid, reason = ContentQualityClassifier.evaluate_html(mock_html, 200)
    assert not is_valid
    assert "unhydrated" in reason.lower()

def test_pure_loading_node_cleaning():
    # 测试静态或残余 HTML 中孤立的 Loading 节点与骨架屏类名是否被彻底清洗
    html = """
    <html>
    <body>
    <article>
        <h1>Article Title</h1>
        <p>Real paragraph content.</p>
        <div class="loadingRing_e0eg"><div></div><div></div></div>
        <div class="panel-loading"><div>Loading...</div></div>
        <p>Loading...</p>
    </article>
    </body>
    </html>
    """
    res = ContentTransformer.transform(html, [OutputFormat.MARKDOWN])
    md = res["markdown"]
    assert "Real paragraph content." in md
    assert "Loading..." not in md
    assert "loadingRing" not in md

    # 测试 converter.html_to_markdown
    conv_md = html_to_markdown(html)
    assert "Real paragraph content." in conv_md
    assert "Loading..." not in conv_md
