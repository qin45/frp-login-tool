#!/usr/bin/env python3
"""
FRP Login Tool - Client
GUI desktop client for managing FRP tunnels with remote server.
Supports Chinese and English languages.
"""
import hashlib
import io
import json
import shutil
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import zipfile

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(sys.executable).parent.resolve() if getattr(sys, 'frozen', False) else Path(__file__).parent.resolve()
FRPC_DIR = BASE_DIR / "frpc"
FRPC_INI = FRPC_DIR / "frpc.ini"
FRPC_EXE = FRPC_DIR / "frpc.exe"
CONFIG_FILE = BASE_DIR / "client_config.json"

# When frozen, copy bundled frpc.exe from _MEIPASS to writable runtime location
if getattr(sys, 'frozen', False):
    bundled_frpc = Path(sys._MEIPASS) / "frpc" / "frpc.exe"
    if bundled_frpc.exists() and not FRPC_EXE.exists():
        FRPC_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(bundled_frpc), str(FRPC_EXE))

frpc_process = None
frpc_process_lock = threading.Lock()

# ============================================================
# Language Support
# ============================================================
LANG_ZH = "zh"
LANG_EN = "en"

LANGUAGES = {
    LANG_ZH: {
        # General
        "lang_name": "中文",
        "lang_toggle": "English",
        "frp_title": "FRP 登录工具",
        "error": "错误",
        "success": "成功",
        "info": "提示",
        "warning": "警告",
        "confirm": "确认",
        "ok": "确定",
        "cancel": "取消",
        "create": "创建",
        # Server connection
        "server_connection": "服务器连接",
        "server_url": "服务器地址:",
        "connect": "连接",
        "connected_to": "已连接到",
        "server_connected": "服务器已连接，请登录或注册。",
        "enter_server_url": "请输入服务器地址",
        "testing_connection": "正在测试连接...",
        "connection_failed": "连接失败:",
        "server_responded": "服务器响应",
        "disable_ssl_verify": "禁用SSL证书验证",
        # Login / Register
        "login": "登录",
        "register": "注册",
        "email": "邮箱:",
        "password": "密码:",
        "confirm_password": "确认密码:",
        "code": "验证码:",
        "send_code": "发送验证码",
        "register_btn": "注册",
        "login_btn": "登录",
        "connect_hint": "连接到服务器开始",
        "code_sent": "验证码已发送到您的邮箱",
        "all_fields_required": "所有字段为必填项",
        "passwords_not_match": "两次密码输入不一致",
        "password_too_short": "密码长度不能少于6位",
        "login_failed": "登录失败",
        "registration_failed": "注册失败",
        # Account info
        "account_info": "账户信息",
        "user": "用户:",
        "email_label": "邮箱:",
        "expiration": "到期时间:",
        "expired": "已到期",
        "expired_status": "已到期 - 无法启用隧道",
        "active": "活跃",
        "active_status": "正常",
        # Tunnels
        "tunnels": "隧道 (最多10条)",
        "tunnel_id": "ID",
        "tunnel_name": "名称",
        "tunnel_type": "类型",
        "tunnel_local": "本地",
        "tunnel_remote": "远程端口",
        "tunnel_status": "状态",
        "tunnel_enabled": "已启用",
        "tunnel_disabled": "已禁用",
        "create_tunnel": "创建隧道",
        "edit_tunnel": "修改隧道",
        "edit": "修改",
        "enable": "启用",
        "disable": "禁用",
        "delete": "删除",
        "frpc_idle": "frpc: 空闲",
        "frpc_running": "frpc: 运行中",
        "logout": "退出登录",
        "refresh": "刷新",
        "select_tunnel": "请选择一条隧道",
        "tunnel_already_enabled": "隧道已启用",
        "tunnel_not_enabled": "隧道未启用",
        "account_expired": "账户已到期",
        "disable_before_delete": "请先禁用隧道再删除",
        "confirm_delete": "确定要删除隧道",
        "delete_success": "删除成功",
        "delete_failed": "删除失败",
        "enable_failed": "启用失败",
        "disable_failed": "禁用失败",
        # Create tunnel dialog
        "create_tunnel_title": "创建隧道",
        "name_label": "名称:",
        "type_label": "类型:",
        "local_ip_label": "本地 IP:",
        "local_port_label": "本地端口:",
        "name_port_required": "名称和端口为必填项",
        "port_must_be_number": "端口必须为数字",
        # Enable info dialog
        "tunnel_enabled_title": "隧道已启用",
        "tunnel_enabled_msg": "隧道已启用成功",
        "frpc_started_msg": "frpc核心启动成功",
        "copy_address": "复制外网地址",
        "address_copied": "外网地址已复制",
        "enable_then_copy": "请先启用隧道后再复制外网地址",
        # frpc
        "frpc_not_found": "未找到 frpc.exe",
        "frpc_ini_not_found": "未找到 frpc.ini",
        "frpc_started": "frpc 已启动",
        "frpc_stopped": "frpc 已停止",
        "frpc_force_killed": "frpc 已强制结束",
        "frpc_not_running": "frpc 未运行",
        "start_frpc_failed": "启动 frpc 失败",
        # Tunnel disable
        "tunnel_disabled": "隧道已禁用",
        # Remember password
        "remember_password": "记住密码",
        # Reset password
        "reset_password": "重置密码",
        "new_password": "新密码:",
        "reset_btn": "重置密码",
        "reset_code_sent": "验证码已发送到您的邮箱",
        "password_reset_success": "密码重置成功",
        "reset_failed": "重置失败",
        "send_reset_code": "发送验证码",
        # Activation code
        "activate": "激活",
        "activation_code": "激活码",
        "enter_activation_code": "请输入激活码",
        "activation_success": "激活成功",
        "activation_failed": "激活失败",
        "new_expiry": "新的到期时间",
        # Only one tunnel
        "only_one_tunnel": "同时只能启用一条隧道",
        # Core file download
        "missing_core_file": "缺失核心文件",
        "missing_core_file_prompt": "缺失核心文件，是否自动下载？",
        "downloading": "正在下载核心文件...",
        "verifying": "正在校验文件完整性...",
        "extracting": "正在解压...",
        "core_download_success": "核心文件下载成功\n若杀毒软件报毒请添加排除项，本软件及frp核心完全开源，请放心使用",
        "core_download_failed": "核心文件下载失败",
        "sha256_mismatch": "文件校验失败，下载文件可能已被篡改",
    },
    LANG_EN: {
        "lang_name": "English",
        "lang_toggle": "中文",
        "frp_title": "FRP Login Tool",
        "error": "Error",
        "success": "Success",
        "info": "Info",
        "warning": "Warning",
        "confirm": "Confirm",
        "ok": "OK",
        "cancel": "Cancel",
        "create": "Create",
        "server_connection": "Server Connection",
        "server_url": "Server URL:",
        "connect": "Connect",
        "connected_to": "Connected to",
        "server_connected": "Server connected. Login or register.",
        "enter_server_url": "Please enter a server URL",
        "testing_connection": "Testing connection...",
        "connection_failed": "Connection failed:",
        "server_responded": "Server responded",
        "disable_ssl_verify": "Disable SSL Verify",
        "login": "Login",
        "register": "Register",
        "email": "Email:",
        "password": "Password:",
        "confirm_password": "Confirm:",
        "code": "Code:",
        "send_code": "Send Code",
        "register_btn": "Register",
        "login_btn": "Login",
        "connect_hint": "Connect to a server to begin",
        "code_sent": "Verification code sent to your email",
        "all_fields_required": "All fields required",
        "passwords_not_match": "Passwords do not match",
        "password_too_short": "Password must be at least 6 characters",
        "login_failed": "Login failed",
        "registration_failed": "Registration failed",
        "account_info": "Account Info",
        "user": "User:",
        "email_label": "Email:",
        "expiration": "Expiration:",
        "expired": "Expired",
        "expired_status": "Expired - tunnels cannot be enabled",
        "active": "Active",
        "active_status": "Active",
        "tunnels": "Tunnels (max 10)",
        "tunnel_id": "ID",
        "tunnel_name": "Name",
        "tunnel_type": "Type",
        "tunnel_local": "Local",
        "tunnel_remote": "Remote Port",
        "tunnel_status": "Status",
        "tunnel_enabled": "Enabled",
        "tunnel_disabled": "Disabled",
        "create_tunnel": "Create Tunnel",
        "edit_tunnel": "Edit Tunnel",
        "edit": "Edit",
        "enable": "Enable",
        "disable": "Disable",
        "delete": "Delete",
        "frpc_idle": "frpc: idle",
        "frpc_running": "frpc: RUNNING",
        "logout": "Logout",
        "refresh": "Refresh",
        "select_tunnel": "Please select a tunnel",
        "tunnel_already_enabled": "Tunnel already enabled",
        "tunnel_not_enabled": "Tunnel is not enabled",
        "account_expired": "Account has expired",
        "disable_before_delete": "Disable the tunnel before deleting",
        "confirm_delete": "Delete tunnel",
        "delete_success": "Tunnel deleted",
        "delete_failed": "Failed to delete",
        "enable_failed": "Failed to enable",
        "disable_failed": "Failed to disable",
        "create_tunnel_title": "Create Tunnel",
        "name_label": "Name:",
        "type_label": "Type:",
        "local_ip_label": "Local IP:",
        "local_port_label": "Local Port:",
        "name_port_required": "Name and port required",
        "port_must_be_number": "Port must be a number",
        "tunnel_enabled_title": "Tunnel Enabled",
        "tunnel_enabled_msg": "Tunnel Enabled Successfully",
        "frpc_started_msg": "frpc core started successfully",
        "copy_address": "Copy External Address",
        "address_copied": "External address copied",
        "enable_then_copy": "Please enable the tunnel first",
        "frpc_not_found": "frpc.exe not found",
        "frpc_ini_not_found": "frpc.ini not found",
        "frpc_started": "frpc started",
        "frpc_stopped": "frpc stopped",
        "frpc_force_killed": "frpc force killed",
        "frpc_not_running": "frpc not running",
        "start_frpc_failed": "Failed to start frpc",
        "tunnel_disabled": "Tunnel disabled",
        "remember_password": "Remember Password",
        "reset_password": "Reset Password",
        "new_password": "New Password:",
        "reset_btn": "Reset Password",
        "reset_code_sent": "Verification code sent to your email",
        "password_reset_success": "Password reset successfully",
        "reset_failed": "Reset failed",
        "send_reset_code": "Send Code",
        # Activation code
        "activate": "Activate",
        "activation_code": "Activation Code",
        "enter_activation_code": "Please enter activation code",
        "activation_success": "Activation successful",
        "activation_failed": "Activation failed",
        "new_expiry": "New expiration",
        # Only one tunnel
        "only_one_tunnel": "Only one tunnel can be enabled at a time",
        # Core file download
        "missing_core_file": "Missing Core File",
        "missing_core_file_prompt": "Missing core file. Download automatically?",
        "downloading": "Downloading core file...",
        "verifying": "Verifying file integrity...",
        "extracting": "Extracting...",
        "core_download_success": "Core file downloaded successfully\nIf your antivirus flags it, please add an exclusion.\nThis software and frp core are fully open source.",
        "core_download_failed": "Core file download failed",
        "sha256_mismatch": "SHA256 mismatch - the downloaded file may have been tampered with",
    },
}


