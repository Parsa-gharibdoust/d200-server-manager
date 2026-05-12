from __future__ import annotations

import argparse
import functools
import grp
import json
import os
import platform
import pwd
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Tuple

try:
    from flask import Flask, g, jsonify, request
except ImportError:
    Flask = None
    g = None
    jsonify = None
    request = None


class RouteShim:
    def route(self, *_args: Any, **_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return decorator


DEFAULT_USERNAME = "Parsa_gharibdoust"
DEFAULT_PASSWORD = "12345678"

username = os.environ.get("D200_MANAGER_USERNAME", DEFAULT_USERNAME)
password = os.environ.get("D200_MANAGER_PASSWORD", DEFAULT_PASSWORD)

APP_NAME = "d200-manager"
BUFFER_LIMIT = 200_000
TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, ".d200_manager_sessions.json")
PROTECTED_PATHS = {
    os.path.abspath(__file__),
    os.path.join(BASE_DIR, "Client.py"),
    SESSION_FILE,
}

INSTALL_PRESETS: Dict[str, Dict[str, object]] = {
    "git": {"label": "Install Git", "packages": {"apt-get": "git", "dnf": "git", "yum": "git", "pacman": "git", "zypper": "git", "apk": "git"}},
    "brew": {"label": "Install Homebrew", "custom": "NONINTERACTIVE=1 bash -lc \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""},
    "docker": {"label": "Install Docker", "custom": "curl -fsSL https://get.docker.com | sh"},
    "python3": {"label": "Install Python 3", "packages": {"apt-get": "python3 python3-pip python3-venv", "dnf": "python3 python3-pip", "yum": "python3 python3-pip", "pacman": "python python-pip", "zypper": "python3 python3-pip", "apk": "python3 py3-pip"}},
    "cmake": {"label": "Install CMake", "packages": {"apt-get": "cmake", "dnf": "cmake", "yum": "cmake", "pacman": "cmake", "zypper": "cmake", "apk": "cmake"}},
    "build-essential": {"label": "Install build tools", "packages": {"apt-get": "build-essential", "dnf": "@development-tools", "yum": "@development-tools", "pacman": "base-devel", "zypper": "gcc gcc-c++ make", "apk": "build-base"}},
    "curl": {"label": "Install curl", "packages": {"apt-get": "curl", "dnf": "curl", "yum": "curl", "pacman": "curl", "zypper": "curl", "apk": "curl"}},
    "wget": {"label": "Install wget", "packages": {"apt-get": "wget", "dnf": "wget", "yum": "wget", "pacman": "wget", "zypper": "wget", "apk": "wget"}},
    "htop": {"label": "Install htop", "packages": {"apt-get": "htop", "dnf": "htop", "yum": "htop", "pacman": "htop", "zypper": "htop", "apk": "htop"}},
    "tmux": {"label": "Install tmux", "packages": {"apt-get": "tmux", "dnf": "tmux", "yum": "tmux", "pacman": "tmux", "zypper": "tmux", "apk": "tmux"}},
    "screen": {"label": "Install screen", "packages": {"apt-get": "screen", "dnf": "screen", "yum": "screen", "pacman": "screen", "zypper": "screen", "apk": "screen"}},
    "nodejs": {"label": "Install Node.js", "packages": {"apt-get": "nodejs npm", "dnf": "nodejs npm", "yum": "nodejs npm", "pacman": "nodejs npm", "zypper": "nodejs npm", "apk": "nodejs npm"}},
    "pipx": {"label": "Install pipx", "packages": {"apt-get": "pipx", "dnf": "pipx", "yum": "pipx", "pacman": "python-pipx", "zypper": "python311-pipx", "apk": "py3-pipx"}},
    "nginx": {"label": "Install Nginx", "packages": {"apt-get": "nginx", "dnf": "nginx", "yum": "nginx", "pacman": "nginx", "zypper": "nginx", "apk": "nginx"}},
    "ufw": {"label": "Install UFW", "packages": {"apt-get": "ufw", "dnf": "ufw", "yum": "ufw", "pacman": "ufw", "zypper": "ufw", "apk": "ufw"}},
    "unzip": {"label": "Install unzip", "packages": {"apt-get": "unzip", "dnf": "unzip", "yum": "unzip", "pacman": "unzip", "zypper": "unzip", "apk": "unzip"}},
    "jq": {"label": "Install jq", "packages": {"apt-get": "jq", "dnf": "jq", "yum": "jq", "pacman": "jq", "zypper": "jq", "apk": "jq"}},
    "rsync": {"label": "Install rsync", "packages": {"apt-get": "rsync", "dnf": "rsync", "yum": "rsync", "pacman": "rsync", "zypper": "rsync", "apk": "rsync"}},
    "fail2ban": {"label": "Install fail2ban", "packages": {"apt-get": "fail2ban", "dnf": "fail2ban", "yum": "fail2ban", "pacman": "fail2ban", "zypper": "fail2ban", "apk": "fail2ban"}},
    "net-tools": {"label": "Install net-tools", "packages": {"apt-get": "net-tools", "dnf": "net-tools", "yum": "net-tools", "pacman": "net-tools", "zypper": "net-tools", "apk": "net-tools"}},
}

if Flask is not None:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
else:
    app = RouteShim()

SESSION_LOCK = threading.Lock()


def current_timestamp() -> int:
    return int(time.time())


def ensure_linux() -> None:
    if not sys.platform.startswith("linux"):
        raise SystemExit("This server is Linux-only.")


def clip_output(value: str) -> str:
    return value[:BUFFER_LIMIT]


def load_session_store() -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(SESSION_FILE):
        return {}
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    sessions: Dict[str, Dict[str, Any]] = {}
    for token, payload in raw.items():
        if not isinstance(token, str) or not isinstance(payload, dict):
            continue
        sessions[token] = {
            "ip": str(payload.get("ip") or ""),
            "created_at": int(payload.get("created_at") or current_timestamp()),
            "last_seen": int(payload.get("last_seen") or current_timestamp()),
        }
    return sessions


def save_session_store_locked(sessions: Dict[str, Dict[str, Any]]) -> None:
    os.makedirs(BASE_DIR, exist_ok=True)
    temp_path = SESSION_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(sessions, handle, indent=2)
    os.replace(temp_path, SESSION_FILE)


def prune_session_store_locked(sessions: Dict[str, Dict[str, Any]]) -> None:
    cutoff = current_timestamp() - TOKEN_TTL_SECONDS
    expired = [token for token, payload in sessions.items() if int(payload.get("last_seen") or 0) < cutoff]
    for token in expired:
        sessions.pop(token, None)


ACTIVE_TOKENS = load_session_store()


def json_ok(**payload: Any) -> Tuple[Any, int]:
    return jsonify({"ok": True, **payload}), 200


def json_error(message: str, status: int = 400, **payload: Any) -> Tuple[Any, int]:
    return jsonify({"ok": False, "error": message, **payload}), status


def error_response(error: Exception) -> Tuple[Any, int]:
    if isinstance(error, FileNotFoundError):
        return json_error(str(error), 404)
    if isinstance(error, PermissionError):
        return json_error(str(error), 403)
    if isinstance(error, (ValueError, NotADirectoryError)):
        return json_error(str(error), 400)
    return json_error(str(error) or "Internal server error.", 500)


def get_client_ip() -> str:
    return request.remote_addr or "unknown"


def extract_bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return ""
    return header[7:].strip()


def require_auth(handler: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(handler)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        token = extract_bearer_token()
        if not token:
            return json_error("Missing Bearer token.", 401)

        ip_address = get_client_ip()
        with SESSION_LOCK:
            prune_session_store_locked(ACTIVE_TOKENS)
            session = ACTIVE_TOKENS.get(token)
            if not session:
                save_session_store_locked(ACTIVE_TOKENS)
                return json_error("Session expired or invalid.", 401)
            if session.get("ip") != ip_address:
                ACTIVE_TOKENS.pop(token, None)
                save_session_store_locked(ACTIVE_TOKENS)
                return json_error("Client IP changed. Please login again.", 401)
            session["last_seen"] = current_timestamp()
            save_session_store_locked(ACTIVE_TOKENS)

        g.session_token = token
        g.client_ip = ip_address
        return handler(*args, **kwargs)

    return wrapped


def request_payload() -> Dict[str, Any]:
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object.")
    return payload


def expand_path(path_value: str) -> str:
    if not path_value or not path_value.strip():
        raise ValueError("A path value is required.")
    return os.path.abspath(os.path.expanduser(path_value.strip()))


def format_timestamp(epoch_value: float) -> str:
    return datetime.fromtimestamp(epoch_value, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def human_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(size)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{size} B"


def read_os_release() -> str:
    path = "/etc/os-release"
    if not os.path.exists(path):
        return platform.platform()
    values: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values.get("PRETTY_NAME") or values.get("NAME") or platform.platform()


def read_memory_info() -> Dict[str, str]:
    values: Dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, value = line.split(":", 1)
            amount = value.strip().split()[0]
            values[key] = int(amount) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    used = max(total - available, 0)
    return {
        "total": human_bytes(total),
        "used": human_bytes(used),
        "available": human_bytes(available),
    }


def read_uptime() -> str:
    with open("/proc/uptime", "r", encoding="utf-8") as handle:
        seconds = int(float(handle.read().split()[0]))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def detect_package_manager() -> str | None:
    for manager in ("apt-get", "dnf", "yum", "pacman", "zypper", "apk"):
        if shutil.which(manager):
            return manager
    return None


def run_program(argv: List[str]) -> Dict[str, Any]:
    process = subprocess.run(argv, capture_output=True, text=True)
    return {
        "command": argv,
        "exit_code": process.returncode,
        "stdout": clip_output(process.stdout),
        "stderr": clip_output(process.stderr),
    }


def run_shell(command: str) -> Dict[str, Any]:
    process = subprocess.run(["bash", "-lc", command], capture_output=True, text=True)
    return {
        "command": command,
        "exit_code": process.returncode,
        "stdout": clip_output(process.stdout),
        "stderr": clip_output(process.stderr),
    }


def lookup_owner(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def lookup_group(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def describe_path(path_value: str) -> Dict[str, Any]:
    info = os.lstat(path_value)
    owner = lookup_owner(info.st_uid)
    group = lookup_group(info.st_gid)
    if stat.S_ISDIR(info.st_mode):
        entry_type = "directory"
    elif stat.S_ISREG(info.st_mode):
        entry_type = "file"
    elif stat.S_ISLNK(info.st_mode):
        entry_type = "symlink"
    else:
        entry_type = "other"
    payload = {
        "name": os.path.basename(path_value) or path_value,
        "path": path_value,
        "type": entry_type,
        "size_bytes": info.st_size,
        "size_human": human_bytes(info.st_size),
        "permissions": stat.filemode(info.st_mode),
        "owner": owner,
        "group": group,
        "modified_at": format_timestamp(info.st_mtime),
    }
    if entry_type == "symlink":
        payload["target"] = os.path.realpath(path_value)
    return payload


def list_path(path_value: str) -> Dict[str, Any]:
    resolved = expand_path(path_value)
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"Path not found: {resolved}")
    payload = {"path": resolved, "info": describe_path(resolved), "entries": []}
    if os.path.isdir(resolved):
        entries = []
        with os.scandir(resolved) as iterator:
            for entry in iterator:
                try:
                    entries.append(describe_path(entry.path))
                except OSError:
                    continue
        payload["entries"] = sorted(entries, key=lambda item: (item["type"] != "directory", item["name"].lower()))
    return payload


def read_file(path_value: str) -> Dict[str, Any]:
    resolved = expand_path(path_value)
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"File not found: {resolved}")
    with open(resolved, "rb") as handle:
        raw = handle.read(BUFFER_LIMIT + 1)
    truncated = len(raw) > BUFFER_LIMIT
    text = raw[:BUFFER_LIMIT].decode("utf-8", errors="replace")
    return {
        "path": resolved,
        "content": text,
        "truncated": truncated,
        "size_bytes": os.path.getsize(resolved),
    }


def write_file(path_value: str, content: str) -> Dict[str, Any]:
    resolved = expand_path(path_value)
    parent = os.path.dirname(resolved) or "."
    os.makedirs(parent, exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as handle:
        handle.write(content)
    return {"path": resolved, "bytes_written": len(content.encode("utf-8"))}


def rename_path(source_value: str, destination_value: str) -> Dict[str, Any]:
    source = expand_path(source_value)
    destination = expand_path(destination_value)
    if not os.path.exists(source):
        raise FileNotFoundError(f"Path not found: {source}")
    parent = os.path.dirname(destination) or "."
    os.makedirs(parent, exist_ok=True)
    os.rename(source, destination)
    return {"source": source, "destination": destination}


def delete_path(path_value: str) -> Dict[str, Any]:
    resolved = expand_path(path_value)
    if resolved == "/":
        raise ValueError("Deleting the filesystem root is blocked.")
    if resolved in PROTECTED_PATHS:
        raise ValueError("Deleting d200-manager core files is blocked.")
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"Path not found: {resolved}")
    if os.path.isdir(resolved) and not os.path.islink(resolved):
        shutil.rmtree(resolved)
    else:
        os.remove(resolved)
    return {"deleted": resolved}


def screen_sessions() -> Dict[str, Any]:
    if shutil.which("screen") is None:
        return {"available": False, "sessions": [], "raw_output": "", "stderr": "screen is not installed."}
    result = run_program(["screen", "-ls"])
    sessions = []
    for raw_line in result["stdout"].splitlines():
        line = raw_line.strip()
        if not line or line.startswith("No Sockets"):
            continue
        if "(" not in line or ")" not in line:
            continue
        name = line.split()[0]
        status = line[line.find("(") + 1 : line.find(")")]
        sessions.append({"name": name, "status": status, "raw": line})
    return {
        "available": True,
        "sessions": sessions,
        "raw_output": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
    }


def docker_containers() -> Dict[str, Any]:
    if shutil.which("docker") is None:
        return {"available": False, "containers": [], "stderr": "docker is not installed."}
    result = run_program(["docker", "ps", "-a", "--format", "{{json .}}"])
    containers = []
    for line in result["stdout"].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            containers.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {
        "available": True,
        "containers": containers,
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
    }


def docker_action(name: str, action: str) -> Dict[str, Any]:
    if action not in {"start", "stop", "restart"}:
        raise ValueError("Docker action must be one of: start, stop, restart.")
    if shutil.which("docker") is None:
        raise ValueError("docker is not installed.")
    result = run_program(["docker", action, name])
    return {
        "container": name,
        "action": action,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
    }


def service_list() -> Dict[str, Any]:
    if shutil.which("systemctl") is None:
        return {"available": False, "services": [], "stderr": "systemctl is not available on this server."}
    result = run_program(["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend", "--plain"])
    services = []
    for line in result["stdout"].splitlines()[:200]:
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        services.append(
            {
                "unit": parts[0],
                "load": parts[1],
                "active": parts[2],
                "sub": parts[3],
                "description": parts[4] if len(parts) > 4 else "",
            }
        )
    return {
        "available": True,
        "services": services,
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
    }


def restart_service(service_name: str) -> Dict[str, Any]:
    if not service_name.strip():
        raise ValueError("Service name is required.")
    if shutil.which("systemctl") is None:
        raise ValueError("systemctl is not available on this server.")
    restart_result = run_program(["systemctl", "restart", service_name])
    status_result = run_program(["systemctl", "status", service_name, "--no-pager", "--lines=12"])
    return {
        "service": service_name,
        "restart_exit_code": restart_result["exit_code"],
        "restart_stdout": restart_result["stdout"],
        "restart_stderr": restart_result["stderr"],
        "status_exit_code": status_result["exit_code"],
        "status_stdout": status_result["stdout"],
        "status_stderr": status_result["stderr"],
    }


def journal_logs(service_name: str | None, line_count: int) -> Dict[str, Any]:
    lines = max(1, min(line_count, 200))
    if shutil.which("journalctl") is None:
        raise ValueError("journalctl is not available on this server.")
    if service_name:
        result = run_program(["journalctl", "-u", service_name, "-n", str(lines), "--no-pager"])
    else:
        result = run_program(["journalctl", "-n", str(lines), "--no-pager"])
    return {
        "service": service_name or "",
        "lines": lines,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
    }


def top_processes() -> Dict[str, Any]:
    result = run_shell("ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu | head -n 26")
    return {
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
    }


def listening_ports() -> Dict[str, Any]:
    if shutil.which("ss") is not None:
        result = run_program(["ss", "-tulpn"])
    elif shutil.which("netstat") is not None:
        result = run_program(["netstat", "-tulpn"])
    else:
        raise ValueError("Neither ss nor netstat is available.")
    return {
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
    }


def build_install_command(preset_name: str) -> str:
    preset = INSTALL_PRESETS.get(preset_name)
    if not preset:
        raise ValueError(f"Unknown install preset: {preset_name}")

    custom = preset.get("custom")
    if custom:
        return str(custom)

    manager = detect_package_manager()
    if not manager:
        raise ValueError("No supported package manager found.")

    packages = preset["packages"].get(manager)
    if not packages:
        raise ValueError(f"{preset_name} is not mapped for {manager}.")

    if manager == "apt-get":
        return f"DEBIAN_FRONTEND=noninteractive apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y {packages}"
    if manager == "dnf":
        return f"dnf install -y {packages}"
    if manager == "yum":
        return f"yum install -y {packages}"
    if manager == "pacman":
        return f"pacman -Sy --noconfirm {packages}"
    if manager == "zypper":
        return f"zypper --non-interactive install {packages}"
    if manager == "apk":
        return f"apk add --no-cache {packages}"
    raise ValueError(f"Unsupported package manager: {manager}")


def install_options() -> List[Dict[str, str]]:
    return [{"name": name, "label": str(meta["label"])} for name, meta in sorted(INSTALL_PRESETS.items())]


def run_install(preset_name: str) -> Dict[str, Any]:
    command = build_install_command(preset_name)
    result = run_shell(command)
    return {
        "preset": preset_name,
        "command": command,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
    }


def server_snapshot() -> Dict[str, Any]:
    hostname = socket.gethostname()
    ip_result = run_shell("hostname -I 2>/dev/null || true")
    disk = shutil.disk_usage("/")
    return {
        "app": APP_NAME,
        "hostname": hostname,
        "current_user": lookup_owner(os.getuid()),
        "os_release": read_os_release(),
        "kernel": platform.platform(),
        "uptime": read_uptime(),
        "load_average": os.getloadavg(),
        "ips": ip_result["stdout"].split(),
        "memory": read_memory_info(),
        "disk": {
            "total": human_bytes(disk.total),
            "used": human_bytes(disk.used),
            "free": human_bytes(disk.free),
        },
        "tools": {name: shutil.which(name) is not None for name in ("screen", "docker", "git", "python3", "cmake", "node", "npm")},
        "package_manager": detect_package_manager(),
    }


@app.route("/", methods=["GET"])
def root() -> Any:
    return json_ok(
        app=APP_NAME,
        message="Flask server is running.",
        login="/login",
        docs=[
            "/api/session",
            "/api/server-info",
            "/api/screens",
            "/api/docker",
            "/api/services",
            "/api/logs",
            "/api/files/list",
            "/api/install/options",
        ],
    )


@app.route("/login", methods=["POST"])
def login() -> Any:
    try:
        payload = request_payload()
        submitted_username = str(payload.get("username") or "")
        submitted_password = str(payload.get("password") or "")
        if submitted_username != username or submitted_password != password:
            return json_error("Invalid username or password.", 401)

        token = secrets.token_urlsafe(32)
        session_payload = {
            "ip": get_client_ip(),
            "created_at": current_timestamp(),
            "last_seen": current_timestamp(),
        }
        with SESSION_LOCK:
            prune_session_store_locked(ACTIVE_TOKENS)
            ACTIVE_TOKENS[token] = session_payload
            save_session_store_locked(ACTIVE_TOKENS)

        return json_ok(
            message="Login successful.",
            token=token,
            bind_ip=session_payload["ip"],
            token_ttl_seconds=TOKEN_TTL_SECONDS,
        )
    except Exception as error:  
        return error_response(error)


@app.route("/logout", methods=["POST"])
@require_auth
def logout() -> Any:
    with SESSION_LOCK:
        ACTIVE_TOKENS.pop(g.session_token, None)
        save_session_store_locked(ACTIVE_TOKENS)
    return json_ok(message="Logged out.")


@app.route("/api/session", methods=["GET"])
@require_auth
def session_info() -> Any:
    with SESSION_LOCK:
        session_payload = dict(ACTIVE_TOKENS.get(g.session_token, {}))
    return json_ok(
        username=username,
        bind_ip=session_payload.get("ip"),
        created_at=session_payload.get("created_at"),
        last_seen=session_payload.get("last_seen"),
        token_ttl_seconds=TOKEN_TTL_SECONDS,
    )


@app.route("/api/server-info", methods=["GET"])
@require_auth
def api_server_info() -> Any:
    try:
        return json_ok(info=server_snapshot())
    except Exception as error:  
        return error_response(error)


@app.route("/api/screens", methods=["GET"])
@require_auth
def api_screens() -> Any:
    try:
        return json_ok(data=screen_sessions())
    except Exception as error:  
        return error_response(error)


@app.route("/api/docker", methods=["GET"])
@require_auth
def api_docker() -> Any:
    try:
        return json_ok(data=docker_containers())
    except Exception as error:  
        return error_response(error)


@app.route("/api/docker/action", methods=["POST"])
@require_auth
def api_docker_action() -> Any:
    try:
        payload = request_payload()
        name = str(payload.get("name") or "")
        action = str(payload.get("action") or "")
        return json_ok(data=docker_action(name, action))
    except Exception as error:  
        return error_response(error)


@app.route("/api/services", methods=["GET"])
@require_auth
def api_services() -> Any:
    try:
        return json_ok(data=service_list())
    except Exception as error:  
        return error_response(error)


@app.route("/api/services/restart", methods=["POST"])
@require_auth
def api_services_restart() -> Any:
    try:
        payload = request_payload()
        service_name = str(payload.get("service") or "")
        return json_ok(data=restart_service(service_name))
    except Exception as error:  #
        return error_response(error)


@app.route("/api/logs", methods=["POST"])
@require_auth
def api_logs() -> Any:
    try:
        payload = request_payload()
        service_name = str(payload.get("service") or "").strip() or None
        lines = int(payload.get("lines") or 80)
        return json_ok(data=journal_logs(service_name, lines))
    except Exception as error:  
        return error_response(error)


@app.route("/api/processes", methods=["GET"])
@require_auth
def api_processes() -> Any:
    try:
        return json_ok(data=top_processes())
    except Exception as error:  
        return error_response(error)


@app.route("/api/ports", methods=["GET"])
@require_auth
def api_ports() -> Any:
    try:
        return json_ok(data=listening_ports())
    except Exception as error:  
        return error_response(error)


@app.route("/api/files/list", methods=["POST"])
@require_auth
def api_files_list() -> Any:
    try:
        payload = request_payload()
        return json_ok(data=list_path(str(payload.get("path") or "/")))
    except Exception as error:  
        return error_response(error)


@app.route("/api/files/read", methods=["POST"])
@require_auth
def api_files_read() -> Any:
    try:
        payload = request_payload()
        return json_ok(data=read_file(str(payload.get("path") or "")))
    except Exception as error:  
        return error_response(error)


@app.route("/api/files/write", methods=["POST"])
@require_auth
def api_files_write() -> Any:
    try:
        payload = request_payload()
        path_value = str(payload.get("path") or "")
        content = str(payload.get("content") or "")
        return json_ok(data=write_file(path_value, content))
    except Exception as error:  
        return error_response(error)


@app.route("/api/files/rename", methods=["POST"])
@require_auth
def api_files_rename() -> Any:
    try:
        payload = request_payload()
        source_value = str(payload.get("source") or "")
        destination_value = str(payload.get("destination") or "")
        return json_ok(data=rename_path(source_value, destination_value))
    except Exception as error:  
        return error_response(error)


@app.route("/api/files/delete", methods=["POST"])
@require_auth
def api_files_delete() -> Any:
    try:
        payload = request_payload()
        return json_ok(data=delete_path(str(payload.get("path") or "")))
    except Exception as error:  
        return error_response(error)


@app.route("/api/install/options", methods=["GET"])
@require_auth
def api_install_options() -> Any:
    return json_ok(package_manager=detect_package_manager(), options=install_options())


@app.route("/api/install", methods=["POST"])
@require_auth
def api_install() -> Any:
    try:
        payload = request_payload()
        preset_name = str(payload.get("preset") or "")
        return json_ok(data=run_install(preset_name))
    except Exception as error:  
        return error_response(error)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Flask server manager")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind")
    parser.add_argument("--debug", action="store_true", help="Run Flask in debug mode")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if Flask is None:
        raise SystemExit("Flask is not installed. Run: pip3 install flask")

    ensure_linux()
    print(f"{APP_NAME} listening on http://{args.host}:{args.port}")
    print(f"Configured login username: {username}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
