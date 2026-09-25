#!/usr/bin/env bash
# Jeik 官方纯二进制一键在线安装器 (Linux & macOS, 支持 x86_64 与 ARM64)
set -e

echo "=========================================================="
echo "    🚀 Jeik (Jeik-Web-Fetch) 纯二进制独立运行一键安装器"
echo "    (无需安装 Python、Node.js 或 Docker，开箱即用)"
echo "=========================================================="

REPO="${JEIK_REPO:-JeikCode/Jeik-Web-Fetch}"
INSTALL_DIR="/usr/local/bin"

# 1. 自动检测 OS 与 硬件架构
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$OS" in
  linux*)
    PLATFORM="linux"
    ;;
  darwin*)
    PLATFORM="darwin"
    ;;
  *)
    echo "[-] 暂不支持的操作系统: $OS"
    exit 1
    ;;
esac

case "$ARCH" in
  x86_64|amd64)
    TARGET_ARCH="x64"
    ;;
  aarch64|arm64)
    TARGET_ARCH="arm64"
    ;;
  *)
    echo "[-] 暂不支持的架构: $ARCH"
    exit 1
    ;;
esac

BINARY_NAME="jeik-web-fetch-${PLATFORM}-${TARGET_ARCH}"
DOWNLOAD_URL="https://github.com/${REPO}/releases/latest/download/${BINARY_NAME}"

echo "[+] 检测到当前系统环境: ${PLATFORM} (${TARGET_ARCH})"
echo "[*] 正在从 GitHub 官方发布源下载纯独立二进制..."
echo "    URL: ${DOWNLOAD_URL}"

# 2. 安全下载到临时目录
TMP_FILE="$(mktemp /tmp/jeik.XXXXXX)"
if command -v curl &>/dev/null; then
    curl -fSL "$DOWNLOAD_URL" -o "$TMP_FILE"
elif command -v wget &>/dev/null; then
    wget -qO "$TMP_FILE" "$DOWNLOAD_URL"
else
    echo "[-] 错误: 请先安装 curl 或 wget。"
    exit 1
fi

chmod +x "$TMP_FILE"

# 3. 部署到系统 PATH 目录
echo "[*] 正在将二进制部署到 ${INSTALL_DIR}/jeik ..."
if [ -w "$INSTALL_DIR" ]; then
    mv "$TMP_FILE" "${INSTALL_DIR}/jeik"
else
    echo "[!] 需要 sudo 权限移动到系统目录:"
    sudo mv "$TMP_FILE" "${INSTALL_DIR}/jeik"
fi

# 4. 环境健康检查：提示或自动补齐 Chromium
HAS_BROWSER=false
for b in google-chrome google-chrome-stable chromium chromium-browser msedge brave-browser; do
    if command -v "$b" &>/dev/null; then
        HAS_BROWSER=true
        break
    fi
done

if [ "$PLATFORM" = "darwin" ]; then
    if [ -d "/Applications/Google Chrome.app" ] || [ -d "/Applications/Microsoft Edge.app" ]; then
        HAS_BROWSER=true
    fi
fi

if [ "$HAS_BROWSER" = false ]; then
    echo ""
    echo "[!] 提示: 检测到当前系统尚未安装任何 Chrome/Chromium 浏览器。"
    echo "    若需要抓取复杂的单页应用 (SPA / 钉钉文档 / 反爬站点)，请运行以下命令一键补齐:"
    if command -v apt-get &>/dev/null; then
        echo "    👉 sudo apt-get update && sudo apt-get install -y chromium-browser"
    elif command -v dnf &>/dev/null; then
        echo "    👉 sudo dnf install -y chromium"
    elif command -v brew &>/dev/null; then
        echo "    👉 brew install --cask google-chrome"
    fi
fi

echo ""
echo "=========================================================="
echo "    🎉 安装大功告成！无需任何 Python 运行环境！"
echo "    现在你可以在终端直接使用:"
echo "    👉 jeik fetch \"https://open.dingtalk.com/...\""
echo "=========================================================="