# ============================================================
# Client Config
# ============================================================
def load_client_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_client_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


# ============================================================
# API Client
# ============================================================
class ApiClient:
    def __init__(self):
        self.base_url = ""
        self.session_token = ""
        self._verify = True
        self.cfg = load_client_config()
        if "server_url" in self.cfg:
            self.base_url = self.cfg["server_url"]
        if "session_token" in self.cfg:
            self.session_token = self.cfg["session_token"]
        if "disable_ssl_verify" in self.cfg:
            self._verify = not self.cfg["disable_ssl_verify"]

    def set_server(self, server_url):
        self.base_url = server_url.rstrip("/")
        self.cfg["server_url"] = self.base_url
        save_client_config(self.cfg)

    def set_ssl_verify(self, enabled):
        self._verify = enabled

    @property
    def ssl_verify_enabled(self):
        return self._verify

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.session_token:
            h["Authorization"] = f"Bearer {self.session_token}"
        return h

    def _post(self, path, data=None):
        url = f"{self.base_url}{path}"
        return requests.post(url, json=data, headers=self._headers(), verify=self._verify, timeout=15)

    def _get(self, path):
        url = f"{self.base_url}{path}"
        return requests.get(url, headers=self._headers(), verify=self._verify, timeout=15)

    def _delete(self, path):
        url = f"{self.base_url}{path}"
        return requests.delete(url, headers=self._headers(), verify=self._verify, timeout=15)

    def register_send_code(self, email):
        return self._post("/api/auth/register", {"email": email})

    def register_verify(self, email, code, password):
        resp = self._post("/api/auth/register/verify", {
            "email": email, "code": code, "password": password,
        })
        if resp.status_code == 200:
            data = resp.json()
            self.session_token = data.get("session_token", "")
            self.cfg["session_token"] = self.session_token
            save_client_config(self.cfg)
        return resp

    def reset_send_code(self, email):
        return self._post("/api/auth/reset-password/send-code", {"email": email})

    def reset_password(self, email, code, new_password):
        return self._post("/api/auth/reset-password", {
            "email": email, "code": code, "new_password": new_password,
        })

    def login(self, email, password):
        resp = self._post("/api/auth/login", {"email": email, "password": password})
        if resp.status_code == 200:
            data = resp.json()
            self.session_token = data.get("session_token", "")
            self.cfg["session_token"] = self.session_token
            save_client_config(self.cfg)
        return resp

    def get_user_info(self):
        return self._get("/api/user/info")

    def list_tunnels(self):
        return self._get("/api/tunnels")

    def create_tunnel(self, name, tunnel_type, local_port, local_ip="127.0.0.1"):
        return self._post("/api/tunnels", {
            "name": name, "type": tunnel_type,
            "local_port": local_port, "local_ip": local_ip,
        })

    def delete_tunnel(self, tunnel_id):
        return self._delete(f"/api/tunnels/{tunnel_id}")

    def update_tunnel(self, tunnel_id, name=None, tunnel_type=None, local_ip=None, local_port=None):
        data = {}
        if name is not None:
            data["name"] = name
        if tunnel_type is not None:
            data["type"] = tunnel_type
        if local_ip is not None:
            data["local_ip"] = local_ip
        if local_port is not None:
            data["local_port"] = local_port
        return self._post(f"/api/tunnels/{tunnel_id}/update", data)

    def enable_tunnel(self, tunnel_id):
        return self._post(f"/api/tunnels/{tunnel_id}/enable")

    def disable_tunnel(self, tunnel_id):
        return self._post(f"/api/tunnels/{tunnel_id}/disable")

    def activate(self, code):
        return self._post("/api/user/activate", {"code": code})

    def logout(self):
        self.session_token = ""
        self.cfg.pop("session_token", None)
        save_client_config(self.cfg)


