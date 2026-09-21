# 阿里云 ECS 部署复现手册

适用项目：[bupt-ycq/ai-gateway](https://github.com/bupt-ycq/ai-gateway)。基于 QuantumNous/New API，包含定制页面及支付宝、微信模拟充值。本文整理于 2026-09-21，目标是从一台 Ubuntu 22.04 服务器重新部署，并能够维护和排查故障。

## 1. 本次环境与实际进度

| 项目 | 已知信息 |
| --- | --- |
| 操作系统 | Ubuntu 22.04.5 LTS，x86_64 |
| 资源 | 2 vCPU，约 8 GB 内存，40 GB 系统盘 |
| 安装时剩余空间 | 约 33 GB |
| Docker / Compose | 29.8.1 / v5.5.1 |
| 本次公网 IP | `8.149.237.46`，换服务器后必须替换 |
| 源码目录 | `/opt/ai-gateway` |
| 部署目录 | `/opt/ai-gateway/deploy/chenghuai` |
| 已确认下载的功能版本 | `038229fba46ca5901030bbdb5759c284e83b358c` |
| 登录途径 | 阿里云 Workbench 网页终端，root 用户 |

**已确认：** 网页终端登录正常、SSH 服务正常监听 22、Docker 和 Compose 已安装、私有仓库已成功下载。服务器的 UFW 已开启，用户提供的规则中尚无 3000 端口。

**尚未确认：** 云服务器上的镜像构建、初始化、容器健康状态和公网访问成功。最后一次从助手环境访问公网 3000 端口超时；不能据此断定只有 UFW 一个问题。HTTPS、真实上游调用和真实收款尚未配置。

助手环境直接 SSH 连接曾在身份认证前断开；部署公钥已核对一致，但未取得远程控制。本文以下步骤由操作者在 Workbench 中执行，不能把文档中的预期输出当成已完成结果。

本机开发环境的账号、数据库不会随着 GitHub 源码复制过来。新服务器需要自行初始化。模拟充值余额不能用于真实模型调用。

## 2. 命令复制约定

- 以下服务器命令默认以 root 执行；普通用户需要相应 sudo 权限。
- 只复制代码块，不复制 `root@...#`、`>` 等终端提示符。
- 多行命令末尾的 `\` 必须保留，后面不能加空格。
- 如果意外进入一直显示 `>` 的多行输入，按 `Ctrl+C` 取消，再重新复制。
- 一步报错后先处理报错，不要继续执行依赖它的后续步骤。
- 本文使用 `printf` 生成配置，避免 heredoc 的结束标记前带空格而无法结束。

## 3. 登录并检查环境

阿里云控制台 → ECS → 实例 → 远程连接 → Workbench。Linux 用户名按创建实例时的设置选择 root 或 ecs-user；密码为实例登录密码。

```bash
cat /etc/os-release
uname -m
nproc
free -h
df -h /
docker --version
docker compose version
```

本项目转发上游模型请求，不需要购买 GPU。2 核 8 GB 可作为试运行环境，不能据此保证 1000 人同时调用；上线容量需要结合真实请求长度、上游限额和压测判断。

### 没安装 Docker 时

已有 Docker 和 Compose 的服务器跳过本小节。以下针对全新 Ubuntu 22.04，使用 [Docker 官方安装方式](https://docs.docker.com/engine/install/ubuntu/)。不要在有业务的服务器上盲目卸载现有容器组件。

```bash
apt-get update
apt-get install -y ca-certificates curl git python3
install -m 0755 -d /etc/apt/keyrings
curl -fsSL --connect-timeout 15 --max-time 90 \
  https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
```

确认下载成功后添加软件源：

```bash
printf '%s\n' \
  'Types: deb' \
  'URIs: https://download.docker.com/linux/ubuntu' \
  'Suites: jammy' \
  'Components: stable' \
  "Architectures: $(dpkg --print-architecture)" \
  'Signed-By: /etc/apt/keyrings/docker.asc' \
  > /etc/apt/sources.list.d/docker.sources

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker --version
docker compose version
systemctl is-active docker
```

最后应显示版本号及 `active`。若软件源访问失败，检查 DNS、网络和已有源配置；不要关闭 TLS 校验。仅安装 Docker 成功，并不代表服务器可以拉取 Docker Hub 镜像或下载构建依赖。

## 4. 下载私有 GitHub 仓库

### 4.1 生成服务器专用下载密钥

```bash
apt-get update
apt-get install -y git python3 ca-certificates
mkdir -p /root/.ssh
chmod 700 /root/.ssh

if [ ! -f /root/.ssh/ai_gateway_github ]; then
  ssh-keygen -t ed25519 -N '' \
    -C 'ai-gateway-ecs-readonly' \
    -f /root/.ssh/ai_gateway_github
fi
cat /root/.ssh/ai_gateway_github.pub
```

打开 GitHub 仓库 → Settings → Deploy keys → Add deploy key。填写名称，粘贴 `.pub` 文件输出，**不勾选 Allow write access**。本次服务器的只读密钥已登记，新机器需生成自己的密钥并重新登记。

`ai_gateway_github` 是私钥，留在服务器；`ai_gateway_github.pub` 是公钥，可以登记到 GitHub。这个密钥用于服务器下载代码，与允许他人登录服务器的 `authorized_keys` 用途不同。

### 4.2 配置 GitHub 身份校验

下面的公钥取自 [GitHub 官方主机公钥文档](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)。若以后官方轮换密钥，应核对官方公告后更新，不能直接跳过身份校验。

```bash
printf '%s\n' \
  'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' \
  > /root/.ssh/ai_gateway_known_hosts

printf '%s\n' \
  'Host github.com' \
  '  User git' \
  '  IdentityFile /root/.ssh/ai_gateway_github' \
  '  IdentitiesOnly yes' \
  '  UserKnownHostsFile /root/.ssh/ai_gateway_known_hosts' \
  '  StrictHostKeyChecking yes' \
  '  ConnectTimeout 15' \
  > /root/.ssh/ai_gateway_config

export GIT_SSH_COMMAND='ssh -F /root/.ssh/ai_gateway_config'
git clone --depth 1 git@github.com:bupt-ycq/ai-gateway.git /opt/ai-gateway
git -C /opt/ai-gateway config core.sshCommand \
  'ssh -F /root/.ssh/ai_gateway_config'
git -C /opt/ai-gateway log -1 --oneline
```

最后的配置将下载密钥持久化到这个仓库的 Git 设置，之后重新打开终端也可拉取更新。已有 `/opt/ai-gateway` 时不要重复 clone，更不要删除现有目录；先检查其状态。默认下载 main 最新版本，本次功能基线是 `038229f`，之后的文档提交会让显示的提交号变化。

## 5. 构建并初始化定制版

普通 `./start.sh` 默认使用上游官方镜像；要包含本项目的模拟充值功能，使用本节的源码构建及 `compose.demo.yml`。不要在后续操作中漏掉这个文件。

```bash
cd /opt/ai-gateway/deploy/chenghuai
```

首次生成随机会话密钥，重复运行保留已有 `.env`。它不是管理员密码。

```bash
(
  set -e
  umask 077
  if [ ! -f .env ]; then
    printf 'GATEWAY_PORT=3000\nSESSION_SECRET=' > .env
    python3 -c 'import secrets; print(secrets.token_hex(32))' >> .env
  fi

  docker compose \
    -f compose.yml \
    -f compose.demo.yml \
    up -d --build --wait --wait-timeout 180
)
```

第一次会下载 Bun、Go、Debian 镜像及 npm/Go 依赖，并编译前后端。180 秒是等待服务健康的期限，不是整个构建的时间上限。构建报错时保存最后约 30 行，先判断是下载失败、内存不足还是编译错误。

构建上下文必须排除 `.env`、数据库、证书、备份和 `.local/`；当前仓库的 `.dockerignore` 已包含这些规则。Git 忽略规则不等于 Docker 构建忽略规则。

初始化必须在开放公网之前完成，避免别人先访问初始化页面创建管理员：

```bash
python3 bootstrap.py \
  --base-url http://127.0.0.1:3000 \
  --username admin
```

按提示输入自己设置的管理员密码，输入时不显示字符。成功时应出现 `Brand settings verified`。已有实例要输入它的现有管理员密码；该脚本不是密码重置工具。它配置首页、Logo、页脚等，不导入参考站的用户、余额或 API Key。

检查：

```bash
docker compose -f compose.yml -f compose.demo.yml ps
curl --max-time 10 -fsS http://127.0.0.1:3000/api/status
```

预期容器为 `healthy`，接口包含 `"success":true`。默认映射 `127.0.0.1:3000`，此时仅服务器本机可访问。

## 6. 可选：公网 IP 临时预览

有域名时可直接跳到第 7 节。HTTP 临时入口没有传输加密；只用于查看页面，管理登录和真实 API Key 应通过 HTTPS 或自己电脑的 SSH 隧道使用。首次本机初始化的首页示例可能仍指向 localhost，第 7 节会统一更新为正式域名。

### 6.1 阿里云安全组

ECS 实例 → 安全组 → 实际绑定的安全组 → 入方向 → 添加规则：

| 字段 | 值 |
| --- | --- |
| 授权策略 | 允许 |
| 优先级 | 100 |
| 协议 | 自定义 TCP |
| 来源 | `0.0.0.0/0`；仅自己预览时可收窄为自己的公网 IP/32 |
| 目的端口 | `3000` 或 `3000/3000`，按页面要求填写 |

UFW 已启用时添加对应规则，不要关闭整个防火墙：

```bash
ufw status
ufw allow 3000/tcp
```

注意：Docker 发布端口的流量可能绕过 UFW，不能仅凭 UFW 规则判断公网是否可达或已被限制。限制外部来源优先在阿里云安全组完成。参见 [Docker 防火墙说明](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations)。

### 6.2 改为对外监听

```bash
cd /opt/ai-gateway/deploy/chenghuai
printf '%s\n' \
  'services:' \
  '  new-api:' \
  '    ports: !override' \
  '      - "0.0.0.0:3000:3000"' \
  > compose.public.yml

docker compose \
  -f compose.yml \
  -f compose.demo.yml \
  -f compose.public.yml \
  up -d --no-build --wait
```

`!override` 需要 Compose 2.24.4 或更新版本，用于替换原端口映射，避免把两条映射叠加。本次 Compose v5.5.1 满足要求。[官方说明](https://docs.docker.com/reference/compose-file/merge/#replace-value)

在自己的电脑浏览器访问 `http://服务器公网IP:3000`，本次为 `http://8.149.237.46:3000`。不要把这里的服务器公网 IP 换成自己电脑上的 `127.0.0.1`。

## 7. 域名和 HTTPS（保留模拟充值）

准备自己拥有的域名。把子域名的 DNS A 记录指向服务器公网 IPv4，例如 `ai.example.com` → 服务器 IP；`example.com` 是示例，必须替换。没有配置可用 IPv6 时不要添加错误的 AAAA 记录。

中国内地服务器对外提供网站前需办理相应 ICP 备案，按云厂商流程完成。[阿里云说明](https://help.aliyun.com/zh/icp-filing/basic-icp-service/user-guide/icp-filing-server-access-information-check)

安全组放行 TCP 80、443，UFW 已启用时执行：

```bash
ufw allow 80/tcp
ufw allow 443/tcp
ss -lntp '( sport = :80 or sport = :443 )'
```

如果端口被已有网站、Nginx 或面板占用，先确认用途，选择复用已有反向代理或安排迁移，不要直接停止不明服务。当前 Caddy 配置要求占用宿主机 80/443。

在部署目录按提示输入自己的域名；命令只修改域名，保留会话密钥：

```bash
cd /opt/ai-gateway/deploy/chenghuai
read -r -p '输入域名，不含 https://：' GATEWAY_DOMAIN
export GATEWAY_DOMAIN
python3 -c '
import os
from pathlib import Path
p = Path(".env")
lines = p.read_text().splitlines()
lines = [x for x in lines if not x.startswith("GATEWAY_DOMAIN=")]
lines.append("GATEWAY_DOMAIN=" + os.environ["GATEWAY_DOMAIN"])
p.write_text("\n".join(lines) + "\n")
'
chmod 600 .env
```

先用原来的模式停止容器，以便更换网络配置。此操作不会删除挂载的数据库目录：

```bash
# 如果使用过公网 IP 预览，执行这一条：
docker compose \
  -f compose.yml -f compose.demo.yml -f compose.public.yml down
```

若没有使用过第 6 节，则使用下面这条停止命令，不要同时执行两条：

```bash
docker compose -f compose.yml -f compose.demo.yml down
```

然后切换到 HTTPS，**此处不加载 `compose.public.yml`**：

```bash
docker compose \
  -f compose.yml \
  -f compose.demo.yml \
  -f compose.https.yml \
  up -d --no-build --wait

docker compose \
  -f compose.yml -f compose.demo.yml -f compose.https.yml \
  logs --tail=60 caddy
```

Caddy 会申请和续期证书，需要 DNS 正确、外部能访问 80/443。容器启动成功不代表证书一定已签发，要继续验证 HTTPS。[Caddy 官方说明](https://caddyserver.com/docs/automatic-https)

在仍保留 `GATEWAY_DOMAIN` 变量的同一个终端执行；重新登录终端后需再次输入域名：

```bash
curl --max-time 15 -fsS "https://${GATEWAY_DOMAIN}/api/status"
python3 bootstrap.py \
  --base-url "https://${GATEWAY_DOMAIN}" \
  --site-url "https://${GATEWAY_DOMAIN}" \
  --username admin
```

输入现有管理员密码。此步骤更新网站地址和首页示例，然后用浏览器访问 `https://你的域名` 登录。若启用了管理员 2FA，需按脚本提示从已登录后台修改相关设置。

确认 HTTPS 可用后，删除安全组中临时的 3000 入方向规则，并删除 UFW 临时规则：

```bash
ufw delete allow 3000/tcp
```

HTTPS 模式会恢复应用的 localhost 端口映射，由 Caddy 提供公网入口。代理内部网段固定为 `172.30.89.0/24`；若冲突，按原部署 README 同步调整网段、静态 IP 和受信代理地址。

## 8. 维护时始终使用相同模式

重新打开终端后，在部署目录按实际运行模式选择下面一组数组定义，只选一组：

```bash
cd /opt/ai-gateway/deploy/chenghuai
# 本机模式
gateway_files=(-f compose.yml -f compose.demo.yml)
```

```bash
# 公网 IP 临时预览模式
gateway_files=(-f compose.yml -f compose.demo.yml -f compose.public.yml)
```

```bash
# HTTPS 模式
gateway_files=(-f compose.yml -f compose.demo.yml -f compose.https.yml)
```

后续命令使用这个 Bash 数组：

```bash
docker compose "${gateway_files[@]}" ps
docker compose "${gateway_files[@]}" logs --tail=100 new-api
docker compose "${gateway_files[@]}" restart new-api
```

`./start.sh` 不会自动带上 demo/public 文件。按本手册部署定制版后，使用上面的完整 Compose 文件组合维护，避免意外切回上游镜像或关闭模拟充值。

### 备份

当前使用单实例 SQLite。先在本节选好模式，再停止服务取得一致备份；会产生短暂停机：

```bash
(
  set -e
  umask 077
  mkdir -p backups
  docker compose "${gateway_files[@]}" stop
  backup_items=(data .env)
  if [ -d caddy ]; then backup_items+=(caddy); fi
  if [ -f compose.public.yml ]; then backup_items+=(compose.public.yml); fi
  tar -czf "backups/gateway-$(date +%Y%m%d-%H%M%S).tar.gz" \
    "${backup_items[@]}"
  docker compose "${gateway_files[@]}" up -d --no-build --wait
)
```

如果备份命令失败，处理错误并手动执行最后的启动命令恢复服务。将备份另存到服务器之外的私有存储，不能只留在同一块磁盘。备份包含账号和上游密钥，不能提交到 GitHub。

恢复时先保存目标实例自己的备份，在空的部署数据目录中还原上述文件，设置 `.env` 权限为 600，再以备份对应的代码/镜像版本及 Compose 模式启动。不要把旧备份直接覆盖到正在运行的数据库上。

### 更新

先备份，记录当前提交号和镜像 ID；需要精确回滚时也保留旧镜像导出文件。数据库迁移后不能只回退二进制，需评估是否一并恢复匹配的数据备份。

```bash
git -C /opt/ai-gateway rev-parse HEAD
docker image inspect chenghuai-new-api:demo --format '{{.Id}}'
git -C /opt/ai-gateway pull --ff-only
docker compose "${gateway_files[@]}" build new-api
docker compose "${gateway_files[@]}" up -d --no-build --wait
```

如要原样复用已验证的镜像而不重新解析外部依赖，可私下保存镜像归档；镜像不是数据库备份：

```bash
docker save -o backups/ai-gateway-image.tar chenghuai-new-api:demo
# 新服务器安装 Docker 后，可用以下命令导入：
# docker load -i backups/ai-gateway-image.tar
```

## 9. 常见问题

| 现象 | 判断和处理 |
| --- | --- |
| 终端一直显示 `>` | 引号未闭合或 heredoc 未结束；按 Ctrl+C，重新复制完整代码块 |
| `option requires an argument -- o` | 把 SSH 长命令中的 `-o` 和参数拆进了引号内的不同命令行；使用第 4 节的独立 SSH 配置 |
| `Permission denied (publickey)` | 检查 GitHub Deploy key、公钥对应私钥和 `core.sshCommand`；不要发送私钥 |
| `/opt/ai-gateway` 不存在 | clone 未成功，先解决下载问题 |
| SSH `Connection reset by peer` | 可能在认证前被服务器或中间网络中断，不能直接判断为密码或公钥错误；保留 Workbench 登录途径 |
| Docker 拉取或构建依赖超时 | 记录失败的域名和构建步骤，检查网络、DNS或可信镜像服务；不要使用来历不明的替代镜像 |
| `SESSION_SECRET` 缺失 | 检查部署目录 `.env` 是否生成；不要公开文件内容或随意更换已使用的密钥 |
| 没有模拟充值入口 | 检查是否使用源码构建的 `chenghuai-new-api:demo`，并加载 `compose.demo.yml` |
| 本机 API 也失败 | 先看容器状态和应用日志；安全组不能解决容器未启动问题 |
| 本机 API 成功，外部超时 | 检查实际绑定安全组、端口映射、主机网络和公网 IP；UFW 只是其中一环 |
| 80/443 被占用 | 用 `ss` 确认已有服务，协调反向代理入口，不要直接杀进程 |
| HTTPS 证书失败 | 查看 Caddy 日志，检查 A/AAAA 记录及 80/443 公网连通性 |
| 模型调用失败或额度不足 | 检查自己的上游渠道、模型名、上游额度和站内额度，模拟余额不参与实际计费 |

公网预览诊断命令：

```bash
cd /opt/ai-gateway/deploy/chenghuai
docker compose \
  -f compose.yml -f compose.demo.yml -f compose.public.yml ps
curl --max-time 10 -fsS http://127.0.0.1:3000/api/status
ufw status
```

预期看到容器 `healthy`、`0.0.0.0:3000->3000/tcp`，以及包含 `"success":true` 的 JSON；再从自己电脑测试公网地址。

## 10. 部署完成的验收标准

- 容器健康，重新启动后用户和订单仍存在。
- HTTPS 证书正常，首页、登录页、钱包页能打开。
- 支付宝和微信模拟成功/失败/取消符合预期，演示余额与真实余额分离。
- 配置自己的上游后，使用自己签发的客户端令牌完成一次非流式与流式调用，并核对用量记录；这会消耗上游额度。
- 已有可恢复的私有备份，且保存了代码版本和镜像信息。

真实收款需要另行配置支付商户和回调地址。公网运行修改后的 New API 应遵循仓库 AGPL-3.0 许可，保留 QuantumNous/New API 及相关许可声明，并按许可要求提供对应源码。
