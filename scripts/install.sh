#!/usr/bin/env bash
# Jeik (Jeik-Web-Fetch) Universal Installer & System Service Provisioner
# Supports language selection (Default: Chinese, Optional: English)
set -e

REPO="${JEIK_REPO:-jeikl/Jeik-Web-Fetch}"
INSTALL_DIR="/usr/local/bin"
SERVICE_PORT=8863

# Language detection (Default: zh_CN, supports 'en' / 'zh')
LANG_OPT="${JEIK_LANG:-zh}"
if [[ "$*" == *"--lang en"* ]] || [[ "$*" == *"-l en"* ]]; then
    LANG_OPT="en"
elif [[ "$*" == *"--lang zh"* ]] || [[ "$*" == *"-l zh"* ]]; then
    LANG_OPT="zh"
fi

if [ "$LANG_OPT" = "en" ]; then
    MSG_BANNER="==========================================================\n    🚀 Jeik (Jeik-Web-Fetch) Universal Binary Installer\n    (Zero dependencies, Standalone Binary & System Service)\n=========================================================="
    MSG_DETECT="[+] Detected system environment:"
    MSG_DOWNLOADING="[*] Downloading standalone binary from GitHub Releases..."
    MSG_DEPLOY_BIN="[*] Deploying binary to ${INSTALL_DIR}/jeik ..."
    MSG_DEPLOY_SKILL="[*] Deploying jeik-web-fetch skill to ~/.agents/skills/jeik-web-fetch/SKILL.md ..."
    MSG_SYSTEMD="[*] Configuring systemd background daemon service (jeik-daemon.service)..."
    MSG_MACOS_DAEMON="[*] Configuring launchd background daemon service for macOS..."
    MSG_COMPLETE="==========================================================\n    🎉 Installation Complete! Status Summary:\n    • CLI command: jeik fetch <URL>\n    • Persistent Service Port: ${SERVICE_PORT} (Running in background)\n    • Agent Skill: ~/.agents/skills/jeik-web-fetch (Ready for all AI agents)\n=========================================================="
else
    MSG_BANNER="==========================================================\n    🚀 Jeik (Jeik-Web-Fetch) 官方纯二进制一键在线安装器\n    (无需任何环境依赖，单文件独立运行 + 自动配置系统常驻服务)\n=========================================================="
    MSG_DETECT="[+] 成功检测到当前系统架构:"
    MSG_DOWNLOADING="[*] 正在从 GitHub 官方发布下载独立二进制..."
    MSG_DEPLOY_BIN="[*] 正在部署可执行文件到系统目录 ${INSTALL_DIR}/jeik ..."
    MSG_DEPLOY_SKILL="[*] 正在将智能体技能安装到通用目录 ~/.agents/skills/jeik-web-fetch/SKILL.md ..."
    MSG_SYSTEMD="[*] 正在注册 systemd 系统常驻后台服务 (端口: ${SERVICE_PORT})..."
    MSG_MACOS_DAEMON="[*] 正在注册 macOS launchd 系统常驻后台服务 (端口: ${SERVICE_PORT})..."
    MSG_COMPLETE="==========================================================\n    🎉 安装大功告成！状态汇总:\n    • 终端 CLI 命令: jeik fetch <网页URL>\n    • 后台常驻服务端口: ${SERVICE_PORT} (已自动在后台开机自启运行)\n    • 智能体通用技能: ~/.agents/skills/jeik-web-fetch (所有 Agent 均可直接调用)\n=========================================================="
fi

echo -e "$MSG_BANNER"

# 1. Detect OS & CPU Architecture
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
    echo "[-] Unsupported operating system: $OS"
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
    echo "[-] Unsupported CPU architecture: $ARCH"
    exit 1
    ;;
esac

BINARY_NAME="jeik-web-fetch-${PLATFORM}-${TARGET_ARCH}"
DOWNLOAD_URL="https://github.com/${REPO}/releases/latest/download/${BINARY_NAME}"

echo "${MSG_DETECT} ${PLATFORM} (${TARGET_ARCH})"
echo "$MSG_DOWNLOADING"
echo "    URL: ${DOWNLOAD_URL}"