# ============================================================
# frpc Manager
# ============================================================
def write_frpc_ini(server_addr, server_port, user, token, tunnel_name,
                   tunnel_type, local_port, remote_port, local_ip="127.0.0.1"):
    content = f"""[common]
server_addr = {server_addr}
server_port = {server_port}
user = {user}
meta_token = {token}

[{tunnel_name}]
type = {tunnel_type}
local_ip = {local_ip}
local_port = {local_port}
remote_port = {remote_port}
"""
    FRPC_DIR.mkdir(parents=True, exist_ok=True)
    with open(FRPC_INI, "w", encoding="utf-8") as f:
        f.write(content)


def start_frpc():
    global frpc_process
    with frpc_process_lock:
        if frpc_process and frpc_process.poll() is None:
            return True, "frpc already running"
        if not FRPC_EXE.exists():
            return False, f"frpc.exe not found at {FRPC_EXE}"
        if not FRPC_INI.exists():
            return False, "frpc.ini not found"
        try:
            startupinfo = None
            creationflags = 0
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = subprocess.CREATE_NO_WINDOW
            frpc_process = subprocess.Popen(
                [str(FRPC_EXE), "-c", str(FRPC_INI)],
                cwd=str(FRPC_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )

            def log_output():
                for line in iter(frpc_process.stdout.readline, b""):
                    if line:
                        print(f"[frpc] {line.decode('utf-8', errors='replace').rstrip()}")
                    else:
                        break

            threading.Thread(target=log_output, daemon=True).start()
            return True, f"frpc started (PID {frpc_process.pid})"
        except Exception as e:
            return False, str(e)


def stop_frpc():
    global frpc_process
    with frpc_process_lock:
        if not frpc_process or frpc_process.poll() is not None:
            frpc_process = None
            return True, "frpc not running"
        try:
            if sys.platform == "win32":
                frpc_process.terminate()
            else:
                frpc_process.send_signal(signal.SIGINT)
            frpc_process.wait(timeout=10)
            frpc_process = None
            return True, "frpc stopped"
        except subprocess.TimeoutExpired:
            frpc_process.kill()
            frpc_process.wait()
            frpc_process = None
            return True, "frpc force killed"
        except Exception as e:
            return False, str(e)


def is_frpc_running():
    with frpc_process_lock:
        return frpc_process is not None and frpc_process.poll() is None


# ============================================================
# Tunnel Enable Info Dialog
# ============================================================
class TunnelEnableDialog(tk.Toplevel):
    def __init__(self, parent, tunnel, enable_data, tr_func):
        super().__init__(parent)
        self.tr = tr_func
        self.enable_data = enable_data
        self.title(self.tr("tunnel_enabled_title"))
        self.geometry("500x450")
        self.resizable(True, True)
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=self.tr("tunnel_enabled_msg"),
                  font=("", 14, "bold")).pack(pady=5)

        info = (
            f"Tunnel: {tunnel.get('name', '')}\n"
            f"Type: {tunnel.get('tunnel_type', '')}\n"
            f"Local: {tunnel.get('local_ip', '127.0.0.1')}:{tunnel.get('local_port', '')}\n"
            f"Remote Port: {enable_data.get('remote_port', '')}\n"
            f"FRP Server: {enable_data.get('ftps_ip', '')}:{enable_data.get('ftps_port', '')}\n"
            f"Token: {enable_data.get('token', '')[:20]}..."
        )
        ttk.Label(frame, text=info, justify=tk.LEFT).pack(pady=10)

        status_label = ttk.Label(
            frame, text=self.tr("frpc_started_msg"), foreground="green"
        )
        status_label.pack(pady=5)

        # External address display + copy button
        ext_addr = f"{enable_data.get('ftps_ip', '')}:{enable_data.get('remote_port', '')}"
        addr_frame = ttk.Frame(frame)
        addr_frame.pack(pady=10)
        ttk.Label(addr_frame, text=ext_addr,
                  font=("", 12, "bold"), foreground="blue").pack()
        self.copy_btn = ttk.Button(addr_frame, text=self.tr("copy_address"),
                                   command=self._copy_address)
        self.copy_btn.pack(pady=5)

        ttk.Button(frame, text=self.tr("ok"), command=self.destroy).pack(pady=10)

    def _copy_address(self):
        ext_addr = f"{self.enable_data.get('ftps_ip', '')}:{self.enable_data.get('remote_port', '')}"
        self.clipboard_clear()
        self.clipboard_append(ext_addr)
        self.copy_btn.configure(text=self.tr("address_copied"))
        self.after(2000, lambda: self.copy_btn.configure(text=self.tr("copy_address")))


