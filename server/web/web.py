"""
FRP Login Tool - Web Admin Panel
Flask-based admin interface for managing users, tunnels, and activation codes.
"""
import json
import hashlib
import ipaddress
import os
import random
import socket
import ssl
import string
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


def migrate_web_config(cfg):
    """Fill in missing web config keys with defaults."""
    defaults = {
        "username": "admin",
        "password_hash": "",
        "port": 5000,
        "allowed_ips": [],
        "secret_key": secrets.token_hex(32),
        "ssl": {
            "enabled": True,
            "self_signed": True,
            "cert_file": "",
            "key_file": "",
            "ca_cert_file": "",
        },
    }

    added = []
    for key, val in defaults.items():
        if key not in cfg:
            cfg[key] = val
            added.append(key)

    # Handle nested ssl section
    if "ssl" in cfg and not isinstance(cfg["ssl"], dict):
        cfg["ssl"] = defaults["ssl"]
        added.append("ssl (replaced)")
    elif "ssl" in cfg:
        for key, val in defaults["ssl"].items():
            if key not in cfg["ssl"]:
                cfg["ssl"][key] = val
                added.append(f"ssl.{key}")

    if added:
        print(f"[Web Config] Missing keys filled with defaults: {', '.join(added)}")
        save_web_config(cfg)
    return cfg


