# fp-multiuser 动态用户管理 API

本工具为 FRP 的多用户认证插件 `fp-multiuser` 提供了一个基于 REST API 的管理接口。您可以通过 HTTP 请求动态地添加、删除用户，工具会自动更新 `tokens` 文件并重启插件进程，**整个过程不会影响已建立的 FRP 隧道连接**。

## 功能特点

- ✅ **零停机管理**：添加或删除用户后自动重启插件，不影响已有客户端连接。
- ✅ **简洁 REST API**：支持用户列表查询、新增用户、删除用户。
- ✅ **可选文件监控**：支持监控 `tokens` 文件的外部修改并自动重启插件。
- ✅ **日志输出**：记录插件子进程的输出和 API 请求。

## 环境要求

- Python 3.6 或更高版本
- `fp-multiuser` 二进制文件（[下载地址](https://github.com/gofrp/fp-multiuser/releases)）
- FRP 服务端版本 ≥ v0.31.0

### 安装 Python 依赖

```bash
pip install flask watchdog   # watchdog 可选，用于文件监控
```

## 配置

通过环境变量进行配置（也可直接修改脚本中的默认值）：

| 环境变量 | 说明 | 默认值 |
| -------- | ---- | ------ |
| `FP_MULTIUSER_BIN` | fp-multiuser 二进制文件路径 | `./fp-multiuser` |
| `PLUGIN_LISTEN` | 插件监听的地址和端口 | `127.0.0.1:7200` |
| `TOKENS_FILE` | 用户凭证文件路径 | `./tokens` |
| `API_HOST` | API 服务监听地址 | `127.0.0.1` |
| `API_PORT` | API 服务端口 | `8080` |
| `WATCH_TOKENS_FILE` | 是否监控 tokens 文件变化（true/false） | `true` |

### 启动管理脚本

```bash
# 设置环境变量（可选）
export FP_MULTIUSER_BIN=/usr/local/bin/fp-multiuser
export TOKENS_FILE=/etc/frp/tokens
export API_HOST=0.0.0.0
export API_PORT=8080

# 启动
python fp_manager.py
```

建议使用 systemd 或 supervisor 将脚本托管为后台服务。

## API 接口说明

所有接口的 Base URL 为 `http://<API_HOST>:<API_PORT>`。

### 1. 获取所有用户列表

**`GET /users`**

返回所有已注册的用户名（不包含 token）。

#### 响应示例

```json
{
  "users": ["alice", "bob", "carol"]
}
```

#### curl 示例

```bash
curl http://127.0.0.1:8080/users
```

### 2. 添加新用户

**`POST /users`**

添加一个用户，如果用户名已存在则更新其 token。

#### 请求体（JSON）

| 参数 | 类型 | 必填 | 描述 |
| ---- | ---- | ---- | ---- |
| `username` | string | 是 | 用户名 |
| `token`   | string | 是 | 认证凭证 |

#### 响应示例

```json
{
  "status": "ok",
  "user": "alice"
}
```

#### curl 示例

```bash
curl -X POST http://127.0.0.1:8080/users \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "token": "mySecret123"}'
```

### 3. 删除用户

**`DELETE /users/{username}`**

删除指定的用户。

#### 请求参数

路径参数 `username` 为要删除的用户名。

#### 响应示例

成功时：
```json
{
  "status": "ok",
  "user": "alice"
}
```

用户不存在时（HTTP 404）：
```json
{
  "error": "user not found"
}
```

#### curl 示例

```bash
curl -X DELETE http://127.0.0.1:8080/users/alice
```

## 工作原理

1. 管理脚本启动后，会以子进程方式运行 `fp-multiuser` 插件。
2. 当通过 API 添加/删除用户时：
   - 修改 `tokens` 文件。
   - 终止当前的插件进程（不影响 frps 和已建立连接）。
   - 重新启动插件进程，加载新的 `tokens` 文件。
3. 新客户端使用新凭证连接时，插件会正确验证并允许登录。

## 注意事项

- **插件重启期间（约 1-2 秒）**：新客户端的登录请求可能会失败（连接拒绝或超时），客户端内置的重试机制会自动处理，对业务影响极小。
- **已连接的隧道不会中断**：`fp-multiuser` 只负责登录鉴权，隧道建立后数据流不经过插件，因此插件重启不会影响现有连接。
- **frps 无需重启**：整个管理过程只重启认证插件，`frps` 进程保持运行。
- **安全性**：建议将 API 服务监听在 `127.0.0.1` 或通过反向代理增加认证，避免未授权访问。

## 常见问题

### Q: 添加用户后客户端仍然连接失败？

检查 `frpc` 配置中的 `user` 和 `metadatas.token` 是否与添加的用户名、token 完全一致。注意 `metadatas.token` 在 TOML 配置中的写法。

### Q: 如何验证插件是否正常运行？

查看管理脚本的日志输出，会包含 `[fp-multiuser]` 开头的插件标准输出。也可以查看 `frps` 日志，观察登录认证是否成功。

### Q: 可以手动编辑 tokens 文件吗？

可以。如果启用了文件监控（`WATCH_TOKENS_FILE=true`），脚本会自动检测文件变化并重启插件。也可以手动调用 API 进行管理。

### Q: 如何停止管理脚本？

按 `Ctrl+C` 即可停止，脚本会先终止插件子进程再退出。