# ============================================================
# Main Application
# ============================================================
class FrpLoginApp:
    def __init__(self):
        self.api = ApiClient()
        cfg = load_client_config()
        self.lang = cfg.get("lang", LANG_ZH)
        self.root = tk.Tk()
        self.root.title(self._tr("frp_title"))
        self.root.geometry("900x650")
        self.root.minsize(700, 500)
        self.current_user_id = None
        self.current_user_info = None
        self.ftps_ip = ""
        self.ftps_port = ""
        self._refresh_timer = None
        self._cooldown_sec = 0
        self._reset_cooldown_sec = 0

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Header.TLabel", font=("", 16, "bold"))
        style.configure("Status.TLabel", font=("", 10))
        style.configure("Accent.TButton", font=("", 10, "bold"))

        self.container = ttk.Frame(self.root)
        self.container.pack(fill=tk.BOTH, expand=True)

        self.login_frame = None
        self.main_frame = None

        # Check / auto-download frpc.exe before showing UI
        self.root.after(100, self._ensure_frpc_core)

        self._show_login()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _tr(self, key):
        """Translate a key to the current language."""
        return LANGUAGES.get(self.lang, LANGUAGES[LANG_ZH]).get(key, key)

    def _tr_error(self, msg):
        """Translate known server error messages for Chinese mode."""
        if self.lang != LANG_ZH or not msg:
            return msg
        _err_map = {
            "Invalid email or password": "邮箱或密码错误",
            "Email already registered": "该邮箱已被注册",
            "Password must be >= 6 characters": "密码长度不能少于6位",
            "No verification code requested": "未请求验证码",
            "Invalid verification code": "验证码错误",
            "Verification code expired": "验证码已过期",
            "Email not registered": "该邮箱未注册",
            "Maximum 10 tunnels per user": "每用户最多创建10条隧道",
            "No available ports": "没有可用端口",
            "Tunnel not found": "隧道不存在",
            "Tunnel already enabled": "隧道已启用",
            "Tunnel is not enabled": "隧道未启用",
            "Account has expired": "账户已到期",
            "Disable the tunnel before deleting": "请先禁用隧道再删除",
            "Failed to get token from fp-multiuser": "获取令牌失败（fp-multiuser 未运行）",
            "Invalid or already used activation code": "无效的激活码或已被使用",
            "Activation code required": "请输入激活码",
            "Unauthorized": "未授权，请重新登录",
            "email, code, password required": "邮箱、验证码和密码为必填项",
            "email, code, new_password required": "邮箱、验证码和新密码为必填项",
            "Email required": "请输入邮箱",
            "Request body required": "请求数据为空",
            "name and local_port required": "名称和端口为必填项",
            "local_port must be integer": "端口必须为数字",
            "User not found": "用户不存在",
        }
        # Try exact match first, then partial match
        if msg in _err_map:
            return _err_map[msg]
        for en, zh in _err_map.items():
            if en in msg:
                return msg.replace(en, zh)
        return msg

    def _toggle_lang(self):
        """Switch between Chinese and English, then rebuild the UI."""
        self.lang = LANG_EN if self.lang == LANG_ZH else LANG_ZH
        cfg = load_client_config()
        cfg["lang"] = self.lang
        save_client_config(cfg)
        self.root.title(self._tr("frp_title"))
        # Rebuild current screen
        if self.login_frame is not None and self.login_frame.winfo_exists():
            self._show_login()
        elif self.main_frame is not None and self.main_frame.winfo_exists():
            self._show_main()

    def _clear_container(self):
        for w in self.container.winfo_children():
            w.destroy()
        if self._refresh_timer:
            self.root.after_cancel(self._refresh_timer)
            self._refresh_timer = None

    def _on_close(self):
        self._disable_all_tunnels()
        stop_frpc()
        self.root.destroy()

    def _ensure_frpc_core(self):
        """Check if frpc.exe exists; if not, prompt to download and extract it."""
        if FRPC_EXE.exists():
            return
        want = messagebox.askyesno(
            self._tr("missing_core_file"),
            self._tr("missing_core_file_prompt"),
        )
        if not want:
            return

        threading.Thread(target=self._download_frpc_thread, daemon=True).start()

    def _download_frpc_thread(self):
        url = "https://github.com/fatedier/frp/releases/download/v0.68.1/frp_0.68.1_windows_amd64.zip"
        expected_hash = "74d753a681d2c07931d150b21ed294c224abe36053f67393cf46223f53bc871c"

        # Update status on main thread
        self.root.after(0, lambda: self.status_var.set(self._tr("downloading")))

        try:
            resp = requests.get(url, stream=True, timeout=120, verify=False)
            resp.raise_for_status()
            data = resp.content
        except requests.RequestException as e:
            self.root.after(0, lambda: messagebox.showerror(
                self._tr("core_download_failed"), str(e)))
            return

        # Verify SHA256
        self.root.after(0, lambda: self.status_var.set(self._tr("verifying")))
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash.lower() != expected_hash.lower():
            self.root.after(0, lambda: messagebox.showerror(
                self._tr("core_download_failed"),
                self._tr("sha256_mismatch"),
            ))
            return

        # Extract frpc.exe from zip in memory
        self.root.after(0, lambda: self.status_var.set(self._tr("extracting")))
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                frpc_path = next(
                    (n for n in zf.namelist() if n.endswith("frpc.exe")),
                    None,
                )
                if not frpc_path:
                    self.root.after(0, lambda: messagebox.showerror(
                        self._tr("core_download_failed"),
                        "frpc.exe not found in archive",
                    ))
                    return
                FRPC_DIR.mkdir(parents=True, exist_ok=True)
                with zf.open(frpc_path) as src, open(FRPC_EXE, "wb") as dst:
                    dst.write(src.read())
        except zipfile.BadZipFile:
            self.root.after(0, lambda: messagebox.showerror(
                self._tr("core_download_failed"), "Invalid zip file",
            ))
            return

        # Create frpc.ini if not present
        if not FRPC_INI.exists():
            FRPC_DIR.mkdir(parents=True, exist_ok=True)
            FRPC_INI.write_text("[common]\n", encoding="utf-8")

        self.root.after(0, lambda: messagebox.showinfo(
            self._tr("success"),
            self._tr("core_download_success"),
        ))

        # Restore status
        self.root.after(0, lambda: self.status_var.set(self._tr("connect_hint")))

    # ============================
    # Login / Register Screen
    # ============================
    def _show_login(self):
        self._clear_container()
        self.login_frame = ttk.Frame(self.container, padding=30)
        self.login_frame.pack(fill=tk.BOTH, expand=True)

        # Top bar: language toggle
        top_bar = ttk.Frame(self.login_frame)
        top_bar.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(top_bar, text=self._tr("frp_title"),
                  font=("", 16, "bold")).pack(side=tk.LEFT)
        lang_btn_text = LANGUAGES.get(LANG_EN if self.lang == LANG_ZH else LANG_ZH,
                                      {}).get("lang_name", "")
        ttk.Button(top_bar, text=lang_btn_text,
                   command=self._toggle_lang).pack(side=tk.RIGHT)

        # Server URL
        server_frame = ttk.LabelFrame(
            self.login_frame, text=self._tr("server_connection"), padding=15
        )
        server_frame.pack(fill=tk.X, pady=10)
        ttk.Label(server_frame, text=self._tr("server_url")).grid(
            row=0, column=0, sticky=tk.W, padx=5
        )
        self.server_url_var = tk.StringVar(value=self.api.base_url or "https://")
        ttk.Entry(server_frame, textvariable=self.server_url_var, width=40).grid(
            row=0, column=1, padx=5
        )
        ttk.Button(server_frame, text=self._tr("connect"),
                   command=self._check_server).grid(row=0, column=2, padx=5)
        self.disable_ssl_var = tk.BooleanVar(
            value=self.api.cfg.get("disable_ssl_verify", False)
        )
        ttk.Checkbutton(server_frame, text=self._tr("disable_ssl_verify"),
                        variable=self.disable_ssl_var,
                        command=self._toggle_ssl_verify).grid(
            row=0, column=3, padx=5
        )
        self.server_status_var = tk.StringVar(value="")
        ttk.Label(server_frame, textvariable=self.server_status_var,
                  foreground="gray", wraplength=450).grid(
            row=1, column=0, columnspan=4, sticky=tk.W, padx=5
        )

        # Login/Register/Reset Password Notebook
        notebook = ttk.Notebook(self.login_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=10)

        # ---------- Login tab ----------
        login_tab = ttk.Frame(notebook, padding=20)
        notebook.add(login_tab, text=self._tr("login"))
        cfg = load_client_config()
        ttk.Label(login_tab, text=self._tr("email")).grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        saved_email = cfg.get("saved_email", "") if cfg.get("remember_pwd") else ""
        self.login_email_var = tk.StringVar(value=saved_email)
        ttk.Entry(login_tab, textvariable=self.login_email_var, width=35).grid(
            row=0, column=1, pady=5
        )
        ttk.Label(login_tab, text=self._tr("password")).grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        saved_password = cfg.get("saved_password", "") if cfg.get("remember_pwd") else ""
        self.login_pass_var = tk.StringVar(value=saved_password)
        ttk.Entry(login_tab, textvariable=self.login_pass_var, show="*",
                  width=35).grid(row=1, column=1, pady=5)
        # Remember password checkbox
        self.login_remember_var = tk.BooleanVar(value=cfg.get("remember_pwd", False))
        ttk.Checkbutton(login_tab, text=self._tr("remember_password"),
                        variable=self.login_remember_var).grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        ttk.Button(login_tab, text=self._tr("login_btn"),
                   command=self._login).grid(row=2, column=1, pady=5, sticky=tk.E)

        # ---------- Register tab ----------
        reg_tab = ttk.Frame(notebook, padding=20)
        notebook.add(reg_tab, text=self._tr("register"))
        ttk.Label(reg_tab, text=self._tr("email")).grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        self.reg_email_var = tk.StringVar()
        ttk.Entry(reg_tab, textvariable=self.reg_email_var, width=35).grid(
            row=0, column=1, pady=5
        )
        ttk.Label(reg_tab, text=self._tr("password")).grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        self.reg_pass_var = tk.StringVar()
        ttk.Entry(reg_tab, textvariable=self.reg_pass_var, show="*",
                  width=35).grid(row=1, column=1, pady=5)
        ttk.Label(reg_tab, text=self._tr("confirm_password")).grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        self.reg_confirm_var = tk.StringVar()
        ttk.Entry(reg_tab, textvariable=self.reg_confirm_var, show="*",
                  width=35).grid(row=2, column=1, pady=5)
        ttk.Label(reg_tab, text=self._tr("code")).grid(
            row=3, column=0, sticky=tk.W, pady=5
        )
        self.reg_code_var = tk.StringVar()
        ttk.Entry(reg_tab, textvariable=self.reg_code_var, width=20).grid(
            row=3, column=1, sticky=tk.W, pady=5
        )
        btn_frame = ttk.Frame(reg_tab)
        btn_frame.grid(row=4, column=1, pady=10, sticky=tk.E)
        self.send_code_btn = ttk.Button(btn_frame, text=self._tr("send_code"),
                                        command=self._send_code)
        self.send_code_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=self._tr("register_btn"),
                   command=self._register).pack(side=tk.LEFT, padx=5)

        # ---------- Reset Password tab ----------
        reset_tab = ttk.Frame(notebook, padding=20)
        notebook.add(reset_tab, text=self._tr("reset_password"))
        ttk.Label(reset_tab, text=self._tr("email")).grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        self.reset_email_var = tk.StringVar()
        ttk.Entry(reset_tab, textvariable=self.reset_email_var, width=35).grid(
            row=0, column=1, pady=5
        )
        ttk.Label(reset_tab, text=self._tr("code")).grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        self.reset_code_var = tk.StringVar()
        ttk.Entry(reset_tab, textvariable=self.reset_code_var, width=20).grid(
            row=1, column=1, sticky=tk.W, pady=5
        )
        ttk.Label(reset_tab, text=self._tr("new_password")).grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        self.reset_pass_var = tk.StringVar()
        ttk.Entry(reset_tab, textvariable=self.reset_pass_var, show="*",
                  width=35).grid(row=2, column=1, pady=5)
        ttk.Label(reset_tab, text=self._tr("confirm_password")).grid(
            row=3, column=0, sticky=tk.W, pady=5
        )
        self.reset_confirm_var = tk.StringVar()
        ttk.Entry(reset_tab, textvariable=self.reset_confirm_var, show="*",
                  width=35).grid(row=3, column=1, pady=5)
        reset_btn_frame = ttk.Frame(reset_tab)
        reset_btn_frame.grid(row=4, column=1, pady=10, sticky=tk.E)
        self.reset_send_code_btn = ttk.Button(
            reset_btn_frame, text=self._tr("send_reset_code"),
            command=self._send_reset_code
        )
        self.reset_send_code_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(reset_btn_frame, text=self._tr("reset_btn"),
                   command=self._reset_password).pack(side=tk.LEFT, padx=5)

        # Status bar
        self.status_var = tk.StringVar(value=self._tr("connect_hint"))
        ttk.Label(self.login_frame, textvariable=self.status_var,
                  foreground="gray").pack(pady=5)

        # Try auto-login
        if self.api.session_token and self.api.base_url:
            self._try_auto_login()

    def _check_server(self):
        url = self.server_url_var.get().strip()
        if not url:
            self.server_status_var.set(self._tr("enter_server_url"))
            return
        self.api.set_server(url)
        self.api.set_ssl_verify(not self.disable_ssl_var.get())
        self.server_status_var.set(self._tr("testing_connection"))
        self.root.update()

        def test():
            try:
                resp = self.api._get("/api/user/info")
                if resp.status_code in (200, 401):
                    tr_connected = self._tr("connected_to")
                    tr_connected_msg = self._tr("server_connected")
                    self.server_status_var.set(f"{tr_connected} {url}")
                    self.root.after(0, lambda: self.status_var.set(tr_connected_msg))
                else:
                    tr_resp = self._tr("server_responded")
                    self.server_status_var.set(f"{tr_resp} ({resp.status_code})")
            except requests.RequestException as e:
                tr_fail = self._tr("connection_failed")
                self.server_status_var.set(f"{tr_fail} {e}")

        threading.Thread(target=test, daemon=True).start()

    def _toggle_ssl_verify(self):
        disabled = self.disable_ssl_var.get()
        cfg = load_client_config()
        cfg["disable_ssl_verify"] = disabled
        save_client_config(cfg)
        self.api.set_ssl_verify(not disabled)

    def _try_auto_login(self):
        threading.Thread(target=self._auto_login_thread, daemon=True).start()

    def _auto_login_thread(self):
        # Try saved session token first
        try:
            resp = self.api.get_user_info()
            if resp.status_code == 200:
                data = resp.json()
                self.current_user_id = data["user_id"]
                self.current_user_info = data
                self.root.after(0, self._show_main)
                return
        except requests.RequestException:
            pass
        # If session expired but remember_pwd is on, auto-login
        cfg = load_client_config()
        if cfg.get("remember_pwd") and cfg.get("saved_email") and cfg.get("saved_password"):
            self.api.base_url = cfg.get("server_url", "")
            self.root.after(0, lambda: [
                self.login_email_var.set(cfg["saved_email"]),
                self.login_pass_var.set(cfg["saved_password"]),
            ])
            self._login()

    def _show_error(self, title_key, message):
        """Show error messagebox with translated title."""
        messagebox.showerror(self._tr(title_key), message)

    def _show_info(self, title_key, message):
        messagebox.showinfo(self._tr(title_key), message)

    def _show_warning(self, title_key, message):
        messagebox.showwarning(self._tr(title_key), message)

    def _show_yesno(self, title_key, message):
        return messagebox.askyesno(self._tr(title_key), message)

    def _send_code(self):
        email = self.reg_email_var.get().strip()
        if not email:
            self._show_error("error", self._tr("all_fields_required"))
            return
        self.send_code_btn.configure(state=tk.DISABLED)
        threading.Thread(target=self._send_code_thread,
                         args=(email,), daemon=True).start()

    def _send_code_thread(self, email):
        try:
            resp = self.api.register_send_code(email)
            if resp.status_code == 200:
                self.root.after(0, lambda: self._show_info("success", self._tr("code_sent")))
                self.root.after(0, self._start_send_code_cooldown)
            else:
                self.root.after(0, lambda: self.send_code_btn.configure(state=tk.NORMAL))
                err = self._tr_error(resp.json().get("error", self._tr("error")))
                self.root.after(0, lambda: self._show_error("error", err))
        except requests.RequestException as e:
            self.root.after(0, lambda: self.send_code_btn.configure(state=tk.NORMAL))
            self.root.after(0, lambda: self._show_error("error", str(e)))

    def _start_send_code_cooldown(self):
        self._cooldown_sec = 60
        self._update_cooldown()

    def _update_cooldown(self):
        if self._cooldown_sec <= 0:
            self.send_code_btn.configure(text=self._tr("send_code"), state=tk.NORMAL)
            return
        self.send_code_btn.configure(text=f"{self._tr('send_code')} ({self._cooldown_sec}s)")
        self._cooldown_sec -= 1
        self.root.after(1000, self._update_cooldown)

    def _register(self):
        email = self.reg_email_var.get().strip()
        password = self.reg_pass_var.get()
        confirm = self.reg_confirm_var.get()
        code = self.reg_code_var.get().strip()
        if not email or not password or not code:
            self._show_error("error", self._tr("all_fields_required"))
            return
        if password != confirm:
            self._show_error("error", self._tr("passwords_not_match"))
            return
        if len(password) < 6:
            self._show_error("error", self._tr("password_too_short"))
            return
        threading.Thread(target=self._register_thread,
                         args=(email, password, code), daemon=True).start()

    def _register_thread(self, email, password, code):
        try:
            resp = self.api.register_verify(email, code, password)
            if resp.status_code == 200:
                data = resp.json()
                self.current_user_id = data["user_id"]
                self.root.after(0, self._show_main)
            else:
                err = self._tr_error(resp.json().get("error", self._tr("registration_failed")))
                self.root.after(0, lambda: self._show_error("error", err))
        except requests.RequestException as e:
            self.root.after(0, lambda: self._show_error("error", str(e)))

    # ---- Reset Password ----
    def _send_reset_code(self):
        email = self.reset_email_var.get().strip()
        if not email:
            self._show_error("error", self._tr("all_fields_required"))
            return
        self.reset_send_code_btn.configure(state=tk.DISABLED)
        threading.Thread(target=self._send_reset_code_thread,
                         args=(email,), daemon=True).start()

    def _send_reset_code_thread(self, email):
        try:
            resp = self.api.reset_send_code(email)
            if resp.status_code == 200:
                self.root.after(0, lambda: self._show_info("success", self._tr("reset_code_sent")))
                self.root.after(0, self._start_reset_code_cooldown)
            else:
                self.root.after(0, lambda: self.reset_send_code_btn.configure(state=tk.NORMAL))
                err = self._tr_error(resp.json().get("error", self._tr("error")))
                self.root.after(0, lambda: self._show_error("error", err))
        except requests.RequestException as e:
            self.root.after(0, lambda: self.reset_send_code_btn.configure(state=tk.NORMAL))
            self.root.after(0, lambda: self._show_error("error", str(e)))

    def _start_reset_code_cooldown(self):
        self._reset_cooldown_sec = 60
        self._update_reset_cooldown()

    def _update_reset_cooldown(self):
        if self._reset_cooldown_sec <= 0:
            self.reset_send_code_btn.configure(text=self._tr("send_reset_code"), state=tk.NORMAL)
            return
        self.reset_send_code_btn.configure(text=f"{self._tr('send_reset_code')} ({self._reset_cooldown_sec}s)")
        self._reset_cooldown_sec -= 1
        self.root.after(1000, self._update_reset_cooldown)

    def _reset_password(self):
        email = self.reset_email_var.get().strip()
        code = self.reset_code_var.get().strip()
        password = self.reset_pass_var.get()
        confirm = self.reset_confirm_var.get()
        if not email or not code or not password:
            self._show_error("error", self._tr("all_fields_required"))
            return
        if password != confirm:
            self._show_error("error", self._tr("passwords_not_match"))
            return
        if len(password) < 6:
            self._show_error("error", self._tr("password_too_short"))
            return
        threading.Thread(target=self._reset_password_thread,
                         args=(email, code, password), daemon=True).start()

    def _reset_password_thread(self, email, code, new_password):
        try:
            resp = self.api.reset_password(email, code, new_password)
            if resp.status_code == 200:
                # Clear fields and show success
                self.reset_code_var.set("")
                self.reset_pass_var.set("")
                self.reset_confirm_var.set("")
                self.root.after(0, lambda: self._show_info("success", self._tr("password_reset_success")))
            else:
                err = self._tr_error(resp.json().get("error", self._tr("reset_failed")))
                self.root.after(0, lambda: self._show_error("error", err))
        except requests.RequestException as e:
            self.root.after(0, lambda: self._show_error("error", str(e)))

    def _login(self):
        email = self.login_email_var.get().strip()
        password = self.login_pass_var.get()
        if not email or not password:
            self._show_error("error", self._tr("all_fields_required"))
            return
        threading.Thread(target=self._login_thread,
                         args=(email, password), daemon=True).start()

    def _login_thread(self, email, password):
        try:
            resp = self.api.login(email, password)
            if resp.status_code == 200:
                data = resp.json()
                self.current_user_id = data["user_id"]
                # Save remember password settings
                cfg = load_client_config()
                cfg["remember_pwd"] = self.login_remember_var.get()
                if self.login_remember_var.get():
                    cfg["saved_email"] = email
                    cfg["saved_password"] = password
                else:
                    cfg.pop("saved_email", None)
                    cfg.pop("saved_password", None)
                save_client_config(cfg)
                self.root.after(0, self._show_main)
            else:
                err = self._tr_error(resp.json().get("error", self._tr("login_failed")))
                self.root.after(0, lambda: self._show_error("error", err))
        except requests.RequestException as e:
            self.root.after(0, lambda: self._show_error("error", str(e)))

    # ============================
    # Main Dashboard
    # ============================
    def _show_main(self):
        self._clear_container()
        self.main_frame = ttk.Frame(self.container, padding=15)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Header with lang toggle
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=5)
        ttk.Label(header, text=self._tr("frp_title"),
                  font=("", 18, "bold")).pack(side=tk.LEFT)
        lang_btn_text = LANGUAGES.get(LANG_EN if self.lang == LANG_ZH else LANG_ZH,
                                      {}).get("lang_name", "")
        ttk.Button(header, text=lang_btn_text,
                   command=self._toggle_lang).pack(side=tk.RIGHT, padx=5)
        ttk.Button(header, text=self._tr("logout"),
                   command=self._logout).pack(side=tk.RIGHT, padx=5)
        ttk.Button(header, text=self._tr("refresh"),
                   command=self._refresh_data).pack(side=tk.RIGHT, padx=5)
        ttk.Button(header, text=self._tr("activate"),
                   command=self._activate_account).pack(side=tk.RIGHT, padx=5)

        # User info bar
        info_frame = ttk.LabelFrame(
            self.main_frame, text=self._tr("account_info"), padding=10
        )
        info_frame.pack(fill=tk.X, pady=5)
        self.user_id_var = tk.StringVar()
        self.expiry_var = tk.StringVar()
        self.expiry_status_var = tk.StringVar()
        ttk.Label(info_frame, textvariable=self.user_id_var,
                  font=("", 11)).pack(anchor=tk.W)
        ttk.Label(info_frame, textvariable=self.expiry_var).pack(anchor=tk.W)
        self.expiry_status_label = ttk.Label(
            info_frame, textvariable=self.expiry_status_var,
            font=("", 11, "bold")
        )
        self.expiry_status_label.pack(anchor=tk.W)

        # Tunnel list
        tunnel_frame = ttk.LabelFrame(
            self.main_frame, text=self._tr("tunnels"), padding=10
        )
        tunnel_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        columns = ("id", "name", "type", "local", "remote_port", "status")
        self.tree = ttk.Treeview(
            tunnel_frame, columns=columns, show="headings", selectmode="browse"
        )
        self.tree.heading("id", text=self._tr("tunnel_id"))
        self.tree.heading("name", text=self._tr("tunnel_name"))
        self.tree.heading("type", text=self._tr("tunnel_type"))
        self.tree.heading("local", text=self._tr("tunnel_local"))
        self.tree.heading("remote_port", text=self._tr("tunnel_remote"))
        self.tree.heading("status", text=self._tr("tunnel_status"))
        self.tree.column("id", width=40)
        self.tree.column("name", width=120)
        self.tree.column("type", width=60)
        self.tree.column("local", width=120)
        self.tree.column("remote_port", width=100)
        self.tree.column("status", width=80)

        scrollbar = ttk.Scrollbar(tunnel_frame, orient=tk.VERTICAL,
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Action buttons
        action_frame = ttk.Frame(self.main_frame)
        action_frame.pack(fill=tk.X, pady=10)
        ttk.Button(action_frame, text=self._tr("create_tunnel"),
                   command=self._create_tunnel_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text=self._tr("edit"),
                   command=self._edit_tunnel_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text=self._tr("enable"),
                   command=self._enable_tunnel).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text=self._tr("disable"),
                   command=self._disable_tunnel).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text=self._tr("delete"),
                   command=self._delete_tunnel).pack(side=tk.LEFT, padx=5)
        self.copy_addr_btn = ttk.Button(action_frame, text=self._tr("copy_address"),
                   command=self._copy_external_address)
        self.copy_addr_btn.pack(side=tk.LEFT, padx=5)

        # frpc status
        self.frpc_status_var = tk.StringVar(value=self._tr("frpc_idle"))
        ttk.Label(self.main_frame, textvariable=self.frpc_status_var,
                  foreground="gray").pack(anchor=tk.W, pady=2)

        self._update_frpc_status()
        self._refresh_data()

    def _update_frpc_status(self):
        if is_frpc_running():
            self.frpc_status_var.set(self._tr("frpc_running"))
        else:
            self.frpc_status_var.set(self._tr("frpc_idle"))
        self._refresh_timer = self.root.after(5000, self._update_frpc_status)

    def _refresh_data(self):
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _refresh_thread(self):
        try:
            info_resp = self.api.get_user_info()
            if info_resp.status_code == 200:
                data = info_resp.json()
                self.current_user_info = data
                self.ftps_ip = data.get("ftps_ip", self.ftps_ip)
                self.ftps_port = data.get("ftps_port", self.ftps_port)
                self.root.after(0, self._update_info_display)
            tunnels_resp = self.api.list_tunnels()
            if tunnels_resp.status_code == 200:
                tunnels = tunnels_resp.json().get("tunnels", [])
                self.root.after(0, self._update_tunnel_list, tunnels)
        except requests.RequestException:
            pass

    def _update_info_display(self):
        info = self.current_user_info
        if not info:
            return
        tr_user = self._tr("user")
        tr_email = self._tr("email_label")
        tr_expiration = self._tr("expiration")
        self.user_id_var.set(
            f"{tr_user} {info['user_id']}  |  {tr_email} {info['email']}"
        )
        if info["expired"]:
            self.expiry_var.set(f"{tr_expiration} {self._tr('expired')}")
            self.expiry_status_var.set(self._tr("expired_status"))
            self.expiry_status_label.configure(foreground="red")
        else:
            self.expiry_var.set(f"{tr_expiration} {info['expires_at']}")
            self.expiry_status_var.set(self._tr("active_status"))
            self.expiry_status_label.configure(foreground="green")

    def _update_tunnel_list(self, tunnels):
        for item in self.tree.get_children():
            self.tree.delete(item)
        tr_enabled = self._tr("tunnel_enabled")
        tr_disabled = self._tr("tunnel_disabled")
        for t in tunnels:
            local = f"{t.get('local_ip', '127.0.0.1')}:{t['local_port']}"
            remote = t.get("remote_port", "")
            status = tr_enabled if t["enabled"] else tr_disabled
            self.tree.insert(
                "", tk.END,
                values=(t["id"], t["name"], t["tunnel_type"], local, remote, status),
            )

    def _get_selected_tunnel(self):
        sel = self.tree.selection()
        if not sel:
            self._show_warning("warning", self._tr("select_tunnel"))
            return None
        item = self.tree.item(sel[0])
        values = item["values"]
        return {
            "id": int(values[0]),
            "name": values[1],
            "type": values[2],
            "local": values[3],
            "remote_port": values[4],
            "status": values[5],
        }

    # ---- Tunnel Actions ----
    def _create_tunnel_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(self._tr("create_tunnel_title"))
        dialog.geometry("400x300")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        # Center dialog on parent window
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 400) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 300) // 2
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=self._tr("name_label")).grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=name_var, width=30).grid(
            row=0, column=1, pady=5
        )

        ttk.Label(frame, text=self._tr("type_label")).grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        type_var = tk.StringVar(value="tcp")
        type_combo = ttk.Combobox(
            frame, textvariable=type_var, values=["tcp", "udp"],
            width=27, state="readonly"
        )
        type_combo.grid(row=1, column=1, pady=5)

        ttk.Label(frame, text=self._tr("local_ip_label")).grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        ip_var = tk.StringVar(value="127.0.0.1")
        ttk.Entry(frame, textvariable=ip_var, width=30).grid(
            row=2, column=1, pady=5
        )

        ttk.Label(frame, text=self._tr("local_port_label")).grid(
            row=3, column=0, sticky=tk.W, pady=5
        )
        port_var = tk.StringVar()
        ttk.Entry(frame, textvariable=port_var, width=30).grid(
            row=3, column=1, pady=5
        )

        err_var = tk.StringVar()
        ttk.Label(frame, textvariable=err_var, foreground="red").grid(
            row=4, column=0, columnspan=2, pady=5
        )

        def do_create():
            name = name_var.get().strip()
            ttype = type_var.get()
            local_ip = ip_var.get().strip()
            local_port = port_var.get().strip()
            if not name or not local_port:
                err_var.set(self._tr("name_port_required"))
                return
            try:
                local_port = int(local_port)
            except ValueError:
                err_var.set(self._tr("port_must_be_number"))
                return

            def create_thread():
                try:
                    resp = self.api.create_tunnel(name, ttype, local_port, local_ip)
                    if resp.status_code == 201:
                        self.root.after(0, lambda: [dialog.destroy(),
                                                     self._refresh_data()])
                    else:
                        err = self._tr_error(resp.json().get("error", self._tr("error")))
                        self.root.after(0, lambda: err_var.set(err))
                except requests.RequestException as e:
                    self.root.after(0, lambda: err_var.set(str(e)))

            threading.Thread(target=create_thread, daemon=True).start()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=5, column=1, pady=15, sticky=tk.E)
        ttk.Button(btn_frame, text=self._tr("create"),
                   command=do_create).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=self._tr("cancel"),
                   command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def _edit_tunnel_dialog(self):
        tunnel = self._get_selected_tunnel()
        if not tunnel:
            return
        # Parse local IP and port from the "local" column value (format "ip:port")
        local_parts = tunnel["local"].rsplit(":", 1)
        current_ip = local_parts[0] if len(local_parts) == 2 else "127.0.0.1"
        current_port = local_parts[1] if len(local_parts) == 2 else local_parts[0]

        dialog = tk.Toplevel(self.root)
        dialog.title(self._tr("edit_tunnel"))
        dialog.geometry("400x300")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        # Center dialog on parent window
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 400) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 300) // 2
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=self._tr("name_label")).grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        name_var = tk.StringVar(value=tunnel["name"])
        ttk.Entry(frame, textvariable=name_var, width=30).grid(
            row=0, column=1, pady=5
        )

        ttk.Label(frame, text=self._tr("type_label")).grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        type_var = tk.StringVar(value=tunnel["type"])
        type_combo = ttk.Combobox(
            frame, textvariable=type_var, values=["tcp", "udp"],
            width=27, state="readonly"
        )
        type_combo.grid(row=1, column=1, pady=5)

        ttk.Label(frame, text=self._tr("local_ip_label")).grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        ip_var = tk.StringVar(value=current_ip)
        ttk.Entry(frame, textvariable=ip_var, width=30).grid(
            row=2, column=1, pady=5
        )

        ttk.Label(frame, text=self._tr("local_port_label")).grid(
            row=3, column=0, sticky=tk.W, pady=5
        )
        port_var = tk.StringVar(value=current_port)
        ttk.Entry(frame, textvariable=port_var, width=30).grid(
            row=3, column=1, pady=5
        )

        err_var = tk.StringVar()
        ttk.Label(frame, textvariable=err_var, foreground="red").grid(
            row=4, column=0, columnspan=2, pady=5
        )

        def do_update():
            name = name_var.get().strip()
            ttype = type_var.get()
            local_ip = ip_var.get().strip()
            local_port = port_var.get().strip()
            if not name or not local_port:
                err_var.set(self._tr("name_port_required"))
                return
            try:
                local_port = int(local_port)
            except ValueError:
                err_var.set(self._tr("port_must_be_number"))
                return

            def update_thread():
                try:
                    resp = self.api.update_tunnel(
                        tunnel["id"], name=name, tunnel_type=ttype,
                        local_ip=local_ip, local_port=local_port,
                    )
                    if resp.status_code == 200:
                        self.root.after(0, lambda: [dialog.destroy(),
                                                     self._refresh_data()])
                    else:
                        err = resp.json().get("error", self._tr("error"))
                        self.root.after(0, lambda: err_var.set(err))
                except requests.RequestException as e:
                    self.root.after(0, lambda: err_var.set(str(e)))

            threading.Thread(target=update_thread, daemon=True).start()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=5, column=1, pady=15, sticky=tk.E)
        ttk.Button(btn_frame, text=self._tr("edit"),
                   command=do_update).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=self._tr("cancel"),
                   command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def _enable_tunnel(self):
        tunnel = self._get_selected_tunnel()
        if not tunnel:
            return
        tr_enabled = self._tr("tunnel_enabled")
        if tunnel["status"] == tr_enabled:
            self._show_info("info", self._tr("tunnel_already_enabled"))
            return
        if self.current_user_info and self.current_user_info.get("expired"):
            self._show_error("error", self._tr("account_expired"))
            return

        # Check that no other tunnel is already enabled
        tr_enabled = self._tr("tunnel_enabled")
        for item in self.tree.get_children():
            vals = self.tree.item(item)["values"]
            if int(vals[0]) != tunnel["id"] and vals[5] == tr_enabled:
                self._show_error("error", self._tr("only_one_tunnel"))
                return

        threading.Thread(target=self._enable_thread,
                         args=(tunnel,), daemon=True).start()

    def _enable_thread(self, tunnel):
        try:
            resp = self.api.enable_tunnel(tunnel["id"])
            if resp.status_code != 200:
                err = self._tr_error(resp.json().get("error", self._tr("enable_failed")))
                self.root.after(0, lambda: self._show_error("error", err))
                return
            data = resp.json()
            write_frpc_ini(
                server_addr=data["ftps_ip"],
                server_port=data["ftps_port"],
                user=self.current_user_id,
                token=data["token"],
                tunnel_name=tunnel["name"],
                tunnel_type=tunnel["type"],
                local_ip=tunnel["local"].split(":")[0],
                local_port=int(tunnel["local"].split(":")[1]),
                remote_port=data["remote_port"],
            )
            frpc_ok, msg = start_frpc()
            if frpc_ok:
                self.root.after(0, lambda: [
                    TunnelEnableDialog(self.root, tunnel, data, self._tr),
                    self._refresh_data(),
                ])
            else:
                err_msg = f"{self._tr('start_frpc_failed')}: {msg}"
                self.root.after(
                    0, lambda: self._show_error("error", err_msg)
                )
        except requests.RequestException as e:
            self.root.after(0, lambda: self._show_error("error", str(e)))

    def _disable_tunnel(self):
        tunnel = self._get_selected_tunnel()
        if not tunnel:
            return
        if tunnel["status"] != self._tr("tunnel_enabled"):
            self._show_info("info", self._tr("tunnel_not_enabled"))
            return
        threading.Thread(target=self._disable_thread,
                         args=(tunnel,), daemon=True).start()

    def _disable_thread(self, tunnel):
        try:
            resp = self.api.disable_tunnel(tunnel["id"])
            if resp.status_code != 200:
                err = self._tr_error(resp.json().get("error", self._tr("disable_failed")))
                self.root.after(0, lambda: self._show_error("error", err))
                return
            _, msg = stop_frpc()
            self.root.after(0, lambda m=msg: [
                self._show_info("success",
                                f"{self._tr('tunnel_disabled')}\n{m}"),
                self._refresh_data(),
            ])
        except requests.RequestException as e:
            self.root.after(0, lambda: self._show_error("error", str(e)))

    def _delete_tunnel(self):
        tunnel = self._get_selected_tunnel()
        if not tunnel:
            return
        if tunnel["status"] == self._tr("tunnel_enabled"):
            self._show_error("error", self._tr("disable_before_delete"))
            return
        msg = f"{self._tr('confirm_delete')} '{tunnel['name']}'?"
        if not self._show_yesno("confirm", msg):
            return
        threading.Thread(target=self._delete_thread,
                         args=(tunnel,), daemon=True).start()

    def _delete_thread(self, tunnel):
        try:
            resp = self.api.delete_tunnel(tunnel["id"])
            if resp.status_code == 200:
                self.root.after(0, self._refresh_data)
            else:
                err = self._tr_error(resp.json().get("error", self._tr("delete_failed")))
                self.root.after(0, lambda: self._show_error("error", err))
        except requests.RequestException as e:
            self.root.after(0, lambda: self._show_error("error", str(e)))

    def _activate_account(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(self._tr("activate"))
        dialog.geometry("400x200")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        # Center dialog on parent window
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 400) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 200) // 2
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=self._tr("activation_code"),
                  font=("", 11)).pack(anchor=tk.W, pady=5)
        code_var = tk.StringVar()
        ttk.Entry(frame, textvariable=code_var, width=35).pack(pady=5)

        err_var = tk.StringVar()
        ttk.Label(frame, textvariable=err_var, foreground="red").pack(pady=5)

        def do_activate():
            code = code_var.get().strip()
            if not code:
                err_var.set(self._tr("enter_activation_code"))
                return

            def activate_thread():
                try:
                    resp = self.api.activate(code)
                    if resp.status_code == 200:
                        data = resp.json()
                        self.root.after(0, lambda: [
                            dialog.destroy(),
                            self._show_info("success",
                                f"{self._tr('activation_success')}\n{self._tr('new_expiry')}: {data['new_expires_at']}"),
                            self._refresh_data(),
                        ])
                    else:
                        err = self._tr_error(resp.json().get("error", self._tr("activation_failed")))
                        self.root.after(0, lambda: err_var.set(err))
                except requests.RequestException as e:
                    self.root.after(0, lambda: err_var.set(str(e)))

            threading.Thread(target=activate_thread, daemon=True).start()

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text=self._tr("ok"),
                   command=do_activate).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=self._tr("cancel"),
                   command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def _copy_external_address(self):
        tunnel = self._get_selected_tunnel()
        if not tunnel:
            return
        if tunnel["status"] != self._tr("tunnel_enabled"):
            self._show_info("info", self._tr("enable_then_copy"))
            return
        ext_addr = f"{self.ftps_ip}:{tunnel['remote_port']}"
        self.root.clipboard_clear()
        self.root.clipboard_append(ext_addr)
        self.copy_addr_btn.configure(text=self._tr("address_copied"))
        self.root.after(2000, lambda: self.copy_addr_btn.configure(
            text=self._tr("copy_address")))

    def _disable_all_tunnels(self):
        """Disable all enabled tunnels for the current user."""
        try:
            resp = self.api.list_tunnels()
            if resp.status_code == 200:
                tunnels = resp.json().get("tunnels", [])
                for t in tunnels:
                    if t.get("enabled"):
                        self.api.disable_tunnel(t["id"])
        except requests.RequestException:
            pass

    def _logout(self):
        self._disable_all_tunnels()
        stop_frpc()
        self.current_user_id = None
        self.current_user_info = None
        self.api.logout()
        self._show_login()

    # ============================
    # Run
    # ============================
    def run(self):
        self.root.mainloop()


# ============================================================
# Entry Point
# ============================================================
if __name__ == "__main__":
    app = FrpLoginApp()
    app.run()
