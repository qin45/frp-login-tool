# FRP Login Tool

[**README**](README.md) | **中文文档**

FRP 内网穿透多用户登录管理工具，包含 GUI 客户端和 CLI 服务端。

## 架构

- **服务端** (`server/main.py`): 基于 CLI 的服务端，使用 MySQL 存储数据、SMTP 邮箱验证、fp-multiuser 认证集成管理 FRP 隧道。
- **客户端** (`client/client.py`): 桌面 GUI（tkinter），用户可注册、登录和管理隧道。

## 功能特点

- **用户注册与登录**：通过邮箱 + SMTP 验证码注册
- **自动分配用户 ID**：格式 `user0001`、`user0002` ...
- **隧道管理**：每用户最多创建 10 条隧道
- **自动端口分配**：每条隧道从 20000-21000 分配固定端口
- **到期控制**：管理员可设置用户到期时间，到期后自动禁用
- **激活码**：管理员可生成带时长的激活码，用户输入后延长到期时间
- **fp-multiuser 集成**：通过 REST API 自动生成和清理令牌
- **HTTPS 通信**：服务端与客户端之间使用 HTTPS 协议
- **子进程管理**：服务端管理 `frps` 和 `fp-multiuser.py`；客户端管理 `frpc.exe`

## 前置要求

- Python 3.6+
- MySQL 数据库
- SMTP 邮箱账号（用于发送验证码）
- FRP 二进制文件（已包含）：
  - 服务端：`server/frps/frps`、`server/frps/fp-multiuser`
  - 客户端：`client/frpc/frpc.exe`

## 快速开始

### 服务端配置

1. 安装服务端依赖：
   ```bash
   cd server
   pip install -r requirements.txt
   ```

2. 运行初始配置：
   ```bash
   python main.py setup
   ```
   按照提示配置 SMTP、FTPS、MySQL 和 HTTPS 设置。

3. 启动服务端：
   ```bash
   python main.py start
   ```
   将启动 HTTPS API 服务、fp-multiuser.py 和 frps 子进程。

### 客户端配置

1. 安装客户端依赖：
   ```bash
   cd client
   pip install -r requirements.txt
   ```

2. 启动 GUI：
   ```bash
   python client.py
   ```

3. 输入服务器 URL（如 `https://your-server:8443`），点击 **连接**。

4. 注册新账号或使用已有账号登录。

## 服务端 CLI 命令

| 命令 | 说明 |
|---------|-------------|
| `python main.py setup` | 初始配置 |
| `python main.py start` | 启动服务端 |
| `python main.py set-expiry <user_id> <YYYY-MM-DD HH:MM>` | 设置用户到期时间 |
| `python main.py list-users` | 列出所有注册用户 |
| `python main.py add-code <code> <DD-HH-MM>` | 添加激活码 |
| `python main.py list-codes` | 列出所有激活码 |

### 设置用户到期时间

```bash
python main.py set-expiry user0001 "2026-12-31 23:59"
```

设置到期时间后会自动通过 fp-multiuser API 为该用户生成令牌。

### 管理激活码

添加一个时长为 30 天的激活码：

```bash
python main.py add-code MYCODE30 30-00-00
```

列出所有激活码：

```bash
python main.py list-codes
```

用户在客户端主面板点击 **激活** 按钮，输入激活码即可延长到期时间。若账户已到期，则从当前时间加上激活时长；若未到期，则在原到期时间上累加。

## 管理 API

服务端提供独立的 HTTP 管理 API，用于自动化管理。可在 `config.json` 或 `python main.py setup` 中配置：

```json
{
  "management_api": {
    "enabled": true,
    "port": 8444,
    "api_key": "your-secret-key",
    "allowed_ips": ["127.0.0.1"]
  }
}
```

所有请求需携带配置的 `api_key` — POST/PUT 在 JSON 体中传入 `key`，GET/DELETE 以查询参数 `?key=...` 传递。如配置了 `allowed_ips`，其他 IP 的请求将被拒绝（`403 Forbidden`）。

### 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/management/user` | 创建用户 |
| PUT | `/api/management/user/<user_id>` | 修改用户 |
| DELETE | `/api/management/user/<user_id>` | 删除用户 |
| GET | `/api/management/users` | 获取所有用户 |
| POST | `/api/management/tunnel` | 创建隧道 |
| PUT | `/api/management/tunnel/<id>` | 修改隧道 |
| DELETE | `/api/management/tunnel/<id>` | 删除隧道 |
| GET | `/api/management/tunnels` | 获取所有隧道 |
| POST | `/api/management/code` | 创建激活码 |
| PUT | `/api/management/code/<id>` | 修改激活码 |
| DELETE | `/api/management/code/<id>` | 删除激活码 |
| GET | `/api/management/codes` | 获取所有激活码 |

