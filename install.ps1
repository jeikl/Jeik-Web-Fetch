# Jeik-Web-Fetch 一键 Windows 安装脚本 (PowerShell)
$ErrorActionPreference = "Stop"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "   🚀 Jeik-Web-Fetch Windows 一键配置脚本" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# 1. 检查 Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[-] 未检测到 Python，正在尝试通过 winget 安装 Python 3.12..." -ForegroundColor Yellow
    winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

# 2. 检查浏览器 (Edge 是 Windows 自带的)
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if ((Test-Path $edgePath) -or (Test-Path $chromePath)) {
    Write-Host "[+] 成功检测到系统原生 Edge / Chrome 浏览器。" -ForegroundColor Green
} else {
    Write-Host "[!] 建议安装 Google Chrome 或 Microsoft Edge 浏览器以支持 SPA 页面渲染。" -ForegroundColor Yellow
}

# 3. 安装依赖与注册 jeik 命令
Write-Host "[*] 正在安装 Jeik-Web-Fetch 运行时依赖..." -ForegroundColor Cyan
$PSScriptRoot = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
python -m pip install -e $PSScriptRoot

Write-Host "`n==============================================" -ForegroundColor Green
Write-Host "   🎉 安装成功！现在你可以直接在任何终端运行:" -ForegroundColor Green
Write-Host "   jeik fetch <目标网页URL>" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
