# FRP Login Tool

A multi-user FRP (Fast Reverse Proxy) intranet penetration management tool with a GUI client and CLI server.

## Architecture

- **Server** (`server/main.py`): CLI-based server managing FRP tunnels with MySQL storage, SMTP email verification, and fp-multiuser authentication integration.
- **Client** (`client/client.py`): Desktop GUI (tkinter) for users to register, login, and manage tunnels.

## Features

- **User Registration & Login** via email with SMTP verification code
- **Automatic User ID** assignment (`user0001`, `user0002`, ...)
- **Tunnel Management**: each user can create up to 10 tunnels
- **Automatic Port Allocation**: each tunnel gets a fixed port from 20000-21000
- **Expiration Control**: admin sets expiration per user; expired users lose access
- **Activation Codes**: admin generates codes with custom durations to extend user expiration
- **fp-multiuser Integration**: automatic token generation and cleanup via REST API
- **HTTPS Communication** between client and server
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
   Follow the prompts to configure SMTP, FTPS, MySQL, and HTTPS settings.

3. Start the server:
   ```bash
   python main.py start
   ```
   This starts the HTTPS API server, fp-multiuser.py, and frps as subprocesses.

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
| `python main.py start` | Start the server |
| `python main.py set-expiry <user_id> <YYYY-MM-DD HH:MM>` | Set user expiration |
| `python main.py list-users` | List all registered users |
| `python main.py add-code <code> <DD-HH-MM>` | Add an activation code |
| `python main.py list-codes` | List all activation codes |

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

## How It Works

1. **Registration Flow**: User enters email → server sends verification code via SMTP → user verifies → account created with auto-generated ID.
2. **Login Flow**: User logs in via email/password → receives session token → views account status and tunnels.
3. **Tunnel Creation**: User creates a tunnel → server allocates a port from 20000-21000 → tunnel is stored in MySQL.
4. **Tunnel Enable**: User enables a tunnel → server requests token from fp-multiuser API → client updates `frpc.ini` → client starts `frpc.exe` as subprocess.
5. **Tunnel Disable**: User disables a tunnel → client sends SIGINT to `frpc.exe` → server marks tunnel as disabled.
6. **Expiration Check**: Server checks every 60 seconds for expired users → removes their tokens via fp-multiuser API.

## Security

- All client-server communication uses HTTPS
- Passwords are hashed with SHA-256
- Session tokens expire after 24 hours
- fp-multiuser API runs on localhost by default

## License

MIT