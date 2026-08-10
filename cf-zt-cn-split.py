import requests
import os
import re

CF_API_TOKEN = os.getenv("CF_API_TOKEN")
ACCOUNT_ID   = os.getenv("CF_ACCOUNT_ID")
PROFILE_ID   = os.getenv("CF_PROFILE_ID", "")

LDF_DNS_SERVER = os.getenv("LDF_DNS_SERVER", "")  # 可选：强行指定 LDF 的 DNS IP，如 "223.5.5.5,223.6.6.6"

if not all([CF_API_TOKEN, ACCOUNT_ID]):
    raise ValueError("缺少环境变量！请在 GitHub Secrets 设置 CF_API_TOKEN、CF_ACCOUNT_ID")

HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

# 域名合法性正则
VALID_DOMAIN_RE = re.compile(r'^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$')

# 域名数据源：Loyalsoldier 精选直连域名
DOMAIN_URL = "https://raw.githubusercontent.com/Loyalsoldier/surge-rules/release/direct.txt"


def get_cn_domains():
    """拉取精选 CN 基础域名列表（纯域名格式）"""
    print("🔄 正在拉取 CN 域名数据源...")
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
    print(f"✅ 获取并去重后得到 {len(unique)} 条基础域名")
    return unique


def update_fallback_domains(domains):
    """覆写 Local Domain Fallback 列表（保留系统默认/非脚本创建的规则）"""
    print("\n🚀 开始更新 Local Domain Fallback...")

    if PROFILE_ID:
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/{PROFILE_ID}/fallback_domains"
    else:
        url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/devices/policy/fallback_domains"

    # 1. 先获取现有的 LDF 列表，保留系统默认规则
    preserved_entries = []
    try:
        get_resp = requests.get(url, headers=HEADERS, timeout=15)
        if get_resp.status_code == 200:
            current_entries = get_resp.json().get("result", [])
            # 过滤掉上次脚本生成的 CN 规则，保留系统默认规则（如 *.local, *.lan 等）
            preserved_entries = [
                e for e in current_entries 
                if e.get("description") != "CN Local Fallback"
            ]
            print(f"   找到并保留 {len(preserved_entries)} 条系统默认/自定义规则")
    except Exception as e:
        print(f"⚠️ 获取现有 Fallback 列表失败，将忽略旧规则直接写入: {e}")

    dns_servers = [s.strip() for s in LDF_DNS_SERVER.split(",") if s.strip()] if LDF_DNS_SERVER else []

    # 2. 全量构建 CN 域名条目（读取 Loyalsoldier 的所有域名，不做数量限制）
    cn_entries = []
    for d in domains:
        entry = {
            "suffix": d,
            "description": "CN Local Fallback"
        }
        if dns_servers:
            entry["dns_server"] = dns_servers
        cn_entries.append(entry)

    # 3. 合并默认规则与全部 CN 规则
    final_entries = preserved_entries + cn_entries
    print(f"   默认规则：{len(preserved_entries)} 条 | 注入 CN 域名：{len(cn_entries)} 条 | 合计提交：{len(final_entries)} 条")

    # 4. 提交 API 写入
    resp = requests.put(url, json=final_entries, headers=HEADERS)
    if resp.status_code in (200, 204):
        print(f"✅ Local Domain Fallback 全量同步成功！")
    else:
        print(f"❌ 失败 {resp.status_code}: Cloudflare API 请求未成功")
        print(f"错误详情: {resp.text}")
        resp.raise_for_status()


if __name__ == "__main__":
    domains = get_cn_domains()
    update_fallback_domains(domains)