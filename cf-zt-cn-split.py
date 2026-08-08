# 导入依赖库
# requests：用于发起Cloudflare API网络请求
import requests
# os：读取本地.env文件、判断文件是否存在、读取系统环境变量
import os
# re：正则表达式，校验域名与CIDR格式合法性
import re

# ===================== 全局自定义常量（无需修改） =====================
# 单策略最大分流规则条数限制
MAX_RULES               = 16
# 通用CN域名取用数量，0=不加载公共域名
TARGET_COMMON_DOMAIN_NUM = 0
# ====================================================

# ===================== 函数：加载.env本地环境变量 =====================
def load_local_env():
    # 定义字典存储.env读取到的键值对
    env_dict = {}
    # 本地配置文件名称
    env_path = ".env"
    # 判断文件是否存在
    if os.path.exists(env_path):
        print("✅ 检测到本地.env文件，加载配置...")
        # 以utf-8-sig编码打开文件，兼容Windows带BOM的txt文件
        with open(env_path, "r", encoding="utf-8-sig") as f:
            # 一次性读取文件所有行存入列表
            raw_lines = f.readlines()
        # 遍历每一行，line_num从1开始计数（用户直观看到行数）
        for line_num, raw in enumerate(raw_lines, start=1):
            # 清理换行符、制表符、全角空格，再去除首尾空白
            s = raw.replace("\r", "").replace("\t", "").replace("　", "").strip()
            # 空行 / #注释行直接跳过
            if not s or s.startswith("#"):
                continue
            # 一行没有等号，格式非法，打印警告跳过
            if "=" not in s:
                print(f"⚠️ 第{line_num}行无=，跳过")
                continue
            # 仅分割第一个等号，避免值内部包含=被拆分
            key_raw, val_raw = s.split("=", 1)
            # 清理键两侧空格
            key = key_raw.strip()
            # 清理值两侧空格
            val = val_raw.strip()
            # 键为空，无效配置，跳过
            if not key:
                print(f"⚠️ 第{line_num}行key为空，跳过该行")
                continue
            # 存入环境字典
            env_dict[key] = val
            # 长值截断展示，避免日志刷屏
            show_val = val[:20] + "..." if len(val) > 20 else val
            print(f"ℹ️ 加载 {key} = {show_val}")
    # 内部函数：优先读取.env，不存在则读取系统环境变量
    def get_env(key, default=None):
        # 本地.env存在该键，优先返回
        if key in env_dict:
            return env_dict[key]
        # 读取系统环境变量，无值则返回默认值
        return os.getenv(key, default)
    # 返回读取工具函数，外部全局调用
    return get_env

# 全局获取环境变量读取函数
get_env = load_local_env()

# ===================== 读取基础固定公共配置 =====================
# Cloudflare API全局鉴权令牌（全账号共用）
CF_API_TOKEN = get_env("CF_API_TOKEN")
# Cloudflare全局公共账号ID，所有策略操作共用此账号
CF_ACCOUNT_ID = get_env("CF_ACCOUNT_ID")
# 多设备自定义策略ID，逗号分隔，序号1/2/3/4依次对应
CF_PROFILE_ID = get_env("CF_PROFILE_ID", "")
# 分流模式 exclude/include
MODE = get_env("MODE", "exclude")
# 合法模式白名单
ALLOWED_MODES = {"exclude", "include"}

# ===================== 功能控制配置（仅保留功能1 更新分流） =====================
# RUN_UPDATE：true=更新指定序号策略分流规则 false=跳过更新
RUN_UPDATE = get_env("RUN_UPDATE", "true")
# CF_PROFILE_INDEX：逗号分隔数字，指定需要更新的策略序号，0=账号默认设备策略，1~N=自定义策略
CF_PROFILE_INDEX = get_env("CF_PROFILE_INDEX", "")
# 布尔值合法白名单
ALLOWED_BOOL = {"true", "false"}

# ===================== 打印调试信息 =====================
print("\n===== 调试变量 =====")
print(f"CF_API_TOKEN: {CF_API_TOKEN if CF_API_TOKEN else 'None'}")
print(f"CF_ACCOUNT_ID(全局公共账号): {CF_ACCOUNT_ID if CF_ACCOUNT_ID else 'None'}")
print(f"CF_PROFILE_ID(全部自定义策略): {CF_PROFILE_ID}")
print(f"RUN_UPDATE(更新分流开关): {RUN_UPDATE}")
print(f"CF_PROFILE_INDEX(待更新策略序号): {CF_PROFILE_INDEX}")
print(f"MODE: {MODE}")
print("====================\n")

# ===================== 基础参数合法性校验 =====================
# 全局认证参数缺失直接终止程序
if not all([CF_API_TOKEN, CF_ACCOUNT_ID]):
    raise ValueError("缺少环境变量！请配置 .env 文件或在 GitHub Secrets 设置 CF_API_TOKEN、CF_ACCOUNT_ID")
# 分流模式非法校验
if MODE not in ALLOWED_MODES:
    raise ValueError(f"非法 MODE: {MODE}，允许值：exclude/include")