### 请求体参考

#### 用户管理

**POST `/api/management/user`** — 创建用户

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `key` | string | **是** | API 密钥 |
| `email` | string | **是** | 用户邮箱 |
| `password` | string | **是** | 用户密码 |
| `user_id` | string | 否 | 自定义 ID（不传则自动生成） |
| `expires_at` | string | 否 | `YYYY-MM-DD HH:MM`（默认为已到期） |

**PUT `/api/management/user/<user_id>`** — 修改用户

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `key` | string | **是** | API 密钥 |
| `email` | string | 否 | 新邮箱 |
| `password` | string | 否 | 新密码 |
| `new_user_id` | string | 否 | 修改用户 ID |
| `expires_at` | string | 否 | `YYYY-MM-DD HH:MM` |

**DELETE `/api/management/user/<user_id>`** — 删除用户（需 `?key=...`）

**GET `/api/management/users`** — 获取所有用户（需 `?key=...`）

#### 隧道管理

**POST `/api/management/tunnel`** — 创建隧道

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `key` | string | **是** | API 密钥 |
| `user_id` | string | **是** | 所属用户 ID |
| `name` | string | **是** | 隧道名称 |
| `type` | string | 否 | `tcp`（默认）或 `udp` |
| `local_ip` | string | 否 | 默认 `127.0.0.1` |
| `local_port` | int | **是** | 本地端口 |
| `remote_port` | int | 否 | 远程端口（不传则自动分配） |

**PUT `/api/management/tunnel/<id>`** — 修改隧道（所有字段可选）

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | API 密钥 |
| `name` | string | 新名称 |
| `type` | string | `tcp` 或 `udp` |
| `local_ip` | string | 本地 IP |
| `local_port` | int | 本地端口 |
| `remote_port` | int | 远程端口 |
| `user_id` | string | 变更所属用户 |

#### 激活码管理

**POST `/api/management/code`** — 创建激活码

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `key` | string | **是** | API 密钥 |
| `code` | string | **是** | 激活码内容 |
| `duration` | string | **是** | `DD-HH-MM` 格式 |

**PUT `/api/management/code/<id>`** — 修改激活码

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | API 密钥 |
| `code` | string | 新激活码内容 |
| `duration` | string | `DD-HH-MM` 格式 |

已使用的激活码不可修改。

### 示例

**创建用户（密钥在请求体中）**
```bash
curl -X POST http://localhost:8444/api/management/user \
  -H "Content-Type: application/json" \
  -d '{"key":"your-secret-key","email":"user@example.com","password":"secret123","user_id":"custom001","expires_at":"2027-12-31 23:59"}'
```

**获取用户列表（密钥作为查询参数）**
```bash
curl "http://localhost:8444/api/management/users?key=your-secret-key"
```

**删除隧道（密钥作为查询参数）**
```bash
curl -X DELETE "http://localhost:8444/api/management/tunnel/1?key=your-secret-key"
```

## 工作原理

1. **注册流程**：用户输入邮箱 → 服务端通过 SMTP 发送验证码 → 用户验证 → 账号创建成功，自动生成用户 ID。
2. **登录流程**：用户通过邮箱/密码登录 → 获得会话令牌 → 查看账户状态和隧道列表。
3. **隧道创建**：用户创建隧道 → 服务端从 20000-21000 分配端口 → 隧道信息存入 MySQL。
4. **启用隧道**：用户启用隧道 → 服务端向 fp-multiuser 请求令牌 → 客户端更新 `frpc.ini` → 客户端启动 `frpc.exe` 子进程。
5. **禁用隧道**：用户禁用隧道 → 客户端向 `frpc.exe` 发送 SIGINT 信号 → 服务端标记隧道为禁用状态。
6. **到期检查**：服务端每分钟检查到期用户 → 通过 fp-multiuser API 删除其令牌。

## 安全

- 所有客户端-服务端通信使用 HTTPS
- 密码使用 SHA-256 哈希存储
- 会话令牌 24 小时过期
- fp-multiuser API 默认绑定本地地址

## 许可证

MIT