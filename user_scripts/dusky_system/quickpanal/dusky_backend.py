#!/usr/bin/env python3
"""
Backend module for Dusky Quick Panal.
Handles multithreading, process execution, memory reclamation, 
hardware interfaces, MPRIS media fetching, and notification DBUS states.
"""

from __future__ import annotations

import contextvars
import ctypes
import gc
import json
import logging
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

APP_ID: Final = "org.dusky.quickpanal"
HOME: Final = os.path.expanduser("~")

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.WARNING, format=f"{APP_ID}: %(levelname)s: %(message)s")

LOG: Final = logging.getLogger(APP_ID)

COMMAND_ENV: Final = os.environ.copy()
COMMAND_ENV["LC_ALL"] = "C.UTF-8"
COMMAND_ENV["LANG"] = "C.UTF-8"

type CommandArg = str | os.PathLike[str]
type FloatGetter = Callable[[], float | None]
type FloatSubmitter = Callable[[float], None]

DEFAULT_SUNSET: Final = 4500.0
QUERY_TIMEOUT: Final = 0.90
CONTROL_TIMEOUT: Final = 1.50
DDC_DETECT_TIMEOUT: Final = 15.0
DDC_QUERY_TIMEOUT: Final = 2.50
DDC_SET_TIMEOUT: Final = 2.75
SUNSET_READY_TIMEOUT: Final = 2.50
SUNSET_FALLBACK_READY_TIMEOUT: Final = 1.25
LIVE_REFRESH_INTERVAL_SECONDS: Final = 2
BRIGHTNESS_POST_SUBMIT_REFRESH_GRACE_SECONDS: Final = max(1.50, QUERY_TIMEOUT + 0.50)
SUNSET_STATE_WRITE_DEBOUNCE_SECONDS: Final = 0.40

NO_PENDING: Final = object()

WPCTL: Final = shutil.which("wpctl")
BRIGHTNESSCTL: Final = shutil.which("brightnessctl")
DDCUTIL: Final = shutil.which("ddcutil")
HYPRCTL: Final = shutil.which("hyprctl")
HYPRSUNSET: Final = shutil.which("hyprsunset")
PGREP: Final = shutil.which("pgrep")
SYSTEMCTL: Final = shutil.which("systemctl")
PLAYERCTL: Final = shutil.which("playerctl")

_RE_MAKO_BADGE: Final = re.compile(r'\d+')
_RE_UPDATES_TOTAL: Final = re.compile(r'Total:\s*(\d+)')

# ==============================================================================
# IDLE RAM RECLAMATION
# ==============================================================================
_LIBC: Final = ctypes.CDLL("libc.so.6", use_errno=True)
_MADV_PAGEOUT: Final = 21

def _reclaim_idle_memory() -> None:
    re.purge()
    if hasattr(sys, "_clear_internal_caches"):
        sys._clear_internal_caches()
    elif hasattr(sys, "_clear_type_cache"):
        sys._clear_type_cache()
    gc.collect()
    gc.freeze()
    try:
        _LIBC.malloc_trim(0)
    except Exception:
        pass
    _pageout_idle_pages()

def _pageout_idle_pages() -> None:
    try:
        with open("/proc/self/maps", "r") as f:
            for line in f:
                parts = line.split(None, 5)
                if len(parts) < 2: continue
                perms = parts[1]
                if "r" not in perms or "x" in perms or "p" not in perms: continue
                path = parts[5].strip() if len(parts) > 5 else ""
                if path in ("[vdso]", "[vvar]", "[vsyscall]") or path.startswith("[stack"): continue
                
                start_s, end_s = parts[0].split("-")
                start, length = int(start_s, 16), int(end_s, 16) - int(start_s, 16)
                if length > 0:
                    _LIBC.madvise(ctypes.c_void_p(start), ctypes.c_size_t(length), _MADV_PAGEOUT)
    except Exception:
        pass

# ==============================================================================
# UTILITIES
# ==============================================================================
def clamp(value: float, lower: float, upper: float) -> float:
    if not math.isfinite(value): return lower
    return max(lower, min(upper, value))

def parse_float(text: str) -> float | None:
    try: return float(text.strip()) if math.isfinite(float(text.strip())) else None
    except ValueError: return None

def percent_int(value: float, lower: int = 0) -> int:
    return int(clamp(round(value), float(lower), 100.0))

