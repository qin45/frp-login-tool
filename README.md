# FRP Login Tool

**README** | [**中文文档**](README_zh.md)

A multi-user FRP (Fast Reverse Proxy) intranet penetration management tool with a GUI client and CLI server.

## Architecture

- **Server** (`server/main.py`): CLI-based server managing FRP tunnels with MySQL storage, SMTP email verification, fp-multiuser authentication integration, and an optional web admin panel.
- **Web Admin** (`server/web/web.py`): Flask-based browser admin interface for managing users, tunnels, activation codes, and system settings over HTTPS.
- **Client** (`client/client.py`): Desktop GUI (tkinter) for users to register, login, and manage tunnels.

## Features

- **User Registration & Login** via email with SMTP verification code
- **Token-based Authentication**: two-step login (request password → get persistent token → exchange for session token); persistent tokens can be stored for auto-login
- **bcrypt Password Hashing**: all passwords hashed with bcrypt; legacy SHA256 hashes migrated on password reset
- **Automatic User ID** assignment (`user0001`, `user0002`, ...)
- **Tunnel Management**: each user can create up to 10 tunnels
- **Automatic Port Allocation**: each tunnel gets a fixed port from a configurable range (default 20000-21000)
- **Expiration Control**: admin sets expiration per user; expired users lose access
- **Activation Codes**: admin generates codes with custom durations to extend user expiration
- **fp-multiuser Integration**: automatic token generation and cleanup via REST API
- **HTTPS Communication** between client and server
- **Web Admin Panel**: browser-based management with admin login, user/tunnel/code CRUD, batch operations, config editor, and admin password management
- **Auto-SSL**: automatic self-signed CA and server certificate generation for the web admin panel, with CA root certificate download
- **Subprocess Management**: server manages `frps` and `fp-multiuser.py`; client manages `frpc.exe`

## Prerequisites

- Python 3.6+
- MySQL database
- SMTP email account (for sending verification codes)
- FRP binaries (included):
  - Server: `server/frps/frps`, `server/frps/fp-multiuser`
  - Client: `client/frpc/frpc.exe`

## Quick Start

### Server Setup

1. Install server dependencies:
   ```bash
   cd server
   pip install -r requirements.txt
   ```

2. Run initial configuration:
   ```bash
   python main.py setup
   ```
   Follow the prompts to configure SMTP, FTPS (including tunnel port range), MySQL, and HTTPS settings.

3. Start the server:
   ```bash
   python main.py start            # Starts API server, frps, fp-multiuser
   python main.py start --web on   # Also starts the web admin panel
   ```
   This starts the HTTPS API server, fp-multiuser.py, and frps as subprocesses. The `--web on` flag additionally starts the browser-based admin panel.

4. (Optional) Set up the web admin panel before starting with `--web on`:
   ```bash
   python main.py web setup
   ```
   Follow the prompts to configure admin credentials, port, and SSL settings.

### Client Setup

1. Install client dependencies:
   ```bash
   cd client
   pip install -r requirements.txt
   ```

2. Launch the GUI:
   ```bash
   python client.py
   ```

3. Enter the server URL (e.g., `https://your-server:8443`) and click **Connect**.

4. Register a new account or log in with an existing one.

## Server CLI Commands

| Command | Description |
|---------|-------------|
| `python main.py setup` | Initial server configuration |
| `python main.py start` | Start the server (add `--web on` to enable web admin) |
| `python main.py set-expiry <user_id> <YYYY-MM-DD HH:MM>` | Set user expiration |
| `python main.py list-users` | List all registered users |
| `python main.py add-code <code> <DD-HH-MM>` | Add an activation code |
| `python main.py list-codes` | List all activation codes |
| `python main.py web setup` | Configure the web admin panel |

### Setting User Expiration

```bash
python main.py set-expiry user0001 "2026-12-31 23:59"
```

This sets the expiration time and automatically generates a token for the user via fp-multiuser API.

### Managing Activation Codes

Add an activation code with a duration of 30 days:

```bash
python main.py add-code MYCODE30 30-00-00
```

List all activation codes:

```bash
python main.py list-codes
```

Users can enter activation codes in the client GUI by clicking the **Activate** button on the main dashboard. If the account is already expired, the activation duration is added from the current time; if still active, the duration is added to the existing expiration.

## Web Admin Panel

The server includes an optional browser-based admin panel for managing the FRP system without using the CLI or Management API.

### Setup

```bash
python main.py web setup
```

Prompts for admin username, password, port (default 5000), IP restrictions, and SSL/HTTPS configuration.

### Starting

```bash
python main.py start --web on
```

The panel runs in a background thread alongside the main API server.

### Access

| Protocol | URL |
|----------|-----|
| HTTPS (default) | `https://your-server:5000/` |
| HTTP | `http://your-server:5000/` |

If using the auto-generated self-signed certificate, browsers will show a security warning. You can download the CA root certificate from the Settings page to trust the certificate chain.

### Features

| Page | Description |
|------|-------------|
| **User Management** | Create, edit, delete users; set custom user IDs, email, password, and expiration |
| **Tunnel Management** | Create, edit, delete tunnels; assign to users; batch delete |
| **Activation Codes** | Create, edit, delete codes; batch generate (1-99 codes at once); batch delete; one-click copy |
| **System Settings** | Edit server config and web config files in browser; change admin password; download CA certificate |

### SSL / HTTPS

- When SSL is enabled and no certificate files are configured, the server auto-generates a CA key pair and a server certificate signed by the CA on first start
- The CA root certificate can be downloaded from the Settings page for client trust configuration
- Custom certificates can be configured via `python main.py web setup` or by editing `server/web/web_config.json`

### Configuration File

