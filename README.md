# cf-zt-cn-split

自动同步中国大陆 IP 段与直连域名到 Cloudflare Zero Trust 分流隧道（Split Tunnels），实现 CN 流量直连、其余流量走 WARP 的网络分流策略。

-----

## 功能简介

- 自动拉取最新中国大陆 IP 数据（来源：[soffchen/GeoIP2-CN](https://github.com/soffchen/GeoIP2-CN) 全运营商聚合版）
- 通过 `mydomain.txt` 统一管理自定义直连域名与 IP/CIDR（含内网保留网段）
- 自定义规则优先加载，CN 公网 IP 段兜底填满剩余配额，在 4000 条限额内最大化分流准确性
- 通过 Cloudflare Zero Trust API 更新设备策略的 Split Tunnels 规则
- 支持多设备策略按**序号**精确选更：`CF_PROFILE_ID` 逗号分隔登记自定义策略，`CF_PROFILE_INDEX` 指定本次更新哪些序号（`0`=账号默认策略，`1~N`=自定义策略）
- 提供 `RUN_UPDATE` 总开关，可一键跳过更新（仅演练拉取，不改动线上策略）
- 支持 `exclude`（CN 直连）和 `include`（仅 CN 走 WARP）两种模式
- 通过 GitHub Actions 定时自动运行，无需手动维护

-----

## 工作原理

```text
   mydomain.txt (自定义域名 + IP/CIDR)      soffchen/GeoIP2-CN (CN-ip-cidr.txt)
        ↓ 自定义 CIDR + 自定义直连域名               ↓ 全运营商聚合 CIDR（兜底填满剩余配额）
                        ↓ 自定义规则在前 ↓
                      cf-zt-cn-split.py
                        ↓ Cloudflare Zero Trust API（PUT）
              设备策略 Split Tunnels 规则（exclude / include）
                        ↓
      自定义域名 DNS 层直连 + 自定义/CN IP 网络层兜底，其余走 WARP
```

### 分流优先级逻辑

```text
用户访问 mydomain.txt 收录的域名（如 *.baidu.com）
  → 命中自定义域名规则 → DNS + 流量均走直连通道 ✅

用户访问未收录域名，但解析到 mydomain.txt 或 CN 数据源中的 IP
  → 域名规则未命中 → IP/CIDR 规则兜底命中 → 直连 ✅

用户访问未收录域名，IP 也未收录
  → 两层均未命中 → 走 WARP ⚠️（概率极低，可接受）
```

-----

## 前置要求

- Cloudflare Zero Trust 账户（免费版即可）
- 已在设备上部署 Cloudflare WARP 客户端
- Cloudflare API Token（需具备 Zero Trust 写权限）

-----

## 快速开始

### 1. Fork 本仓库

点击右上角 **Fork** 按钮，将仓库复制到你的 GitHub 账户。

### 2. 配置 GitHub Secrets

进入仓库 **Settings → Secrets and variables → Actions**，添加以下 Secrets：

|Secret 名称        |说明                                                        |是否必填|
|-----------------|----------------------------------------------------------|----|
|`CF_API_TOKEN`   |Cloudflare API Token，需具备 Zero Trust 写权限                   |✅必填  |
|`CF_ACCOUNT_ID`  |Cloudflare 账户 ID（全局公共账号，所有策略共用），可在控制台右侧边栏找到       |✅必填  |
|`CF_PROFILE_ID`  |设备策略 ID 清单，逗号分隔登记（如 `id1,id2,id3`），序号从 **1** 起依次对应       |❌可选  |
|`CF_PROFILE_INDEX`|本次要更新的策略**序号**，逗号分隔（如 `0,1,3`）；`0`=账号默认策略，`1~N`=自定义策略；留空=不更新任何策略|❌可选  |
|`RUN_UPDATE`     |是否执行更新：`true`（默认）=更新指定序号策略；`false`=只拉取数据、跳过更新   |❌可选  |
|`MODE`           |分流模式：`exclude`（CN 直连）或 `include`（仅 CN 走 WARP），默认 `exclude`|❌可选  |

#### 如何获取 API Token

1. 前往 [Cloudflare Dashboard → API Tokens](https://dash.cloudflare.com/profile/api-tokens)
1. 点击 **Create Token**
1. 选择 **Edit Cloudflare Zero Trust** 模板，或手动添加 `Zero Trust: Edit` 权限
1. 复制生成的 Token

### 3. 启用 GitHub Actions

进入仓库 **Actions** 标签页，启用 Workflow。默认每周日自动运行一次，也可手动触发。

-----

## 配置说明

### 分流模式（MODE）

|模式           |行为                                   |
|-------------|-------------------------------------|
|`exclude`（默认）|自定义规则与 CN IP 加入排除列表，对应流量**不走** WARP，直连出口|
|`include`    |自定义规则与 CN IP 加入包含列表，**只有**这些流量走 WARP   |

大多数用户选择 `exclude` 模式：境外流量走 WARP，国内流量直连，兼顾速度与访问需求。

### 设备策略选更（CF_PROFILE_ID + CF_PROFILE_INDEX）

本项目采用「**登记清单 + 序号选更**」两步机制，精确控制本次更新哪些策略：

1. **登记策略清单**：把所有自定义设备策略 ID 填入 `CF_PROFILE_ID`，逗号分隔，脚本自动编号，序号从 **1** 开始依次对应，序号 `[0]` 固定代表账号默认设备策略：

   ```
   CF_PROFILE_ID=邮箱ID,安卓ID,苹果ID,电脑ID
                    ↓      ↓     ↓     ↓
   序号：  [0]默认  [1]    [2]   [3]   [4]
   ```

   > 序号 `[0]` 是账号默认设备策略（更新时走不带 profile_id 的 API），影响的是**未匹配任何自定义策略的设备**；`[1~N]` 为你登记的自定义策略。

2. **指定本次要更新的序号**：在 `CF_PROFILE_INDEX` 填写序号，逗号分隔：

   | `CF_PROFILE_INDEX` 取值 | 效果                         |
   |------------------------|------------------------------|
   | `0`                    | 只更新账号默认设备策略         |
   | `1`                    | 只更新序号 1 的策略           |
   | `0,1`                  | 同时更新默认策略和序号 1       |
   | `1,3`                  | 更新序号 1 和序号 3 的策略     |
   | `0,1,2,3,4`            | 更新默认策略 + 全部四个自定义策略|
   | 留空                    | 不更新任何策略                |

   > 脚本会对序号做去重、排序与范围校验（超出 `0 ~ N` 会报错终止）。

### 更新总开关（RUN_UPDATE）

- `RUN_UPDATE=true`（默认）：按 `CF_PROFILE_INDEX` 更新对应策略
- `RUN_UPDATE=false`：只拉取并组装数据、打印统计，**跳过所有 PUT 请求**，不改动任何线上策略，适合演练验证

-----

## 规则配额分配

Cloudflare Zero Trust Split Tunnels 单策略最多支持 **4000 条**规则，本项目按如下优先级依次填充配额：

|规则类型              |来源                                  |优先级          |
|------------------|------------------------------------|-------------|
|自定义 CIDR（`address`）|`mydomain.txt`（含内网保留网段）             |最高           |
|自定义域名（`host`）      |`mydomain.txt`                       |高（DNS 层）     |
|CN 公网 IP（`address`）|soffchen/GeoIP2-CN `CN-ip-cidr.txt`  |兜底（填满剩余配额）  |
|**合计**            |                                     |**≤ 4000 条** |

> 自定义规则优先加载，CN 公网 IP 段填满剩余配额；当规则总数超过 `MAX_RULES` 时脚本会自动截断。
> 实际提交条数由脚本顶部常量 `MAX_RULES` 控制（Cloudflare 单策略上限为 4000，可按需调小用于测试）。
> 通用 CN 域名数量由脚本中的 `TARGET_COMMON_DOMAIN_NUM` 控制，当前默认为 `0`（不加载），全部配额留给自定义规则与 CN IP 段。

-----

## 数据源说明

### IP 数据源

|数据源                                                                                    |实测条目数       |状态  |备注              |
|---------------------------------------------------------------------------------------|------------|----|----------------|
|[soffchen/GeoIP2-CN](https://github.com/soffchen/GeoIP2-CN) `CN-ip-cidr.txt`          |~3900 条     |当前使用|全运营商聚合，由于配额充足可完整载入|
|[gaoyifan/china-operator-ip](https://github.com/gaoyifan/china-operator-ip) `china.txt`|~4397 条     |备用  |全运营商聚合，取前 3900 条      |
|[IPdeny aggregated](https://www.ipdeny.com/ipblocks/data/aggregated/cn-aggregated.zone)|~2200 条     |备用  |条目更少，可完整载入            |
|[metowolf/iplist](https://github.com/metowolf/iplist) `china.txt`                      |~1700 条     |备用  |条目最少                      |

### 域名与自定义规则

|来源                                                                                 |用途                 |状态  |备注                         |
|------------------------------------------------------------------------------------|--------------------|----|---------------------------|
|`mydomain.txt`                                                                       |自定义直连域名 + IP/CIDR |当前使用|统一在本文件中管理，含内网保留网段，脚本自动区分域名与 CIDR|
|[Loyalsoldier/surge-rules](https://github.com/Loyalsoldier/surge-rules) `direct.txt`|通用 CN 直连域名         |备用  |由 `TARGET_COMMON_DOMAIN_NUM` 控制加载条数，当前默认为 `0`（不加载）|

> `mydomain.txt` 中每行一条：以 `*.` 或域名格式书写的视为域名规则（自动补全 `*.` 前缀），符合 CIDR 格式的视为 IP 规则，`#` 开头为注释。

-----

## 本地运行

```bash
# 安装依赖
pip install requests

# 方式一：在项目根目录创建 .env 文件
CF_API_TOKEN=your_api_token
CF_ACCOUNT_ID=your_account_id
CF_PROFILE_ID=邮箱ID,安卓ID,苹果ID,电脑ID   # 登记策略清单，序号 1/2/3/4 依次对应
MODE=exclude
RUN_UPDATE=true                          # true=更新 / false=只拉取不更新
CF_PROFILE_INDEX=1                        # 本次更新的序号（0=默认策略，1~N=自定义），逗号分隔；空=不更新

# 方式二：设置系统环境变量（.env 不存在时兜底读取）
export CF_API_TOKEN="your_api_token"
export CF_ACCOUNT_ID="your_account_id"
export CF_PROFILE_ID="邮箱ID,安卓ID,苹果ID,电脑ID"
export MODE="exclude"
export RUN_UPDATE="true"
export CF_PROFILE_INDEX="1"

# 运行脚本
python cf-zt-cn-split.py
```

正常输出示例（`CF_PROFILE_INDEX=0,1`，更新默认策略 + 序号 1）：

```
ℹ️ 策略索引对照表：
   [0] 账号默认设备策略（未匹配自定义策略的设备回落至此）
   [1] 邮箱ID
   [2] 安卓ID
   [3] 苹果ID
   [4] 电脑ID

ℹ️ 本次需要更新的策略序号：[0, 1]

🔄 拉取CN域名、IP、自定义规则数据...
   自定义域名(mydomain.txt)：xxx 条
   自定义CIDR(mydomain.txt)：xx 条
   通用CN域名总数：xxxx，限制取 0 条
   CN IP CIDR 数据源：xxxx 条
   自定义CIDR:xx | 自定义域名:xxx | 通用域名:0 | CN公网IP:xxxx | 总规则:xxxx

===== 执行更新指定序号策略分流规则 =====
✅ 分流更新完成！策略[0] 账号默认设备策略 (1/2) | xxxx 条路由
✅ 分流更新完成！策略[1] 邮箱ID (2/2) | xxxx 条路由

🎉 脚本全部执行完毕
```

-----

## GitHub Actions 定时任务

默认配置为每周日 UTC 03:00（北京时间 11:00）自动运行，也可在 Actions 页面点击 **Run workflow** 手动触发。

如需修改定时频率，编辑 `.github/workflows/sync-cn-split.yml` 中的 `cron` 表达式。

-----

## 常见问题

**Q：同步成功后 WARP 客户端需要重启吗？**  
A：不需要，Cloudflare Zero Trust 策略更新后会自动下发到已连接的 WARP 客户端。

**Q：报错 `invalid number of rules, number of rules cannot be greater than 4000`？**  
A：IP 或域名数据源条目超出上限，脚本已内置截断逻辑，正常情况下不会触发。若触发请检查数据源是否变更。

**Q：报错 `invalid exclude value` 或 `invalid domain name`？**  
A：API payload 格式错误或域名包含非法字符，请确保使用最新版本脚本（已内置正则过滤）。

**Q：报错 `404 Not Found`？**  
A：数据源 URL 失效，请检查脚本中 `IP_URL` / `DOMAIN_URL` 是否仍然可访问，并切换至备用数据源。

**Q：如何确认规则已生效？**  
A：前往 Cloudflare Zero Trust Dashboard → **Settings → WARP Client → Device settings → 对应策略 → Split Tunnels**，查看规则列表是否已更新。

**Q：报错 `更新序号N超出范围！可用更新序号：0（默认策略） 或 1 ~ M`？**  
A：`CF_PROFILE_INDEX` 填写的序号超出了可用范围。请对照运行时打印的「策略索引对照表」，只填 `0`（默认策略）或 `1 ~ M`（M 为 `CF_PROFILE_ID` 登记的自定义策略数量）。

**Q：如何更新账号默认设备策略？**  
A：在 `CF_PROFILE_INDEX` 中加入序号 `0` 即可，例如 `CF_PROFILE_INDEX=0` 只更新默认策略，`CF_PROFILE_INDEX=0,1,2` 同时更新默认策略与序号 1、2 的自定义策略。默认策略更新时走不带 profile_id 的 API，影响的是未匹配任何自定义策略的设备。

**Q：怎样先演练一次而不改动线上策略？**  
A：设 `RUN_UPDATE=false`，脚本会照常拉取数据源、组装并打印规则统计，但跳过所有 PUT 请求，不会改动任何策略。

**Q：如何添加自己的直连域名或 IP 段？**  
A：直接编辑根目录的 `mydomain.txt`，每行一条。域名可写为 `*.example.com` 或 `example.com`（脚本自动补全 `*.` 前缀），IP 段写为标准 CIDR 格式（如 `1.2.3.0/24`），`#` 开头为注释行。

**Q：为什么默认不加载通用 CN 域名？**  
A：脚本中的 `TARGET_COMMON_DOMAIN_NUM` 默认为 `0`，即不从 surge-rules 拉取通用域名，把全部 4000 条配额留给 `mydomain.txt` 自定义规则与 CN 公网 IP 段兜底。如需启用，可调大该值。

-----

## 许可证

MIT License