def snap_to_step(value: float, lower: float, upper: float, step: float) -> float:
    if step <= 0.0: return clamp(value, lower, upper)
    scaled = (value - lower) / step
    snapped = lower + math.floor(scaled + 0.5 + 1e-12) * step
    return round(clamp(snapped, lower, upper), 10)

def kelvin_value(value: float) -> int:
    return int(clamp(round(value), 1000.0, 6000.0))

def start_thread(name: str, target: Callable[..., None], *args: object, daemon: bool = True) -> threading.Thread:
    thread = threading.Thread(name=name, target=target, args=args, daemon=daemon, context=contextvars.Context())
    thread.start()
    return thread

def run_command(args: Sequence[CommandArg], *, timeout: float, capture_stdout: bool = False) -> subprocess.CompletedProcess[str] | None:
    argv = [os.fspath(arg) for arg in args]
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=COMMAND_ENV, close_fds=True, start_new_session=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        LOG.debug("Command failed to start: %r: %s", argv, exc)
        return None
    try:
        stdout, _ = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, None)
    except subprocess.TimeoutExpired:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except OSError: pass
        proc.communicate()
        return None
    except Exception:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except OSError: pass
        proc.communicate()
        return None

def execute_cmd(cmd: str) -> None:
    try:
        subprocess.Popen(["/usr/bin/bash", "-c", cmd], start_new_session=True, env=COMMAND_ENV, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as e:
        LOG.warning(f"Failed to execute command '{cmd}': {e}")

def fetch_json_output(cmd: str) -> dict[str, Any] | None:
    r = run_command(shlex.split(cmd), timeout=1.5, capture_stdout=True)
    if r is not None and r.returncode == 0 and r.stdout.strip():
        try: return json.loads(r.stdout.strip())
        except json.JSONDecodeError: pass
    return None

def _resolve_state_dir() -> Path | None:
    candidates = []
    if (xdg_state := os.environ.get("XDG_STATE_HOME")): candidates.append(Path(xdg_state) / APP_ID)
    candidates.append(Path.home() / ".local" / "state" / APP_ID)
    if (xdg_runtime := os.environ.get("XDG_RUNTIME_DIR")): candidates.append(Path(xdg_runtime) / APP_ID)
    candidates.append(Path(f"/run/user/{os.getuid()}") / APP_ID)
    candidates.append(Path(tempfile.gettempdir()) / f"{APP_ID}-{os.getuid()}")

    for path in candidates:
        try: path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError: pass
        if path.is_dir() and os.access(path, os.W_OK | os.X_OK): return path
    return None

STATE_DIR: Final = _resolve_state_dir()
STATE_FILE: Final = None if STATE_DIR is None else STATE_DIR / "hyprsunset_state.txt"
DDCUTIL_CACHE_FILE: Final = None if STATE_DIR is None else STATE_DIR / "ddcutil_displays.json"

def atomic_write_text(path: Path, text: str, *, durable: bool = True) -> bool:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            if durable: os.fsync(handle.fileno())
        os.replace(temp_path, path)
        if durable:
            try:
                dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                os.fsync(dir_fd)
                os.close(dir_fd)
            except OSError: pass
        return True
    except OSError as exc:
        LOG.warning("Failed to write %s: %s", path, exc)
        return False

# ==============================================================================
# WORKERS & THREADING
# ==============================================================================
class RefreshPool:
    __slots__ = ("_executor", "_max_workers", "_lock")
    def __init__(self, max_workers: int = 4) -> None:
        self._max_workers = max_workers
        self._executor = None
        self._lock = threading.Lock()

    def submit(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any] | None:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="dusky-refresh")
            try: return self._executor.submit(func, *args, **kwargs)
            except RuntimeError: return None

    def shutdown(self) -> None:
        with self._lock:
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)
                self._executor = None

