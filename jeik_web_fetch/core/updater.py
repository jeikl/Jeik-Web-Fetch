import os
import sys
import time
import json
import asyncio
import threading
import subprocess
import urllib.request
from typing import Optional, Tuple
from pathlib import Path

GITHUB_REPO = os.environ.get("JEIK_REPO", "jeikl/Jeik-Web-Fetch")
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

class AutoUpdater:
    """
    Background Autonomous Updater & Hot-Upgrader:
    - Checks GitHub Releases for updates every 10 minutes (600s).
    - Ensures non-destructive upgrades: waits until active tasks == 0 before upgrading.
    - Seamlessly replaces binary or local editable files and restarts.
    """
    def __init__(self, check_interval_sec: int = 600):
        self.check_interval_sec = check_interval_sec
        self.active_tasks: int = 0
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False

    def enter_task(self):
        """Register that a scrape task has started."""
        with self._lock:
            self.active_tasks += 1

    def leave_task(self):
        """Register that a scrape task has ended."""
        with self._lock:
            self.active_tasks = max(0, self.active_tasks - 1)

    def is_idle(self) -> bool:
        """Check whether the engine is currently idle."""
        with self._lock:
            return self.active_tasks == 0

    @classmethod
    def get_current_version(cls) -> str:
        try:
            from . import __version__
            return __version__.lstrip("v")
        except Exception:
            return "1.0.0"

    @classmethod
    def check_remote_version(cls) -> Tuple[Optional[str], Optional[str]]:
        """
        Query GitHub for the latest release version and download URL.
        Returns: (remote_version, download_url)
        """
        try:
            req = urllib.request.Request(
                LATEST_RELEASE_API,
                headers={"User-Agent": "jeik-web-fetch-updater"}
            )
            with urllib.request.urlopen(req, timeout=8) as res:
                if res.status != 200:
                    return None, None
                data = json.loads(res.read().decode("utf-8"))
                tag_name = data.get("tag_name", "").lstrip("v")
                
                # Identify platform binary asset
                assets = data.get("assets", [])
                plat = sys.platform
                import platform
                arch = "arm64" if "arm" in platform.machine().lower() or "aarch" in platform.machine().lower() else "x64"
                
                matched_asset = None
                for a in assets:
                    name = a.get("name", "").lower()
                    if plat.startswith("win") and "windows" in name and ".exe" in name:
                        matched_asset = a.get("browser_download_url")
                        break
                    elif plat.startswith("darwin") and "darwin" in name and arch in name:
                        matched_asset = a.get("browser_download_url")
                        break
                    elif plat.startswith("linux") and "linux" in name and arch in name:
                        matched_asset = a.get("browser_download_url")
                        break

                return tag_name, matched_asset
        except Exception:
            return None, None

    @classmethod
    def is_newer(cls, remote: str, current: str) -> bool:
        def parse(v: str):
            return [int(x) for x in re.sub(r"[^\d.]", "", v).split(".") if x.isdigit()]
        import re
        try:
            return parse(remote) > parse(current)
        except Exception:
            return remote != current

    def perform_upgrade_and_restart(self, direct_cli: bool = False):
        """Wait until idle, execute the upgrade, and restart smoothly."""
        current_ver = self.get_current_version()
        remote_ver, asset_url = self.check_remote_version()

        if not remote_ver:
            if direct_cli:
                print("[-] Could not reach GitHub releases or release not found.", file=sys.stderr)
            return False

        if not self.is_newer(remote_ver, current_ver) and not direct_cli:
            return False

        # Wait until current scraping tasks finish
        if direct_cli:
            print(f"[*] Upgrading jeik-web-fetch: {current_ver} -> {remote_ver}...")
        while not self.is_idle():
            if direct_cli:
                print("[*] Waiting for active scraping tasks to finish before applying upgrade...")
            time.sleep(1.0)

        # Execute online installer script
        try:
            if sys.platform.startswith("win"):
                install_cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "$env:JEIK_LANG='en'; irm https://raw.githubusercontent.com/jeikl/Jeik-Web-Fetch/main/scripts/install.ps1 | iex"]
            else:
                install_cmd = ["/bin/bash", "-c", "export JEIK_LANG='en'; curl -fsSL https://raw.githubusercontent.com/jeikl/Jeik-Web-Fetch/main/scripts/install.sh | bash"]
            
            res = subprocess.run(install_cmd, capture_output=True, text=True)
            if res.returncode == 0:
                if direct_cli:
                    print(f"[✔] Upgrade complete! Successfully upgraded to v{remote_ver}.")
                return True
            else:
                if direct_cli:
                    print(f"[-] Upgrade failed:\n{res.stderr}", file=sys.stderr)
                return False
        except Exception as e:
            if direct_cli:
                print(f"[-] Upgrade error: {e}", file=sys.stderr)
            return False

    def start_background_daemon(self):
        """Start non-blocking daemon thread to auto-check and upgrade every 10 minutes."""
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                try:
                    time.sleep(self.check_interval_sec)
                    if not self._running:
                        break
                    current_ver = self.get_current_version()
                    remote_ver, _ = self.check_remote_version()
                    if remote_ver and self.is_newer(remote_ver, current_ver):
                        # Upgrade in background when idle
                        self.perform_upgrade_and_restart(direct_cli=False)
                except Exception:
                    pass

        self._thread = threading.Thread(target=_loop, daemon=True, name="jeik-updater-daemon")
        self._thread.start()

updater = AutoUpdater()
