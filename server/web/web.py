"""
FRP Login Tool - Web Admin Panel
Flask-based admin interface for managing users, tunnels, and activation codes.
"""
import json
import hashlib
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, request, jsonify, render_template, redirect, session, url_for

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = BASE_DIR / "web_config.json"


def load_web_config():
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except (json.JSONDecodeError, IOError):
        return {}


def save_web_config(cfg):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def setup_web_config():
    """Interactive CLI to configure the admin web panel."""
    print("=" * 60)
    print("  FRP Login Tool - Admin Web Panel Setup")
    print("=" * 60)
    cfg = {}
    cfg["username"] = input("Admin Username (default admin): ").strip() or "admin"
    password = input("Admin Password: ").strip()
    while not password:
        password = input("Admin Password (required): ").strip()
    cfg["password_hash"] = hashlib.sha256(password.encode()).hexdigest()
    cfg["port"] = int(input("Web Panel Port (default 5000): ").strip() or "5000")
    allowed = input("Allowed IPs (comma-separated, empty = no restriction): ").strip()
    cfg["allowed_ips"] = [ip.strip() for ip in allowed.split(",") if ip.strip()] if allowed else []
    cfg["secret_key"] = secrets.token_hex(32)
    save_web_config(cfg)
    print(f"✓ Web config saved to {CONFIG_FILE}")


