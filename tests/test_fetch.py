import os
import sys

# 将上一级目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jeik_web_fetch import fetch

def test_zhihu_anti_bot():
    url = "https://zhuanlan.zhihu.com/p/25964484"
    print(f"[*] 测试知乎专栏强反爬抓取: {url}")
    md = fetch(url, wait_render_sec=4.0)
    assert len(md) > 2000, "Markdown 长度异常，可能触发反爬"
    assert "知乎" in md or "精华问答" in md
    print(f"[+] 知乎抓取成功，字符数: {len(md)}")

def test_dingtalk_spa_codeblock():
    url = "https://open.dingtalk.com/document/development/event-workflow-instance-change-broadcast"
    print(f"[*] 测试钉钉 SPA 与 Monaco 代码框: {url}")
    md = firecrawl_fetch(url, wait_render_sec=4.0)
    assert "eventUnifiedAppId" in md, "未成功还原 Monaco Editor 内存代码块"
    assert "SyncHTTP/RDS推送" in md, "未成功提取完整表格与下部章节"
    print(f"[+] 钉钉复杂单页抓取成功，字符数: {len(md)}")

if __name__ == "__main__":
    test_zhihu_anti_bot()
    print("-" * 50)
    test_dingtalk_spa_codeblock()
    print("\n[✔] 所有端到端测试均通过！")
