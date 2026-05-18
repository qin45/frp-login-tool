#!/usr/bin/env python3
"""
FRP Login Tool - Server
CLI server for managing FRP multi-user tunnels with MySQL, SMTP, and fp-multiuser integration.
"""
import argparse
import json
import os
import sys
import time
import threading
import logging
import random
import string
import hashlib
import smtplib
import subprocess
import signal
import ssl
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

from flask import Flask, request, jsonify
import pymysql
import requests

# ============================================================
# Configuration
# ============================================================
BASE_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = BASE_DIR / "config.json"
FRPS_DIR = BASE_DIR / "frps"
FP_MULTIUSER_PY = FRPS_DIR / "fp-multiuser.py"
FRPS_BIN = FRPS_DIR / "frps"
FRPS_INI = FRPS_DIR / "frps.ini"
TOKENS_FILE = FRPS_DIR / "tokens"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("frp-server")

server_processes = {}
shutdown_event = threading.Event()
session_map = {}
session_lock = threading.Lock()

# In-memory verification codes: {email: {"code": str, "expires_at": datetime, "cooldown_until": datetime}}
verification_codes = {}
verification_lock = threading.Lock()


# ============================================================
# Config Management
# ============================================================
def load_config():
    if not CONFIG_FILE.exists():
        return {"configured": False}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {"configured": False}
            return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return {"configured": False}


def save_config(cfg):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def migrate_config(cfg):
    """Fill in missing config keys with defaults and log what was added."""
    defaults = {
        "smtp": {
            "server": "",
            "port": 465,
            "username": "",
            "password": "",
            "from_email": "",
        },
        "ftps": {
            "ip": "",
            "port": 7000,
            "port_range_start": 20000,
            "port_range_end": 21000,
        },
        "mysql": {
            "host": "localhost",
            "port": 3306,
            "user": "",
            "password": "",
            "database": "frp_login",
        },
        "https": {
            "port": 8443,
            "cert_file": "",
            "key_file": "",
        },
        "fp_multiuser": {
            "api_port": 8080,
            "api_url": "http://127.0.0.1:8080",
        },
        "management_api": {
            "enabled": False,
            "port": 8444,
            "api_key": "",
            "allowed_ips": ["127.0.0.1"],
        },
    }

    added = []

    for section, keys in defaults.items():
        if section not in cfg:
            cfg[section] = {}
            added.append(f"  [{section}] (entire section)")
        for key, val in keys.items():
            if key not in cfg[section]:
                cfg[section][key] = val
                added.append(f"  [{section}] {key}")

    if "configured" not in cfg:
        cfg["configured"] = True
        added.append("  configured")

    if added:
        logger.info("Config migration: missing keys filled with defaults:")
        for line in added:
            logger.info(line)
        save_config(cfg)
        logger.info(f"Config auto-updated with {len(added)} missing key(s)")

    return cfg


def setup_config():
    """Interactive CLI setup for first-time configuration."""
    print("=" * 60)
    print("  FRP Login Tool - Server Initial Setup")
    print("=" * 60)

    cfg = {"configured": False}

    print("\n--- SMTP Configuration (for email verification) ---")
    smtp = {}
    smtp["server"] = input("SMTP Server: ").strip()
    smtp["port"] = int(input("SMTP Port (SSL 465 recommended): ").strip() or "465")
    smtp["username"] = input("SMTP Username: ").strip()
    smtp["password"] = input("SMTP Password: ").strip()
    smtp["from_email"] = input("From Email (default same as username): ").strip() or smtp["username"]
    cfg["smtp"] = smtp

    print("\n--- FRP Server Connection Info (sent to clients) ---")
    ftps = {}
    ftps["ip"] = input("FRP Server IP: ").strip()
    ftps["port"] = int(input("FRP Server Port (default 7000): ").strip() or "7000")
    port_start = input("Tunnel Port Range Start (default 20000): ").strip()
    ftps["port_range_start"] = int(port_start) if port_start else 20000
    port_end = input("Tunnel Port Range End (default 21000): ").strip()
    ftps["port_range_end"] = int(port_end) if port_end else 21000
    cfg["ftps"] = ftps

    print("\n--- MySQL Database Configuration ---")
    mysql = {}
    mysql["host"] = input("MySQL Host (default localhost): ").strip() or "localhost"
    mysql["port"] = int(input("MySQL Port (default 3306): ").strip() or "3306")
    mysql["user"] = input("MySQL User: ").strip()
    mysql["password"] = input("MySQL Password: ").strip()
    mysql["database"] = input("Database Name (default frp_login): ").strip() or "frp_login"
    cfg["mysql"] = mysql

    print("\n--- HTTPS Configuration ---")
    https = {}
    https["port"] = int(input("API Server Port (default 8443): ").strip() or "8443")
    https["cert_file"] = input("SSL Certificate File path (empty = auto-generated): ").strip()
    https["key_file"] = input("SSL Key File path (empty = auto-generated): ").strip()
    cfg["https"] = https

    fp = {}
    fp["api_port"] = int(input(
        "fp-multiuser API Port (default 8080): "
    ).strip() or "8080")
    fp["api_url"] = f"http://127.0.0.1:{fp['api_port']}"
    cfg["fp_multiuser"] = fp

    print("\n--- Management API Configuration ---")
    mgmt = {}
    mgmt["enabled"] = input("Enable Management API? (Y/n): ").strip().lower() != "n"
    if mgmt["enabled"]:
        mgmt["port"] = int(input("Management API Port (default 8444): ").strip() or "8444")
        mgmt["api_key"] = input("API Key (required in all requests): ").strip()
        allowed = input("Allowed IPs (comma-separated, empty = localhost only): ").strip()
        mgmt["allowed_ips"] = [ip.strip() for ip in allowed.split(",") if ip.strip()] if allowed else ["127.0.0.1"]
    cfg["management_api"] = mgmt

    cfg["configured"] = True
    save_config(cfg)
    print("\n✓ Configuration saved to config.json")
    print("Run 'python main.py start' to start the server.")

    print("\nTesting MySQL connection...")
    try:
        db = Database(cfg["mysql"])
        db.init_database()
        print("✓ MySQL connection successful, tables created.")
    except Exception as e:
        print(f"✗ MySQL connection failed: {e}")
        print("  Please fix the configuration and run 'python main.py setup' again.")
        sys.exit(1)