# 功能开关只能填写true/false
if RUN_UPDATE.lower() not in ALLOWED_BOOL:
    raise ValueError("RUN_UPDATE 仅支持 true/false")

# ===================== 解析自定义策略ID列表，生成索引对照表 =====================
# 分割逗号、去除空值、清理空格，得到纯自定义策略ID数组
ALL_PROFILES = [p.strip() for p in CF_PROFILE_ID.split(",") if p.strip()]
max_custom_num = len(ALL_PROFILES)
print(f"ℹ️ 策略索引对照表：")
print(f"   [0] 账号默认设备策略（未匹配自定义策略的设备回落至此）")
for idx, pid in enumerate(ALL_PROFILES, start=1):
    print(f"   [{idx}] {pid}")
print()

# ===================== 解析待更新策略序号列表 CF_PROFILE_INDEX =====================
update_target_index_list = []
if CF_PROFILE_INDEX.strip():
    raw_index_arr = [s.strip() for s in CF_PROFILE_INDEX.split(",") if s.strip()]
    for num_str in raw_index_arr:
        # 转换数字校验
        try:
            num = int(num_str)
        except ValueError:
            raise ValueError(f"CF_PROFILE_INDEX 仅允许填写数字，非法值：{num_str}")
        # 校验序号范围：0=默认策略，1~N=自定义策略
        if num < 0 or num > max_custom_num:
            raise ValueError(f"更新序号{num}超出范围！可用更新序号：0（默认策略） 或 1 ~ {max_custom_num}")
        update_target_index_list.append(num)
    # 去重并排序
    update_target_index_list = sorted(list(set(update_target_index_list)))
    print(f"ℹ️ 本次需要更新的策略序号：{update_target_index_list}")
else:
    # 未填写CF_PROFILE_INDEX代表不更新任何策略
    print(f"ℹ️ CF_PROFILE_INDEX 为空，无自定义策略需要更新")
print()

# ===================== API请求统一请求头 =====================
HEADERS = {
    # Bearer鉴权Token
    "Authorization": f"Bearer {CF_API_TOKEN}",
    # 请求体为JSON格式
    "Content-Type": "application/json"
}


# 正则：校验域名格式
VALID_DOMAIN_RE = re.compile(r'^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$')
# 正则：校验IP CIDR网段格式
CIDR_RE = re.compile(r'^[0-9a-fA-F:.]+/\d+$')
# 自定义域名/IP文件路径
MYDOMAIN_FILE = "mydomain.txt"
# 公共CN域名规则远程地址
DOMAIN_URL = "https://raw.githubusercontent.com/Loyalsoldier/surge-rules/release/direct.txt"
# 国内IP网段远程地址
IP_URL = "https://raw.githubusercontent.com/soffchen/GeoIP2-CN/release/CN-ip-cidr.txt"

# ===================== 函数：读取本地自定义域名&CIDR =====================
def get_myhost_content():
    # 存储自定义域名列表
    mydomain_list = []
    # 存储自定义IP网段列表
    mycidr_list = []
    # 判断自定义文件是否存在
    if os.path.exists(MYDOMAIN_FILE):
        # 读取自定义规则文件
        with open(MYDOMAIN_FILE, "r", encoding="utf-8") as f:
            # 逐行遍历
            for line in f.readlines():
                # 去除首尾空白
                line = line.strip()
                # 空行、注释行跳过
                if not line or line.startswith("#"):
                    continue
                # 当前行是CIDR网段，加入CIDR列表
                if CIDR_RE.match(line):
                    mycidr_list.append(line)
                    continue
                # 去除开头泛域名前缀 *.
                if line.startswith("*."):
                    line = line[2:]
                # 去除开头多余点号
                line = line.lstrip(".")
                # 校验域名合法，转为泛域名格式存入列表
                if VALID_DOMAIN_RE.match(line):
                    mydomain_list.append(f"*.{line}")
        # 去重，避免重复规则占用配额
        mydomain_list = list(set(mydomain_list))
        mycidr_list = list(set(mycidr_list))
        # 打印统计数量
        print(f"   自定义域名(mydomain.txt)：{len(mydomain_list)} 条")
        print(f"   自定义CIDR(mydomain.txt)：{len(mycidr_list)} 条")
    else:
        # 文件不存在提示
        print(f"   未找到 {MYDOMAIN_FILE}，跳过自定义规则")
    # 返回自定义域名、自定义网段两个数组
    return mydomain_list, mycidr_list

# ===================== 函数：拉取公共国内IP网段 =====================
def get_cn_cidrs():
    # GET请求远程IP文件，超时30秒
    r = requests.get(IP_URL, timeout=30)
    # 请求失败直接抛出异常终止
    r.raise_for_status()
    # 分行、去空白、过滤注释行
    cidrs = [x.strip() for x in r.text.splitlines() if x.strip() and not x.startswith("#")]
    # 打印总条数
    print(f"   CN IP CIDR 数据源：{len(cidrs)} 条")
    return cidrs

