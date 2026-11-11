#!/usr/bin/env python3
"""One-command launcher for the Helpdesk app.

    python start.py            set everything up (first run only) and start the server
    python start.py test       run the automated tests

Options:  --port 8000   --host 127.0.0.1   --reload   --no-browser
Optional environment variables for the first admin: ADMIN_EMAIL, ADMIN_PASSWORD
"""

import argparse
import hashlib
import os
import secrets
import socket
import subprocess
import sys
import threading
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

ENV_TEMPLATE = """# Created automatically by start.py - edit freely. See .env.example for every option.
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:///./helpdesk.db
AUTO_CREATE_TABLES=false
SECRET_KEY={key}
LOG_JSON=false
"""


def say(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def fail(message: str) -> None:
    print(f"\nERROR: {message}", flush=True)
    sys.exit(1)


def run(args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], cwd=ROOT, **kwargs)


def ensure_venv() -> None:
    if not PY.exists():
        say("Creating virtual environment (.venv)")
        venv.create(VENV, with_pip=True)
    if not PY.exists():
        fail("Could not create the virtual environment (.venv).")


def ensure_requirements(filename: str) -> None:
    stamp = VENV / f".{filename}.sha256"
    digest = hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
    if stamp.exists() and stamp.read_text() == digest:
        return
    say(f"Installing packages from {filename} (the first run takes a minute or two)")
    result = run([PY, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", filename])
    if result.returncode:
        fail("Package installation failed. Check your internet connection and run `python start.py` again.")
    stamp.write_text(digest)


def ensure_env_file() -> None:
    env_file = ROOT / ".env"
    if env_file.exists():
        return
    say("Creating .env with a new random SECRET_KEY")
    env_file.write_text(ENV_TEMPLATE.format(key=secrets.token_hex(32)), encoding="utf-8")


def migrate() -> None:
    say("Setting up the database (alembic upgrade head)")
    if run([PY, "-m", "alembic", "upgrade", "head"]).returncode:
        fail("Database migration failed. See the messages above.")


def ensure_admin() -> None:
    email = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    password = os.environ.get("ADMIN_PASSWORD", "StrongPass123")
    result = run(
        [PY, "-m", "scripts.create_admin", email, "Administrator", password, "--if-none"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        say(f"Created the first admin account:  {email}  /  {password}   (change it before sharing the app)")
    elif result.returncode != 3:
        fail(f"Could not create the admin account:\n{result.stdout}{result.stderr}")


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, port)) != 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the Helpdesk app (sets everything up on first run).")
    parser.add_argument("command", nargs="?", choices=["run", "test"], default="run")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="auto-restart on code changes (development)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = parser.parse_args()

    if sys.version_info < (3, 11):  # noqa: UP036 - friendly message instead of a crash on old Pythons
        fail(f"Python 3.11 or newer is required (you have {sys.version.split()[0]}). Install it from python.org.")

    ensure_venv()
    if args.command == "test":
        ensure_requirements("requirements-dev.txt")
        sys.exit(run([PY, "-m", "pytest", "-q"]).returncode)

    ensure_requirements("requirements.txt")
    ensure_env_file()
    migrate()
    ensure_admin()

    if not port_is_free(args.host, args.port):
        fail(
            f"Port {args.port} is already in use. Close the other server or run: python start.py --port {args.port + 1}"
        )

    url = f"http://{args.host}:{args.port}/"
    say(f"Starting the server at {url}   (press Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(3, webbrowser.open, [url]).start()
    cmd = [PY, "-m", "uvicorn", "app.main:app", "--host", args.host, "--port", str(args.port)]
    if args.reload:
        cmd.append("--reload")
    try:
        sys.exit(run(cmd).returncode)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