# ============================================================
# Database
# ============================================================
class Database:
    def __init__(self, mysql_cfg, port_range_start=20000, port_range_end=21000):
        self.cfg = mysql_cfg
        self.port_range_start = port_range_start
        self.port_range_end = port_range_end
        self.conn = None
        self._connect()

    def _connect(self):
        self.conn = pymysql.connect(
            host=self.cfg["host"],
            port=self.cfg["port"],
            user=self.cfg["user"],
            password=self.cfg["password"],
            database=self.cfg["database"],
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _execute(self, sql, params=None):
        for attempt in range(3):
            try:
                with self.conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    self.conn.commit()
                    return cursor
            except (pymysql.err.OperationalError, pymysql.err.InterfaceError):
                if attempt < 2:
                    time.sleep(1)
                    self._connect()
                else:
                    raise

    def _fetch_one(self, sql, params=None):
        return self._execute(sql, params).fetchone()

    def _fetch_all(self, sql, params=None):
        return self._execute(sql, params).fetchall()

    def init_database(self):
        sql = """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id VARCHAR(10) UNIQUE,
            email VARCHAR(255) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL DEFAULT '',
            verified TINYINT(1) DEFAULT 0,
            expires_at DATETIME NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
        self._execute(sql)
        sql2 = """
        CREATE TABLE IF NOT EXISTS tunnels (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id VARCHAR(10) NOT NULL,
            name VARCHAR(100) NOT NULL,
            tunnel_type VARCHAR(10) DEFAULT 'tcp',
            local_ip VARCHAR(255) DEFAULT '127.0.0.1',
            local_port INT NOT NULL,
            remote_port INT UNIQUE,
            enabled TINYINT(1) DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
        self._execute(sql2)
        sql3 = """
        CREATE TABLE IF NOT EXISTS activation_codes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            code VARCHAR(255) UNIQUE NOT NULL,
            duration_days INT NOT NULL DEFAULT 0,
            duration_hours INT NOT NULL DEFAULT 0,
            duration_minutes INT NOT NULL DEFAULT 0,
            used TINYINT(1) DEFAULT 0,
            used_by VARCHAR(10),
            used_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
        self._execute(sql3)

    # ---- User operations ----
    def create_user(self, email, password_hash):
        # Check if email already registered
        existing = self._fetch_one("SELECT id FROM users WHERE email=%s", (email,))
        if existing:
            return None
        user_id = self._generate_user_id()
        self._execute(
            "INSERT INTO users (user_id, email, password, verified, expires_at) "
            "VALUES (%s, %s, %s, 1, %s)",
            (user_id, email, password_hash, datetime.now() - timedelta(days=1)),
        )
        return user_id

    def _generate_user_id(self):
        row = self._fetch_one(
            "SELECT user_id FROM users WHERE user_id LIKE 'user%' ORDER BY id DESC LIMIT 1"
        )
        if row:
            num = int(row["user_id"][4:]) + 1
        else:
            num = 1
        return f"user{num:04d}"

    def get_user_by_email(self, email):
        return self._fetch_one("SELECT * FROM users WHERE email=%s", (email,))

    def get_user_by_id(self, user_id):
        return self._fetch_one("SELECT * FROM users WHERE user_id=%s", (user_id,))

    def update_expiry(self, user_id, expires_at):
        self._execute(
            "UPDATE users SET expires_at=%s WHERE user_id=%s", (expires_at, user_id)
        )

    def list_users(self):
        return self._fetch_all(
            "SELECT id, user_id, email, verified, expires_at, created_at FROM users ORDER BY id"
        )

    def get_expired_users(self):
        return self._fetch_all(
            "SELECT user_id FROM users WHERE expires_at <= %s AND verified=1",
            (datetime.now(),),
        )

    # ---- Activation code operations ----
    def add_activation_code(self, code, days, hours, minutes):
        self._execute(
            "INSERT INTO activation_codes (code, duration_days, duration_hours, duration_minutes) "
            "VALUES (%s, %s, %s, %s)",
            (code, days, hours, minutes),
        )

    def use_activation_code(self, code, user_id):
        row = self._fetch_one(
            "SELECT * FROM activation_codes WHERE code=%s AND used=0", (code,)
        )
        if not row:
            return False, "无效的激活码或已被使用"
        duration = timedelta(
            days=row["duration_days"],
            hours=row["duration_hours"],
            minutes=row["duration_minutes"],
        )
        user = self.get_user_by_id(user_id)
        if not user:
            return False, "User not found"
        now = datetime.now()
        current_expiry = user["expires_at"]
        if current_expiry and current_expiry > now:
            new_expiry = current_expiry + duration
        else:
            new_expiry = now + duration
        self._execute(
            "UPDATE users SET expires_at=%s WHERE user_id=%s", (new_expiry, user_id)
        )
        self._execute(
            "UPDATE activation_codes SET used=1, used_by=%s, used_at=%s WHERE code=%s",
            (user_id, now, code),
        )
        return True, new_expiry

    def list_activation_codes(self):
        return self._fetch_all("SELECT * FROM activation_codes ORDER BY id")

    # ---- Management operations ----
    def admin_create_user(self, user_id, email, password, expires_at):
        existing = self._fetch_one("SELECT id FROM users WHERE email=%s", (email,))
        if existing:
            return False, "Email already in use"
        if user_id:
            existing_id = self._fetch_one("SELECT id FROM users WHERE user_id=%s", (user_id,))
            if existing_id:
                return False, "User ID already in use"
        else:
            user_id = self._generate_user_id()
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        self._execute(
            "INSERT INTO users (user_id, email, password, verified, expires_at) "
            "VALUES (%s, %s, %s, 1, %s)",
            (user_id, email, pw_hash, expires_at),
        )
        return True, user_id

    def admin_update_user(self, old_user_id, email=None, password=None, expires_at=None, new_user_id=None):
        user = self.get_user_by_id(old_user_id)
        if not user:
            return False, "User not found"
        if new_user_id and new_user_id != old_user_id:
            existing = self._fetch_one("SELECT id FROM users WHERE user_id=%s", (new_user_id,))
            if existing:
                return False, "New user ID already in use"
            self._execute("UPDATE users SET user_id=%s WHERE user_id=%s", (new_user_id, old_user_id))
            old_user_id = new_user_id
        if email is not None:
            existing = self._fetch_one("SELECT id FROM users WHERE email=%s AND user_id!=%s", (email, old_user_id))
            if existing:
                return False, "Email already in use by another user"
            self._execute("UPDATE users SET email=%s WHERE user_id=%s", (email, old_user_id))
        if password is not None:
            pw_hash = hashlib.sha256(password.encode()).hexdigest()
            self._execute("UPDATE users SET password=%s WHERE user_id=%s", (pw_hash, old_user_id))
        if expires_at is not None:
            self._execute("UPDATE users SET expires_at=%s WHERE user_id=%s", (expires_at, old_user_id))
        return True, self.get_user_by_id(old_user_id)

    def admin_create_tunnel(self, user_id, name, tunnel_type, local_ip, local_port, remote_port):
        user = self.get_user_by_id(user_id)
        if not user:
            return False, "User not found"
        count = self._fetch_one(
            "SELECT COUNT(*) as cnt FROM tunnels WHERE user_id=%s", (user_id,)
        )["cnt"]
        if count >= 10:
            return False, "User already has 10 tunnels"
        if remote_port:
            existing_port = self._fetch_one(
                "SELECT id FROM tunnels WHERE remote_port=%s", (remote_port,)
            )
            if existing_port:
                return False, f"Remote port {remote_port} already in use"
        else:
            remote_port = self.get_available_port()
            if not remote_port:
                return False, "No available ports in range 20000-21000"
        self._execute(
            "INSERT INTO tunnels (user_id, name, tunnel_type, local_ip, local_port, remote_port) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, name, tunnel_type, local_ip, local_port, remote_port),
        )
        tid = self._execute("SELECT LAST_INSERT_ID() as id").fetchone()["id"]
        return True, self._fetch_one("SELECT * FROM tunnels WHERE id=%s", (tid,))

    def admin_update_tunnel(self, tunnel_id, name=None, tunnel_type=None, local_ip=None,
                            local_port=None, remote_port=None, user_id=None):
        tunnel = self._fetch_one("SELECT * FROM tunnels WHERE id=%s", (tunnel_id,))
        if not tunnel:
            return False, "Tunnel not found"
        if name is not None:
            self._execute("UPDATE tunnels SET name=%s WHERE id=%s", (name, tunnel_id))
        if tunnel_type is not None:
            self._execute("UPDATE tunnels SET tunnel_type=%s WHERE id=%s", (tunnel_type, tunnel_id))
        if local_ip is not None:
            self._execute("UPDATE tunnels SET local_ip=%s WHERE id=%s", (local_ip, tunnel_id))
        if local_port is not None:
            self._execute("UPDATE tunnels SET local_port=%s WHERE id=%s", (local_port, tunnel_id))
        if remote_port is not None:
            existing = self._fetch_one(
                "SELECT id FROM tunnels WHERE remote_port=%s AND id!=%s", (remote_port, tunnel_id)
            )
            if existing:
                return False, f"Remote port {remote_port} already in use"
            self._execute("UPDATE tunnels SET remote_port=%s WHERE id=%s", (remote_port, tunnel_id))
        if user_id is not None:
            user = self.get_user_by_id(user_id)
            if not user:
                return False, "New owner user not found"
            self._execute("UPDATE tunnels SET user_id=%s WHERE id=%s", (user_id, tunnel_id))
        return True, self._fetch_one("SELECT * FROM tunnels WHERE id=%s", (tunnel_id,))

    def admin_delete_tunnel(self, tunnel_id):
        tunnel = self._fetch_one("SELECT * FROM tunnels WHERE id=%s", (tunnel_id,))
        if not tunnel:
            return False, "Tunnel not found"
        self._execute("DELETE FROM tunnels WHERE id=%s", (tunnel_id,))
        return True, None

    def admin_create_code(self, code, days, hours, minutes):
        existing = self._fetch_one("SELECT id FROM activation_codes WHERE code=%s", (code,))
        if existing:
            return False, "Code already exists"
        self._execute(
            "INSERT INTO activation_codes (code, duration_days, duration_hours, duration_minutes) "
            "VALUES (%s, %s, %s, %s)",
            (code, days, hours, minutes),
        )
        return True, None

    def admin_update_code(self, code_id, new_code=None, days=None, hours=None, minutes=None):
        existing = self._fetch_one("SELECT * FROM activation_codes WHERE id=%s", (code_id,))
        if not existing:
            return False, "Code not found"
        if existing["used"]:
            return False, "Cannot modify a used code"
        if new_code is not None:
            dup = self._fetch_one("SELECT id FROM activation_codes WHERE code=%s AND id!=%s", (new_code, code_id))
            if dup:
                return False, "Code string already exists"
            self._execute("UPDATE activation_codes SET code=%s WHERE id=%s", (new_code, code_id))
        if days is not None:
            self._execute("UPDATE activation_codes SET duration_days=%s WHERE id=%s", (days, code_id))
        if hours is not None:
            self._execute("UPDATE activation_codes SET duration_hours=%s WHERE id=%s", (hours, code_id))
        if minutes is not None:
            self._execute("UPDATE activation_codes SET duration_minutes=%s WHERE id=%s", (minutes, code_id))
        return True, self._fetch_one("SELECT * FROM activation_codes WHERE id=%s", (code_id,))

    def admin_delete_code(self, code_id):
        existing = self._fetch_one("SELECT * FROM activation_codes WHERE id=%s", (code_id,))
        if not existing:
            return False, "Code not found"
        self._execute("DELETE FROM activation_codes WHERE id=%s", (code_id,))
        return True, None

    def admin_delete_user(self, user_id):
        user = self.get_user_by_id(user_id)
        if not user:
            return False, "User not found"
        self._execute("DELETE FROM tunnels WHERE user_id=%s", (user_id,))
        self._execute("DELETE FROM users WHERE user_id=%s", (user_id,))
        return True, None

    def admin_list_all_tunnels(self):
        return self._fetch_all(
            """SELECT t.*, u.email FROM tunnels t
               LEFT JOIN users u ON t.user_id = u.user_id
               ORDER BY t.id"""
        )

    # ---- Tunnel operations ----
    def get_available_port(self):
        used = self._fetch_all(
            "SELECT remote_port FROM tunnels WHERE remote_port IS NOT NULL"
        )
        used_ports = {r["remote_port"] for r in used}
        for port in range(self.port_range_start, self.port_range_end + 1):
            if port not in used_ports:
                return port
        return None

    def create_tunnel(self, user_id, name, tunnel_type, local_port, local_ip="127.0.0.1"):
        count = self._fetch_one(
            "SELECT COUNT(*) as cnt FROM tunnels WHERE user_id=%s", (user_id,)
        )["cnt"]
        if count >= 10:
            return None, "Maximum 10 tunnels per user"
        remote_port = self.get_available_port()
        if not remote_port:
            return None, "No available ports in range 20000-21000"
        self._execute(
            "INSERT INTO tunnels (user_id, name, tunnel_type, local_ip, local_port, remote_port) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, name, tunnel_type, local_ip, local_port, remote_port),
        )
        tid = self._execute("SELECT LAST_INSERT_ID() as id").fetchone()["id"]
        return self._fetch_one("SELECT * FROM tunnels WHERE id=%s", (tid,)), None

    def list_tunnels(self, user_id):
        return self._fetch_all(
            "SELECT * FROM tunnels WHERE user_id=%s ORDER BY id", (user_id,)
        )

    def get_tunnel(self, tunnel_id):
        return self._fetch_one("SELECT * FROM tunnels WHERE id=%s", (tunnel_id,))

    def delete_tunnel(self, tunnel_id, user_id):
        tunnel = self._fetch_one(
            "SELECT * FROM tunnels WHERE id=%s AND user_id=%s", (tunnel_id, user_id)
        )
        if not tunnel:
            return False, "Tunnel not found"
        if tunnel["enabled"]:
            return False, "Disable the tunnel before deleting"
        self._execute("DELETE FROM tunnels WHERE id=%s", (tunnel_id,))
        return True, None

    def enable_tunnel(self, tunnel_id, user_id):
        tunnel = self._fetch_one(
            "SELECT * FROM tunnels WHERE id=%s AND user_id=%s", (tunnel_id, user_id)
        )
        if not tunnel:
            return None, "Tunnel not found"
        if tunnel["enabled"]:
            return None, "Tunnel already enabled"
        user = self.get_user_by_id(user_id)
        if user and user["expires_at"] <= datetime.now():
            return None, "Account has expired"
        self._execute("UPDATE tunnels SET enabled=1 WHERE id=%s", (tunnel_id,))
        return self._fetch_one("SELECT * FROM tunnels WHERE id=%s", (tunnel_id,)), None

    def disable_tunnel(self, tunnel_id, user_id):
        tunnel = self._fetch_one(
            "SELECT * FROM tunnels WHERE id=%s AND user_id=%s", (tunnel_id, user_id)
        )
        if not tunnel:
            return False, "Tunnel not found"
        if not tunnel["enabled"]:
            return False, "Tunnel is not enabled"
        self._execute("UPDATE tunnels SET enabled=0 WHERE id=%s", (tunnel_id,))
        return True, None


# ============================================================
# Session Management
# ============================================================
def generate_token(length=32):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def create_session(user_id):
    token = generate_token(32)
    with session_lock:
        session_map[token] = {
            "user_id": user_id,
            "expires_at": datetime.now() + timedelta(hours=24),
        }
    return token


def validate_session(token):
    with session_lock:
        sess = session_map.get(token)
        if not sess:
            return None
        if sess["expires_at"] < datetime.now():
            del session_map[token]
            return None
        return sess["user_id"]


# ============================================================
# SMTP Email
# ============================================================
class EmailSender:
    def __init__(self, smtp_cfg):
        self.cfg = smtp_cfg

    def send_verification_code(self, to_email, code):
        subject = "FRP 内网穿透 - 验证码"
        body = f"""
        <html><body>
        <h2>FRP 内网穿透工具</h2>
        <p>您的验证码为：</p>
        <h1 style="color:#4CAF50;font-size:32px;letter-spacing:5px;">{code}</h1>
        <p>验证码有效期为 10 分钟，请尽快完成操作。</p>
        <p>如果这不是您本人的操作，请忽略此邮件。</p>
        </body></html>
        """
        return self._send(to_email, subject, body)

    def _send(self, to_email, subject, html_body):
        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self.cfg["from_email"]
        msg["To"] = to_email
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            port = self.cfg["port"]
            if port == 465:
                with smtplib.SMTP_SSL(self.cfg["server"], port, context=ctx) as server:
                    server.login(self.cfg["username"], self.cfg["password"])
                    server.sendmail(self.cfg["from_email"], [to_email], msg.as_string())
            else:
                with smtplib.SMTP(self.cfg["server"], port) as server:
                    server.starttls(context=ctx)
                    server.login(self.cfg["username"], self.cfg["password"])
                    server.sendmail(self.cfg["from_email"], [to_email], msg.as_string())
            return True, None
        except Exception as e:
            return False, str(e)


# ============================================================
# fp-multiuser Token Manager
# ============================================================
class TokenManager:
    def __init__(self, api_url):
        self.api_url = api_url.rstrip("/")

    def add_user(self, user_id, token):
        try:
            resp = requests.post(
                f"{self.api_url}/users",
                json={"username": user_id, "token": token},
                timeout=10,
            )
            return resp.status_code == 200, resp.text
        except requests.RequestException as e:
            return False, str(e)

    def remove_user(self, user_id):
        try:
            resp = requests.delete(f"{self.api_url}/users/{user_id}", timeout=10)
            return resp.status_code == 200, resp.text
        except requests.RequestException as e:
            return False, str(e)

    def generate_token_for_user(self, user_id):
        token = generate_token(32)
        ok, _ = self.add_user(user_id, token)
        return token if ok else None


# ============================================================
# Process Management
# ============================================================
def start_subprocess(name, cmd, cwd=None, env=None):
    logger.info(f"Starting {name}: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd or str(BASE_DIR),
            env={**os.environ, **(env or {})},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        def log_output():
            for line in iter(proc.stdout.readline, b""):
                if line:
                    logger.info(
                        f"[{name}] {line.decode('utf-8', errors='replace').rstrip()}"
                    )
                else:
                    break

        threading.Thread(target=log_output, daemon=True).start()
        server_processes[name] = proc
        logger.info(f"{name} started with PID {proc.pid}")
        return proc
    except Exception as e:
        logger.error(f"Failed to start {name}: {e}")
        return None


def stop_subprocess(name):
    proc = server_processes.pop(name, None)
    if proc and proc.poll() is None:
        logger.info(f"Stopping {name} (PID {proc.pid})...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning(f"Force killing {name}")
            proc.kill()
            proc.wait()
        logger.info(f"{name} stopped")


def start_all_processes(cfg):
    if FP_MULTIUSER_PY.exists():
        fp_multiuser_bin = FRPS_DIR / "fp-multiuser"
        env = {}
        if fp_multiuser_bin.exists():
            if not os.access(str(fp_multiuser_bin), os.X_OK):
                logger.error(
                    f"fp-multiuser binary at {fp_multiuser_bin} is not executable. "
                    f"Run: chmod +x {fp_multiuser_bin}"
                )
            else:
                env["FP_MULTIUSER_BIN"] = str(fp_multiuser_bin)
        fp_cfg = cfg.get("fp_multiuser", {})
        if "api_port" in fp_cfg:
            env["API_PORT"] = str(fp_cfg["api_port"])
        proc = start_subprocess(
            "fp-multiuser",
            [sys.executable, str(FP_MULTIUSER_PY)],
            cwd=str(FRPS_DIR),
            env=env,
        )
        # Wait briefly and check if still alive
        if proc:
            time.sleep(1)
            if proc.poll() is not None:
                logger.error(
                    f"fp-multiuser.py exited early (code {proc.poll()}). "
                    f"The fp-multiuser binary may not be executable. "
                    f"Run: chmod +x {fp_multiuser_bin}"
                )
    else:
        logger.warning(f"fp-multiuser.py not found at {FP_MULTIUSER_PY}")

    if FRPS_BIN.exists() and FRPS_INI.exists():
        if not os.access(str(FRPS_BIN), os.X_OK):
            logger.error(
                f"frps binary at {FRPS_BIN} is not executable. "
                f"Run: chmod +x {FRPS_BIN}"
            )
        start_subprocess("frps", [str(FRPS_BIN), "-c", str(FRPS_INI)])
    else:
        logger.warning("frps binary or config not found")


def stop_all_processes():
    for name in list(server_processes.keys()):
        stop_subprocess(name)


# ============================================================
# Expiry Checker
# ============================================================
class ExpiryChecker:
    def __init__(self, db, token_mgr):
        self.db = db
        self.token_mgr = token_mgr
        self._stop_event = threading.Event()

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        logger.info("Expiry checker started (every 60s)")

    def stop(self):
        self._stop_event.set()

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self._check()
            except Exception as e:
                logger.error(f"Expiry check error: {e}")
            self._stop_event.wait(60)

    def _check(self):
        for user in self.db.get_expired_users():
            uid = user["user_id"]
            logger.info(f"User {uid} expired, removing token...")
            ok, msg = self.token_mgr.remove_user(uid)
            if ok:
                logger.info(f"Token removed for {uid}")
            else:
                logger.warning(f"Failed to remove token for {uid}: {msg}")


# ============================================================
# Flask API
# ============================================================
def create_app(db, email_sender, token_mgr, cfg):
    app = Flask(__name__)

    @app.route("/api/auth/register", methods=["POST"])
    def register_send_code():
        data = request.get_json()
        if not data or "email" not in data:
            return jsonify({"error": "Email required"}), 400
        email = data["email"].strip().lower()

        # Check if already registered
        if db.get_user_by_email(email):
            return jsonify({"error": "Email already registered"}), 400

        # Check cooldown (60s)
        with verification_lock:
            existing = verification_codes.get(email)
            if existing and existing["cooldown_until"] > datetime.now():
                remaining = int((existing["cooldown_until"] - datetime.now()).total_seconds())
                return jsonify({"error": f"Please wait {remaining}s before requesting again"}), 429

        code = "".join(random.choices(string.digits, k=6))
        now = datetime.now()
        with verification_lock:
            verification_codes[email] = {
                "code": code,
                "expires_at": now + timedelta(minutes=10),
                "cooldown_until": now + timedelta(seconds=60),
            }

        ok, err = email_sender.send_verification_code(email, code)
        if ok:
            return jsonify({"status": "ok", "message": "Verification code sent"})
        # Remove on send failure
        with verification_lock:
            verification_codes.pop(email, None)
        return jsonify({"error": f"Failed to send email: {err}"}), 500

    @app.route("/api/auth/register/verify", methods=["POST"])
    def register_verify():
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400
        email = data.get("email", "").strip().lower()
        code = data.get("code", "").strip()
        password = data.get("password", "").strip()
        if not email or not code or not password:
            return jsonify({"error": "email, code, password required"}), 400
        if len(password) < 6:
            return jsonify({"error": "Password must be >= 6 characters"}), 400

        # Verify in-memory code
        with verification_lock:
            stored = verification_codes.get(email)
            if not stored:
                return jsonify({"error": "No verification code requested"}), 400
            if stored["code"] != code:
                return jsonify({"error": "Invalid verification code"}), 400
            if stored["expires_at"] < datetime.now():
                verification_codes.pop(email, None)
                return jsonify({"error": "Verification code expired"}), 400
            # Code is valid - remove it so it can't be reused
            verification_codes.pop(email, None)

        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        user_id = db.create_user(email, pw_hash)
        if not user_id:
            return jsonify({"error": "Email already registered"}), 400
        token = create_session(user_id)
        user = db.get_user_by_id(user_id)
        return jsonify({
            "status": "ok", "session_token": token, "user_id": user_id,
            "expires_at": user["expires_at"].isoformat() if user["expires_at"] else None,
        })

    @app.route("/api/auth/reset-password/send-code", methods=["POST"])
    def reset_send_code():
        data = request.get_json()
        if not data or "email" not in data:
            return jsonify({"error": "Email required"}), 400
        email = data["email"].strip().lower()
        user = db.get_user_by_email(email)
        if not user:
            return jsonify({"error": "Email not registered"}), 404
        # Check cooldown
        with verification_lock:
            existing = verification_codes.get(email)
            if existing and existing["cooldown_until"] > datetime.now():
                remaining = int((existing["cooldown_until"] - datetime.now()).total_seconds())
                return jsonify({"error": f"Please wait {remaining}s"}), 429
        code = "".join(random.choices(string.digits, k=6))
        now = datetime.now()
        with verification_lock:
            verification_codes[email] = {
                "code": code,
                "expires_at": now + timedelta(minutes=10),
                "cooldown_until": now + timedelta(seconds=60),
            }
        ok, err = email_sender.send_verification_code(email, code)
        if ok:
            return jsonify({"status": "ok", "message": "Verification code sent"})
        with verification_lock:
            verification_codes.pop(email, None)
        return jsonify({"error": f"Failed to send email: {err}"}), 500

    @app.route("/api/auth/reset-password", methods=["POST"])
    def reset_password():
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400
        email = data.get("email", "").strip().lower()
        code = data.get("code", "").strip()
        new_password = data.get("new_password", "").strip()
        if not email or not code or not new_password:
            return jsonify({"error": "email, code, new_password required"}), 400
        if len(new_password) < 6:
            return jsonify({"error": "Password must be >= 6 characters"}), 400
        # Verify in-memory code
        with verification_lock:
            stored = verification_codes.get(email)
            if not stored:
                return jsonify({"error": "No verification code requested"}), 400
            if stored["code"] != code:
                return jsonify({"error": "Invalid code"}), 400
            if stored["expires_at"] < datetime.now():
                verification_codes.pop(email, None)
                return jsonify({"error": "Code expired"}), 400
            verification_codes.pop(email, None)
        # Update password
        pw_hash = hashlib.sha256(new_password.encode()).hexdigest()
        user = db.get_user_by_email(email)
        if not user:
            return jsonify({"error": "Email not registered"}), 404
        db._execute(
            "UPDATE users SET password=%s WHERE email=%s", (pw_hash, email)
        )
        return jsonify({"status": "ok", "message": "Password reset successfully"})

    @app.route("/api/auth/login", methods=["POST"])
    def login():
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400
        email = data.get("email", "").strip().lower()
        password = data.get("password", "").strip()
        user = db.get_user_by_email(email)
        if not user or not user["verified"]:
            return jsonify({"error": "Invalid email or password"}), 401
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        if user["password"] != pw_hash:
            return jsonify({"error": "Invalid email or password"}), 401
        token = create_session(user["user_id"])
        return jsonify({
            "status": "ok", "session_token": token, "user_id": user["user_id"],
            "expires_at": user["expires_at"].isoformat() if user["expires_at"] else None,
        })

    @app.route("/api/user/info", methods=["GET"])
    def user_info():
        uid = validate_session(
            request.headers.get("Authorization", "").replace("Bearer ", "")
        )
        if not uid:
            return jsonify({"error": "Unauthorized"}), 401
        user = db.get_user_by_id(uid)
        if not user:
            return jsonify({"error": "User not found"}), 404
        expired = user["expires_at"] <= datetime.now() if user["expires_at"] else True
        return jsonify({
            "user_id": user["user_id"], "email": user["email"],
            "expires_at": user["expires_at"].isoformat() if user["expires_at"] else None,
            "expired": expired,
        })

    @app.route("/api/tunnels", methods=["GET"])
    def list_tunnels():
        uid = validate_session(
            request.headers.get("Authorization", "").replace("Bearer ", "")
        )
        if not uid:
            return jsonify({"error": "Unauthorized"}), 401
        return jsonify({"tunnels": db.list_tunnels(uid)})

    @app.route("/api/tunnels", methods=["POST"])
    def create_tunnel():
        uid = validate_session(
            request.headers.get("Authorization", "").replace("Bearer ", "")
        )
        if not uid:
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400
        name = data.get("name", "").strip()
        ttype = data.get("type", "tcp").strip()
        local_port = data.get("local_port")
        local_ip = data.get("local_ip", "127.0.0.1").strip()
        if not name or not local_port:
            return jsonify({"error": "name and local_port required"}), 400
        try:
            local_port = int(local_port)
        except ValueError:
            return jsonify({"error": "local_port must be integer"}), 400
        tunnel, err = db.create_tunnel(uid, name, ttype, local_port, local_ip)
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok", "tunnel": tunnel}), 201

    @app.route("/api/tunnels/<int:tunnel_id>", methods=["DELETE"])
    def delete_tunnel(tunnel_id):
        uid = validate_session(
            request.headers.get("Authorization", "").replace("Bearer ", "")
        )
        if not uid:
            return jsonify({"error": "Unauthorized"}), 401
        ok, err = db.delete_tunnel(tunnel_id, uid)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/tunnels/<int:tunnel_id>/enable", methods=["POST"])
    def enable_tunnel(tunnel_id):
        uid = validate_session(
            request.headers.get("Authorization", "").replace("Bearer ", "")
        )
        if not uid:
            return jsonify({"error": "Unauthorized"}), 401
        tunnel, err = db.enable_tunnel(tunnel_id, uid)
        if err:
            return jsonify({"error": err}), 400
        fp_token = token_mgr.generate_token_for_user(uid)
        if not fp_token:
            db.disable_tunnel(tunnel_id, uid)
            return jsonify({"error": "Failed to get token from fp-multiuser"}), 500
        ftps_cfg = cfg.get("ftps", {})
        return jsonify({
            "status": "ok", "token": fp_token,
            "ftps_ip": ftps_cfg.get("ip", ""),
            "ftps_port": ftps_cfg.get("port", 7000),
            "remote_port": tunnel["remote_port"],
            "tunnel_type": tunnel["tunnel_type"],
        })

    @app.route("/api/tunnels/<int:tunnel_id>/disable", methods=["POST"])
    def disable_tunnel(tunnel_id):
        uid = validate_session(
            request.headers.get("Authorization", "").replace("Bearer ", "")
        )
        if not uid:
            return jsonify({"error": "Unauthorized"}), 401
        ok, err = db.disable_tunnel(tunnel_id, uid)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/user/activate", methods=["POST"])
    def activate_account():
        uid = validate_session(
            request.headers.get("Authorization", "").replace("Bearer ", "")
        )
        if not uid:
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json()
        if not data or "code" not in data:
            return jsonify({"error": "Activation code required"}), 400
        code = data["code"].strip()
        if not code:
            return jsonify({"error": "Activation code required"}), 400
        ok, result = db.use_activation_code(code, uid)
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({
            "status": "ok",
            "new_expires_at": result.isoformat(),
        })

    return app


# ============================================================
# Management API
# ============================================================
def require_api_auth(allowed_ips, api_key):
    """Middleware factory: reject requests without valid API key or from non-allowed IPs."""
    def decorator(f):
        def wrapper(*args, **kwargs):
            if allowed_ips:
                remote = request.remote_addr or "127.0.0.1"
                if remote not in allowed_ips:
                    return jsonify({"error": "Forbidden: IP not allowed"}), 403
            # Check API key from body (POST/PUT) or query param (GET/DELETE)
            key = None
            if request.is_json:
                key = (request.get_json() or {}).get("key")
            if not key:
                key = request.args.get("key")
            if not key or key != api_key:
                return jsonify({"error": "Forbidden: invalid or missing API key"}), 403
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator


def create_management_app(db, cfg):
    mgmt_cfg = cfg.get("management_api", {})
    allowed_ips = mgmt_cfg.get("allowed_ips", ["127.0.0.1"])
    api_key = mgmt_cfg.get("api_key", "")
    app = Flask(__name__)

    # ---- User management ----
    @app.route("/api/management/user", methods=["POST"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_create_user():
        data = request.get_json()
        if not data or not data.get("email") or not data.get("password"):
            return jsonify({"error": "email and password required"}), 400
        email = data["email"].strip().lower()
        password = data["password"]
        user_id = data.get("user_id", "").strip() or None
        expires_at = data.get("expires_at")
        if expires_at:
            try:
                expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M")
            except ValueError:
                return jsonify({"error": "expires_at must be YYYY-MM-DD HH:MM"}), 400
        else:
            expires_at = datetime.now() - timedelta(days=1)
        ok, result = db.admin_create_user(user_id, email, password, expires_at)
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({"status": "ok", "user_id": result}), 201

    @app.route("/api/management/user/<user_id>", methods=["PUT"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_update_user(user_id):
        data = request.get_json() or {}
        email = data.get("email")
        password = data.get("password")
        expires_at = data.get("expires_at")
        new_user_id = data.get("new_user_id")
        if email is not None:
            email = email.strip().lower()
        if expires_at is not None:
            try:
                expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M")
            except ValueError:
                return jsonify({"error": "expires_at must be YYYY-MM-DD HH:MM"}), 400
        ok, result = db.admin_update_user(user_id, email, password, expires_at, new_user_id)
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({"status": "ok", "user": {
            "user_id": result["user_id"],
            "email": result["email"],
            "expires_at": result["expires_at"].isoformat() if result["expires_at"] else None,
        }})

    @app.route("/api/management/user/<user_id>", methods=["DELETE"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_delete_user(user_id):
        ok, err = db.admin_delete_user(user_id)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/management/users", methods=["GET"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_list_users():
        users = db.list_users()
        return jsonify({"users": users})

    # ---- Tunnel management ----
    @app.route("/api/management/tunnel", methods=["POST"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_create_tunnel():
        data = request.get_json()
        if not data or not data.get("user_id") or not data.get("name") or not data.get("local_port"):
            return jsonify({"error": "user_id, name, and local_port required"}), 400
        try:
            local_port = int(data["local_port"])
        except ValueError:
            return jsonify({"error": "local_port must be integer"}), 400
        remote_port = data.get("remote_port")
        if remote_port is not None:
            try:
                remote_port = int(remote_port)
            except ValueError:
                return jsonify({"error": "remote_port must be integer"}), 400
        ok, result = db.admin_create_tunnel(
            data["user_id"], data["name"].strip(),
            data.get("type", "tcp"), data.get("local_ip", "127.0.0.1"),
            local_port, remote_port,
        )
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({"status": "ok", "tunnel": result}), 201

    @app.route("/api/management/tunnel/<int:tunnel_id>", methods=["PUT"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_update_tunnel(tunnel_id):
        data = request.get_json() or {}
        name = data.get("name")
        ttype = data.get("type")
        local_ip = data.get("local_ip")
        local_port = data.get("local_port")
        remote_port = data.get("remote_port")
        user_id = data.get("user_id")
        if local_port is not None:
            try:
                local_port = int(local_port)
            except ValueError:
                return jsonify({"error": "local_port must be integer"}), 400
        if remote_port is not None:
            try:
                remote_port = int(remote_port)
            except ValueError:
                return jsonify({"error": "remote_port must be integer"}), 400
        ok, result = db.admin_update_tunnel(tunnel_id, name, ttype, local_ip, local_port, remote_port, user_id)
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({"status": "ok", "tunnel": result})

    @app.route("/api/management/tunnel/<int:tunnel_id>", methods=["DELETE"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_delete_tunnel(tunnel_id):
        ok, err = db.admin_delete_tunnel(tunnel_id)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/management/tunnels", methods=["GET"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_list_tunnels():
        tunnels = db.admin_list_all_tunnels()
        return jsonify({"tunnels": tunnels})

    # ---- Activation code management ----
    @app.route("/api/management/code", methods=["POST"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_create_code():
        data = request.get_json()
        if not data or not data.get("code"):
            return jsonify({"error": "code required"}), 400
        try:
            parts = data.get("duration", "0-0-0").split("-")
            days, hours, minutes = int(parts[0]), int(parts[1]), int(parts[2])
        except (ValueError, IndexError):
            return jsonify({"error": "duration must be DD-HH-MM format"}), 400
        ok, err = db.admin_create_code(data["code"].strip(), days, hours, minutes)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"}), 201

    @app.route("/api/management/code/<int:code_id>", methods=["PUT"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_update_code(code_id):
        data = request.get_json() or {}
        new_code = data.get("code")
        duration = data.get("duration")
        days = hours = minutes = None
        if duration:
            try:
                parts = duration.split("-")
                days, hours, minutes = int(parts[0]), int(parts[1]), int(parts[2])
            except (ValueError, IndexError):
                return jsonify({"error": "duration must be DD-HH-MM format"}), 400
        ok, result = db.admin_update_code(code_id, new_code, days, hours, minutes)
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({"status": "ok", "code": result})

    @app.route("/api/management/code/<int:code_id>", methods=["DELETE"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_delete_code(code_id):
        ok, err = db.admin_delete_code(code_id)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/management/codes", methods=["GET"])
    @require_api_auth(allowed_ips, api_key)
    def mgmt_list_codes():
        codes = db.list_activation_codes()
        return jsonify({"codes": codes})

    return app


# ============================================================
# CLI Commands
# ============================================================
def cmd_setup():
    cfg = load_config()
    if cfg.get("configured"):
        if input("Already configured. Reconfigure? (y/N): ").strip().lower() != "y":
            return
    setup_config()


def cmd_start(args=None):
    cfg = load_config()
    if not cfg.get("configured"):
        print("Not configured. Run 'python main.py setup' first.")
        sys.exit(1)
    cfg = migrate_config(cfg)
    try:
        ftps = cfg.get("ftps", {})
        db = Database(
            cfg["mysql"],
            ftps.get("port_range_start", 20000),
            ftps.get("port_range_end", 21000),
        )
        db.init_database()
        logger.info("Database initialized")
        # Reset all tunnels to disabled on startup
        db._execute("UPDATE tunnels SET enabled=0 WHERE enabled=1")
        logger.info("All tunnels reset to disabled")
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        sys.exit(1)
    email_sender = EmailSender(cfg["smtp"])
    token_mgr = TokenManager(cfg["fp_multiuser"]["api_url"])
    start_all_processes(cfg)
    ExpiryChecker(db, token_mgr).start()
    app = create_app(db, email_sender, token_mgr, cfg)

    # Start web admin panel if --web on
    if args and args.web == "on":
        web_module = None
        web_py = BASE_DIR / "web" / "web.py"
        if web_py.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("web_admin", str(web_py))
            if spec and spec.loader:
                web_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(web_module)
        if web_module:
            create_web_admin_app = getattr(web_module, "create_web_app", None)
        else:
            create_web_admin_app = None

        if create_web_admin_app:
            web_app, web_ssl_ctx = create_web_admin_app(db, cfg)
            if web_app:
                web_cfg_path = BASE_DIR / "web" / "web_config.json"
                try:
                    with open(web_cfg_path, "r", encoding="utf-8") as f:
                        web_cfg_data = json.load(f)
                except (IOError, json.JSONDecodeError):
                    web_cfg_data = {}
                web_port = web_cfg_data.get("port", 5000)
                proto = "HTTPS" if web_ssl_ctx else "HTTP"
                import socketserver
                from wsgiref.simple_server import WSGIServer, WSGIRequestHandler

                class _ThreadedWSGI(socketserver.ThreadingMixIn, WSGIServer):
                    daemon_threads = True
                    allow_reuse_address = True

                web_server = _ThreadedWSGI(("0.0.0.0", web_port), WSGIRequestHandler)
                web_server.set_app(web_app)
                if web_ssl_ctx:
                    web_server.socket = web_ssl_ctx.wrap_socket(
                        web_server.socket, server_side=True
                    )
                web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
                web_thread.start()
                logger.info(f"Web admin panel started on port {web_port} ({proto})")
            else:
                logger.warning("Web admin panel not started (no web config). Run 'python main.py web setup' first.")
    else:
        logger.info("Web admin panel disabled (use --web on to enable)")
    https_cfg = cfg.get("https", {})
    port = https_cfg.get("port", 8443)
    cert_file = https_cfg.get("cert_file", "")
    key_file = https_cfg.get("key_file", "")
    if cert_file and key_file and os.path.isfile(cert_file) and os.path.isfile(key_file):
        ssl_ctx = (cert_file, key_file)
    else:
        if cert_file and key_file:
            logger.warning(f"SSL files not found (cert={cert_file}, key={key_file}), "
                           "falling back to auto-generated self-signed certificate")
        ssl_ctx = "adhoc"
    # Start management API in a separate thread (if enabled)
    mgmt_cfg = cfg.get("management_api", {})
    if mgmt_cfg.get("enabled", False):
        mgmt_port = mgmt_cfg.get("port", 8444)
        mgmt_app = create_management_app(db, cfg)
        mgmt_thread = threading.Thread(
            target=mgmt_app.run,
            kwargs={"host": "0.0.0.0", "port": mgmt_port, "debug": False, "threaded": True},
            daemon=True,
        )
        mgmt_thread.start()
        logger.info(f"Management API started on port {mgmt_port} (HTTP)")

    logger.info(f"Starting API server on port {port} (HTTPS)...")
    try:
        app.run(host="0.0.0.0", port=port, ssl_context=ssl_ctx, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        stop_all_processes()


def cmd_set_expiry(args):
    cfg = load_config()
    if not cfg.get("configured"):
        print("Not configured. Run 'python main.py setup' first.")
        sys.exit(1)
    try:
        expires_at = datetime.strptime(f"{args.date} {args.time}", "%Y-%m-%d %H:%M")
    except ValueError:
        print("Invalid format. Use: YYYY-MM-DD HH:MM")
        sys.exit(1)
    if expires_at <= datetime.now():
        print("Expiry must be in the future.")
        sys.exit(1)
    try:
        db = Database(cfg["mysql"])
    except Exception as e:
        print(f"DB connection failed: {e}")
        sys.exit(1)
    user = db.get_user_by_id(args.user_id)
    if not user:
        print(f"User {args.user_id} not found.")
        sys.exit(1)
    db.update_expiry(args.user_id, expires_at)
    print(f"✓ Expiry for {args.user_id} set to {expires_at}")
    # Try to generate token via fp-multiuser (may fail if server not running)
    token_mgr = TokenManager(cfg["fp_multiuser"]["api_url"])
    token = token_mgr.generate_token_for_user(args.user_id)
    if token:
        print(f"✓ Token generated for {args.user_id}")
    else:
        print(f"ℹ Token will be generated when server is running and tunnel is enabled.")
        print(f"  Start the server with: python main.py start")


def cmd_list_users(_args=None):
    cfg = load_config()
    if not cfg.get("configured"):
        print("Not configured.")
        return
    try:
        db = Database(cfg["mysql"])
    except Exception as e:
        print(f"DB connection failed: {e}")
        return
    users = db.list_users()
    if not users:
        print("No users.")
        return
    print(f"\n{'ID':<5} {'User ID':<12} {'Email':<30} {'V':<3} {'Expires':<20}")
    print("-" * 75)
    for u in users:
        exp = u["expires_at"].strftime("%Y-%m-%d %H:%M") if u["expires_at"] else "N/A"
        v = "✓" if u["verified"] else "✗"
        print(f"{u['id']:<5} {u['user_id']:<12} {u['email']:<30} {v:<3} {exp:<20}")


def cmd_add_code(args):
    cfg = load_config()
    if not cfg.get("configured"):
        print("Not configured.")
        sys.exit(1)
    try:
        db = Database(cfg["mysql"])
    except Exception as e:
        print(f"DB connection failed: {e}")
        sys.exit(1)
    try:
        parts = args.duration.split("-")
        if len(parts) != 3:
            print("Invalid format. Use: DD-HH-MM")
            sys.exit(1)
        days, hours, minutes = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        print("Invalid format. Use: DD-HH-MM")
        sys.exit(1)
    db.add_activation_code(args.code, days, hours, minutes)
    print(f"✓ Activation code '{args.code}' added (duration: {days}d {hours}h {minutes}m)")


def cmd_list_codes(_args=None):
    cfg = load_config()
    if not cfg.get("configured"):
        print("Not configured.")
        return
    try:
        db = Database(cfg["mysql"])
    except Exception as e:
        print(f"DB connection failed: {e}")
        return
    codes = db.list_activation_codes()
    if not codes:
        print("No activation codes.")
        return
    print(f"\n{'ID':<5} {'Code':<25} {'Duration':<15} {'Used':<5} {'Used By':<12} {'Used At':<20}")
    print("-" * 85)
    for c in codes:
        duration = f"{c['duration_days']}d {c['duration_hours']}h {c['duration_minutes']}m"
        used = "Y" if c["used"] else "N"
        used_at = c["used_at"].strftime("%Y-%m-%d %H:%M") if c["used_at"] else ""
        used_by = c["used_by"] or ""
        print(f"{c['id']:<5} {c['code']:<25} {duration:<15} {used:<5} {used_by:<12} {used_at:<20}")


def cmd_web_setup():
    """Run the web admin panel setup."""
    web_py = BASE_DIR / "web" / "web.py"
    if not web_py.exists():
        print("Web module not found at server/web/web.py")
        sys.exit(1)
    import importlib.util
    spec = importlib.util.spec_from_file_location("web_admin", str(web_py))
    if not spec or not spec.loader:
        print("Failed to load web module")
        sys.exit(1)
    web_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(web_module)
    if hasattr(web_module, "setup_web_config"):
        web_module.setup_web_config()
    else:
        print("setup_web_config not found in web module")
        sys.exit(1)


# ============================================================
# Entry Point
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="FRP Login Tool - Server")
    sp = parser.add_subparsers(dest="command")
    sp.add_parser("setup", help="Initial configuration")
    p_start = sp.add_parser("start", help="Start server")
    p_start.add_argument("--web", choices=["on", "off"], default="off",
                        help="Start web admin panel (requires server/web/web.py)")
    p_exp = sp.add_parser("set-expiry", help="Set user expiration")
    p_exp.add_argument("user_id", help="e.g. user0001")
    p_exp.add_argument("date", help="Date: YYYY-MM-DD")
    p_exp.add_argument("time", help="Time: HH:MM")
    sp.add_parser("list-users", help="List registered users")
    p_code = sp.add_parser("add-code", help="Add activation code")
    p_code.add_argument("code", help="Activation code string")
    p_code.add_argument("duration", help="Duration in DD-HH-MM format (e.g. 30-00-00)")
    sp.add_parser("list-codes", help="List activation codes")
    p_web = sp.add_parser("web", help="Web admin panel management")
    p_web.add_argument("action", choices=["setup"], help="Setup web admin panel")
    args = parser.parse_args()
    if args.command == "setup":
        cmd_setup()
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "set-expiry":
        cmd_set_expiry(args)
    elif args.command == "list-users":
        cmd_list_users()
    elif args.command == "add-code":
        cmd_add_code(args)
    elif args.command == "list-codes":
        cmd_list_codes()
    elif args.command == "web":
        if args.action == "setup":
            cmd_web_setup()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()