def ensure_web_ssl(cfg):
    """Generate self-signed CA + server certificates if SSL enabled and no cert files configured."""
    ssl_cfg = cfg.get("ssl", {})
    if not ssl_cfg.get("enabled", True):
        return None

    cert_file = ssl_cfg.get("cert_file", "")
    key_file = ssl_cfg.get("key_file", "")

    # Already configured with valid files
    if cert_file and key_file and os.path.isfile(cert_file) and os.path.isfile(key_file):
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(cert_file, key_file)
        return ctx

    # Generate self-signed CA and server certs
    ssl_dir = BASE_DIR / "ssl"
    ssl_dir.mkdir(parents=True, exist_ok=True)
    ca_cert_path = ssl_dir / "ca.crt"
    ca_key_path = ssl_dir / "ca.key"
    server_cert_path = ssl_dir / "cert.pem"
    server_key_path = ssl_dir / "key.pem"

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        # CA key
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FRP Login Tool"),
            x509.NameAttribute(NameOID.COMMON_NAME, "FRP Web CA"),
        ])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        with open(ca_key_path, "wb") as f:
            f.write(ca_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
        with open(ca_cert_path, "wb") as f:
            f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

        # Server key + cert signed by CA
        sv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        # Build SAN entries: localhost, 127.0.0.1, and detected LAN IP
        san_entries = [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]
        try:
            tmp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            tmp_sock.connect(("10.255.255.255", 1))
            lan_ip = tmp_sock.getsockname()[0]
            tmp_sock.close()
            if lan_ip and lan_ip != "127.0.0.1":
                san_entries.append(x509.IPAddress(ipaddress.IPv4Address(lan_ip)))
        except Exception:
            pass
        sv_cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FRP Login Tool"),
                x509.NameAttribute(NameOID.COMMON_NAME, "FRP Web Server"),
            ]))
            .issuer_name(ca_name)
            .public_key(sv_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        with open(server_key_path, "wb") as f:
            f.write(sv_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
        with open(server_cert_path, "wb") as f:
            f.write(sv_cert.public_bytes(serialization.Encoding.PEM))

        # Update config
        cfg["ssl"]["cert_file"] = str(server_cert_path)
        cfg["ssl"]["key_file"] = str(server_key_path)
        cfg["ssl"]["ca_cert_file"] = str(ca_cert_path)
        save_web_config(cfg)
        print(f"[Web Config] Self-signed certificates generated in {ssl_dir}")
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(str(server_cert_path), str(server_key_path))
        return ctx

    except ImportError:
        print("[Web Config] cryptography not available, using werkzeug adhoc context")
        return "adhoc"
    except Exception as e:
        print(f"[Web Config] Failed to generate certificates: {e}, using werkzeug adhoc context")
        return "adhoc"


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
    print("\n--- SSL Configuration ---")
    ssl_enabled = input("Enable HTTPS? (Y/n): ").strip().lower() != "n"
    ssl_cfg = {"enabled": ssl_enabled, "self_signed": True,
               "cert_file": "", "key_file": "", "ca_cert_file": ""}
    if ssl_enabled:
        self_signed = input("Use self-signed certificate? (Y/n): ").strip().lower() != "n"
        ssl_cfg["self_signed"] = self_signed
        if not self_signed:
            ssl_cfg["cert_file"] = input("SSL Certificate file path: ").strip()
            ssl_cfg["key_file"] = input("SSL Key file path: ").strip()
    cfg["ssl"] = ssl_cfg
    cfg["secret_key"] = secrets.token_hex(32)
    save_web_config(cfg)
    print(f"✓ Web config saved to {CONFIG_FILE}")
    print("  Self-signed certificates will be auto-generated on startup if needed.")


def create_web_app(db, server_cfg):
    """Create the Flask admin web application. Returns (app, ssl_context)."""
    web_cfg = load_web_config()
    if not web_cfg:
        return None, None

    web_cfg = migrate_web_config(web_cfg)
    ssl_context = ensure_web_ssl(web_cfg)

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

    @app.route("/api/web/tunnel/batch-delete", methods=["POST"])
    @login_required
    @admin_required
    def web_batch_delete_tunnels():
        data = request.form
        ids_str = data.get("ids", "").strip()
        if not ids_str:
            return jsonify({"error": "ids required"}), 400
        ids = []
        for part in ids_str.split(","):
            try:
                ids.append(int(part.strip()))
            except ValueError:
                pass
        if not ids:
            return jsonify({"error": "Invalid ids"}), 400
        deleted = 0
        errors = []
        for tid in ids:
            ok, err = db.admin_delete_tunnel(tid)
            if ok:
                deleted += 1
            else:
                errors.append(err)
        return jsonify({"status": "ok", "deleted": deleted, "errors": errors})

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
        if not code:
            return jsonify({"error": "code required"}), 400
        days = hours = minutes = 0
        duration = data.get("duration", "").strip()
        if duration:
            try:
                days, hours, minutes = parse_duration(duration)
            except (ValueError, IndexError):
                return jsonify({"error": "duration must be DD-HH-MM"}), 400
        else:
            try:
                days = int(data.get("days", 0))
                hours = int(data.get("hours", 0))
                minutes = int(data.get("minutes", 0))
            except (ValueError, TypeError):
                return jsonify({"error": "days, hours, minutes must be integers"}), 400
        if days > 3650:
            return jsonify({"error": "Days cannot exceed 3650"}), 400
        if days == 0 and hours == 0 and minutes == 0:
            return jsonify({"error": "Duration must be greater than 0"}), 400
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
        days = hours = minutes = None
        duration = data.get("duration", "").strip()
        if duration:
            try:
                days, hours, minutes = parse_duration(duration)
            except (ValueError, IndexError):
                return jsonify({"error": "duration must be DD-HH-MM"}), 400
        else:
            d = data.get("days", "").strip()
            h = data.get("hours", "").strip()
            m = data.get("minutes", "").strip()
            if d or h or m:
                try:
                    days = int(d) if d else None
                    hours = int(h) if h else None
                    minutes = int(m) if m else None
                except (ValueError, TypeError):
                    return jsonify({"error": "days, hours, minutes must be integers"}), 400
                if days is not None and days > 3650:
                    return jsonify({"error": "Days cannot exceed 3650"}), 400
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

    @app.route("/api/web/code/batch-create", methods=["POST"])
    @login_required
    @admin_required
    def web_batch_create_codes():
        data = request.form
        try:
            count = int(data.get("count", 0))
            days = int(data.get("days", 0))
            hours = int(data.get("hours", 0))
            minutes = int(data.get("minutes", 0))
        except (ValueError, TypeError):
            return jsonify({"error": "count, days, hours, minutes must be integers"}), 400
        if count < 1 or count > 99:
            return jsonify({"error": "count must be 1-99"}), 400
        if days > 3650:
            return jsonify({"error": "Days cannot exceed 3650"}), 400
        if days == 0 and hours == 0 and minutes == 0:
            return jsonify({"error": "Duration must be greater than 0"}), 400
        created = []
        errors = []
        for _ in range(count):
            code = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            ok, err = db.admin_create_code(code, days, hours, minutes)
            if ok:
                created.append(code)
            else:
                errors.append(err)
        return jsonify({"status": "ok", "created": created, "errors": errors})

    @app.route("/api/web/code/batch-delete", methods=["POST"])
    @login_required
    @admin_required
    def web_batch_delete_codes():
        data = request.form
        ids_str = data.get("ids", "").strip()
        if not ids_str:
            return jsonify({"error": "ids required"}), 400
        ids = []
        for part in ids_str.split(","):
            try:
                ids.append(int(part.strip()))
            except ValueError:
                pass
        if not ids:
            return jsonify({"error": "Invalid ids"}), 400
        deleted = 0
        errors = []
        for tid in ids:
            ok, err = db.admin_delete_code(tid)
            if ok:
                deleted += 1
            else:
                errors.append(err)
        return jsonify({"status": "ok", "deleted": deleted, "errors": errors})

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
        ssl_cfg = web_config.get("ssl", {})
        return render_template("settings.html",
                               server_config=json.dumps(server_config, indent=2, ensure_ascii=False),
                               web_config=json.dumps(web_config, indent=2, ensure_ascii=False),
                               server_cfg_path=server_cfg_path,
                               web_cfg_path=web_cfg_path,
                               ssl_enabled=ssl_cfg.get("enabled", True),
                               is_self_signed=ssl_cfg.get("self_signed", True),
                               ca_cert_available=bool(ssl_cfg.get("ca_cert_file", "")) and os.path.isfile(ssl_cfg["ca_cert_file"]))

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

    @app.route("/api/web/settings/change-password", methods=["POST"])
    @login_required
    @admin_required
    def web_change_password():
        data = request.form
        new = data.get("new_password", "").strip()
        if not new:
            return jsonify({"error": "New password required"}), 400
        if len(new) < 6:
            return jsonify({"error": "New password must be >= 6 characters"}), 400
        cfg = load_web_config()
        cfg["password_hash"] = hashlib.sha256(new.encode()).hexdigest()
        save_web_config(cfg)
        return jsonify({"status": "ok", "message": "Password changed successfully"})

    # ==================== SSL / CA Cert ====================
    @app.route("/api/web/settings/ca-cert")
    @login_required
    @admin_required
    def web_download_ca_cert():
        web_cfg = load_web_config()
        ca_file = (web_cfg.get("ssl") or {}).get("ca_cert_file", "")
        if ca_file and os.path.isfile(ca_file):
            from flask import send_file
            return send_file(ca_file, as_attachment=True,
                             download_name="frp-web-ca.crt",
                             mimetype="application/x-x509-ca-cert")
        return jsonify({"error": "CA certificate not available"}), 404

    return app, ssl_context