def create_web_app(db, server_cfg):
    """Create the Flask admin web application."""
    web_cfg = load_web_config()
    if not web_cfg:
        return None

    app = Flask(__name__,
                template_folder=str(BASE_DIR / "templates"),
                static_folder=str(BASE_DIR / "static") if (BASE_DIR / "static").exists() else None)
    app.secret_key = web_cfg.get("secret_key", secrets.token_hex(32))
    allowed_ips = web_cfg.get("allowed_ips", [])

    def check_ip():
        if allowed_ips:
            remote = request.remote_addr or "127.0.0.1"
            if remote not in allowed_ips:
                return False
        return True

    def login_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "logged_in" not in session:
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper

    def admin_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not check_ip():
                return "Forbidden: IP not allowed", 403
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper

    def parse_duration(dur_str):
        parts = dur_str.split("-")
        return int(parts[0]), int(parts[1]), int(parts[2])

    # ==================== Auth ====================
    @app.route("/login", methods=["GET", "POST"])
    @admin_required
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            pw_hash = hashlib.sha256(password.encode()).hexdigest()
            if username == web_cfg.get("username") and pw_hash == web_cfg.get("password_hash"):
                session["logged_in"] = True
                return redirect(url_for("users"))
            return render_template("login.html", error="用户名或密码错误")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ==================== Users ====================
    @app.route("/")
    @login_required
    @admin_required
    def index():
        return redirect(url_for("users"))

    @app.route("/users")
    @login_required
    @admin_required
    def users():
        user_list = db.list_users()
        return render_template("users.html", users=user_list)

    @app.route("/api/web/user/create", methods=["POST"])
    @login_required
    @admin_required
    def web_create_user():
        data = request.form
        email = data.get("email", "").strip().lower()
        password = data.get("password", "").strip()
        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400
        user_id = data.get("user_id", "").strip() or None
        expires_at = data.get("expires_at", "").strip()
        if expires_at:
            try:
                expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M")
            except ValueError:
                return jsonify({"error": "Invalid date format"}), 400
        else:
            expires_at = datetime.now() - timedelta(days=1)
        ok, result = db.admin_create_user(user_id, email, password, expires_at)
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({"status": "ok", "user_id": result})

    @app.route("/api/web/user/<user_id>/update", methods=["POST"])
    @login_required
    @admin_required
    def web_update_user(user_id):
        data = request.form
        email = data.get("email", "").strip().lower() or None
        password = data.get("password", "").strip() or None
        new_user_id = data.get("new_user_id", "").strip() or None
        expires_at = data.get("expires_at", "").strip()
        if expires_at:
            try:
                expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M")
            except ValueError:
                return jsonify({"error": "Invalid date format"}), 400
        else:
            expires_at = None
        ok, result = db.admin_update_user(user_id, email, password, expires_at, new_user_id)
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/web/user/<user_id>/delete", methods=["POST"])
    @login_required
    @admin_required
    def web_delete_user(user_id):
        ok, err = db.admin_delete_user(user_id)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"})

    # ==================== Tunnels ====================
    @app.route("/tunnels")
    @login_required
    @admin_required
    def tunnels():
        tunnel_list = db.admin_list_all_tunnels()
        users = db.list_users()
        return render_template("tunnels.html", tunnels=tunnel_list, users=users)

    @app.route("/api/web/tunnel/create", methods=["POST"])
    @login_required
    @admin_required
    def web_create_tunnel():
        data = request.form
        uid = data.get("user_id", "").strip()
        name = data.get("name", "").strip()
        local_port = data.get("local_port", "").strip()
        if not uid or not name or not local_port:
            return jsonify({"error": "user_id, name, local_port required"}), 400
        try:
            local_port = int(local_port)
        except ValueError:
            return jsonify({"error": "local_port must be integer"}), 400
        ttype = data.get("type", "tcp")
        local_ip = data.get("local_ip", "127.0.0.1")
        remote_port = data.get("remote_port", "").strip()
        remote_port = int(remote_port) if remote_port else None
        ok, result = db.admin_create_tunnel(uid, name, ttype, local_ip, local_port, remote_port)
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/web/tunnel/<int:tunnel_id>/update", methods=["POST"])
    @login_required
    @admin_required
    def web_update_tunnel(tunnel_id):
        data = request.form
        name = data.get("name", "").strip() or None
        ttype = data.get("type", "").strip() or None
        local_ip = data.get("local_ip", "").strip() or None
        local_port = data.get("local_port", "").strip()
        remote_port = data.get("remote_port", "").strip()
        user_id = data.get("user_id", "").strip() or None
        local_port = int(local_port) if local_port else None
        remote_port = int(remote_port) if remote_port else None
        ok, result = db.admin_update_tunnel(tunnel_id, name, ttype, local_ip, local_port, remote_port, user_id)
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/web/tunnel/<int:tunnel_id>/delete", methods=["POST"])
    @login_required
    @admin_required
    def web_delete_tunnel(tunnel_id):
        ok, err = db.admin_delete_tunnel(tunnel_id)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"})

    # ==================== Activation Codes ====================
    @app.route("/codes")
    @login_required
    @admin_required
    def codes():
        code_list = db.list_activation_codes()
        return render_template("codes.html", codes=code_list)

    @app.route("/api/web/code/create", methods=["POST"])
    @login_required
    @admin_required
    def web_create_code():
        data = request.form
        code = data.get("code", "").strip()
        duration = data.get("duration", "").strip()
        if not code or not duration:
            return jsonify({"error": "code and duration required"}), 400
        try:
            days, hours, minutes = parse_duration(duration)
        except (ValueError, IndexError):
            return jsonify({"error": "duration must be DD-HH-MM"}), 400
        ok, err = db.admin_create_code(code, days, hours, minutes)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/web/code/<int:code_id>/update", methods=["POST"])
    @login_required
    @admin_required
    def web_update_code(code_id):
        data = request.form
        new_code = data.get("code", "").strip() or None
        duration = data.get("duration", "").strip()
        days = hours = minutes = None
        if duration:
            try:
                days, hours, minutes = parse_duration(duration)
            except (ValueError, IndexError):
                return jsonify({"error": "duration must be DD-HH-MM"}), 400
        ok, result = db.admin_update_code(code_id, new_code, days, hours, minutes)
        if not ok:
            return jsonify({"error": result}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/web/code/<int:code_id>/delete", methods=["POST"])
    @login_required
    @admin_required
    def web_delete_code(code_id):
        ok, err = db.admin_delete_code(code_id)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"status": "ok"})

    # ==================== Settings ====================
    @app.route("/settings")
    @login_required
    @admin_required
    def settings():
        server_cfg_path = str(BASE_DIR.parent / "config.json")
        web_cfg_path = str(CONFIG_FILE)
        server_config = {}
        web_config = load_web_config()
        try:
            with open(server_cfg_path, "r", encoding="utf-8") as f:
                server_config = json.load(f)
        except (IOError, json.JSONDecodeError):
            server_config = {"error": "Cannot read server config"}
        return render_template("settings.html",
                               server_config=json.dumps(server_config, indent=2, ensure_ascii=False),
                               web_config=json.dumps(web_config, indent=2, ensure_ascii=False),
                               server_cfg_path=server_cfg_path,
                               web_cfg_path=web_cfg_path)

    @app.route("/api/web/settings/server", methods=["POST"])
    @login_required
    @admin_required
    def web_save_server_config():
        data = request.form.get("config", "").strip()
        if not data:
            return jsonify({"error": "Config content required"}), 400
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as e:
            return jsonify({"error": f"Invalid JSON: {e}"}), 400
        path = BASE_DIR.parent / "config.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=4, ensure_ascii=False)
        return jsonify({"status": "ok", "message": "Server config saved. Restart server to apply changes."})

    @app.route("/api/web/settings/web", methods=["POST"])
    @login_required
    @admin_required
    def web_save_web_config():
        data = request.form.get("config", "").strip()
        if not data:
            return jsonify({"error": "Config content required"}), 400
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as e:
            return jsonify({"error": f"Invalid JSON: {e}"}), 400
        save_web_config(parsed)
        app.secret_key = parsed.get("secret_key", app.secret_key)
        return jsonify({"status": "ok", "message": "Web config saved. Restart server to apply changes."})

    return app