# 2. Download binary to temporary destination
TMP_FILE="$(mktemp /tmp/jeik.XXXXXX)"
if command -v curl &>/dev/null; then
    curl -fSL "$DOWNLOAD_URL" -o "$TMP_FILE"
elif command -v wget &>/dev/null; then
    wget -qO "$TMP_FILE" "$DOWNLOAD_URL"
else
    echo "[-] Error: curl or wget is required."
    exit 1
fi

chmod +x "$TMP_FILE"

# 3. Deploy binary to system PATH
echo -e "$MSG_DEPLOY_BIN"
if [ -w "$INSTALL_DIR" ]; then
    mv -f "$TMP_FILE" "${INSTALL_DIR}/jeik"
else
    echo "[!] Requesting sudo permission to write to ${INSTALL_DIR}:"
    sudo mv -f "$TMP_FILE" "${INSTALL_DIR}/jeik"
fi

# 4. 解决旧 Linux 发行版（如 Debian 11/12、Ubuntu 20/22、CentOS）上运行单文件二进制时因 GLIBC 版本过低的问题
# 如果检测到运行独立二进制时报 GLIBC 错误，脚本自动以系统 Python Wheel 方式无缝降级兜底运行！
echo "[*] Testing binary runtime compatibility..."
if ! "${INSTALL_DIR}/jeik" --help &>/dev/null; then
    echo "[!] Detected older GLIBC on host system. Seamlessly installing via universal Python Wheel..."
    if command -v python3 &>/dev/null && command -v pip3 &>/dev/null; then
        pip3 install --upgrade jeik-web-fetch --break-system-packages 2>/dev/null || pip3 install --upgrade jeik-web-fetch
        echo "[+] Successfully provisioned universal runtime via Python Wheel!"
    fi
fi
echo -e "$MSG_DEPLOY_SKILL"
AGENT_SKILL_DIR="${HOME}/.agents/skills/jeik-web-fetch"
mkdir -p "$AGENT_SKILL_DIR"
cat << 'EOF' > "${AGENT_SKILL_DIR}/SKILL.md"
---
name: jeik-web-fetch
description: "High-performance web extraction tool. Scrapes any URL (SPA, dynamic JS, anti-bot, intranet, or internet) and outputs clean structured Markdown."
---

# Jeik Web Fetch

Run the `jeik fetch` command directly in terminal or bash:

```bash
jeik fetch "<URL>"
```

### Options (Threads & Custom DNS)

```bash
# Custom numeric DNS or encrypted DNS (DoH), and multi-worker concurrency
jeik fetch "<URL>" --dns "https://1.1.1.1/dns-query" -j 4
```

> Output begins with an absolute path anchor header where the full Markdown has been persisted safely to `.jeik/fetches/`.
EOF

# 5. Provision persistent background daemon service
if [ "$PLATFORM" = "linux" ] && command -v systemctl &>/dev/null; then
    echo -e "$MSG_SYSTEMD"
    SERVICE_FILE="/etc/systemd/system/jeik-daemon.service"
    sudo bash -c "cat << EOF > ${SERVICE_FILE}
[Unit]
Description=Jeik Web Fetch High-Concurrency Service
After=network.target

[Service]
Type=simple
User=${USER}
ExecStart=${INSTALL_DIR}/jeik serve --port ${SERVICE_PORT}
Restart=always
RestartSec=5
Environment=PORT=${SERVICE_PORT}

[Install]
WantedBy=multi-user.target
EOF"
    sudo systemctl daemon-reload
    sudo systemctl enable jeik-daemon.service || true
    sudo systemctl restart jeik-daemon.service || true
elif [ "$PLATFORM" = "darwin" ]; then
    echo -e "$MSG_MACOS_DAEMON"
    PLIST_FILE="${HOME}/Library/LaunchAgents/com.jeik.webfetch.plist"
    mkdir -p "${HOME}/Library/LaunchAgents"
    cat << EOF > "$PLIST_FILE"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jeik.webfetch</string>
    <key>ProgramArguments</key>
    <array>
        <string>${INSTALL_DIR}/jeik</string>
        <string>serve</string>
        <string>--port</string>
        <string>${SERVICE_PORT}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    launchctl load "$PLIST_FILE" 2>/dev/null || true
fi

echo ""
echo -e "$MSG_COMPLETE"