# ===================== 函数：拉取公共国内域名规则 =====================
def get_cn_domains():
    # 请求远程域名规则文件
    r = requests.get(DOMAIN_URL, timeout=30)
    r.raise_for_status()
    domains = []
    # 逐行解析
    for line in r.text.splitlines():
        line = line.strip()
        # 空行/注释跳过
        if not line or line.startswith("#"):
            continue
        # 移除Surge规则前缀 DOMAIN-SUFFIX,
        if line.startswith("DOMAIN-SUFFIX,"):
            line = line.replace("DOMAIN-SUFFIX,", "").strip()
        # 清理开头多余点
        line = line.lstrip(".")
        # 域名合法则转为泛域名存入
        if VALID_DOMAIN_RE.match(line):
            domains.append(f"*.{line}")
    # 域名去重
    unique_domains = list(set(domains))
    print(f"   通用CN域名总数：{len(unique_domains)}，限制取 {TARGET_COMMON_DOMAIN_NUM} 条")
    return unique_domains

# ===================== 函数：组装最终分流路由规则 =====================
def build_routes(cidrs, common_domains, custom_domains, custom_cidrs):
    # 最终提交给CF的路由数组
    routes = []
    # 剩余可用规则配额
    remain_quota = MAX_RULES

    # 第一步：添加自定义CIDR网段，不超过剩余配额
    cidr_custom = [{"address": c, "description": "Custom CIDR(mydomain.txt)"} for c in custom_cidrs[:remain_quota]]
    routes.extend(cidr_custom)
    # 扣除已使用配额
    remain_quota -= len(cidr_custom)

    # 第二步：添加自定义域名
    domain_custom = [{"host": d, "description": "Custom Host(mydomain.txt)"} for d in custom_domains[:remain_quota]]
    routes.extend(domain_custom)
    remain_quota -= len(domain_custom)

    # 计数变量
    count_common = 0
    count_ip = 0
    # 还有剩余配额才继续加载公共规则
    if remain_quota > 0:
        # 计算可加载公共域名数量
        take_common = min(TARGET_COMMON_DOMAIN_NUM, remain_quota, len(common_domains))
        common_entries = [{"host": d, "description": "CN Domain(Common)"} for d in common_domains[:take_common]]
        routes.extend(common_entries)
        remain_quota -= len(common_entries)
        count_common = len(common_entries)

        # 仍有配额加载国内IP网段
        if remain_quota > 0:
            ip_entries = [{"address": c, "description": "CN IP"} for c in cidrs[:remain_quota]]
            routes.extend(ip_entries)
            count_ip = len(ip_entries)

    # 打印各类规则统计
    print(f"   自定义CIDR:{len(cidr_custom)} | 自定义域名:{len(domain_custom)} | 通用域名:{count_common} | CN公网IP:{count_ip} | 总规则:{len(routes)}")
    # 超过最大条数直接截断
    if len(routes) > MAX_RULES:
        print(f"⚠️ 规则超上限，截断至 {MAX_RULES} 条")
        routes = routes[:MAX_RULES]
    # 返回组装完成的路由数组
    return routes

# ===================== 函数：仅更新指定序号的自定义策略分流规则 =====================
def update_selected_split_tunnels(routes):
    if len(update_target_index_list) == 0:
        print("ℹ️ 无需要更新的策略，跳过更新流程")
        return
    # 遍历配置的待更新序号
    for seq, target_idx in enumerate(update_target_index_list, start=1):
        # 序号0=默认策略（URL不带profile_id）；1~N=对应自定义策略
        if target_idx == 0:
            api_url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/devices/policy/{MODE}"
            label = f"策略[0] 账号默认设备策略 ({seq}/{len(update_target_index_list)})"
        else:
            profile_id = ALL_PROFILES[target_idx - 1]
            api_url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/devices/policy/{profile_id}/{MODE}"
            label = f"策略[{target_idx}] {profile_id} ({seq}/{len(update_target_index_list)})"

        # PUT请求提交分流规则
        resp = requests.put(api_url, json=routes, headers=HEADERS)
        # 200/204代表更新成功
        if resp.status_code in (200, 204):
            print(f"✅ 分流更新完成！{label} | {len(routes)} 条路由")
        else:
            # 更新失败打印错误信息并终止
            print(f"❌ 更新分流失败 {label} 状态码:{resp.status_code}")
            print("返回详情：", resp.text)
            resp.raise_for_status()

# ===================== 程序入口主逻辑 =====================
if __name__ == "__main__":
    print("🔄 拉取CN域名、IP、自定义规则数据...")
    # 读取本地自定义规则
    cust_dom, cust_cidr = get_myhost_content()
    # 拉取公共国内域名
    cn_domains = get_cn_domains()
    # 拉取公共国内IP网段
    cn_cidr_list = get_cn_cidrs()
    # 组装所有分流规则
    route_data = build_routes(cn_cidr_list, cn_domains, cust_dom, cust_cidr)

    # 判断是否执行更新指定策略分流
    if RUN_UPDATE.lower() == "true":
        print("\n===== 执行更新指定序号策略分流规则 =====")
        update_selected_split_tunnels(route_data)
    else:
        print("\nℹ️ RUN_UPDATE=false，跳过更新分流规则")

    # 全部流程结束提示
    print("\n🎉 脚本全部执行完毕")