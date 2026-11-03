# Jeik Windows 官方纯二进制一键安装与常驻服务配置脚本 (PowerShell)
# 支持语言选项: 默认中文 (-Language zh)，可选英文 (-Language en)
param(
    [string]$Language = "en",
    [string]$Repo = "jeikl/Jeik-Web-Fetch"
)

$ErrorActionPreference = "Stop"
$ServicePort = 8863

if ($env:JEIK_LANG) {
    $Language = $env:JEIK_LANG
}

$IsEn = ($Language -eq "en")

if ($IsEn) {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "    🚀 Jeik (Jeik-Web-Fetch) Windows Universal Installer" -ForegroundColor Cyan
    Write-Host "    (Zero dependencies, Standalone Binary & Auto Service)" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan
    $MsgDownload = "[*] Downloading standalone binary from GitHub Releases..."
    $MsgPath = "[+] Added {0} to User PATH."
    $MsgSkill = "[+] Automatically deployed skill to universal directory: {0}"
    $MsgDaemonReg = "[+] Registered Windows startup background daemon (Port: {0})."
    $MsgDaemonStart = "[+] Started background daemon service immediately."
    $MsgComplete = "`n==========================================================`n    🎉 Installation Complete! Status Summary:`n    • CLI command: jeik fetch <URL>`n    • Persistent Service Port: {0} (Running in background)`n    • Universal Agent Skill: ~/.agents/skills/jeik-web-fetch`n=========================================================="
} else {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "    🚀 Jeik (Jeik-Web-Fetch) Windows 官方纯二进制在线安装器" -ForegroundColor Cyan
    Write-Host "    (无需安装 Python，单文件独立运行 + 自动配置系统常驻服务)" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan
    $MsgDownload = "[*] 正在从 GitHub 官方发布下载独立二进制..."
    $MsgPath = "[+] 成功将 {0} 添加到系统用户 PATH。"
    $MsgSkill = "[+] 已自动将技能安装到所有智能体通用目录: {0}"
    $MsgDaemonReg = "[+] 已成功配置 Windows 开机自动常驻后台服务 (端口: {0})。"
    $MsgDaemonStart = "[+] 已立即拉起后台常驻服务。"
    $MsgComplete = "`n==========================================================`n    🎉 安装大功告成！状态汇总:`n    • 终端 CLI 命令: jeik fetch <目标网页URL>`n    • 后台常驻服务端口: {0} (已在后台持续运行)`n    • 智能体通用技能: ~/.agents/skills/jeik-web-fetch (所有 Agent 均可直接调用)`n=========================================================="
}

$DownloadUrl = "https://github.com/$Repo/releases/latest/download/jeik-web-fetch-windows-x64.exe"

# 1. 目标目录 (.jeik\bin)
$TargetDir = Join-Path $env:USERPROFILE ".jeik\bin"
if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
}
$TargetExe = Join-Path $TargetDir "jeik.exe"

Write-Host $MsgDownload -ForegroundColor Yellow
Write-Host "    URL: $DownloadUrl"

# 关键：Windows 会锁住正在运行的 exe，直接 OutFile 到 $TargetExe 必然报
# "The process cannot access the file ... because it is being used by another process"。
# 因此先下载到 .new，再停掉后台 serve，最后用「重命名旧文件 → 移入新文件」完成替换
# （Windows 允许重命名正在运行的 exe，只是不允许覆盖它）。
$StagedExe = "$TargetExe.new"
$BackupExe = "$TargetExe.old"
foreach ($stale in @($StagedExe, $BackupExe)) {
    if (Test-Path $stale) { Remove-Item $stale -Force -ErrorAction SilentlyContinue }
}
Invoke-WebRequest -Uri $DownloadUrl -OutFile $StagedExe -UseBasicParsing

# 只停后台常驻服务，绝不能误杀正在执行本次升级的 CLI 进程
Get-CimInstance Win32_Process -Filter "Name='jeik.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'serve' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 300

try {
    Move-Item -Path $StagedExe -Destination $TargetExe -Force -ErrorAction Stop
} catch {
    # 目标仍被占用（例如还有另一个 jeik 在用）：先把它改名腾位
    if (Test-Path $TargetExe) {
        Rename-Item -Path $TargetExe -NewName (Split-Path $BackupExe -Leaf) -Force -ErrorAction SilentlyContinue
    }
    Move-Item -Path $StagedExe -Destination $TargetExe -Force
}
Remove-Item $BackupExe -Force -ErrorAction SilentlyContinue

# 2. 将 .jeik\bin 添加到用户环境变量 PATH (如果尚未添加)
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$TargetDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$TargetDir;$UserPath", "User")
    $env:Path = "$TargetDir;$env:Path"
    Write-Host ($MsgPath -f $TargetDir) -ForegroundColor Green
}

# 3. 自动安装技能到全局通用 ~/.agents/skills 目录
$UniversalSkillDir = Join-Path $env:USERPROFILE ".agents\skills\jeik-web-fetch"
if (-not (Test-Path $UniversalSkillDir)) {
    New-Item -ItemType Directory -Path $UniversalSkillDir -Force | Out-Null
}
$SkillContent = @"
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
"@
Set-Content -Path (Join-Path $UniversalSkillDir "SKILL.md") -Value $SkillContent -Encoding UTF8
Write-Host ($MsgSkill -f $UniversalSkillDir) -ForegroundColor Green

# 4. 配置 Windows 登录自动常驻服务 (通过注册表 Run 键)
$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$AppArgs = "`"$TargetExe`" serve --host 127.0.0.1 --port $ServicePort"
Set-ItemProperty -Path $RunKey -Name "JeikWebFetchDaemon" -Value $AppArgs
Write-Host ($MsgDaemonReg -f $ServicePort) -ForegroundColor Green

# 5. 确保后台常驻服务在运行（二进制刚被替换时，上面的循环已把它停掉）
$serveRunning = Get-CimInstance Win32_Process -Filter "Name='jeik.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'serve' }
if (-not $serveRunning) {
    Start-Process -FilePath $TargetExe -ArgumentList "serve --host 127.0.0.1 --port $ServicePort" -WindowStyle Hidden
    Write-Host $MsgDaemonStart -ForegroundColor Green
}

Write-Host ($MsgComplete -f $ServicePort) -ForegroundColor Green
