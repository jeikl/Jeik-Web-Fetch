#!/usr/bin/env bash
# Jeik-Web-Fetch 一键跨平台安装脚本 (Linux / macOS)
set -e

echo "=============================================="
echo "   🚀 Jeik-Web-Fetch 一键跨平台环境配置脚本"
echo "=============================================="

# 1. 检查 Python 3 环境
if ! command -v python3 &>/dev/null; then
    echo "[-] 未检测到 Python 3，正在尝试自动安装..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update && sudo apt-get install -y python3 python3-pip
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3 python3-pip
    elif command -v brew &>/dev/null; then
        brew install python
    else
        echo "[-] 请先安装 Python 3.8+ 后再运行本脚本。"
        exit 1
    fi
fi

# 2. 检查系统浏览器 (Chrome / Chromium / Edge)
HAS_BROWSER=false
for b in google-chrome google-chrome-stable chromium chromium-browser msedge brave-browser; do
    if command -v "$b" &>/dev/null; then
        HAS_BROWSER=true
        echo "[+] 检测到已安装的浏览器: $b"
        break
    fi
done

# 如果是 macOS，检查 /Applications 路径
if [[ "$OSTYPE" == "darwin"* ]]; then
    if [ -d "/Applications/Google Chrome.app" ] || [ -d "/Applications/Microsoft Edge.app" ]; then
        HAS_BROWSER=true
        echo "[+] 检测到 macOS 应用程序目录中的 Chrome / Edge。"
    fi
fi

# 如果未安装浏览器，提示并尝试自动安装轻量 chromium
if [ "$HAS_BROWSER" = false ]; then
    echo "[!] 系统中未检测到 Chrome/Chromium 浏览器，正在自动安装..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update && sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y chromium
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm chromium
    elif command -v brew &>/dev/null; then
        brew install --cask google-chrome
    else
        echo "[!] 请手动安装 Chrome 或 Chromium 浏览器 (如: sudo apt install chromium)"
    fi
fi

# 3. 安装 Python 核心依赖与 jeik CLI
echo "[*] 正在安装 Jeik-Web-Fetch 运行时依赖..."
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pip3 install -e "$DIR" --break-system-packages 2>/dev/null || pip3 install -e "$DIR"

# 4. 创建系统软链接 (保证在任何终端都能直接输入 jeik)
TARGET_BIN="/usr/local/bin/jeik"
if [ -w "/usr/local/bin" ]; then
    ln -sf "$DIR/bin/jeik" "$TARGET_BIN"
else
    sudo ln -sf "$DIR/bin/jeik" "$TARGET_BIN" || true
fi

echo ""
echo "=============================================="
echo "   🎉 安装完成！现在你可以直接运行:"
echo "   jeik fetch <目标网页URL>"
echo "=============================================="
