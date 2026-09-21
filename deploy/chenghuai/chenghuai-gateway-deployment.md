# 骋怀 AI 模型网关部署与公网访问记录

记录日期：2026-09-21。根据本次远程服务器终端输出整理。本文补充 [阿里云部署复现手册](ALIYUN-REPRODUCE.md)，记录后续构建排障、初始化与公网端口配置的实际结果。

## 1. 环境与进度

| 项目 | 内容 |
| --- | --- |
| 云服务器 | 阿里云，杭州地域 |
| 系统 | Ubuntu 22.04.5 LTS |
| 项目目录 | `/opt/ai-gateway` |
| 部署目录 | `/opt/ai-gateway/deploy/chenghuai` |
| 镜像 | `chenghuai-new-api:demo` |
| Compose 服务 | `new-api` |
| 容器 | `chenghuai-gateway-new-api-1` |
| 实际采用的公网方案 | 公网 IPv4 + HTTP，直接发布 3000 端口 |

已完成：镜像构建、容器健康检查、管理员初始化、8 项品牌设置、公网端口绑定、UFW 放行 TCP 3000。

用户展示的安全组已允许所有 IPv4 来源访问 TCP 3000；需确认它属于实例实际绑定的安全组入方向规则。尚未收到外部浏览器访问成功的反馈。

本次使用 compose.demo.yml，启用了模拟充值功能，仅用于演示；真实收款服务不可使用此覆盖配置。

没有配置域名和 HTTPS。此前讨论的 Nginx 方案没有执行成功的记录，本次实际采用的是直接发布 3000 端口。

## 2. 复制命令注意事项

- 只复制代码框中的命令，不复制 `root@...#` 和 `>` 提示符。
- 默认在服务器终端执行；公网浏览器测试在自己的电脑上操作。
- 长命令中不要手动插入换行。
- 使用 heredoc 时，结束标记 `EOF` 或 `PY` 必须顶格、独占一行。本次因结束标记前有空格，Shell 一直等待输入，按 Ctrl+C 后取消执行。
- 本文优先采用短命令。已经完成的初始化无需重复执行。

## 3. 初次构建与配置

前提：项目代码、Docker、Docker Compose 已准备好，部署目录中已有 compose.yml、compose.demo.yml 和 bootstrap.py。代码获取与 Docker 安装不在本记录范围内。

进入部署目录：

```bash
cd /opt/ai-gateway/deploy/chenghuai
```

仅在 .env 不存在时创建配置，再构建启动：

```bash
(
  set -e
  umask 077
  if [ ! -f .env ]; then
    printf 'GATEWAY_PORT=3000\nSESSION_SECRET=' > .env
    python3 -c 'import secrets; print(secrets.token_hex(32))' >> .env
  fi
  export COMPOSE_FILE=compose.yml:compose.demo.yml
  docker compose up -d --build --wait --wait-timeout 180
)
```

不要公开 .env 中的 SESSION_SECRET。`--wait-timeout 180` 是等待服务就绪的超时，不是镜像构建总时长限制。

## 4. 排障：go mod download 卡住

### 检查结果

首次构建中，Go 依赖下载已耗时约 17 分钟；系统依赖安装曾耗时约 12 分钟。

| 检查地址 | 实际结果 |
| --- | --- |
| https://proxy.golang.org | 连接超时 |
| https://sum.golang.org | 连接超时 |
| https://github.com | HTTP 200 |
| https://goproxy.cn/golang.org/x/text/@v/list | HTTP 200，约 0.15 秒 |
| https://goproxy.cn/sumdb/sum.golang.org/supported | HTTP 200，约 0.08 秒 |

复查替代源的命令：

```bash
curl -I --connect-timeout 5 --max-time 20 https://goproxy.cn/golang.org/x/text/@v/list
curl -I --connect-timeout 5 --max-time 20 https://goproxy.cn/sumdb/sum.golang.org/supported
```

### 实际修复

在原构建终端按 Ctrl+C，然后备份 Dockerfile：

```bash
cd /opt/ai-gateway
cp -p Dockerfile "Dockerfile.bak.$(date +%s)"
grep -n -B 2 'go mod download' Dockerfile
```

**仅当尚未加入代理配置时，执行一次：**

```bash
sed -i '/^RUN go mod download/i ENV GOPROXY=https://goproxy.cn,direct' Dockerfile
```

确认修改：

```bash
grep -n -B 2 'go mod download' Dockerfile
```

应看到：

```dockerfile
ENV GOPROXY=https://goproxy.cn,direct
RUN go mod download
```

本次位于 Dockerfile 第 24、25 行。配置加在 Go 构建阶段，保留默认的 GOSUMDB 校验。仅在宿主机执行 export GOPROXY 不会自动传入 Docker 构建。

重新构建启动：

```bash
cd /opt/ai-gateway/deploy/chenghuai
export COMPOSE_FILE=compose.yml:compose.demo.yml
docker compose --progress plain up -d --build --wait --wait-timeout 180
```

CACHED 表示复用之前已完成的构建层。本次最终得到镜像 Built、容器 Healthy，构建问题解决。

## 5. 初始化管理员与站点

```bash
cd /opt/ai-gateway/deploy/chenghuai
python3 bootstrap.py --base-url http://127.0.0.1:3000 --username admin
```

输入新管理员密码，输入时不显示字符。密码自行保存，不贴到聊天或文档中。

