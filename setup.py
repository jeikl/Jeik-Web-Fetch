from setuptools import setup, find_packages

setup(
    name="jeik-web-fetch",
    version="1.0.0",
    description="高性能通用网页抓取与反反爬 Markdown 提取引擎（Firecrawl 架构原生复现）",
    author="JeikCode Team",
    packages=find_packages(),
    install_requires=[
        "beautifulsoup4>=4.11.0",
    ],
    scripts=[
        "bin/jeik-web-fetch",
    ],
    python_requires=">=3.8",
)
