import os
import shutil

def find_system_browser() -> str:
    """
    跨平台寻找系统内已安装的 Chrome / Edge / Chromium / Brave / Firefox 可执行文件路径。
    """
    # 环境变量显式指定优先
    env_override = os.environ.get("JEIK_BROWSER_PATH")
    if env_override and os.path.exists(env_override):
        return env_override

    # 常见标准系统路径探测
    candidates = [
        # Windows
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        # Linux
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/microsoft-edge-stable",
        "/usr/bin/brave-browser",
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    # PATH 环境变量解析
    for name in ["google-chrome", "google-chrome-stable", "chrome", "msedge", "edge", "chromium", "chromium-browser", "brave", "brave-browser"]:
        found = shutil.which(name)
        if found:
            return found

    return ""