本次第一次因密码不足 8 字节失败，第二次成功，确认：

- 创建本地管理员，完成初始设置。
- 应用 SystemName、Footer、Logo、HeaderNavModules、SidebarModulesAdmin、general_setting.quota_display_type、HomePageContent、About。
- 管理员界面语言设为简体中文。
- 验证 8 项品牌设置变更，保留现有业务数据。

若报错找不到 /root/bootstrap.py，说明执行目录错误，先切换到部署目录。初始化已成功后，无需重复运行。

## 6. 发布公网端口

初始映射为 `127.0.0.1:3000->3000/tcp`，仅本机访问。

进入部署目录：

```bash
cd /opt/ai-gateway/deploy/chenghuai
```

创建 compose.public.yml。此命令会覆盖同名文件，已有文件时先检查内容：

```bash
printf '%s\n' \
  'services:' \
  '  new-api:' \
  '    ports: !override' \
  '      - "0.0.0.0:3000:3000"' \
  > compose.public.yml
```

!override 替换原端口列表，本次服务器上的 Compose 已成功解析该配置。

按顺序加载三个配置文件：

```bash
export COMPOSE_FILE=compose.yml:compose.demo.yml:compose.public.yml
docker compose up -d --no-build --wait
docker compose ps
```

实际输出确认 healthy，且端口变为：

```text
0.0.0.0:3000->3000/tcp
```

此操作没有重新编译镜像。

## 7. 防火墙与安全组

### UFW

```bash
ufw status
ufw allow 3000/tcp
```

本次 UFW 已启用，添加规则成功。不需要关闭防火墙。访问来源限制应同时落实到云安全组，不应仅依赖 UFW 限制 Docker 发布端口。

### 阿里云安全组

控制台路径：ECS → 杭州地域 → 对应实例 → 绑定的安全组 → 入方向规则。

本次用户已展示下列规则，无需重复添加：

| 字段 | 值 |
| --- | --- |
| 授权策略 | 允许 |
| 优先级 | 100 |
| 协议 | 自定义 TCP，IPv4 |
| 访问来源 | 任何位置：0.0.0.0/0 |
| 访问目的端口 | 3000/3000 |

确认该规则属于实例实际绑定的安全组入方向规则。0.0.0.0/0 表示允许所有 IPv4 来源；仅自己测试时，可以改为自己电脑公网 IPv4 加 /32。

## 8. 验证访问

本机接口检查，仅打印状态码，避免 Logo 数据刷屏：

```bash
curl -sS --max-time 10 -o /dev/null -w 'HTTP=%{http_code}\n' http://127.0.0.1:3000/api/status
```

本次完整响应已确认包含 `"success":true`、`"setup":true`。长串 `data:image/png;base64,...` 是 Logo 图片，不是报错。

从阿里云实例详情复制公网 IPv4，在自己的电脑浏览器打开：

```text
http://服务器公网IP:3000
```

替换为实际公网 IP，保留 http:// 和 :3000。不要使用内网 IP 或 0.0.0.0。

本机检查成功不等于公网已通。打不开时记录具体报错：连接超时、连接被拒绝或拦截页面，并核对安全组绑定、公网 IP、端口。

当前 HTTP 不加密，先用于首页连通性测试；管理员密码、API 密钥等敏感数据应通过 HTTPS 或 SSH 隧道使用。

接口中的 server_address 当前仍为 http://localhost:3000。确定最终对外地址后，应同步检查站点地址设置，避免生成的客户端链接继续引用 localhost。

## 9. 日常管理与撤销公网发布

每次新开终端，先设置：

```bash
cd /opt/ai-gateway/deploy/chenghuai
export COMPOSE_FILE=compose.yml:compose.demo.yml:compose.public.yml
```

查看状态：

```bash
docker compose ps
```

查看最近日志：

```bash
docker compose logs --tail 50 new-api
```

重启现有服务：

```bash
docker compose restart new-api
```

应用配置变更，不重新构建：

```bash
docker compose up -d --no-build --wait
```

不要遗漏 compose.public.yml 后再执行 up，否则端口可能恢复为仅本机访问。COMPOSE_FILE 环境变量只作用于当前 Shell 及其子进程，新终端需要重新设置。

如需撤销直接公网发布，明确只加载原来的两个文件：

```bash
export COMPOSE_FILE=compose.yml:compose.demo.yml
docker compose up -d --no-build --wait
docker compose ps
```

确认恢复为 127.0.0.1:3000 映射，再删除阿里云安全组的 3000 入方向规则，并执行：

```bash
ufw delete allow 3000/tcp
```

## 10. SSH 操作补充

此前追加 SSH 公钥时因 EOF 前有空格而一直等待输入，两次按 Ctrl+C 取消。后来通过 printf 追加公钥，命令无报错；目录权限设置为 700，authorized_keys 权限为 600。

主机公钥指纹读取成功，但尚无通过新增密钥完成 SSH 登录的确认。本文不保存实际密钥内容或密码。SSH 公钥配置不是解决 Go 下载问题的必要步骤。

## 参考文档

- [Docker Compose 命令](https://docs.docker.com/reference/cli/docker/compose/)
- [Docker 端口发布](https://docs.docker.com/engine/network/port-publishing/)
- [Go 模块校验与代理](https://go.dev/ref/mod#authenticating)
- [阿里云安全组规则](https://www.alibabacloud.com/help/zh/ecs/user-guide/security-group-rules)
