"""Shared setup and on-demand diagnostics for the two WayVNC services."""

import ipaddress
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

HOME = Path.home()
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
MASTER = "dusky_vnc.service"
PHONE = "dusky_phone_display.service"
DESKTOP_PORT = 5902  # 5900 is commonly occupied by a local QEMU VNC console.
PHONE_PORT = 5901
FIREWALL_RULE = ("allow", f"{PHONE_PORT},{DESKTOP_PORT}/tcp", "comment", "Dusky VNC")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check,
                          stdin=subprocess.DEVNULL, timeout=15,
                          env={**os.environ, "LC_ALL": "C"})


def message(value: str, *, error: bool = False) -> None:
    # The service replaces Python with WayVNC; Rich is only needed by the CLI.
    from rich.console import Console
    Console(stderr=error).print(value, markup=False, highlight=False,
                                style="red" if error else None)


def atomic_write(path: Path, content: str, mode: int = 0o600) -> bool:
    if path.exists() and path.read_text() == content:
        path.chmod(mode)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        replacement = Path(directory) / path.name
        replacement.write_text(content)
        replacement.chmod(mode)
        replacement.replace(path)
    return True


def write_config(config: Path, key: Path, cert: Path, port: int) -> bool:
    config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    valid = False
    if key.is_file() and cert.is_file():
        expiry = run("openssl", "x509", "-checkend", "2592000", "-noout", "-in", str(cert), check=False)
        public_key = run("openssl", "pkey", "-in", str(key), "-pubout", check=False)
        cert_key = run("openssl", "x509", "-in", str(cert), "-pubkey", "-noout", check=False)
        valid = expiry.returncode == public_key.returncode == cert_key.returncode == 0 and public_key.stdout == cert_key.stdout
    if not valid:
        with tempfile.TemporaryDirectory(dir=config.parent) as directory:
            new_key, new_cert = Path(directory) / "key.pem", Path(directory) / "cert.pem"
            # Traditional RSA PEM is required by NeatVNC's RSA-AES reader.
            run("openssl", "genrsa", "-traditional", "-out", str(new_key), "3072")
            run("openssl", "req", "-new", "-x509", "-key", str(new_key), "-out", str(new_cert),
                "-days", "3650", "-sha256", "-subj", "/CN=WayVNC")
            new_key.chmod(0o600)
            new_cert.chmod(0o600)
            new_key.replace(key)
            new_cert.replace(cert)
    key.chmod(0o600)
    changed = atomic_write(config, (
        f"address=0.0.0.0\nport={port}\nenable_auth=true\nenable_pam=true\n"
        f"rsa_private_key_file={key}\nprivate_key_file={key}\ncertificate_file={cert}\n"
    ))
    return changed or not valid


def session() -> dict | None:
    result = run("hyprctl", "instances", "-j", check=False)
    if result.returncode:
        return None
    candidates = sorted(json.loads(result.stdout), key=lambda item: item.get("time", 0), reverse=True)
    preferred = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    candidates.sort(key=lambda item: item.get("instance") != preferred)
    for item in candidates:
        name = item.get("wl_socket", "")
        if not name:
            continue
        try:
            info = (RUNTIME / name).stat()
        except FileNotFoundError:
            continue  # A session may exit between discovery and inspection.
        if stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid():
            return item
    return None


def wait_session() -> dict:
    while not (current := session()):
        time.sleep(2)
    return current


def exec_wayvnc(current: dict, config: Path, control: Path, *args: str) -> None:
    env = {**os.environ, "XDG_RUNTIME_DIR": str(RUNTIME),
           "WAYLAND_DISPLAY": current["wl_socket"],
           "HYPRLAND_INSTANCE_SIGNATURE": current["instance"]}
    os.execve("/usr/bin/wayvnc", ["wayvnc", "-C", str(config), "-S", str(control), *args], env)


def script_command(script: Path, action: str) -> str:
    try:
        name = "%h/" + script.resolve().relative_to(HOME).as_posix().replace("%", "%%")
    except ValueError:
        name = str(script.resolve()).replace("%", "%%")
    # Stable Arch interpreter path avoids restarts when setup is invoked through
    # different Python aliases. systemd needs literal dollars escaped as well.
    return " ".join(json.dumps(part.replace("$", "$$"), ensure_ascii=False)
                    for part in ("/usr/bin/python3", name, action))


def prepare() -> None:
    if os.geteuid() == 0:
        raise RuntimeError("Run setup as the desktop user, without sudo")
    if not Path("/usr/bin/wayvnc").is_file():
        raise RuntimeError("Install wayvnc from the ISO or distribution repository, then rerun setup")
    if not Path("/etc/pam.d/wayvnc").is_file():
        raise RuntimeError("WayVNC PAM profile is missing; reinstall the wayvnc package")
    missing = [name for name in ("wayvncctl", "hyprctl", "openssl", "systemctl", "ip") if not shutil.which(name)]
    if missing:
        raise RuntimeError("Missing required commands: " + ", ".join(missing))
    if not session():
        raise RuntimeError("Start a Hyprland desktop session before setup")


def configure_firewall() -> None:
    if shutil.which("ufw"):
        subprocess.run(["sudo", sys.executable, str(Path(__file__).resolve()), "firewall"], check=True)


