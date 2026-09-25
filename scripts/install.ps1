# Jeik Windows 官方纯二进制一键安装脚本 (PowerShell)
$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "    🚀 Jeik (Jeik-Web-Fetch) Windows 纯二进制在线安装器" -ForegroundColor Cyan
Write-Host "    (完全不需要安装 Python，开箱即用)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$Repo = if ($env:JEIK_REPO) { $env:JEIK_REPO } else { "JeikCode/Jeik-Web-Fetch" }
$DownloadUrl = "https://github.com/$Repo/releases/latest/download/jeik-web-fetch-windows-x64.exe"

# 安装目标目录 (用户目录下的 .jeik\bin)
$TargetDir = Join-Path $env:USERPROFILE ".jeik\bin"
if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
}
$TargetExe = Join-Path $TargetDir "jeik.exe"

Write-Host "[*] 正在从 GitHub 官方发布下载独立二进制..." -ForegroundColor Yellow
Write-Host "    URL: $DownloadUrl"
Invoke-WebRequest -Uri $DownloadUrl -OutFile $TargetExe -UseBasicParsing

# 将 .jeik\bin 添加到用户环境变量 PATH (如果尚未添加)
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$TargetDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$TargetDir;$UserPath", "User")
    $env:Path = "$TargetDir;$env:Path"
    Write-Host "[+] 成功将 $TargetDir 添加到系统 PATH。" -ForegroundColor Green
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "    🎉 安装大功告成！直接在任何新开终端运行:" -ForegroundColor Green
Write-Host "    👉 jeik fetch <目标网页URL>" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
