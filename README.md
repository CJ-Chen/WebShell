# WebShell SSH 中转工作台

WebShell 是一个无 Docker 的浏览器 SSH/SFTP 中转面板。面板负责 Web 认证、目标地址授权、SSH 凭据加密、主机指纹校验、终端转发和文件管理；计算任务与文件始终位于用户自己的目标服务器。

## 技术结构

- FastAPI、AsyncSSH、SQLAlchemy、SQLite
- React、Ant Design、xterm.js
- Pixi 统一管理 Python 3.12、Node 22、依赖和项目任务
- Nginx 提供唯一的 HTTPS 入口

完整架构、数据流、接口和安全边界说明见 [项目概况与实现原理](docs/PROJECT_OVERVIEW.md)。

## 本地启动

```bash
pixi install
pixi run frontend-install
cp .env.example .env
pixi run init-key
pixi run migrate
pixi run create-admin --username admin --email admin@example.com
```

分别启动后端和前端：

```bash
pixi run backend
pixi run frontend
```

浏览器访问 `http://localhost:5173`。后端 API 和 OpenAPI 文档位于 `http://localhost:8000/docs`。

`create-admin` 未指定 `--password` 时会输出一次性临时密码。首次登录后必须修改密码。
Web 密码只要求至少 6 个字符，不做字符类型或复杂度限制。

## 常用 Pixi 任务

```bash
pixi run test-backend
pixi run check-backend
pixi run frontend-build
pixi run migrate
pixi run set-password --username admin --password '<new-password>'
```

默认不要求配置目标网段，用户可以直接填写可由面板访问的 SSH 地址。回环、链路本地、组播和系统保留地址仍会被拒绝。需要白名单控制时，将 `WEBSHELL_ENFORCE_DESTINATION_RULES` 设为 `true`，并在管理后台配置 CIDR/域名和端口规则。

## 目标机要求

- 面板服务器能访问目标机 SSH 端口。
- 目标机启用 SSH 和 SFTP。
- 用户提供自己在目标机上的 Linux 用户名与密码，默认使用 SSH 密码认证；也可切换为私钥认证。
- 安装 `tmux` 时终端可在网页断开后继续运行；未安装时自动降级为普通 PTY。
- 新建 tmux pane 和浏览器终端默认保留 50000 行历史，可通过 `WEBSHELL_TMUX_HISTORY_LIMIT` 调整远端 tmux 上限。
- 终端支持左键拖选后自动复制、右键单击粘贴；滚轮事件会合并后驱动 tmux copy-mode，向下滚到最新输出时自动返回实时终端。

## 生产部署

1. 将项目放置到 `/opt/webshell`，安装 Pixi 并执行 `pixi install --frozen`、`pixi run frontend-build`。
2. 创建不可登录的 `webshell` 系统用户，以及 `/var/lib/webshell`、`/etc/webshell`。
3. 从 `deploy/webshell.env.example` 创建 `/etc/webshell/webshell.env`，设置真实域名并限制文件权限。
4. 以 root 执行 `pixi run init-key --path /etc/webshell/credentials.key`，再将密钥设为 `webshell` 用户只读的 `0600` 文件。
5. 加载生产环境变量后执行 `pixi run migrate` 和 `pixi run create-admin ...`。
6. 安装 `deploy/webshell.service` 与 `deploy/nginx.conf`，替换域名和 TLS 证书路径。
7. 启动并启用 systemd 服务，只向公网开放 HTTPS 443。

凭据主密钥位于 `WEBSHELL_CREDENTIAL_KEY_PATH`。数据库备份和主密钥备份必须分开保存；主密钥丢失后，已保存的 SSH 凭据无法恢复。

## 安全边界

- 面板不创建或管理目标服务器上的 Linux 用户。
- 面板不提供任意 TCP 隧道、SSH 端口转发或远端软件自动安装。
- 首次连接必须确认 SSH 主机指纹，后续指纹变化会阻止连接。
- 私钥和可选保存的密码使用 AES-256-GCM 加密；管理员 API 不返回凭据明文。
- 文件管理使用远端账号自身的 SFTP 权限，可访问范围与该 Linux 账号一致。