def firewall_worker() -> None:
    """Put the VNC allowance before user denies without resetting the firewall."""
    if os.geteuid() != 0:
        raise RuntimeError("Firewall configuration requires sudo")

    def rules() -> list[list[str]]:
        return [shlex.split(line)[1:] for line in run("ufw", "show", "added").stdout.splitlines()
                if line.startswith("ufw ")]

    existing = rules()
    if existing and existing[0] == list(FIREWALL_RULE):
        return
    # UFW skips insertion of equivalent rules already present. Normalize its
    # action/comment first, then remove and prepend that exact two-port rule.
    run("ufw", *FIREWALL_RULE)
    run("ufw", "--force", "delete", *FIREWALL_RULE)
    run("ufw", "prepend", *FIREWALL_RULE)
    existing = rules()
    if not existing or existing[0] != list(FIREWALL_RULE):
        raise RuntimeError("UFW did not prioritize the VNC allowance")


def install_unit(unit: Path, content: str) -> bool:
    changed = atomic_write(unit, content, 0o644)
    if changed:
        run("systemctl", "--user", "daemon-reload")
    enabled = run("systemctl", "--user", "is-enabled", unit.name, check=False).stdout.strip() == "enabled"
    if changed and enabled:
        run("systemctl", "--user", "reenable", unit.name)
    elif not enabled:
        run("systemctl", "--user", "enable", unit.name)
    return changed


def control_data(control: Path, command: str) -> list[dict] | None:
    result = run("wayvncctl", "-S", str(control), "--json", command, check=False)
    if result.returncode:
        return None
    try:
        data = json.loads(result.stdout)
        return data if isinstance(data, list) and all(isinstance(item, dict) for item in data) else None
    except ValueError:
        return None


def rfb_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1) as connection:
            deadline = time.monotonic() + 1
            greeting = bytearray()
            while len(greeting) < 12:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                connection.settimeout(remaining)
                chunk = connection.recv(12 - len(greeting))
                if not chunk:
                    return False
                greeting.extend(chunk)
        return greeting == b"RFB 003.008\n"
    except OSError:
        return False


def wait_ready(predicate, unit: str) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    raise RuntimeError(f"Not ready after 15 seconds. Check: journalctl --user -u {unit} -n 30 --no-pager")


def addresses() -> list[tuple[str, str]]:
    links = json.loads(run("ip", "-j", "-4", "addr", "show", "scope", "global").stdout)
    routes = json.loads(run("ip", "-j", "-4", "route", "show", "default").stdout)
    preferred = min(routes, key=lambda item: item.get("metric", 0)).get("dev") if routes else None
    found = []
    for link in links:
        iface = link["ifname"]
        # VM/container bridges do not give phones a directly usable LAN address.
        net = Path("/sys/class/net") / iface
        physical = (net / "device").exists() or (net / "phy80211").exists()
        if "UP" not in link.get("flags", []) or not (physical or iface == preferred or iface == "tailscale0"):
            continue
        for value in link.get("addr_info", []):
            ip = ipaddress.ip_address(value["local"])
            if not (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified):
                found.append((iface, str(ip)))
    found.sort(key=lambda item: (item[0] != preferred, item[0], item[1]))
    return found


def show_status(unit: str, port: int, control: Path, ready: bool, description: str) -> None:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    console = Console()
    state = run("systemctl", "--user", "is-active", unit, check=False).stdout.strip() or "inactive"
    enabled = run("systemctl", "--user", "is-enabled", unit, check=False).stdout.strip()
    label = "Ready" if state == "active" and ready else "Off" if state == "inactive" else "Not ready"
    console.print(Text(f"{description}: {label} ({state}, {enabled})", style="bold green" if label == "Ready" else "yellow"))
    table = Table(title="Connect over the same Wi-Fi")
    table.add_column("Network")
    table.add_column("Address", style="bold cyan")
    ips = addresses()
    for iface, ip in ips:
        table.add_row(Text("Tailscale" if iface == "tailscale0" else iface), Text(f"{ip}:{port}"))
    console.print(table)
    if not ips:
        console.print(Text("No usable IPv4 network address. Connect to Wi-Fi or Ethernet and rerun status."))
    console.print(Text(f"Login: {pwd.getpwuid(os.getuid()).pw_name} · your Linux password · RVNC Viewer or VeNCrypt viewer"))
    if ready and state == "active":
        clients = control_data(control, "client-list")
        console.print(Text(f"Connected viewers: {len(clients)}" if clients is not None else "Connected viewers: unavailable"))
    elif state != "inactive":
        console.print(Text(f"Check: journalctl --user -u {unit} -n 30 --no-pager"))
        raise RuntimeError(f"{description} is not ready")
    console.print(Text(f"All VNC: systemctl --user {'disable' if state == 'active' else 'enable'} --now {MASTER}"))


if __name__ == "__main__":
    try:
        if sys.argv[1:] != ["firewall"]:
            raise RuntimeError("Internal helper: expected firewall")
        firewall_worker()
    except subprocess.CalledProcessError as error:
        print(f"Firewall setup failed: {error.stderr.strip() or error.stdout.strip() or error}", file=sys.stderr)
        sys.exit(1)
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"Firewall setup failed: {error}", file=sys.stderr)
        sys.exit(1)