class LatestValueWorker:
    __slots__ = ("_apply_func", "_busy", "_condition", "_name", "_pending", "_running", "_thread")
    def __init__(self, name: str, apply_func: Callable[[float], None]) -> None:
        self._name = name
        self._apply_func = apply_func
        self._condition = threading.Condition()
        self._pending: float | object = NO_PENDING
        self._busy = False
        self._running = True
        self._thread: threading.Thread | None = None
        with self._condition: self._ensure_thread_locked()

    def submit(self, value: float) -> None:
        with self._condition:
            if not self._running: return
            self._pending = float(value)
            self._ensure_thread_locked()
            self._condition.notify()

    def start(self) -> None:
        with self._condition:
            if self._running: return
            self._running = True
            self._ensure_thread_locked()

    def stop(self, timeout: float = 2.0) -> None:
        with self._condition:
            self._running = False
            self._pending = NO_PENDING
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def _ensure_thread_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive(): return
        self._thread = start_thread(f"{self._name}-worker", self._worker, daemon=True)

    def _worker(self) -> None:
        while True:
            with self._condition:
                while self._running and self._pending is NO_PENDING:
                    self._condition.wait()
                if not self._running: return
                value = self._pending
                self._pending = NO_PENDING
                self._busy = True
            try:
                if value is not NO_PENDING:
                    self._apply_func(float(value))
            except Exception: LOG.exception("Exception in %s worker", self._name)
            finally:
                with self._condition:
                    self._busy = False
                    self._condition.notify_all()

# ==============================================================================
# NOTIFICATION SYSTEM (MAKO DBUS BRIDGE)
# ==============================================================================
@dataclass(slots=True, frozen=True)
class NotificationData:
    id: int
    app_name: str
    summary: str
    body: str
    source: str
    desktop_entry: str

def fetch_notifications() -> list[NotificationData]:
    """Fetch and merge active and history buffers from Mako, respecting blacklists."""
    bl_path = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "mako_rofi_blacklist"
    blacklist = set()
    if bl_path.is_file():
        try: blacklist = set(bl_path.read_text(encoding="utf-8").splitlines())
        except OSError: pass

    ignored_apps = {"OSD", "dusky-keys", "dusky-cava", "dusky-cava-alert", "dusky-glance", "dusky-glance-alert", "Spotify"}

    def _fetch_mako_json(cmd: list[str]) -> list[dict]:
        r = run_command(cmd, timeout=1.0, capture_stdout=True)
        if r is not None and r.returncode == 0:
            try:
                parsed = json.loads(r.stdout)
                if isinstance(parsed, dict) and "data" in parsed:
                    data = parsed["data"]
                    if data and isinstance(data, list) and isinstance(data[0], list): return data[0]
                    if data and isinstance(data, list): return data
                if isinstance(parsed, list):
                    if len(parsed) > 0 and isinstance(parsed[0], list): return parsed[0]
                    return parsed
            except json.JSONDecodeError: pass
        return []

    active_items = _fetch_mako_json(["makoctl", "list", "-j"])
    history_items = _fetch_mako_json(["makoctl", "history", "-j"])

    combined = {}
    for src, items in [("history", history_items), ("active", active_items)]:
        for item in items:
            try:
                nid = int(item.get("id", -1))
                if nid < 0 or str(nid) in blacklist: continue
                app = item.get("app-name", item.get("app_name", ""))
                if app in ignored_apps: continue
                summary = item.get("summary", "")
                if not summary: continue
                
                combined[nid] = NotificationData(
                    id=nid,
                    app_name=app,
                    summary=summary,
                    body=item.get("body", ""),
                    source=src,
                    desktop_entry=item.get("desktop-entry", "")
                )
            except Exception: pass

    return sorted(combined.values(), key=lambda x: x.id, reverse=True)


# ==============================================================================
# MPRIS MEDIA STATE 
# ==============================================================================
@dataclass
class MediaState:
    players: list[str]
    status: str | None
    title: str
    artist: str
    position: float
    length: float
    shuffle: bool
    loop: str

