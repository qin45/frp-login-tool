#!/usr/bin/env python3
"""
fp-multiuser 管理脚本
功能：
- 启动并监控 fp-multiuser 子进程
- 提供 REST API 动态增删用户（更新 tokens 文件后自动重启插件）
- 支持手动修改 tokens 文件时自动重启（可选，通过文件监控）
"""

import os
import subprocess
import sys
import time
import signal
import threading
import logging
from pathlib import Path

from flask import Flask, request, jsonify
from werkzeug.serving import run_simple

# ========== 配置区域（可通过环境变量覆盖）==========
FP_MULTIUSER_BIN = os.getenv("FP_MULTIUSER_BIN", "./fp-multiuser")   # fp-multiuser 二进制路径
PLUGIN_LISTEN = os.getenv("PLUGIN_LISTEN", "127.0.0.1:7200")         # 插件监听地址
TOKENS_FILE = os.getenv("TOKENS_FILE", "./tokens")                   # 用户凭证文件路径
API_HOST = os.getenv("API_HOST", "127.0.0.1")                        # API 监听地址
API_PORT = int(os.getenv("API_PORT", "8080"))                        # API 端口
WATCH_TOKENS_FILE = os.getenv("WATCH_TOKENS_FILE", "true").lower() == "true"  # 是否监控文件变化
# ================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("fp-multiuser-manager")

app = Flask(__name__)

# 全局变量管理子进程
plugin_process = None
process_lock = threading.Lock()
shutdown_event = threading.Event()


def read_tokens():
    """读取 tokens 文件，返回 dict {username: token}"""
    tokens = {}
    if not os.path.exists(TOKENS_FILE):
        return tokens
    with open(TOKENS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                user, token = line.split('=', 1)
                tokens[user.strip()] = token.strip()
    return tokens


def write_tokens(tokens_dict):
    """将 dict 写入 tokens 文件，保持格式 username=token"""
    with open(TOKENS_FILE, 'w', encoding='utf-8') as f:
        for user, token in tokens_dict.items():
            f.write(f"{user}={token}\n")
    logger.info(f"Tokens file updated: {TOKENS_FILE}")


def start_plugin():
    """启动 fp-multiuser 子进程"""
    global plugin_process
    cmd = [FP_MULTIUSER_BIN, "-l", PLUGIN_LISTEN, "-f", TOKENS_FILE]
    logger.info(f"Starting plugin: {' '.join(cmd)}")
    try:
        plugin_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        # 启动一个线程读取子进程输出并记录日志
        def log_output():
            for line in iter(plugin_process.stdout.readline, ''):
                if line:
                    logger.info(f"[fp-multiuser] {line.rstrip()}")
            logger.info("fp-multiuser stdout closed")
        threading.Thread(target=log_output, daemon=True).start()
        logger.info(f"Plugin started with PID {plugin_process.pid}")
    except Exception as e:
        logger.error(f"Failed to start plugin: {e}")
        sys.exit(1)


def stop_plugin():
    """停止 fp-multiuser 子进程"""
    global plugin_process
    if plugin_process and plugin_process.poll() is None:
        logger.info(f"Stopping plugin PID {plugin_process.pid}")
        plugin_process.terminate()
        try:
            plugin_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Force killing plugin")
            plugin_process.kill()
            plugin_process.wait()
        logger.info("Plugin stopped")
    plugin_process = None


def restart_plugin():
    """重启插件（停止当前，启动新进程）"""
    with process_lock:
        stop_plugin()
        start_plugin()


def add_user(username, token):
    """添加用户，如果用户已存在则更新 token"""
    tokens = read_tokens()
    tokens[username] = token
    write_tokens(tokens)
    return True


def remove_user(username):
    """删除用户，如果用户不存在返回 False"""
    tokens = read_tokens()
    if username not in tokens:
        return False
    del tokens[username]
    write_tokens(tokens)
    return True


# ========== API 端点 ==========
@app.route('/users', methods=['GET'])
def list_users():
    """列出所有用户（不显示 token）"""
    tokens = read_tokens()
    return jsonify({"users": list(tokens.keys())})


@app.route('/users', methods=['POST'])
def add_user_api():
    """添加用户，参数：username, token"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    username = data.get('username')
    token = data.get('token')
    if not username or not token:
        return jsonify({"error": "username and token required"}), 400
    add_user(username, token)
    # 重启插件使新用户生效
    restart_plugin()
    logger.info(f"User '{username}' added, plugin restarted")
    return jsonify({"status": "ok", "user": username})


@app.route('/users/<username>', methods=['DELETE'])
def remove_user_api(username):
    """删除用户"""
    if remove_user(username):
        restart_plugin()
        logger.info(f"User '{username}' removed, plugin restarted")
        return jsonify({"status": "ok", "user": username})
    else:
        return jsonify({"error": "user not found"}), 404


# ========== 文件监控（可选）==========
def watch_tokens_file():
    """监控 tokens 文件变化，如有外部修改则自动重启插件"""
    if not WATCH_TOKENS_FILE:
        return
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        logger.warning("watchdog not installed, file monitoring disabled")
        return

    class TokensFileHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.src_path == os.path.abspath(TOKENS_FILE):
                logger.info("Tokens file changed externally, restarting plugin")
                restart_plugin()

    event_handler = TokensFileHandler()
    observer = Observer()
    observer.schedule(event_handler, path=os.path.dirname(TOKENS_FILE) or '.', recursive=False)
    observer.start()
    logger.info(f"Started monitoring {TOKENS_FILE} for changes")
    return observer


# ========== 主流程 ==========
def main():
    # 确保二进制文件存在
    if not os.path.isfile(FP_MULTIUSER_BIN):
        logger.error(f"fp-multiuser binary not found at {FP_MULTIUSER_BIN}")
        sys.exit(1)

    # 启动插件
    start_plugin()

    # 启动文件监控（可选）
    observer = watch_tokens_file()

    # 启动 Flask API 服务（非阻塞方式，在单独线程运行）
    def run_api():
        run_simple(API_HOST, API_PORT, app, use_reloader=False, threaded=True)

    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    logger.info(f"API server listening on http://{API_HOST}:{API_PORT}")

    # 主线程监控插件进程，若意外退出则自动重启
    try:
        while not shutdown_event.is_set():
            if plugin_process.poll() is not None:
                logger.warning("Plugin process exited unexpectedly, restarting...")
                restart_plugin()
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        stop_plugin()
        if observer:
            observer.stop()
            observer.join()
        logger.info("Exited")


if __name__ == '__main__':
    main()