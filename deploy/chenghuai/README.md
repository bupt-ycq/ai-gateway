# 骋怀AI模型网关部署

2026-09-21 后续构建排障、初始化和公网 3000 端口配置的实际记录，见 [部署与公网访问操作手册](chenghuai-gateway-deployment.md)。

阿里云 ECS 从登录、私有仓库下载到公网访问、HTTPS 和备份的逐步操作，见 [阿里云部署复现手册](ALIYUN-REPRODUCE.md)。手册区分已确认的部署进度与待验证步骤。

充值、模型调用预扣与结算流程，见 [当前计费逻辑图解](BILLING-FLOW.md)。

基于 [QuantumNous/new-api](https://github.com/QuantumNous/new-api) 的 `v1.0.0-rc.23`，与参考站公开报告的版本一致。使用原项目完整前后端，通过官方设置接口应用“骋怀AI模型网关”的站点名称、页脚和公开展示设置；保留 New API、QuantumNous 的来源及许可信息。

首页和“关于”页以参考站 `https://llmgw.chenghuai.xin/` 的公开页面为基础，源码保存在 `assets/home.html`、`assets/about.html`。品牌 Logo 和首页配图保存在本地，并由初始化脚本嵌入页面数据，部署后不依赖参考站提供图片。首页代码切换使用可通过 New API HTML 清理的原生控件，页面链接指向新站，并限定背景样式的作用范围，避免影响控制台。界面以桌面浏览器体验为主。

这是独立实例。用户、上游渠道、API Key、余额、订单和调用记录使用新数据库，实际模型调用需要自行配置上游。页面布局来自相同版本的 New API，不用静态页面模拟后台。

本次已运行的预览地址为当前工作环境的 `http://127.0.0.1:3080`，管理员为 `admin`，随机密码保存在仓库根目录 `.local/credentials.json`（权限 `0600`）。这个文件仅属于本次本地实例，不随源码包分发。控制台初始额度是站内记账额度，不代表上游账户余额。公网域名和真实上游尚未配置。

## 本机启动

准备 Docker Engine、Docker Compose v2 和 Python 3，然后克隆仓库并启动：

```bash
git clone https://github.com/bupt-ycq/ai-gateway.git
cd ai-gateway/deploy/chenghuai
./start.sh
python3 bootstrap.py --base-url http://127.0.0.1:3000 --username admin
```

`start.sh` 首次运行生成权限为 `0600` 的 `.env` 和随机会话密钥，之后保留已有文件。初始化脚本在终端隐藏输入新站管理员密码；已有实例需要输入其管理员密码。脚本默认读取同目录的 `brand.json`，可重复执行，只更新有变化的品牌配置。

打开 **http://127.0.0.1:3000**，使用刚设置的账号登录。默认只绑定本机，数据库和日志保存在 `data/`。更换端口时，在 `.env` 修改 `GATEWAY_PORT`，并同步修改初始化命令中的端口。

查看状态、日志和停止：

```bash
docker compose -f compose.yml ps
docker compose -f compose.yml logs --tail=100 new-api
docker compose -f compose.yml down
```

停止不会删除 `data/`。重新启动运行 `./start.sh`。初始化过程不会保存管理员密码，也不需要参考站管理员密码。

如果服务部署在远程机器，可通过 SSH 转发预览：

```bash
ssh -L 3000:127.0.0.1:3000 user@your-server
```

随后在自己的浏览器打开 `http://127.0.0.1:3000`。

## 不安装 Docker 的本机预览

Linux amd64 和 Python 3.11 以上可以直接运行官方二进制，默认端口为 `3080`：

```bash
cd ai-gateway
python3 deploy/chenghuai/run-local.py start
python3 deploy/chenghuai/bootstrap.py --base-url http://127.0.0.1:3080 --username admin
python3 deploy/chenghuai/run-local.py status
```

打开 **http://127.0.0.1:3080**。启动器下载固定版本官方发布二进制并校验 SHA-256；文件保存在仓库根目录 `.local/`，其中 `gateway.db` 是数据库，`server.log` 是日志，`runtime-env.json` 保存本机随机会话密钥。停止使用：

```bash
python3 deploy/chenghuai/run-local.py stop
```

`start --port 3081` 可更换端口，初始化命令也需使用对应端口。上游原生二进制会监听所有网卡，`localhost` 链接不限制其他机器访问；需要仅本机访问时使用前面的 Docker 方案，或在主机防火墙限制该端口。原生模式的 `.local/` 和 Docker 模式的 `deploy/chenghuai/data/` 是两个独立数据库。

## 正式域名与 HTTPS

将自己的域名 A/AAAA 记录指向服务器，并开放 TCP 80/443；可选开放 UDP 443。先完成上述本机初始化，再在 `.env` 添加域名：

```dotenv
GATEWAY_DOMAIN=gateway.example.com
```

运行：

```bash
./start.sh --https
python3 bootstrap.py \
  --base-url https://gateway.example.com \
  --site-url https://gateway.example.com \
  --username admin
```

把示例域名替换成自己的域名。Caddy 自动申请并续期证书，反向代理保留流式输出；证书数据位于 `caddy/`。HTTPS 配置同时启用安全会话 Cookie 和精确 Origin 校验，此后通过 HTTPS 登录。

HTTPS 模式的管理命令需要同时指定两个文件：

```bash
docker compose -f compose.yml -f compose.https.yml ps
docker compose -f compose.yml -f compose.https.yml logs --tail=100 caddy
docker compose -f compose.yml -f compose.https.yml down
```

代理网络使用 `172.30.89.0/24`，仅信任 Caddy 的 `172.30.89.2`。若与已有网络冲突，需一并修改 `compose.https.yml` 中的网段、两个静态 IP 和 `TRUSTED_PROXIES`。

## 接入模型

1. 在“渠道”中新建上游，填写自己的上游地址、API Key 和可用模型，测试连接。
2. 核对模型定价、用户分组和额度。
3. 在“令牌”中新建客户端使用的中转 Key。
4. 客户端填写新站的 `https://你的域名/v1`、中转 Key 和渠道已启用的模型名称。

管理账号、客户端令牌和上游 Key 各自独立。此部署不会附带上游余额或参考站业务数据。

## 支付宝、微信模拟充值

没有商户号也能体验充值流程。在钱包页中选择金额和“支付宝 / 微信”，创建演示订单，再模拟成功、失败或取消。页面会明确显示模拟状态，不会生成真实付款码或请求支付平台。

**演示余额独立存储，不能用于真实模型调用。** 成功订单只增加演示余额；真实账户额度、真实充值记录和支付合规确认都不变。订单十分钟后过期，重复确认不会重复入账，每个用户只能查看和操作自己的订单。每笔支持 ¥1–¥1,000。

该功能默认关闭，需要从当前源码构建（原版官方镜像不包含这项定制）。原生运行方式：

```bash
# 仓库根目录；需要 Bun、Go 和现有 Python 运行环境
./deploy/chenghuai/build-local.sh
python3 deploy/chenghuai/run-local.py stop
python3 deploy/chenghuai/run-local.py start --demo-payments
```

登录 `http://127.0.0.1:3080/wallet`。关闭演示时停止后执行普通的 `run-local.py start`；已有演示记录会保留，但真实钱包不使用这些数据。

Docker 用户在完成前面的初始化后，可在 `deploy/chenghuai` 执行：

```bash
docker compose -f compose.yml -f compose.demo.yml up -d --build --wait
```

恢复普通部署运行 `./start.sh`。`compose.demo.yml` 显式开启 `PAYMENT_DEMO_ENABLED=true`，普通部署不启用。将来真实收款仍需配置自己的支付商户和公网回调地址。

## 从源码构建镜像

默认使用固定版本的官方镜像，不需要在宿主机安装 Go 或 Bun。如需将当前源码构建成镜像，在仓库根目录执行：

```bash
cd ai-gateway
printf '%s\n' 'v1.0.0-rc.23' > VERSION
docker build -t chenghuai-new-api:v1.0.0-rc.23 .
```

在 `deploy/chenghuai/.env` 中设置：

```dotenv
NEW_API_IMAGE=chenghuai-new-api:v1.0.0-rc.23
```

随后再次执行 `./start.sh` 或 `./start.sh --https`。上游 Dockerfile 会编译前端并将其嵌入 Go 二进制；`VERSION` 同时用于前后端版本标识。修改代码后的网络服务需按仓库 AGPL-3.0 许可提供相应源码，并保留 `LICENSE`、`NOTICE`、`THIRD-PARTY-LICENSES.md`。

## 备份与恢复

本方案使用单实例 SQLite。要取得一致的数据库备份，先停止服务，再备份 `data/`、`.env` 和 HTTPS 模式下的 `caddy/`。例如本机模式：

```bash
docker compose -f compose.yml down
mkdir -p backups
umask 077
tar -czf "backups/gateway-$(date +%Y%m%d-%H%M%S).tar.gz" data .env
./start.sh
```

HTTPS 模式用两个 Compose 文件停止，并将存在的 `caddy/` 加入备份，最后执行 `./start.sh --https`。恢复时先停止目标实例，再将备份解压到本目录，保留原 `.env` 会话密钥后启动。备份包含账户、上游密钥等私有信息，不应提交到 Git。

## 文件

| 文件 | 用途 |
| --- | --- |
| `compose.yml` | 固定版本 New API、SQLite 持久化、本机端口、健康检查 |
| `compose.https.yml` / `Caddyfile` | 可选域名、TLS 和流式反向代理 |
| `.env.example` / `start.sh` | 环境变量模板及首次随机密钥生成 |
| `run-local.py` | 可选 Linux amd64 原生启动器，使用仓库根目录 `.local/` |
| `brand.json` / `bootstrap.py` | 品牌配置与初始化/重复同步 |
| `assets/` | 本地首页、关于页、Logo 和首页配图 |

默认镜像内含 `wget`，健康检查访问真实 `/api/status` 并检查 `success`。运行时不依赖本仓库以外的账号或参考站在线状态。

## 验证与截图

完整验证范围和限制见 [VERIFICATION.md](VERIFICATION.md)。在仓库根目录运行以下命令，可使用临时数据库和本地模拟上游验证鉴权、普通聊天、SSE 及用量日志，不消耗真实模型额度，也不修改正在运行的实例：

```bash
python3 deploy/chenghuai/verify-relay.py
```

浏览器验证需要 Python Playwright 和 Chromium，以及已初始化的本地站点：

```bash
python3 -m venv .local/browser-env
.local/browser-env/bin/pip install playwright
.local/browser-env/bin/python -m playwright install chromium
.local/browser-env/bin/python deploy/chenghuai/verify-ui.py
```

新部署可用 `--credentials /安全路径/credentials.json` 指定含 `username`、`password` 的凭据文件，并用 `--base-url` 指定自己的测试实例。请将凭据文件限制为仅本人可读。脚本验证代码切换、深浅主题、桌面和小屏布局、登录与管理页面；截图和 JSON 结果输出到 `.local/previews/`，不调用模型。实际公网证书、支付与上游服务需在配置后单独验证。
