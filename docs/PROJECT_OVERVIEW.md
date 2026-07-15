# WebShell 项目概况与实现原理

## 1. 项目定位

WebShell 是一个无 Docker 的浏览器 SSH/SFTP 中转工作台。面板服务器不承载计算任务，也不在本机为平台用户创建 Linux 账号；它负责 Web 登录、目标服务器配置、SSH 凭据保护、终端和文件流转发以及管理审计。

用户实际执行的命令、tmux 会话和工作文件均位于用户指定的远端 Linux 服务器。

```text
Browser
   |
   | HTTP/WebSocket 443 or development port 5173
   v
Nginx / Vite
   |
   v
FastAPI relay service
   |
   | SSH PTY / SFTP
   v
Remote Linux server
```

## 2. 当前实现范围

- 管理员创建、停用、归档、删除和重置 Web 用户。
- Web 密码使用 Argon2id，仅要求至少 6 个字符。
- 用户维护多台 SSH 目标机，支持用户名密码和私钥认证。
- 首次连接展示并确认 SSH 主机指纹，指纹变化时阻止连接。
- xterm.js 浏览器终端、WebSocket 双向传输和实时 resize。
- 远端 tmux 会话保持；缺少 tmux 时降级为普通 SSH PTY。
- tmux 和 xterm 默认保留 50000 行历史，tmux mouse/copy-mode 支持滚轮浏览。
- SFTP 文件浏览、上传、下载、目录创建、移动、重命名、删除和预览。
- 管理后台用户管理、可选地址规则和审计日志。
- SQLite、Alembic 迁移、Nginx 和 systemd 部署模板。
- Pixi 统一管理 Python、Node、依赖、测试、构建和运维命令。

## 3. 核心工作原理

### 3.1 Web 认证

FastAPI 从 SQLite 查询 Web 用户并使用 Argon2id 校验密码。登录成功后生成随机 Session Token 和 CSRF Token：

- 浏览器只通过 `HttpOnly`、`SameSite=Strict` Cookie 保存 Session Token。
- 数据库只保存 Session Token 的 SHA-256 哈希。
- 写操作同时校验 Cookie、CSRF Header 和请求 Origin。
- 停用用户、重置密码或管理员修改密码时撤销已有会话。

Web 账号只用于面板登录，与远端服务器的 Linux 账号相互独立。

### 3.2 SSH 连接和凭据

目标机配置保存主机、端口、Linux 用户名、认证方式和已确认的主机指纹。密码默认只缓存在当前后端进程中，也可以由用户选择加密保存；私钥默认加密保存。

持久化凭据使用 AES-256-GCM 加密，主密钥独立存放在 `WEBSHELL_CREDENTIAL_KEY_PATH`。数据库泄露但主密钥未泄露时，攻击者不能直接恢复 SSH 凭据。

连接流程：

1. 解析目标 IP 或域名并固定本次连接地址，降低 DNS rebinding 风险。
2. 默认允许可达目标地址，但拒绝回环、链路本地、组播和系统保留地址。
3. 使用 AsyncSSH 建立密码或私钥认证连接。
4. 读取远端 SSH 主机密钥；首次要求用户确认，后续严格比较。
5. 指纹确认后才允许创建终端或执行 SFTP 操作。

需要严格网段白名单时，可启用 `WEBSHELL_ENFORCE_DESTINATION_RULES`。

### 3.3 Web Terminal

终端数据流如下：

```text
xterm.js <-> WebSocket <-> FastAPI <-> AsyncSSH PTY <-> tmux/shell
```

- 前端 FitAddon 计算实际终端列数和行数。
- WebSocket 握手携带初始 `cols/rows`，避免固定 PTY 宽度导致换行错位。
- 容器尺寸变化时，前端发送 resize 消息，后端调用 SSH PTY resize。
- 远端存在 tmux 时，平台创建随机内部会话名并 attach。
- 断开浏览器只会关闭 SSH attach，tmux 内任务继续运行。
- 新建 tmux pane 前设置 `history-limit=50000`，每次连接设置 `mouse on`。
- 滚轮进入 tmux copy-mode；按 `q` 或 `Esc` 返回实时输出。
- 桌面和移动布局只渲染一个 Terminal 组件，避免重复 WebSocket。