def fetch_media_state(player: str | None = None) -> MediaState | None:
    if PLAYERCTL is None: return None
    
    r_players = run_command([PLAYERCTL, "-l"], timeout=0.8, capture_stdout=True)
    current_players = []
    if r_players and r_players.returncode == 0 and r_players.stdout:
        current_players = [p.strip() for p in r_players.stdout.splitlines() if p.strip()]

    if not current_players: return None

    fmt = "{{playerName}}\x1f{{status}}\x1f{{title}}\x1f{{artist}}\x1f{{position}}\x1f{{mpris:length}}\x1f{{shuffle}}\x1f{{loop}}"
    args = [PLAYERCTL, "metadata", "--format", fmt]
    
    if player and player != "auto":
        args = [PLAYERCTL, "-p", player, "metadata", "--format", fmt]

    r_stat = run_command(args, timeout=1.5, capture_stdout=True)
    
    if not r_stat or r_stat.returncode != 0 or not r_stat.stdout.strip():
        fallback_args = [PLAYERCTL, "status"]
        if player and player != "auto":
            fallback_args = [PLAYERCTL, "-p", player, "status"]
            
        r_fallback = run_command(fallback_args, timeout=0.8, capture_stdout=True)
        if not r_fallback or r_fallback.returncode != 0 or r_fallback.stdout.strip() not in ("Playing", "Paused"):
            return None
            
        p_name = player if player and player != "auto" else current_players[0]
        return MediaState(current_players, r_fallback.stdout.strip(), "Unknown", "", -1.0, -1.0, False, "None")

    parts = r_stat.stdout.strip().split("\x1f")
    if len(parts) < 8:
        return None

    p_name, status, title, artist = parts[0], parts[1], parts[2] or "Unknown", parts[3]
    if status not in ("Playing", "Paused"): return None
    
    try: pos = float(parts[4]) / 1000000.0 if parts[4] else -1.0
    except ValueError: pos = -1.0
    try: length = float(parts[5]) / 1000000.0 if parts[5] else -1.0
    except ValueError: length = -1.0
    
    shuffle = parts[6].lower() in ("on", "true")
    loop = parts[7] or "None"
    return MediaState(current_players, status, title, artist, pos, length, shuffle, loop)


# ==============================================================================
# HARDWARE CONTROL STUBS 
# ==============================================================================
def get_volume() -> float | None:
    if WPCTL is None: return None
    r = run_command([WPCTL, "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=QUERY_TIMEOUT, capture_stdout=True)
    if r is None or r.returncode != 0: return None
    parts = r.stdout.split()
    if len(parts) < 2: return None
    val = parse_float(parts[1])
    return clamp(val * 100.0, 0.0, 100.0) if val is not None else None

def apply_volume(value: float) -> None:
    if WPCTL is None: return
    vol = percent_int(value)
    r = run_command([WPCTL, "set-volume", "@DEFAULT_AUDIO_SINK@", f"{vol}%"], timeout=CONTROL_TIMEOUT)
    if r is not None and r.returncode == 0 and vol > 0:
        run_command([WPCTL, "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], timeout=CONTROL_TIMEOUT)

def get_brightness() -> float | None:
    if BRIGHTNESSCTL is None: return 50.0
    r = run_command([BRIGHTNESSCTL, "-m"], timeout=QUERY_TIMEOUT, capture_stdout=True)
    if r and r.returncode == 0:
        parts = r.stdout.split(",")
        if len(parts) >= 4:
            val = parse_float(parts[3].rstrip("%"))
            if val is not None: return clamp(val, 0.0, 100.0)
    return 50.0

def apply_local_brightness(value: float) -> None:
    if BRIGHTNESSCTL:
        run_command([BRIGHTNESSCTL, "set", f"{percent_int(value, 1)}%"], timeout=CONTROL_TIMEOUT)

def get_hyprsunset_state() -> float:
    if STATE_FILE is None: return DEFAULT_SUNSET
    try: val = parse_float(STATE_FILE.read_text(encoding="utf-8"))
    except OSError: return DEFAULT_SUNSET
    return clamp(val, 1000.0, 6000.0) if val is not None else DEFAULT_SUNSET

class HyprsunsetController:
    def __init__(self):
        self._worker = LatestValueWorker("sunset", self._apply)
    def submit(self, value: float) -> None: self._worker.submit(value)
    def start(self) -> None: self._worker.start()
    def stop(self, timeout: float = 3.0) -> None: self._worker.stop(timeout)
    def _apply(self, value: float) -> None:
        target = kelvin_value(value)
        if HYPRCTL: run_command([HYPRCTL, "hyprsunset", "temperature", str(target)], timeout=CONTROL_TIMEOUT)
        if STATE_FILE: atomic_write_text(STATE_FILE, f"{target}\n")

HAS_VOLUME: Final = WPCTL is not None
HAS_BRIGHTNESS: Final = BRIGHTNESSCTL is not None
HAS_SUNSET: Final = HYPRCTL is not None and HYPRSUNSET is not None
