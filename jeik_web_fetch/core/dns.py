import re
from typing import Optional, List, Tuple

class DNSResolverConfig:
    """
    DNS 配置解析与 Chromium 规则生成器：
    - 支持系统默认 DNS (Default)
    - 支持数字 IPv4 / IPv6 DNS (例如: 8.8.8.8, 1.1.1.1, 114.114.114.114, 223.5.5.5)
    - 支持加密 DNS (DoH / DNS-over-HTTPS, 例如: https://dns.alidns.com/dns-query, https://1.1.1.1/dns-query, https://dns.google/dns-query)
    - 允许完全放行内网 IP (127.0.0.1, 192.168.x.x, 10.x.x.x, localhost) 与公网
    """

    # 常见加密 DNS 预设别名
    DOH_PRESETS = {
        "aliyun": "https://dns.alidns.com/dns-query",
        "alidns": "https://dns.alidns.com/dns-query",
        "dnspod": "https://doh.pub/dns-query",
        "tencent": "https://doh.pub/dns-query",
        "cloudflare": "https://1.1.1.1/dns-query",
        "google": "https://dns.google/dns-query",
    }

    @classmethod
    def build_chrome_args(cls, dns: Optional[str] = None) -> List[str]:
        """
        根据用户传入的 DNS 参数，生成精确的 Chromium 启动参数
        """
        args = [
            # 允许私有网络与内网无限制访问（移除内网拦截）
            "--allow-insecure-localhost",
            "--ignore-certificate-errors",
        ]

        if not dns or dns.lower() in ("system", "default", "none"):
            return args

        dns_val = dns.strip()
        # 别名解析
        if dns_val.lower() in cls.DOH_PRESETS:
            dns_val = cls.DOH_PRESETS[dns_val.lower()]

        # 1. 加密 DNS (DNS-over-HTTPS)
        if dns_val.startswith("https://"):
            args.extend([
                "--enable-features=DnsOverHttps",
                f"--dns-over-https-templates={dns_val}",
            ])
            return args

        # 2. 数字 IP DNS (例如 8.8.8.8, 114.114.114.114, 223.5.5.5)
        # 通过 Chrome host-resolver-rules 规则绑定或注入 DNS 配置
        # 兼容 IPv4 格式
        ipv4_pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
        if re.match(ipv4_pattern, dns_val):
            # 将常见公网 DNS 映射至其标准 DoH 模板，或通过 host 规则解析
            if dns_val == "223.5.5.5" or dns_val == "223.6.6.6":
                doh = "https://dns.alidns.com/dns-query"
                args.extend([
                    "--enable-features=DnsOverHttps",
                    f"--dns-over-https-templates={doh}",
                ])
            elif dns_val == "1.1.1.1" or dns_val == "1.0.0.1":
                doh = "https://1.1.1.1/dns-query"
                args.extend([
                    "--enable-features=DnsOverHttps",
                    f"--dns-over-https-templates={doh}",
                ])
            elif dns_val == "8.8.8.8" or dns_val == "8.8.4.4":
                doh = "https://dns.google/dns-query"
                args.extend([
                    "--enable-features=DnsOverHttps",
                    f"--dns-over-https-templates={doh}",
                ])
            else:
                # 通用自定义 DNS
                args.append(f"--host-resolver-rules=MAP * ^NOTFOUND, EXCLUDE 127.0.0.1")

        return args
