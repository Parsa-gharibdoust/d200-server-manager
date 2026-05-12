from __future__ import annotations

import argparse
import getpass
import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    import requests
except ImportError:
    requests = None

APP_NAME = "d200-manager"
SESSION_FILE = os.path.expanduser("~/.d200_manager_client.json")
DEFAULT_TIMEOUT = 25
MENU_WIDTH = 64


class ApiError(Exception):
    pass


class AuthError(ApiError):
    pass


def divider(char: str = "-") -> None:
    print(char * MENU_WIDTH)


def header(title: str) -> None:
    print()
    divider("=")
    print(title)
    divider("=")


def subheader(title: str) -> None:
    print()
    print(title)
    divider()


def prompt(text: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    if value:
        return value
    return default or ""


def ask_yes_no(text: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    value = input(f"{text} [{marker}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def prompt_multiline() -> str:
    print("Paste or type the full content below.")
    print("When you are done, write EOF on its own line.")
    lines: List[str] = []
    while True:
        line = input()
        if line == "EOF":
            break
        lines.append(line)
    return "\n".join(lines)


def pause() -> None:
    input("\nPress Enter to return to the menu...")


def choose_menu(title: str, options: Sequence[Tuple[str, str]]) -> str:
    header(title)
    for key, label in options:
        print(f"{key}. {label}")
    while True:
        choice = input("\nChoose a number: ").strip()
        if any(choice == key for key, _label in options):
            return choice
        print("Please choose one of the numbers shown above.")


def print_label(label: str, value: Any) -> None:
    print(f"{label:<18} {value}")


def format_epoch(value: Any) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromtimestamp(int(value)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)


def short_text(value: str, width: int = 54) -> str:
    text = value.strip()
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


def type_label(entry_type: str) -> str:
    mapping = {
        "directory": "DIR ",
        "file": "FILE",
        "symlink": "LINK",
    }
    return mapping.get(entry_type, "ITEM")


def show_text_block(title: str, body: str, empty_message: str = "(no output)") -> None:
    header(title)
    print(body.strip() or empty_message)


def load_session_cache() -> Dict[str, Any]:
    if not os.path.exists(SESSION_FILE):
        return {}
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_session_cache(payload: Dict[str, Any]) -> None:
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except OSError:
        pass


def clear_session_cache() -> None:
    try:
        os.remove(SESSION_FILE)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def normalize_url(base_url: str) -> str:
    if not base_url.startswith(("http://", "https://")):
        base_url = "http://" + base_url
    return base_url.rstrip("/")


class ManagerClient:
    def __init__(self, base_url: str, token: Optional[str] = None) -> None:
        if requests is None:
            raise RuntimeError("requests is not installed. Run: pip3 install requests")
        self.base_url = normalize_url(base_url)
        self.session = requests.Session()
        self.timeout = DEFAULT_TIMEOUT
        self.token: Optional[str] = None
        if token:
            self.set_token(token)

    def set_token(self, token: str) -> None:
        self.token = token
        self.session.headers["Authorization"] = f"Bearer {token}"

    def clear_token(self) -> None:
        self.token = None
        self.session.headers.pop("Authorization", None)

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.base_url + path
        try:
            response = self.session.request(method=method, url=url, json=payload, timeout=self.timeout)
        except requests.RequestException as error:
            raise ApiError(f"Could not reach the server: {error}") from error

        try:
            data = response.json()
        except ValueError as error:
            raise ApiError(f"The server returned a non-JSON response ({response.status_code}).") from error

        if response.status_code == 401:
            raise AuthError(str(data.get("error") or "Unauthorized"))
        if not response.ok or not data.get("ok", False):
            raise ApiError(str(data.get("error") or f"Request failed with status {response.status_code}."))
        return data

    def login(self, user_name: str, password_value: str) -> Dict[str, Any]:
        data = self.request("POST", "/login", {"username": user_name, "password": password_value})
        token = str(data.get("token") or "")
        if not token:
            raise ApiError("Login succeeded but no token was returned.")
        self.set_token(token)
        return data

    def logout(self) -> None:
        try:
            self.request("POST", "/logout", {})
        finally:
            self.clear_token()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} terminal client")
    parser.add_argument("--url", help="Base URL of the Flask server")
    parser.add_argument("--username", help="Login username")
    parser.add_argument("--password", help="Login password")
    parser.add_argument("--no-session-cache", action="store_true", help="Do not store URL and token locally")
    return parser


def resolve_base_url(args: argparse.Namespace) -> tuple[str, Dict[str, Any]]:
    cached = {} if args.no_session_cache else load_session_cache()
    default_url = str(cached.get("base_url") or "http://127.0.0.1:5000")
    base_url = args.url or prompt("Server address", default_url)
    return normalize_url(base_url), cached


def perform_login(client: ManagerClient, args: argparse.Namespace, cached: Dict[str, Any], use_cache: bool) -> str:
    cached_token = str(cached.get("token") or "")
    cached_username = str(cached.get("username") or "Parsa_gharibdoust")

    if cached_token and cached.get("base_url") == client.base_url:
        client.set_token(cached_token)
        try:
            client.request("GET", "/api/session")
            print("Saved login found. You are already signed in.")
            return cached_username
        except AuthError:
            client.clear_token()

    user_name = args.username or prompt("Login username", cached_username or "Parsa_gharibdoust")
    password_value = args.password or getpass.getpass("Password: ")
    data = client.login(user_name, password_value)
    print(f"Login successful. This session is tied to IP: {data.get('bind_ip')}")

    if use_cache:
        save_session_cache(
            {
                "base_url": client.base_url,
                "username": user_name,
                "token": client.token,
            }
        )
    return user_name


def show_server_info(client: ManagerClient) -> None:
    info = client.request("GET", "/api/server-info")["info"]
    header("Quick Server Overview")
    print_label("Hostname", info.get("hostname", "-"))
    print_label("Server user", info.get("current_user", "-"))
    print_label("OS", info.get("os_release", "-"))
    print_label("Kernel", info.get("kernel", "-"))
    print_label("Uptime", info.get("uptime", "-"))
    print_label("Load average", info.get("load_average", "-"))
    print_label("IP addresses", ", ".join(info.get("ips") or []) or "-")

    memory = info.get("memory") or {}
    disk = info.get("disk") or {}
    print_label("Memory", f"{memory.get('used', '-')} used / {memory.get('total', '-')}")
    print_label("Disk", f"{disk.get('used', '-')} used / {disk.get('total', '-')}")
    print_label("Free disk", disk.get("free", "-"))
    print_label("Package mgr", info.get("package_manager", "-"))

    tools = info.get("tools") or {}
    installed = sorted(name for name, ready in tools.items() if ready)
    missing = sorted(name for name, ready in tools.items() if not ready)
    print_label("Installed tools", ", ".join(installed) or "-")
    print_label("Missing tools", ", ".join(missing) or "-")


def show_session_info(client: ManagerClient) -> None:
    data = client.request("GET", "/api/session")
    header("Current Login Session")
    print_label("Username", data.get("username", "-"))
    print_label("Bound IP", data.get("bind_ip", "-"))
    print_label("Created at", format_epoch(data.get("created_at")))
    print_label("Last seen", format_epoch(data.get("last_seen")))
    print_label("Session TTL", f"{int(data.get('token_ttl_seconds', 0)) // 3600} hours")


def show_screens(client: ManagerClient) -> None:
    data = client.request("GET", "/api/screens")["data"]
    header("Screen Sessions")
    if not data.get("available"):
        print(data.get("stderr") or "screen is not installed on this server.")
        return

    sessions = data.get("sessions") or []
    if not sessions:
        print("No screen sessions are open right now.")
        return

    print(f"Open screen sessions: {len(sessions)}")
    divider()
    for index, session in enumerate(sessions, start=1):
        print(f"{index}. {session.get('name', '-'):<26} {session.get('status', '-')}")


def show_docker(client: ManagerClient) -> List[Dict[str, Any]]:
    data = client.request("GET", "/api/docker")["data"]
    header("Docker Containers")
    if not data.get("available"):
        print(data.get("stderr") or "docker is not installed on this server.")
        return []

    containers = data.get("containers") or []
    if not containers:
        print("No Docker containers were found.")
        return []

    for index, container in enumerate(containers, start=1):
        name = container.get("Names", "-")
        image = short_text(str(container.get("Image", "-")), 24)
        status = short_text(str(container.get("Status", "-")), 24)
        ports = short_text(str(container.get("Ports", "-") or "-"), 22)
        print(f"{index:>2}. {name:<18} {status:<24} {image:<24} {ports}")
    return containers


def choose_item(title: str, items: Sequence[Dict[str, Any]], formatter: Callable[[Dict[str, Any]], str]) -> Optional[Dict[str, Any]]:
    header(title)
    if not items:
        print("Nothing is available here yet.")
        return None

    for index, item in enumerate(items, start=1):
        print(f"{index}. {formatter(item)}")
    print("0. Cancel")

    while True:
        raw = input("\nChoose a number: ").strip()
        if raw == "0" or raw == "":
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(items):
                return items[index - 1]
        print("Please choose a valid number.")


def run_docker_action(client: ManagerClient, action: str) -> None:
    containers = client.request("GET", "/api/docker")["data"].get("containers") or []
    chosen = choose_item(
        f"Docker: {action.capitalize()} a Container",
        containers,
        lambda item: f"{item.get('Names', '-')} ({item.get('Status', '-')})",
    )
    if not chosen:
        print("No container selected.")
        return

    result = client.request(
        "POST",
        "/api/docker/action",
        {"name": chosen.get("Names", ""), "action": action},
    )["data"]
    show_text_block(
        f"Docker {action.capitalize()} Result",
        (result.get("stdout") or "") + ("\n" + result.get("stderr", "") if result.get("stderr") else ""),
        empty_message="The command finished without extra output.",
    )


def browse_path(client: ManagerClient) -> None:
    path = prompt("Folder path", "/")
    data = client.request("POST", "/api/files/list", {"path": path})["data"]
    info = data.get("info") or {}
    entries = data.get("entries") or []

    header("Folder View")
    print_label("Path", data.get("path", "-"))
    print_label("Type", info.get("type", "-"))
    print_label("Owner", f"{info.get('owner', '-')}:{info.get('group', '-')}")
    print_label("Permissions", info.get("permissions", "-"))
    print_label("Updated", info.get("modified_at", "-"))
    print_label("Items", len(entries))

    if not entries:
        print("\nThis folder is empty.")
        return

    subheader("Contents")
    for index, entry in enumerate(entries[:60], start=1):
        print(
            f"{index:>2}. {type_label(str(entry.get('type', '')))}  "
            f"{short_text(str(entry.get('name', '-')), 30):<30}  "
            f"{str(entry.get('size_human', '-')):<10}  "
            f"{entry.get('modified_at', '-')}"
        )
    if len(entries) > 60:
        print(f"\nOnly the first 60 items are shown here. Total items: {len(entries)}")


def read_file(client: ManagerClient) -> None:
    path = prompt("File path")
    data = client.request("POST", "/api/files/read", {"path": path})["data"]
    header(f"File: {data.get('path', path)}")
    if data.get("truncated"):
        print("Note: this file is large, so only the first part is shown.")
        divider()
    print(data.get("content") or "(empty file)")


def write_file(client: ManagerClient) -> None:
    path = prompt("File path")
    header("Write File")
    print(f"You are about to replace the full content of: {path}")
    if not ask_yes_no("Do you want to continue", default=False):
        print("Write cancelled.")
        return
    content = prompt_multiline()
    data = client.request("POST", "/api/files/write", {"path": path, "content": content})["data"]
    header("File Saved")
    print_label("Path", data.get("path", "-"))
    print_label("Bytes written", data.get("bytes_written", "-"))


def rename_path(client: ManagerClient) -> None:
    header("Rename or Move")
    source = prompt("Current path")
    destination = prompt("New path")
    data = client.request("POST", "/api/files/rename", {"source": source, "destination": destination})["data"]
    print("Done.")
    print_label("From", data.get("source", "-"))
    print_label("To", data.get("destination", "-"))


def delete_path(client: ManagerClient) -> None:
    path = prompt("Path to delete")
    header("Delete File or Folder")
    print(f"Target: {path}")
    print("This action cannot be undone.")
    confirmation = input("Type DELETE to continue: ").strip()
    if confirmation != "DELETE":
        print("Delete cancelled.")
        return
    data = client.request("POST", "/api/files/delete", {"path": path})["data"]
    print(f"Deleted: {data.get('deleted', path)}")


def show_services(client: ManagerClient) -> List[Dict[str, Any]]:
    data = client.request("GET", "/api/services")["data"]
    header("Services")
    if not data.get("available"):
        print(data.get("stderr") or "Service management is not available here.")
        return []

    services = data.get("services") or []
    if not services:
        print("No services were returned by the server.")
        return []

    active_services = [service for service in services if service.get("active") == "active"]
    shown = active_services[:40] if active_services else services[:40]
    print(f"Showing {len(shown)} service(s).")
    divider()
    for index, service in enumerate(shown, start=1):
        print(
            f"{index:>2}. {service.get('unit', '-'):<28} "
            f"{service.get('active', '-'):<10} "
            f"{short_text(str(service.get('description', '-')), 20)}"
        )
    if len(services) > len(shown):
        print(f"\nMore services exist on the server. Total seen by API: {len(services)}")
    return services


def restart_service(client: ManagerClient) -> None:
    show_services(client)
    service_name = prompt("Service to restart", "nginx.service")
    data = client.request("POST", "/api/services/restart", {"service": service_name})["data"]
    header("Restart Service")
    print_label("Service", data.get("service", "-"))
    print_label("Restart exit", data.get("restart_exit_code", "-"))
    print()
    print((data.get("status_stdout") or "").strip() or (data.get("restart_stdout") or "").strip() or "The service command finished.")
    if data.get("restart_stderr"):
        print("\nWarnings:")
        print(data.get("restart_stderr"))


def show_logs(client: ManagerClient) -> None:
    service_name = prompt("Service name (leave blank for full system logs)", "")
    lines_raw = prompt("How many lines", "80")
    lines = int(lines_raw or "80")
    data = client.request("POST", "/api/logs", {"service": service_name, "lines": lines})["data"]
    title = f"Logs: {service_name}" if service_name else "System Logs"
    show_text_block(title, data.get("stdout", ""), empty_message="No logs were returned.")
    if data.get("stderr"):
        print("\nWarnings:")
        print(data.get("stderr"))


def show_processes(client: ManagerClient) -> None:
    data = client.request("GET", "/api/processes")["data"]
    show_text_block("Top Processes", data.get("stdout", ""), empty_message="No process data was returned.")
    if data.get("stderr"):
        print("\nWarnings:")
        print(data.get("stderr"))


def show_ports(client: ManagerClient) -> None:
    data = client.request("GET", "/api/ports")["data"]
    show_text_block("Listening Ports", data.get("stdout", ""), empty_message="No open port data was returned.")
    if data.get("stderr"):
        print("\nWarnings:")
        print(data.get("stderr"))


def choose_install_preset(options: Sequence[Dict[str, Any]]) -> Optional[str]:
    header("Install Common Tools")
    for index, option in enumerate(options, start=1):
        print(f"{index}. {option.get('label', '-'):<24} ({option.get('name', '-')})")
    print("0. Cancel")

    while True:
        raw = input("\nChoose a tool to install: ").strip()
        if raw in {"", "0"}:
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(options):
                return str(options[index - 1].get("name", ""))
        print("Please choose a valid number.")


def run_install(client: ManagerClient) -> None:
    payload = client.request("GET", "/api/install/options")
    options = payload.get("options") or []
    package_manager = payload.get("package_manager") or "-"
    preset = choose_install_preset(options)
    if not preset:
        print("Install cancelled.")
        return

    print(f"\nPackage manager detected: {package_manager}")
    if not ask_yes_no(f"Install '{preset}' now", default=True):
        print("Install cancelled.")
        return

    data = client.request("POST", "/api/install", {"preset": preset})["data"]
    header("Install Result")
    print_label("Preset", data.get("preset", "-"))
    print_label("Exit code", data.get("exit_code", "-"))
    if data.get("stdout"):
        subheader("Output")
        print(data.get("stdout"))
    if data.get("stderr"):
        subheader("Warnings")
        print(data.get("stderr"))


def files_menu(client: ManagerClient) -> None:
    while True:
        choice = choose_menu(
            "Files and Folders",
            [
                ("1", "Open a folder"),
                ("2", "Read a file"),
                ("3", "Write text into a file"),
                ("4", "Rename or move something"),
                ("5", "Delete a file or folder"),
                ("0", "Back"),
            ],
        )
        if choice == "0":
            return
        if choice == "1":
            browse_path(client)
        elif choice == "2":
            read_file(client)
        elif choice == "3":
            write_file(client)
        elif choice == "4":
            rename_path(client)
        elif choice == "5":
            delete_path(client)
        pause()


def docker_menu(client: ManagerClient) -> None:
    while True:
        choice = choose_menu(
            "Docker",
            [
                ("1", "Show all containers"),
                ("2", "Start a container"),
                ("3", "Stop a container"),
                ("4", "Restart a container"),
                ("0", "Back"),
            ],
        )
        if choice == "0":
            return
        if choice == "1":
            show_docker(client)
        elif choice == "2":
            run_docker_action(client, "start")
        elif choice == "3":
            run_docker_action(client, "stop")
        elif choice == "4":
            run_docker_action(client, "restart")
        pause()


def services_menu(client: ManagerClient) -> None:
    while True:
        choice = choose_menu(
            "Services and Logs",
            [
                ("1", "Show services"),
                ("2", "Restart a service"),
                ("3", "View logs"),
                ("0", "Back"),
            ],
        )
        if choice == "0":
            return
        if choice == "1":
            show_services(client)
        elif choice == "2":
            restart_service(client)
        elif choice == "3":
            show_logs(client)
        pause()


def status_menu(client: ManagerClient) -> None:
    while True:
        choice = choose_menu(
            "Live Status",
            [
                ("1", "Screen sessions"),
                ("2", "Top processes"),
                ("3", "Open ports"),
                ("0", "Back"),
            ],
        )
        if choice == "0":
            return
        if choice == "1":
            show_screens(client)
        elif choice == "2":
            show_processes(client)
        elif choice == "3":
            show_ports(client)
        pause()


def account_menu(client: ManagerClient, args: argparse.Namespace, cache_enabled: bool, user_name: str) -> str:
    while True:
        choice = choose_menu(
            "Account and Session",
            [
                ("1", "Show current session"),
                ("2", "Sign out and login again"),
                ("0", "Back"),
            ],
        )
        if choice == "0":
            return user_name
        if choice == "1":
            show_session_info(client)
            pause()
            continue
        if choice == "2":
            try:
                client.logout()
            except ApiError as error:
                print(f"Logout warning: {error}")
            if cache_enabled:
                clear_session_cache()
            new_user = perform_login(client, args, {"username": user_name}, cache_enabled)
            pause()
            return new_user
    return user_name


def main_menu(client: ManagerClient, args: argparse.Namespace, cache_enabled: bool, user_name: str) -> None:
    current_user = user_name
    while True:
        choice = choose_menu(
            f"{APP_NAME} - Main Menu",
            [
                ("1", "Quick server overview"),
                ("2", "Files and folders"),
                ("3", "Docker"),
                ("4", "Services and logs"),
                ("5", "Live status"),
                ("6", "Install common tools"),
                ("7", "Account and session"),
                ("0", "Exit"),
            ],
        )
        try:
            if choice == "0":
                return
            if choice == "1":
                show_server_info(client)
                pause()
            elif choice == "2":
                files_menu(client)
            elif choice == "3":
                docker_menu(client)
            elif choice == "4":
                services_menu(client)
            elif choice == "5":
                status_menu(client)
            elif choice == "6":
                run_install(client)
                pause()
            elif choice == "7":
                current_user = account_menu(client, args, cache_enabled, current_user)
        except AuthError as error:
            print(f"\nSession error: {error}")
            current_user = perform_login(client, args, {"username": current_user}, cache_enabled)
            pause()
        except ApiError as error:
            print(f"\nAPI error: {error}")
            pause()
        except ValueError as error:
            print(f"\nInput error: {error}")
            pause()

        if cache_enabled and client.token:
            save_session_cache(
                {
                    "base_url": client.base_url,
                    "username": current_user,
                    "token": client.token,
                }
            )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if requests is None:
        raise SystemExit("requests is not installed. Run: pip3 install requests")

    base_url, cached = resolve_base_url(args)
    client = ManagerClient(base_url=base_url, token=None)
    cache_enabled = not args.no_session_cache
    user_name = perform_login(client, args, cached, cache_enabled)

    header("Connected")
    print(f"Server: {client.base_url}")
    print(f"User:   {user_name}")
    print("Choose what you want to do from the menu below.")

    main_menu(client, args, cache_enabled, user_name)
    print("\nGoodbye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
