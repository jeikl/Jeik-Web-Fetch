# Jeik-Web-Fetch 🚀

高性能、通用网页抓取与反反爬 Markdown 提取引擎。

完全吸收 **Firecrawl 生产级无头渲染架构** 与 **Puppeteer-Stealth 反爬绕过精髓**，以极简、零重量级外部依赖（无需 Playwright/Node/Docker）的原生方式实现。

---

## 🌟 核心特性

- ⚡ **零重型外部依赖**：无需安装庞大的 Playwright、Docker 镜像或 Node.js 环境，直接无缝复用系统级已安装的 Chrome / Edge / Chromium。
- 🛡️ **生产级反爬对抗 (Stealth)**：
  - 自动化标识抹除（`navigator.webdriver` 原型链清洗）
  - 1080P 物理视口与媒体查询伪装（规避知乎等对小窗口的 403 拦截）
  - 硬件环境与 `window.chrome.runtime` 运行结构补齐
- 🧩 **现代 SPA 代码框原生穿透**：
  - 原生支持 **Monaco Editor**（VS Code 网页版同款）
  - 解决前端虚拟滚动（Virtual Scroll）导致的下半部分长代码丢失、截断问题
  - 完美支持 **CodeMirror / Prism / Highlight.js**
- 📊 **高保真 Markdown 提取**：
  - 标题（`#` ~ `######`）层级还原
  - 表格补齐 Markdown 对齐线（`|---|`）
  - 自动清洗 `<script>`、`<style>`、无用弹窗与长轮询埋点

---

## 📦 安装与使用

### 1. 安装依赖
```bash
pip install beautifulsoup4
```

### 2. Python 代码中调用
```python
from jeik_web_fetch import firecrawl_fetch

# 抓取任意复杂的 JS / SPA / 强反爬网页
markdown = firecrawl_fetch("https://open.dingtalk.com/document/development/event-workflow-instance-change-broadcast")

print(markdown)
```

### 3. 命令行 CLI 调用
```bash
python bin/jeik-web-fetch "https://zhuanlan.zhihu.com/p/25964484" -o zhihu.md
```

---

## 🧪 验证过的典型高难度站点

- [x] **钉钉开放平台**：全客户端异步 React 渲染，Monaco Editor 内存代码块全量提取。
- [x] **知乎专栏**：`zse-ck` 强反爬探针穿透，秒级输出万字长文。
- [x] **火山引擎文档中心**：单页 SPA 300+ 完整超链接与多级分类提取。
- [x] **阿里云活动页**：电商高并发页面，75 个活动小节与规格参数完整落盘。