The web admin panel stores its configuration at `server/web/web_config.json`. Key settings:

| Field | Default | Description |
|-------|---------|-------------|
| `port` | `5000` | Panel listen port |
| `ssl.enabled` | `true` | Enable HTTPS |
| `ssl.self_signed` | `true` | Auto-generate certificates |
| `ssl.cert_file` | `""` | Custom cert path |
| `ssl.key_file` | `""` | Custom key path |
| `allowed_ips` | `[]` | IP access restrictions (empty = no restriction) |

## Management API

The server provides a separate HTTP management API for automated administration. Configure it in `config.json` or during `python main.py setup`:

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

All endpoints require the configured `api_key` — pass it in the JSON body (POST/PUT) or as a query parameter `?key=...` (GET/DELETE). If `allowed_ips` is configured, requests from other IPs are rejected with `403 Forbidden`.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/management/user` | Create user |
| PUT | `/api/management/user/<user_id>` | Update user |
| DELETE | `/api/management/user/<user_id>` | Delete user |
| GET | `/api/management/users` | List all users |
| POST | `/api/management/tunnel` | Create tunnel |
| PUT | `/api/management/tunnel/<id>` | Update tunnel |
| DELETE | `/api/management/tunnel/<id>` | Delete tunnel |
| GET | `/api/management/tunnels` | List all tunnels |
| POST | `/api/management/code` | Create activation code |
| PUT | `/api/management/code/<id>` | Update activation code |
| DELETE | `/api/management/code/<id>` | Delete activation code |
| GET | `/api/management/codes` | List all activation codes |

### Request Body Reference

#### User Management

**POST `/api/management/user`** — Create user

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | **yes** | API key |
| `email` | string | **yes** | User email |
| `password` | string | **yes** | User password |
| `user_id` | string | no | Custom ID (auto-generated if omitted) |
| `expires_at` | string | no | `YYYY-MM-DD HH:MM` (defaults to expired) |

**PUT `/api/management/user/<user_id>`** — Update user

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | **yes** | API key |
| `email` | string | no | New email |
| `password` | string | no | New password |
| `new_user_id` | string | no | Change user ID |
| `expires_at` | string | no | `YYYY-MM-DD HH:MM` |

**DELETE `/api/management/user/<user_id>`** — Delete user (requires `?key=...`)

**GET `/api/management/users`** — List all users (requires `?key=...`)

#### Tunnel Management

**POST `/api/management/tunnel`** — Create tunnel

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | **yes** | API key |
| `user_id` | string | **yes** | Owner user ID |
| `name` | string | **yes** | Tunnel name |
| `type` | string | no | `tcp` (default) or `udp` |
| `local_ip` | string | no | Default `127.0.0.1` |
| `local_port` | int | **yes** | Local port |
| `remote_port` | int | no | Remote port (auto-assigned if omitted) |

**PUT `/api/management/tunnel/<id>`** — Update tunnel (all fields optional)

| Field | Type | Description |
|-------|------|-------------|
| `key` | string | API key |
| `name` | string | New name |
| `type` | string | `tcp` or `udp` |
| `local_ip` | string | Local IP |
| `local_port` | int | Local port |
| `remote_port` | int | Remote port |
| `user_id` | string | Change owner |

#### Activation Code Management

**POST `/api/management/code`** — Create code

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | **yes** | API key |
| `code` | string | **yes** | Code string |
| `duration` | string | **yes** | `DD-HH-MM` format |

**PUT `/api/management/code/<id>`** — Update code

| Field | Type | Description |
|-------|------|-------------|
| `key` | string | API key |
| `code` | string | New code string |
| `duration` | string | `DD-HH-MM` format |

Cannot modify a used code.

### Examples

**Create user (key in body)**
```bash
curl -X POST http://localhost:8444/api/management/user \
  -H "Content-Type: application/json" \
  -d '{"key":"your-secret-key","email":"user@example.com","password":"secret123","user_id":"custom001","expires_at":"2027-12-31 23:59"}'
```

**List users (key as query param)**
```bash
curl "http://localhost:8444/api/management/users?key=your-secret-key"
```

**Delete tunnel (key as query param)**
```bash
curl -X DELETE "http://localhost:8444/api/management/tunnel/1?key=your-secret-key"
```

## How It Works

1. **Registration Flow**: User enters email → server sends verification code via SMTP → user verifies → account created with auto-generated ID.
2. **Login Flow**: User logs in via email/password → server generates a persistent token (stored in DB with configurable expiry) → client exchanges it for a 24h session token. If "remember me" is checked, the persistent token is encrypted with Windows DPAPI and saved locally for automatic re-authentication.
3. **Tunnel Creation**: User creates a tunnel → server allocates a port from the configured range (default 20000-21000) → tunnel is stored in MySQL.
4. **Tunnel Enable**: User enables a tunnel → server requests token from fp-multiuser API → client updates `frpc.ini` → client starts `frpc.exe` as subprocess.
5. **Tunnel Disable**: User disables a tunnel → client sends SIGINT to `frpc.exe` → server marks tunnel as disabled.
6. **Expiration Check**: Server checks every 60 seconds for expired users → removes their tokens via fp-multiuser API.

## Security

- All client-server communication uses HTTPS
- Passwords are hashed with **bcrypt** (legacy SHA-256 hashes migrated on password reset)
- **Token-based authentication**: two-step flow separates credential verification from session creation
- Session tokens expire after 24 hours and are stored **in memory only** (never persisted to disk)
- Persistent login tokens are encrypted with **Windows DPAPI** (bound to the current Windows user account)
- Client config is automatically cleaned of legacy sensitive fields on startup
- Server verifies database table structure on startup, auto-restoring missing columns
- fp-multiuser API runs on localhost by default

## License

MIT
