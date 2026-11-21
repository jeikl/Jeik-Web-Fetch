import os
import sys
import subprocess

def test_cli_utf8_encoding_with_emoji():
    """
    Simulate a legacy non-UTF8 environment (like Chinese Windows GBK/cp936 stdout pipe)
    and verify that jeik cli handles emojis (\U0001f468, etc.) and Unicode characters
    without raising UnicodeEncodeError.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "gbk"

    # Test the module import and safe_print / configure_utf8_io
    test_code = """
import sys
from jeik_web_fetch.cli import safe_print, configure_utf8_io

configure_utf8_io()
safe_print("Test emoji: \\U0001f468, check: ✔, cross: ✘, Chinese: 中文测试")
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", test_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env
    )
    stdout, stderr = proc.communicate(timeout=10)
    assert proc.returncode == 0, f"Process failed with returncode {proc.returncode}, stderr: {stderr.decode('utf-8', errors='replace')}"
    decoded_out = stdout.decode("utf-8", errors="replace")
    assert "👨" in decoded_out or "Test emoji" in decoded_out
    print("[+] test_cli_utf8_encoding_with_emoji passed!")

if __name__ == "__main__":
    test_cli_utf8_encoding_with_emoji()
    print("[✔] All encoding tests passed!")
