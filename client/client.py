#!/usr/bin/env python3
"""
FRP Login Tool - Client
GUI desktop client for managing FRP tunnels with remote server.
"""
import json
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).parent.resolve()
FRPC_DIR = BASE_DIR / "frpc"
FRPC_INI = FRPC_DIR / "frpc.ini"
FRPC_EXE = FRPC_DIR / "frpc.exe"
CONFIG_FILE = BASE_DIR / "client_config.json"

frpc_process = None
frpc_process_lock = threading.Lock()


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
        self.cfg = load_client_config()
        if "server_url" in self.cfg:
            self.base_url = self.cfg["server_url"]
        if "session_token" in self.cfg:
            self.session_token = self.cfg["session_token"]

    def set_server(self, server_url):
        self.base_url = server_url.rstrip("/")
        self.cfg["server_url"] = self.base_url
        save_client_config(self.cfg)

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.session_token:
            h["Authorization"] = f"Bearer {self.session_token}"
        return h

    def _post(self, path, data=None):
        url = f"{self.base_url}{path}"
        return requests.post(url, json=data, headers=self._headers(), verify=False, timeout=15)

    def _get(self, path):
        url = f"{self.base_url}{path}"
        return requests.get(url, headers=self._headers(), verify=False, timeout=15)

    def _delete(self, path):
        url = f"{self.base_url}{path}"
        return requests.delete(url, headers=self._headers(), verify=False, timeout=15)

    def register_send_code(self, email):
        return self._post("/api/auth/register", {"email": email})

    def register_verify(self, email, code, password):
        return self._post("/api/auth/register/verify", {
            "email": email, "code": code, "password": password,
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

    def enable_tunnel(self, tunnel_id):
        return self._post(f"/api/tunnels/{tunnel_id}/enable")

    def disable_tunnel(self, tunnel_id):
        return self._post(f"/api/tunnels/{tunnel_id}/disable")

    def logout(self):
        self.session_token = ""
        self.cfg.pop("session_token", None)
        save_client_config(self.cfg)


# ============================================================
# frpc Manager
# ============================================================
def write_frpc_ini(server_addr, server_port, user, token, tunnel_name, tunnel_type, local_port, remote_port, local_ip="127.0.0.1"):
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
            frpc_process = subprocess.Popen(
                [str(FRPC_EXE), "-c", str(FRPC_INI)],
                cwd=str(FRPC_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
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
    def __init__(self, parent, tunnel, enable_data):
        super().__init__(parent)
        self.title("Tunnel Enabled")
        self.geometry("500x400")
        self.resizable(True, True)
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Tunnel Enabled Successfully", font=("", 14, "bold")).pack(pady=5)
        info = f"""
Tunnel: {tunnel['name']}
Type: {tunnel['tunnel_type']}
Local: {tunnel.get('local_ip', '127.0.0.1')}:{tunnel['local_port']}
Remote Port: {enable_data['remote_port']}
FRP Server: {enable_data['ftps_ip']}:{enable_data['ftps_port']}
Token: {enable_data['token'][:20]}...
"""
        ttk.Label(frame, text=info, justify=tk.LEFT).pack(pady=10)
        ttk.Label(frame, text="frpc.ini has been updated and frpc.exe started.", foreground="green").pack()
        ttk.Button(frame, text="OK", command=self.destroy).pack(pady=10)


# ============================================================
# Main Application
# ============================================================
class FrpLoginApp:
    def __init__(self):
        self.api = ApiClient()
        self.root = tk.Tk()
        self.root.title("FRP Login Tool")
        self.root.geometry("900x650")
        self.root.minsize(700, 500)
        self.current_user_id = None
        self.current_user_info = None
        self._refresh_timer = None

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Header.TLabel", font=("", 16, "bold"))
        style.configure("Status.TLabel", font=("", 10))
        style.configure("Accent.TButton", font=("", 10, "bold"))

        self.container = ttk.Frame(self.root)
        self.container.pack(fill=tk.BOTH, expand=True)

        self.login_frame = None
        self.main_frame = None
        self._show_login()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _clear_container(self):
        for w in self.container.winfo_children():
            w.destroy()
        if self._refresh_timer:
            self.root.after_cancel(self._refresh_timer)
            self._refresh_timer = None

    def _on_close(self):
        stop_frpc()
        self.root.destroy()

    # ============================
    # Login / Register Screen
    # ============================
    def _show_login(self):
        self._clear_container()
        self.login_frame = ttk.Frame(self.container, padding=30)
        self.login_frame.pack(fill=tk.BOTH, expand=True)

        # Server URL
        server_frame = ttk.LabelFrame(self.login_frame, text="Server Connection", padding=15)
        server_frame.pack(fill=tk.X, pady=10)
        ttk.Label(server_frame, text="Server URL:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.server_url_var = tk.StringVar(value=self.api.base_url or "https://")
        ttk.Entry(server_frame, textvariable=self.server_url_var, width=40).grid(row=0, column=1, padx=5)
        ttk.Button(server_frame, text="Connect", command=self._check_server).grid(row=0, column=2, padx=5)
        self.server_status_var = tk.StringVar(value="")
        ttk.Label(server_frame, textvariable=self.server_status_var, foreground="gray").grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=5)

        # Login/Register Notebook
        notebook = ttk.Notebook(self.login_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=10)

        # Login tab
        login_tab = ttk.Frame(notebook, padding=20)
        notebook.add(login_tab, text="Login")
        ttk.Label(login_tab, text="Email:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.login_email_var = tk.StringVar()
        ttk.Entry(login_tab, textvariable=self.login_email_var, width=35).grid(row=0, column=1, pady=5)
        ttk.Label(login_tab, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.login_pass_var = tk.StringVar()
        ttk.Entry(login_tab, textvariable=self.login_pass_var, show="*", width=35).grid(row=1, column=1, pady=5)
        ttk.Button(login_tab, text="Login", command=self._login).grid(row=2, column=1, pady=15, sticky=tk.E)

        # Register tab
        reg_tab = ttk.Frame(notebook, padding=20)
        notebook.add(reg_tab, text="Register")
        ttk.Label(reg_tab, text="Email:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.reg_email_var = tk.StringVar()
        ttk.Entry(reg_tab, textvariable=self.reg_email_var, width=35).grid(row=0, column=1, pady=5)
        ttk.Label(reg_tab, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.reg_pass_var = tk.StringVar()
        ttk.Entry(reg_tab, textvariable=self.reg_pass_var, show="*", width=35).grid(row=1, column=1, pady=5)
        ttk.Label(reg_tab, text="Confirm:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.reg_confirm_var = tk.StringVar()
        ttk.Entry(reg_tab, textvariable=self.reg_confirm_var, show="*", width=35).grid(row=2, column=1, pady=5)
        ttk.Label(reg_tab, text="Code:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.reg_code_var = tk.StringVar()
        ttk.Entry(reg_tab, textvariable=self.reg_code_var, width=20).grid(row=3, column=1, sticky=tk.W, pady=5)
        btn_frame = ttk.Frame(reg_tab)
        btn_frame.grid(row=4, column=1, pady=10, sticky=tk.E)
        ttk.Button(btn_frame, text="Send Code", command=self._send_code).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Register", command=self._register).pack(side=tk.LEFT, padx=5)

        # Status bar
        self.status_var = tk.StringVar(value="Connect to a server to begin")
        ttk.Label(self.login_frame, textvariable=self.status_var, foreground="gray").pack(pady=5)

        # Try auto-login
        if self.api.session_token and self.api.base_url:
            self._try_auto_login()

    def _check_server(self):
        url = self.server_url_var.get().strip()
        if not url:
            self.server_status_var.set("Please enter a server URL")
            return
        self.api.set_server(url)
        self.server_status_var.set("Testing connection...")
        self.root.update()

        def test():
            try:
                resp = self.api._get("/api/user/info")
                if resp.status_code in (200, 401):
                    self.server_status_var.set(f"Connected to {url}")
                    self.root.after(0, lambda: self.status_var.set("Server connected. Login or register."))
                else:
                    self.server_status_var.set(f"Server responded ({resp.status_code})")
            except requests.RequestException as e:
                self.server_status_var.set(f"Connection failed: {e}")

        threading.Thread(target=test, daemon=True).start()

    def _try_auto_login(self):
        threading.Thread(target=self._auto_login_thread, daemon=True).start()

    def _auto_login_thread(self):
        try:
            resp = self.api.get_user_info()
            if resp.status_code == 200:
                data = resp.json()
                self.current_user_id = data["user_id"]
                self.current_user_info = data
                self.root.after(0, self._show_main)
            else:
                self.api.logout()
        except requests.RequestException:
            self.api.logout()

    def _send_code(self):
        email = self.reg_email_var.get().strip()
        if not email:
            messagebox.showerror("Error", "Please enter email")
            return
        threading.Thread(target=self._send_code_thread, args=(email,), daemon=True).start()

    def _send_code_thread(self, email):
        try:
            resp = self.api.register_send_code(email)
            if resp.status_code == 200:
                self.root.after(0, lambda: messagebox.showinfo("Success", "Verification code sent to your email"))
            else:
                err = resp.json().get("error", "Unknown error")
                self.root.after(0, lambda: messagebox.showerror("Error", err))
        except requests.RequestException as e:
            self.root.after(0, lambda: messagebox.showerror("Connection Error", str(e)))

    def _register(self):
        email = self.reg_email_var.get().strip()
        password = self.reg_pass_var.get()
        confirm = self.reg_confirm_var.get()
        code = self.reg_code_var.get().strip()
        if not email or not password or not code:
            messagebox.showerror("Error", "All fields required")
            return
        if password != confirm:
            messagebox.showerror("Error", "Passwords do not match")
            return
        if len(password) < 6:
            messagebox.showerror("Error", "Password must be at least 6 characters")
            return
        threading.Thread(target=self._register_thread, args=(email, password, code), daemon=True).start()

    def _register_thread(self, email, password, code):
        try:
            resp = self.api.register_verify(email, code, password)
            if resp.status_code == 200:
                data = resp.json()
                self.current_user_id = data["user_id"]
                self.root.after(0, self._show_main)
            else:
                err = resp.json().get("error", "Registration failed")
                self.root.after(0, lambda: messagebox.showerror("Error", err))
        except requests.RequestException as e:
            self.root.after(0, lambda: messagebox.showerror("Connection Error", str(e)))

    def _login(self):
        email = self.login_email_var.get().strip()
        password = self.login_pass_var.get()
        if not email or not password:
            messagebox.showerror("Error", "Email and password required")
            return
        threading.Thread(target=self._login_thread, args=(email, password), daemon=True).start()

    def _login_thread(self, email, password):
        try:
            resp = self.api.login(email, password)
            if resp.status_code == 200:
                data = resp.json()
                self.current_user_id = data["user_id"]
                self.root.after(0, self._show_main)
            else:
                err = resp.json().get("error", "Login failed")
                self.root.after(0, lambda: messagebox.showerror("Error", err))
        except requests.RequestException as e:
            self.root.after(0, lambda: messagebox.showerror("Connection Error", str(e)))

    # ============================
    # Main Dashboard
    # ============================
    def _show_main(self):
        self._clear_container()
        self.main_frame = ttk.Frame(self.container, padding=15)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=5)
        ttk.Label(header, text=f"FRP Login Tool", font=("", 18, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="Logout", command=self._logout).pack(side=tk.RIGHT, padx=5)
        ttk.Button(header, text="Refresh", command=self._refresh_data).pack(side=tk.RIGHT, padx=5)

        # User info bar
        info_frame = ttk.LabelFrame(self.main_frame, text="Account Info", padding=10)
        info_frame.pack(fill=tk.X, pady=5)
        self.user_id_var = tk.StringVar()
        self.expiry_var = tk.StringVar()
        self.expiry_status_var = tk.StringVar()
        ttk.Label(info_frame, textvariable=self.user_id_var, font=("", 11)).pack(anchor=tk.W)
        ttk.Label(info_frame, textvariable=self.expiry_var).pack(anchor=tk.W)
        self.expiry_status_label = ttk.Label(info_frame, textvariable=self.expiry_status_var, font=("", 11, "bold"))
        self.expiry_status_label.pack(anchor=tk.W)

        # Tunnel list
        tunnel_frame = ttk.LabelFrame(self.main_frame, text="Tunnels (max 10)", padding=10)
        tunnel_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        columns = ("id", "name", "type", "local", "remote_port", "status")
        self.tree = ttk.Treeview(tunnel_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.heading("local", text="Local")
        self.tree.heading("remote_port", text="Remote Port")
        self.tree.heading("status", text="Status")
        self.tree.column("id", width=40)
        self.tree.column("name", width=120)
        self.tree.column("type", width=60)
        self.tree.column("local", width=120)
        self.tree.column("remote_port", width=100)
        self.tree.column("status", width=80)

        scrollbar = ttk.Scrollbar(tunnel_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Action buttons
        action_frame = ttk.Frame(self.main_frame)
        action_frame.pack(fill=tk.X, pady=10)
        ttk.Button(action_frame, text="Create Tunnel", command=self._create_tunnel_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Enable", command=self._enable_tunnel).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Disable", command=self._disable_tunnel).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Delete", command=self._delete_tunnel).pack(side=tk.LEFT, padx=5)

        # frpc status
        self.frpc_status_var = tk.StringVar(value="frpc: idle")
        ttk.Label(self.main_frame, textvariable=self.frpc_status_var, foreground="gray").pack(anchor=tk.W, pady=2)

        self._update_frpc_status()
        self._refresh_data()

    def _update_frpc_status(self):
        if is_frpc_running():
            self.frpc_status_var.set("frpc: RUNNING")
        else:
            self.frpc_status_var.set("frpc: idle")
        if self._refresh_timer is None:
            self._refresh_timer = self.root.after(5000, self._update_frpc_status)

    def _refresh_data(self):
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _refresh_thread(self):
        try:
            info_resp = self.api.get_user_info()
            if info_resp.status_code == 200:
                data = info_resp.json()
                self.current_user_info = data
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
        self.user_id_var.set(f"User: {info['user_id']}  |  Email: {info['email']}")
        if info["expired"]:
            self.expiry_var.set("Expiration: EXPIRED")
            self.expiry_status_var.set("Status: Expired - tunnels cannot be enabled")
            self.expiry_status_label.configure(foreground="red")
        else:
            self.expiry_var.set(f"Expires: {info['expires_at']}")
            self.expiry_status_var.set("Status: Active")
            self.expiry_status_label.configure(foreground="green")

    def _update_tunnel_list(self, tunnels):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for t in tunnels:
            local = f"{t.get('local_ip', '127.0.0.1')}:{t['local_port']}"
            remote = t.get("remote_port", "")
            status = "Enabled" if t["enabled"] else "Disabled"
            self.tree.insert(
                "", tk.END,
                values=(t["id"], t["name"], t["tunnel_type"], local, remote, status),
            )

    def _get_selected_tunnel(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Please select a tunnel")
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
        dialog.title("Create Tunnel")
        dialog.geometry("400x300")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=name_var, width=30).grid(row=0, column=1, pady=5)

        ttk.Label(frame, text="Type:").grid(row=1, column=0, sticky=tk.W, pady=5)
        type_var = tk.StringVar(value="tcp")
        type_combo = ttk.Combobox(frame, textvariable=type_var, values=["tcp", "udp"], width=27, state="readonly")
        type_combo.grid(row=1, column=1, pady=5)

        ttk.Label(frame, text="Local IP:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ip_var = tk.StringVar(value="127.0.0.1")
        ttk.Entry(frame, textvariable=ip_var, width=30).grid(row=2, column=1, pady=5)

        ttk.Label(frame, text="Local Port:").grid(row=3, column=0, sticky=tk.W, pady=5)
        port_var = tk.StringVar()
        ttk.Entry(frame, textvariable=port_var, width=30).grid(row=3, column=1, pady=5)

        err_var = tk.StringVar()
        ttk.Label(frame, textvariable=err_var, foreground="red").grid(row=4, column=0, columnspan=2, pady=5)

        def do_create():
            name = name_var.get().strip()
            ttype = type_var.get()
            local_ip = ip_var.get().strip()
            local_port = port_var.get().strip()
            if not name or not local_port:
                err_var.set("Name and port required")
                return
            try:
                local_port = int(local_port)
            except ValueError:
                err_var.set("Port must be a number")
                return

            def create_thread():
                try:
                    resp = self.api.create_tunnel(name, ttype, local_port, local_ip)
                    if resp.status_code == 201:
                        self.root.after(0, lambda: [dialog.destroy(), self._refresh_data()])
                    else:
                        err = resp.json().get("error", "Unknown error")
                        self.root.after(0, lambda: err_var.set(err))
                except requests.RequestException as e:
                    self.root.after(0, lambda: err_var.set(str(e)))

            threading.Thread(target=create_thread, daemon=True).start()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=5, column=1, pady=15, sticky=tk.E)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Create", command=do_create).pack(side=tk.LEFT, padx=5)

    def _enable_tunnel(self):
        tunnel = self._get_selected_tunnel()
        if not tunnel:
            return
        if tunnel["status"] == "Enabled":
            messagebox.showinfo("Info", "Tunnel already enabled")
            return
        if self.current_user_info and self.current_user_info.get("expired"):
            messagebox.showerror("Error", "Account has expired")
            return

        threading.Thread(target=self._enable_thread, args=(tunnel,), daemon=True).start()

    def _enable_thread(self, tunnel):
        try:
            resp = self.api.enable_tunnel(tunnel["id"])
            if resp.status_code != 200:
                err = resp.json().get("error", "Failed to enable")
                self.root.after(0, lambda: messagebox.showerror("Error", err))
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
                    TunnelEnableDialog(self.root, tunnel, data),
                    self._refresh_data(),
                ])
            else:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to start frpc: {msg}"))
        except requests.RequestException as e:
            self.root.after(0, lambda: messagebox.showerror("Connection Error", str(e)))

    def _disable_tunnel(self):
        tunnel = self._get_selected_tunnel()
        if not tunnel:
            return
        if tunnel["status"] != "Enabled":
            messagebox.showinfo("Info", "Tunnel is not enabled")
            return
        threading.Thread(target=self._disable_thread, args=(tunnel,), daemon=True).start()

    def _disable_thread(self, tunnel):
        try:
            resp = self.api.disable_tunnel(tunnel["id"])
            if resp.status_code != 200:
                err = resp.json().get("error", "Failed to disable")
                self.root.after(0, lambda: messagebox.showerror("Error", err))
                return
            _, msg = stop_frpc()
            self.root.after(0, lambda m=msg: [
                messagebox.showinfo("Success", f"Tunnel disabled\n{m}"),
                self._refresh_data(),
            ])
        except requests.RequestException as e:
            self.root.after(0, lambda: messagebox.showerror("Connection Error", str(e)))

    def _delete_tunnel(self):
        tunnel = self._get_selected_tunnel()
        if not tunnel:
            return
        if tunnel["status"] == "Enabled":
            messagebox.showerror("Error", "Disable the tunnel before deleting")
            return
        if not messagebox.askyesno("Confirm", f"Delete tunnel '{tunnel['name']}'?"):
            return
        threading.Thread(target=self._delete_thread, args=(tunnel,), daemon=True).start()

    def _delete_thread(self, tunnel):
        try:
            resp = self.api.delete_tunnel(tunnel["id"])
            if resp.status_code == 200:
                self.root.after(0, self._refresh_data)
            else:
                err = resp.json().get("error", "Failed to delete")
                self.root.after(0, lambda: messagebox.showerror("Error", err))
        except requests.RequestException as e:
            self.root.after(0, lambda: messagebox.showerror("Connection Error", str(e)))

    def _logout(self):
        self.current_user_id = None
        self.current_user_info = None
        stop_frpc()
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