### 3.4 文件管理

文件操作通过 AsyncSSH SFTP 完成，面板不把远端文件持久化到本地：

- 浏览从远端用户 Home 开始，并允许访问该 SSH 账号有权限访问的路径。
- 上传按块读取并写入同目录临时文件，完成后原子重命名。
- 下载使用流式响应和 HTTP Range，不在内存中完整缓存文件。
- 文本和常见图片在大小限制内可在线预览。
- 删除非空目录需要递归参数和前端二次确认。
- 最终权限由远端 Linux 用户及文件系统权限决定。

### 3.5 管理与审计

管理员可以管理 Web 用户，但不能通过 API 查看 SSH 密码或私钥明文。系统记录登录、账号变更、目标机操作、终端创建删除及高风险文件操作，不记录终端输出和文件内容。

用户归档和永久删除只影响面板账号、目标机配置及加密凭据，不会删除远端 Linux 账号或远端文件。

## 4. 代码结构

```text
backend/app/
  routers/       REST 与 WebSocket 接口
  services/      SSH、地址解析、加密、审计和终端连接管理
  models.py      SQLAlchemy 数据模型
  schemas.py     API 输入输出模型
  security.py    密码与 Session 工具

frontend/src/
  App.tsx        登录、工作区、目标机和管理后台
  api.ts         REST/WebSocket 客户端
  styles.css     响应式工作台样式

backend/alembic/ 数据库迁移
deploy/          Nginx、systemd 和生产环境模板
```

## 5. 数据模型

- `users`：Web 用户、角色、状态和密码哈希。
- `web_sessions`：Session 哈希、CSRF、有效期和客户端信息。
- `target_hosts`：SSH 目标配置和主机指纹。
- `encrypted_credentials`：AES-GCM 加密后的密码或私钥。
- `terminal_sessions`：终端名称、目标机和远端 tmux 会话名。
- `destination_rules`：可选 CIDR/域名及端口规则。
- `audit_logs`：管理和安全相关事件。

## 6. 主要接口

- `/api/v1/auth/*`：登录、退出、当前用户和修改密码。
- `/api/v1/targets/*`：目标机、凭据解锁、连接测试和指纹确认。
- `/api/v1/terminals/*`：终端列表、创建、重命名和删除。
- `/api/v1/terminals/ws/{id}`：终端 WebSocket。
- `/api/v1/files/*`：SFTP 文件操作。
- `/api/v1/admin/*`：用户、地址规则和审计日志。
- `/health/live`、`/health/ready`：进程和依赖健康检查。

## 7. 部署模型

开发环境由 Vite 监听 `5173`，将 `/api` 和 WebSocket 代理到 FastAPI `8000`。生产环境由 Nginx 提供静态前端、HTTPS 和反向代理，FastAPI 只监听本机地址。

Pixi 锁定 Python 3.12、Node 22 和全部 Python 依赖；npm lockfile 锁定前端依赖。生产环境使用 systemd 运行 FastAPI，并通过 Nginx 仅暴露 HTTPS 入口。

## 8. 当前限制

- 当前面向单台面板服务器，数据库使用 SQLite。
- 尚未实现多实例 Session/临时凭据共享；临时 SSH 密码在后端重启后需要重新输入。
- 尚未实现断点续传、任务调度、Slurm、LDAP 和远端 Agent。
- tmux `history-limit` 对新 pane 生效；旧 pane 不能在不重启任务的情况下扩大原始历史容量。
- 面板只能连接其网络能够访问且启用 SSH/SFTP 的目标服务器。

## 9. 验证状态

- 后端自动化测试：13 项通过。
- 前端 TypeScript 生产构建通过。
- 前端 ESLint 通过。
- 已在局域网环境验证密码 SSH、主机指纹、SFTP 浏览/下载、tmux 终端和 WebSocket resize。
