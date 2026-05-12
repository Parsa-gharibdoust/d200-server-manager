# d200-manager

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/flask-API-111111?logo=flask&logoColor=white)
![Platform](https://img.shields.io/badge/platform-linux-0f172a?logo=linux&logoColor=white)

`d200-manager` is a lightweight Flask-based Linux server manager with a simple terminal client for remote monitoring and everyday server control.

## Links

- Website: [parsagharibdoust.xyz](https://parsagharibdoust.xyz)
- GitHub: [github.com/parsa-gharibdoust](https://github.com/parsa-gharibdoust)

## Highlights

- Flask server API for Linux administration
- Menu-based terminal client for normal users
- Token-based login sessions tied to client IP
- Quick server overview: hostname, IP, uptime, memory, disk, installed tools
- File and folder management: list, read, write, rename, delete
- Docker container listing and start/stop/restart actions
- GNU Screen session listing
- Service listing, restart, and log viewing
- Open ports and top process monitoring
- Install presets for common tools like `git`, `docker`, `python3`, `cmake`, `nginx`, `screen`, `tmux`, and more

## Project Structure

```text
Server.py        Flask server that runs on the Linux machine
Client.py        Terminal client that connects to the server API
requirements.txt Python dependencies
```

## Requirements

- Python 3.10 or newer
- Linux server for `Server.py`
- Dependencies from `requirements.txt`

Install dependencies:

```bash
pip3 install -r requirements.txt
```

## Configuration

The project supports environment variable overrides for the default login:

```bash
export D200_MANAGER_USERNAME="your_username"
export D200_MANAGER_PASSWORD="your_password"
```

If you do not set them, `Server.py` falls back to these defaults:

```python
DEFAULT_USERNAME = "Parsa_gharibdoust"
DEFAULT_PASSWORD = "12345678"
```

## Quick Start

### 1. Run the server

On your Linux server:

```bash
python3 Server.py --host 0.0.0.0 --port 5000
```

The API will be available at:

```text
http://SERVER_IP:5000
```

### 2. Run the client

From your own machine:

```bash
python3 Client.py --url http://SERVER_IP:5000
```

The client will:

- ask for the server address if needed
- ask for login credentials
- save the session token locally for reuse
- open a simple terminal menu

## Client Sections

- Quick server overview
- Files and folders
- Docker
- Services and logs
- Live status
- Install common tools
- Account and session

## API Overview

Main routes exposed by `Server.py`:

```text
POST /login
POST /logout
GET  /api/session
GET  /api/server-info
GET  /api/screens
GET  /api/docker
POST /api/docker/action
GET  /api/services
POST /api/services/restart
POST /api/logs
GET  /api/processes
GET  /api/ports
POST /api/files/list
POST /api/files/read
POST /api/files/write
POST /api/files/rename
POST /api/files/delete
GET  /api/install/options
POST /api/install
```

## Notes

- `Server.py` is Linux-only.
- Sessions are tied to the client IP. If the IP changes, login is required again.
- The server runs commands with the same permissions as the user running `Server.py`.
- File delete protection exists for core manager files such as `Server.py`, `Client.py`, and the session store file.
- Tool installation actions may require running the server with enough privileges.

## Recommended Before Publishing

- Change the default login
- Review download links and branding if you are packaging releases
- Add a license that matches how you want others to use the project

## License

No license file has been added yet. Choose one before publishing if you want the reuse terms to be clear.
