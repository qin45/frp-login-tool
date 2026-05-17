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


def setup_config():
    """Interactive CLI setup for first-time configuration."""
    print("=" * 60)
    print("  FRP Login Tool - Server Initial Setup")
    print("=" * 60)

    cfg = {"configured": False}

    print("\n--- SMTP Configuration (for email verification) ---")
    smtp = {}
    smtp["server"] = input("SMTP Server: ").strip()
    smtp["port"] = int(input("SMTP Port (default 587): ").strip() or "587")
    smtp["username"] = input("SMTP Username: ").strip()
    smtp["password"] = input("SMTP Password: ").strip()
    smtp["from_email"] = input("From Email (default same as username): ").strip() or smtp["username"]
    cfg["smtp"] = smtp

    print("\n--- FRP Server Connection Info (sent to clients) ---")
    ftps = {}
    ftps["ip"] = input("FRP Server IP: ").strip()
    ftps["port"] = int(input("FRP Server Port (default 7000): ").strip() or "7000")
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
    fp["api_url"] = input(
        "fp-multiuser API URL (default http://127.0.0.1:8080): "
    ).strip() or "http://127.0.0.1:8080"
    cfg["fp_multiuser"] = fp

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
    def __init__(self, mysql_cfg):
        self.cfg = mysql_cfg
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
            password VARCHAR(255) NOT NULL,
            verified TINYINT(1) DEFAULT 0,
            verification_code VARCHAR(6),
            code_expires_at DATETIME,
            expires_at DATETIME NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
        self._execute(sql)
        # Fix existing tables that may have user_id NOT NULL
        try:
            self._execute("ALTER TABLE users MODIFY user_id VARCHAR(10) UNIQUE")
        except Exception:
            pass
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

    # ---- User operations ----
    def create_user(self, email, password_hash, code):
        user = self._fetch_one(
            "SELECT * FROM users WHERE email=%s AND verification_code=%s AND verified=0",
            (email, code),
        )
        if not user:
            return None
        if user["code_expires_at"] and user["code_expires_at"] < datetime.now():
            return None
        user_id = self._generate_user_id()
        self._execute(
            "UPDATE users SET user_id=%s, password=%s, verified=1, "
            "expires_at=%s WHERE email=%s",
            (user_id, password_hash, datetime.now() - timedelta(days=1), email),
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

    def save_verification_code(self, email, code):
        expires_at = datetime.now() + timedelta(minutes=10)
        existing = self._fetch_one("SELECT id FROM users WHERE email=%s", (email,))
        if existing:
            self._execute(
                "UPDATE users SET verification_code=%s, code_expires_at=%s WHERE email=%s",
                (code, expires_at, email),
            )
        else:
            self._execute(
                "INSERT INTO users (email, password, verification_code, code_expires_at, "
                "verified, expires_at) VALUES (%s, '', %s, %s, 0, %s)",
                (email, code, expires_at, datetime.now()),
            )

    def verify_code(self, email, code):
        user = self._fetch_one(
            "SELECT * FROM users WHERE email=%s AND verification_code=%s AND verified=0",
            (email, code),
        )
        if not user:
            return False
        if user["code_expires_at"] and user["code_expires_at"] < datetime.now():
            return False
        return True

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

    # ---- Tunnel operations ----
    def get_available_port(self):
        used = self._fetch_all(
            "SELECT remote_port FROM tunnels WHERE remote_port IS NOT NULL"
        )
        used_ports = {r["remote_port"] for r in used}
        for port in range(20000, 21001):
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
        subject = "FRP Login Tool - Verification Code"
        body = f"""
        <html><body>
        <h2>FRP Login Tool</h2>
        <p>Your verification code:</p>
        <h1 style="color:#4CAF50;font-size:32px;letter-spacing:5px;">{code}</h1>
        <p>Expires in 10 minutes.</p>
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
            with smtplib.SMTP(self.cfg["server"], self.cfg["port"]) as server:
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
            env["FP_MULTIUSER_BIN"] = str(fp_multiuser_bin)
        start_subprocess(
            "fp-multiuser",
            [sys.executable, str(FP_MULTIUSER_PY)],
            cwd=str(FRPS_DIR),
            env=env,
        )
    else:
        logger.warning(f"fp-multiuser.py not found at {FP_MULTIUSER_PY}")

    if FRPS_BIN.exists() and FRPS_INI.exists():
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
        code = "".join(random.choices(string.digits, k=6))
        db.save_verification_code(email, code)
        ok, err = email_sender.send_verification_code(email, code)
        if ok:
            return jsonify({"status": "ok", "message": "Verification code sent"})
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
        if not db.verify_code(email, code):
            return jsonify({"error": "Invalid or expired code"}), 400
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        user_id = db.create_user(email, pw_hash, code)
        if not user_id:
            return jsonify({"error": "Verification failed, re-request code"}), 400
        token = create_session(user_id)
        user = db.get_user_by_id(user_id)
        return jsonify({
            "status": "ok", "session_token": token, "user_id": user_id,
            "expires_at": user["expires_at"].isoformat() if user["expires_at"] else None,
        })

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


def cmd_start():
    cfg = load_config()
    if not cfg.get("configured"):
        print("Not configured. Run 'python main.py setup' first.")
        sys.exit(1)
    try:
        db = Database(cfg["mysql"])
        db.init_database()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        sys.exit(1)
    email_sender = EmailSender(cfg["smtp"])
    token_mgr = TokenManager(cfg["fp_multiuser"]["api_url"])
    start_all_processes(cfg)
    ExpiryChecker(db, token_mgr).start()
    app = create_app(db, email_sender, token_mgr, cfg)
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


# ============================================================
# Entry Point
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="FRP Login Tool - Server")
    sp = parser.add_subparsers(dest="command")
    sp.add_parser("setup", help="Initial configuration")
    sp.add_parser("start", help="Start server")
    p_exp = sp.add_parser("set-expiry", help="Set user expiration")
    p_exp.add_argument("user_id", help="e.g. user0001")
    p_exp.add_argument("date", help="Date: YYYY-MM-DD")
    p_exp.add_argument("time", help="Time: HH:MM")
    sp.add_parser("list-users", help="List registered users")
    args = parser.parse_args()
    if args.command == "setup":
        cmd_setup()
    elif args.command == "start":
        cmd_start()
    elif args.command == "set-expiry":
        cmd_set_expiry(args)
    elif args.command == "list-users":
        cmd_list_users()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()