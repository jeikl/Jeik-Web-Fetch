from setuptools import setup, find_packages

setup(
    name="jeik-web-fetch",
    version="1.1.1",
    description="高性能通用网页抓取与反反爬 Markdown 提取引擎",
    author="JeikCode Team",
    packages=find_packages(),
    install_requires=[
        "beautifulsoup4>=4.11.0",
        "fastapi>=0.100.0",
        "uvicorn>=0.20.0",
        "httpx>=0.24.0",
        "websockets>=11.0",
    ],
    entry_points={
        "console_scripts": [
            "jeik=jeik_web_fetch.cli:main",
            "jeik-web-fetch=jeik_web_fetch.cli:main",
        ],
    },
    scripts=[
        "bin/jeik",
        "bin/jeik-web-fetch",
    ],
    python_requires=">=3.8",
)
