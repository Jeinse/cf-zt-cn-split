import requests
import os
import re

CF_API_TOKEN   = os.getenv("CF_API_TOKEN")
ACCOUNT_ID     = os.getenv("CF_ACCOUNT_ID")
PROFILE_ID     = os.getenv("CF_PROFILE_ID", "")
MODE           = os.getenv("MODE", "exclude")  # Split Tunnel 模式: exclude 或 include
ALLOWED_MODES  = {"exclude", "include"}

# 功能开关与配额控制
ENABLE_SPLIT_TUNNEL = os.getenv("ENABLE_SPLIT_TUNNEL", "true").lower() == "true"
ENABLE_LDF          = os.getenv("ENABLE_LDF", "true").lower() == "true"

MAX_SPLIT_RULES     = 4000  # Split Tunnel 总上限
TARGET_DOMAIN_N     = 0     # Split Tunnel 中分配给域名的配额

MAX_LDF_RULES       = int(os.getenv("MAX_LDF_RULES", "200"))  # LDF 建议限制在 100~500 以内
LDF_DNS_SERVER      = os.getenv("LDF_DNS_SERVER", "")         # 可选：强行指定 LDF 的 DNS IP，如 "223.5.5.5,223.6.6.6"

if not all([CF_API_TOKEN, ACCOUNT_ID]):
    raise ValueError("缺少环境变量！请在 GitHub Secrets 设置 CF_API_TOKEN、CF_ACCOUNT_ID")

if MODE not in ALLOWED_MODES:
    raise ValueError(f"非法 MODE: {MODE}，只允许 {'/'.join(sorted(ALLOWED_MODES))}")

HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

VALID_DOMAIN_RE = re.compile(r'^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$')

DOMAIN_URL = "https://raw.githubusercontent.com/Loyalsoldier/surge-rules/release/direct.txt"
IP_URL     = "https://raw.githubusercontent.com/soffchen/GeoIP2-CN/release/CN-ip-cidr.txt"


def get_cn_cidrs():
    """拉取 CN CIDR 列表"""
    r = requests.get(IP_URL, timeout=30)
    r.raise_for_status()
    cidrs = [line.strip() for line in r.text.splitlines() if line.strip() and not line.startswith('#')]
    print(f"   IP 数据源获取到 {len(cidrs)} 条 CIDR")
    return cidrs


def get_cn_domains():
    """拉取精选 CN 基础域名列表（纯域名格式）"""
    r = requests.get(DOMAIN_URL, timeout=30)
    r.raise_for_status()
    domains = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('DOMAIN-SUFFIX,'):
            line = line.replace('DOMAIN-SUFFIX,', '').strip()
        line = line.lstrip('.')
        if line and VALID_DOMAIN_RE.match(line):
            domains.append(line.lower())
    unique = list(set(domains))
    print(f"   域名数据源获取到 {len(unique)} 条基础域名")
    return unique


def update_split_tunnels(cidrs, domains):
    """更新 Split Tunnels (IP 与 域名)"""
    print("\n🚀 [1/2] 开始更新 Split Tunnels...")
    max_domains = min(TARGET_DOMAIN_N, len(domains))
    max_ips     = min(MAX_SPLIT_RULES - max_domains, len(cidrs))

    # Split Tunnel 域名格式：*.example.com
    domain_entries = [{"host": f"*.{d}", "description": "CN Domain"} for d in domains[:max_domains]]
    ip_entries     = [{"address": cidr,  "description": "CN IP"}     for cidr in cidrs[:max_ips]]
    routes = domain_entries + ip_entries

    print(f"   域名规则：{len(domain_entries)} 条 | IP 规则：{len(ip_entries)} 条 | 合计：{len(routes)} 条")

    if PROFILE_ID:
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/{PROFILE_ID}/{MODE}"
    else:
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/{MODE}"

    resp = requests.put(url, json=routes, headers=HEADERS)
    if resp.status_code in (200, 204):
        print(f"✅ Split Tunnels 同步成功！ Mode: {MODE}")
    else:
        print(f"❌ Split Tunnels 失败 {resp.status_code}: {resp.text}")
        resp.raise_for_status()


def update_fallback_domains(domains):
    """覆写 Local Domain Fallback 列表"""
    print("\n🚀 [2/2] 开始更新 Local Domain Fallback...")

    dns_servers = [s.strip() for s in LDF_DNS_SERVER.split(",") if s.strip()] if LDF_DNS_SERVER else []

    # LDF 格式：{"suffix": "example.com", "description": "..."}
    ldf_entries = []
    for d in domains[:MAX_LDF_RULES]:
        entry = {
            "suffix": d,
            "description": "CN Local Fallback"
        }
        if dns_servers:
            entry["dns_server"] = dns_servers
        ldf_entries.append(entry)

    print(f"   准备写入 {len(ldf_entries)} 条 Local Domain Fallback 规则 (上限: {MAX_LDF_RULES})")

    if PROFILE_ID:
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/{PROFILE_ID}/fallback_domains"
    else:
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/fallback_domains"

    resp = requests.put(url, json=ldf_entries, headers=HEADERS)
    if resp.status_code in (200, 204):
        print(f"✅ Local Domain Fallback 同步成功！")
    else:
        print(f"❌ Local Domain Fallback 失败 {resp.status_code}: {resp.text}")
        resp.raise_for_status()


if __name__ == "__main__":
    print("🔄 拉取最新 CN geo 数据...")
    cidrs   = get_cn_cidrs()
    domains = get_cn_domains()

    if ENABLE_SPLIT_TUNNEL:
        update_split_tunnels(cidrs, domains)

    if ENABLE_LDF:
        update_fallback_domains(domains)