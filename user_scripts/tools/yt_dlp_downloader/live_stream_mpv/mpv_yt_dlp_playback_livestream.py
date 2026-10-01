#!/usr/bin/env python3
"""Watch videos and live broadcasts using mpv + yt-dlp.

Auto mode plays regular videos directly and active broadcasts with live travel
keys and a tmpfs archive when a single muxed stream is selected. mpv cannot
archive separate video/audio streams together; live mode disables that archive,
while file mode requires a single stream. Live rewind depends on the server.

Examples:
  %(prog)s URL                             # choose format; auto video/live mode
  %(prog)s URL -F                          # list format IDs and row numbers
  %(prog)s URL -f '#1' --speed 2            # second row, including separate audio
  %(prog)s URL --mode file --buffer full   # growing-file DVR on tmpfs
  %(prog)s URL --mode plain                # direct URL playback
  %(prog)s URL --cookies ~/cookies.txt     # original cookie jar is untouched
  %(prog)s --set-global buffer=near speed=2
  %(prog)s --history
  %(prog)s --replay 0
  %(prog)s --doctor
  %(prog)s URL --ytdlp-option=socket-timeout=15

Preferences: CLI > replay entry > env > config.toml > builtin.
Settings/history use XDG_CONFIG_HOME/dusky/settings/ytdlp_stream (0600).
Each playback has its own temporary session, removed even on failure. --keep
moves archives into the recording pool; live jumps create separate segments.
Tmpfs prevents direct video writes to persistent filesystems; it may be swapped.

Env overrides: MPV_DVR_FORMAT, MPV_DVR_SPEED, MPV_DVR_TMPDIR, MPV_DVR_BUFFER,
MPV_DVR_CODEC, MPV_DVR_COOKIES, MPV_DVR_COOKIES_FROM_BROWSER, MPV_DVR_TIMEOUT,
MPV_DVR_MODE, MPV_DVR_START. Default keys follow your mpv input configuration.
Live travel keys: Ctrl+Left/Right = ±60s, Shift+Left/Right = ±10min.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
import fcntl
import http.client
import json
import math
import os
import re
import shlex
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.request

PROG = os.path.basename(sys.argv[0]) or "mpv_yt_dlp_playback_livestream.py"
CANDIDATE_TMPFS = ["/dev/shm", "/tmp"]
MIN_FREE_MB_DEFAULT = 500
START_BYTES = 256 * 1024
# Player RAM window presets.
# DVR file itself stays fully seekable on tmpfs either way; this only
# controls how much mpv holds in RAM for instant back/forth scrubbing.
BUFFER_PRESETS = {
    "near": [],
    "full": ["--cache=yes", "--demuxer-max-bytes=1G", "--demuxer-max-back-bytes=1G",
             "--demuxer-readahead-secs=10"],
}

try:
    from rich.console import Console
    from rich.table import Table

    _RICH = True
except ImportError:
    _RICH = False


# ---------- config + history (global prefs + per-stream prefs) ----------
# ~/.config/dusky/settings/ytdlp_stream/config.toml   global preferences
# ~/.config/dusky/settings/ytdlp_stream/history.toml  per-URL preferences

def _cfg_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "dusky", "settings", "ytdlp_stream")


CONFIG_FILE = os.path.join(_cfg_dir(), "config.toml")
HISTORY_FILE = os.path.join(_cfg_dir(), "history.toml")
MAX_HISTORY = 100

# key: (type, builtin default)
GLOBAL_SPEC: dict[str, tuple[str, object]] = {
    "format": ("str", ""),
    "prefer_codec": ("str", ""),
    "buffer": ("str", "ask"),
    "speed": ("float", 1.0),
    "tmpdir": ("str", ""),
    "cookies": ("str", ""),
    "cookies_from_browser": ("str", ""),
    "min_free": ("int", MIN_FREE_MB_DEFAULT),
    "timeout": ("float", 30.0),
    "fullscreen": ("bool", False),
    "mute": ("bool", False),
    "low_latency": ("bool", False),
    "keep": ("bool", False),
    "show_recorder": ("bool", False),
    "mode": ("str", "auto"),
    "start": ("str", ""),
    "ignore_ytdlp_config": ("bool", True),
    "floor_mb": ("int", 256),
    "allow_disk": ("bool", False),
}


def _tstr(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif o < 0x20 or o == 0x7F:
            out.append(f"\\u{o:04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _tval(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return _tstr(str(v))


def _dump_toml(data: dict) -> str:
    """Minimal writer for our schemas: flat scalars + lists of flat dicts."""
    lines = []
    for k, v in data.items():
        if isinstance(v, list):
            for item in v:
                lines.append(f"[[{k}]]")
                for ik, iv in item.items():
                    if iv is None:
                        continue
                    lines.append(f"{ik} = {_tval(iv)}")
        elif isinstance(v, dict):
            lines.append(f"[{k}]")
            for ik, iv in v.items():
                lines.append(f"{ik} = {_tval(iv)}")
        else:
            lines.append(f"{k} = {_tval(v)}")
    return "\n".join(lines) + "\n"


def _load_toml(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            d = tomllib.load(f)
            return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise SystemExit(f"ERROR: cannot read {path}: {e}")


def _atomic_write(path: str, text: str) -> None:
    secure_dir(os.path.dirname(path) or ".")
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        dirfd = os.open(os.path.dirname(path) or ".", os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def preferences_lock():
    """Serialize short read/modify/write operations across simultaneous players."""
    secure_dir(_cfg_dir())
    fd = os.open(os.path.join(_cfg_dir(), ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def load_config() -> dict:
    d = _load_toml(CONFIG_FILE)
    if d.get("version", 1) != 1:
        raise SystemExit(f"ERROR: unsupported config version in {CONFIG_FILE}")
    d = d.get("defaults", d) if isinstance(d, dict) else {}
    return d if isinstance(d, dict) else {}


def save_config(values: dict) -> None:
    _atomic_write(CONFIG_FILE, _dump_toml({"version": 1, "defaults": values}))


def parse_global_pair(pair: str) -> tuple[str, object]:
    if "=" not in pair:
        raise SystemExit(f"ERROR: --set-global needs KEY=VALUE, got {pair!r}")
    k, _, raw = pair.partition("=")
    k, raw = k.strip(), raw.strip()
    if k not in GLOBAL_SPEC:
        raise SystemExit(f"ERROR: unknown key {k!r}. Known: {', '.join(sorted(GLOBAL_SPEC))}")
    typ, _ = GLOBAL_SPEC[k]
    if typ == "bool":
        if raw.lower() in ("1", "true", "yes", "on"):
            return k, True
        if raw.lower() in ("0", "false", "no", "off"):
            return k, False
        raise SystemExit(f"ERROR: {k} needs true/false, got {raw!r}")
    if typ == "int":
        try:
            return k, int(raw)
        except ValueError:
            raise SystemExit(f"ERROR: {k} needs an integer, got {raw!r}")
    if typ == "float":
        try:
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError
            return k, value
        except ValueError:
            raise SystemExit(f"ERROR: {k} needs a number, got {raw!r}")
    return k, raw


def load_history() -> list[dict]:
    d = _load_toml(HISTORY_FILE)
    if d.get("version", 1) != 1:
        raise SystemExit(f"ERROR: unsupported history version in {HISTORY_FILE}")
    e = d.get("entries", [])
    return [x for x in e if isinstance(x, dict) and x.get("url")] if isinstance(e, list) else []


def save_history(entries: list[dict]) -> None:
    _atomic_write(HISTORY_FILE, _dump_toml({"version": 1, "entries": entries[:MAX_HISTORY]}))


ENTRY_FIELDS = ("url", "title", "uploader", "live_status", "format", "buffer",
                "speed", "prefer_codec", "fullscreen", "mute", "low_latency",
                "cookies_used", "cookies", "cookies_from_browser", "mode", "start",
                "last_played", "plays")


def parse_start(value: str) -> str:
    """Validate the documented mpv time, percentage and chapter syntax."""
    value = value.strip()
    if value == "none" or re.fullmatch(r"#[1-9]\d*", value):
        return value
    if re.fullmatch(r"\d+(?:\.\d+)?%", value):
        if 0 <= float(value[:-1]) <= 100:
            return value
    elif re.fullmatch(r"[+-]?(?:\d+:){0,2}\d+(?:\.\d+)?", value):
        parts = value.lstrip("+-").split(":")
        if (all(math.isfinite(float(x)) for x in parts)
                and (len(parts) < 2 or float(parts[-1]) < 60)
                and (len(parts) < 3 or int(parts[-2]) < 60)):
            return value
    raise SystemExit(f"ERROR: bad --start {value!r}. Use seconds, MM:SS, HH:MM:SS, "
                     "0..100%, #chapter, or none; negative times are relative to the end.")


def find_entry(spec: str) -> dict:
    """Match a history entry by # index, exact URL, or unique substring."""
    entries = load_history()
    if not entries:
        raise SystemExit("ERROR: history is empty.")
    s = spec.strip()
    if s.isdigit() and int(s) < len(entries):
        return entries[int(s)]
    exact = [e for e in entries if e.get("url") == s]
    if exact:
        return exact[0]
    sub = [e for e in entries if s.lower() in str(e.get("url", "")).lower()
           or s.lower() in str(e.get("title", "")).lower()]
    if len(sub) == 1:
        return sub[0]
    if not sub:
        raise SystemExit(f"ERROR: no history match for {spec!r}. Use --history to list.")
    raise SystemExit("ERROR: ambiguous match:\n" + "\n".join(
        f"  {i}: {e.get('title')} | {e.get('url')}" for i, e in enumerate(entries) if e in sub))


def remember(entry: dict) -> int:
    """Insert/update entry by URL, newest first. Returns its index (0)."""
    with preferences_lock():
        history = load_history()
        entries = [e for e in history if e.get("url") != entry["url"]]
        old = next((e for e in history if e.get("url") == entry["url"]), {})
        entry["plays"] = int(old.get("plays", 0) or 0) + 1
        entries.insert(0, {k: entry.get(k) for k in ENTRY_FIELDS})
        save_history(entries)
    return 0


# ---------- tmpfs enforcement (no disk write amplification) ----------

def _mount_fstype(path: str) -> str | None:
    """Filesystem type of the mount containing path, via /proc/self/mountinfo."""
    path = os.path.realpath(os.path.abspath(path))
    best_fs, best_len = None, -1
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                left, sep, right = line.partition(" - ")
                if not sep:
                    continue
                pre = left.split()
                if len(pre) < 5:
                    continue
                mnt = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), pre[4])
                if path == mnt or path.startswith(mnt.rstrip("/") + "/"):
                    fields = right.split()
                    if not fields:
                        continue
                    if len(mnt) > best_len:
                        best_len, best_fs = len(mnt), fields[0]
    except FileNotFoundError:
        return None
    return best_fs


def is_tmpfs(path: str) -> bool:
    return _mount_fstype(path) == "tmpfs"


def secure_dir(path: str, mode: int = 0o700) -> str:
    """mkdir 0700, rejecting a leaf symlink and other owners."""
    os.makedirs(path, mode=mode, exist_ok=True)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError(f"Unsafe directory (symlink or other owner): {path}")
    os.chmod(path, mode)
    return path


def secure_subdir(root: str, name: str, mode: int = 0o700) -> str:
    """Create name directly under root, refusing symlink escapes in between."""
    if os.path.realpath(root) != os.path.abspath(root):
        raise ValueError(f"Refusing symlinked pool root: {root}")
    if "/" in name or name in (".", ".."):
        raise ValueError(f"Refusing unsafe pool name: {name!r}")
    pool = os.path.join(root, name)
    os.makedirs(pool, mode=mode, exist_ok=True)
    if os.path.realpath(pool) != os.path.join(os.path.realpath(root), name):
        raise ValueError(f"Refusing path escaping {root}: {pool}")
    return secure_dir(pool, mode)


def pick_tmpfs(user_dir: str | None, allow_disk: bool) -> str:
    # Discover tmpfs mounts instead of assuming a particular zram mount name.
    if user_dir:
        candidates = [os.path.abspath(os.path.expanduser(user_dir))]
    else:
        candidates = []
        with open("/proc/self/mountinfo", encoding="utf-8") as f:
            for line in f:
                left, sep, right = line.partition(" - ")
                if sep and right.split()[0] == "tmpfs":
                    mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), left.split()[4])
                    if os.path.isdir(mount) and os.access(mount, os.W_OK | os.X_OK):
                        candidates.append(mount)
        candidates += CANDIDATE_TMPFS
        # Prefer the largest writable tmpfs; space is critical for DVR.
        def free(path: str) -> int:
            try:
                return shutil.disk_usage(path).free
            except OSError:
                return -1
        candidates = sorted(set(candidates), key=free, reverse=True)
    for root in candidates:
        if not allow_disk or not user_dir:
            if not is_tmpfs(root):
                continue
        try:
            pool = secure_subdir(root, f"mpv-dvr-{os.getuid()}")
            if os.stat(pool).st_dev != os.stat(root).st_dev:
                continue
            fd, name = tempfile.mkstemp(prefix=".write-test-", dir=pool)
            os.close(fd)
            os.unlink(name)
            return pool
        except (OSError, ValueError):
            continue
    raise SystemExit("ERROR: no usable recording directory. --tmpdir must be writable "
                     "tmpfs unless --allow-disk is specified. Tried: " + ", ".join(candidates))


# ---------- cookies (login-walled / sensitive broadcasts) ----------

def stage_cookies(src: str | None, browser: str | None, ram_dir: str,
                  ) -> tuple[list[str], str | None, str | None]:
    """Copy the cookie jar into tmpfs; return (yt-dlp flags, mpv raw opt, staged path).

    The original jar is never handed to yt-dlp (it rewrites the file).
    """
    if src and browser:
        raise SystemExit("ERROR: use either --cookies or --cookies-from-browser, not both.")
    if browser:
        return (["--cookies-from-browser", browser], f"cookies-from-browser={browser}", None)
    if not src:
        return ([], None, None)
    if not os.path.isfile(os.path.expanduser(src)):
        raise SystemExit(f"ERROR: not a cookie file: {src}")
    fd, name = tempfile.mkstemp(prefix=".mpv-live-cookies-", dir=ram_dir)
    try:
        with os.fdopen(fd, "wb") as dst, open(os.path.expanduser(src), "rb") as fh:
            shutil.copyfileobj(fh, dst)
        os.chmod(name, 0o600)
    except OSError as e:
        raise SystemExit(f"ERROR: cannot stage cookies in tmpfs: {e}")
    return (["--cookies", name], f"cookies={name}", name)


def check_free(path: str, min_mb: int) -> None:
    free_mb = shutil.disk_usage(path).free // (1024 * 1024)
    if free_mb < min_mb:
        raise SystemExit(
            f"ERROR: only {free_mb}MB free on {path} (need {min_mb}MB). "
            "4K live is ~2MB/s. Free tmpfs space or pick lower -f."
        )


# ---------- yt-dlp ----------

def _failure_hint(message: str) -> str:
    m = (message or "").lower()
    if "sign in" in m or "login" in m or "not a bot" in m or "authenticate" in m:
        return "HINT: login needed — pass --cookies ~/cookies.txt or --cookies-from-browser chromium."
    if "429" in m:
        return "HINT: rate-limited, wait and retry."
    if "403" in m:
        return "HINT: access denied — check cookies / link permissions."
    if "unsupported url" in m:
        return "HINT: update with: yt-dlp -U"
    if "requested format" in m:
        return "HINT: codec/height absent — try -f best or a lower cap."
    return ""


def run_yt_dlp_json(url: str, extra_flags: list[str] | None = None,
                    *, executable: str = "yt-dlp", env: dict | None = None) -> dict:
    cmd = [executable, "--no-playlist", "--no-cache-dir", "--skip-download"]
    cmd += extra_flags or []
    cmd += ["-J", "--", url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    except FileNotFoundError:
        raise SystemExit("ERROR: yt-dlp not found in PATH (need recent yt-dlp for x.com)")
    except subprocess.TimeoutExpired:
        raise SystemExit("ERROR: yt-dlp metadata extraction timed out after 60 seconds.")
    if p.returncode != 0:
        sys.stderr.write((p.stderr or p.stdout or "yt-dlp failed")[-3000:])
        hint = _failure_hint(p.stderr or p.stdout or "")
        if hint:
            sys.stderr.write("\n" + hint + "\n")
        raise SystemExit(1)
    if p.stderr:
        sys.stderr.write(p.stderr[-3000:])
    try:
        info = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise SystemExit("ERROR: could not parse yt-dlp -J output")
    if not isinstance(info, dict):
        raise SystemExit("ERROR: yt-dlp returned non-object metadata")
    # --no-playlist should prevent this, but stay robust for YT mixes
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise SystemExit("ERROR: playlist returned no entries")
        info = entries[0]
    return info


def codec_fam(vc: str | None) -> str:
    """Short codec family: av1 / vp9 / hevc / avc / none / raw-prefix."""
    v = (vc or "").strip().lower()
    if not v or v in ("?", "none"):
        return v or "?"
    if "av01" in v or v == "av1":
        return "av1"
    if "vp09" in v or v == "vp9":
        return "vp9"
    if v.startswith(("hev1", "hev2", "hvc1", "hevk")) or "hevc" in v or "h265" in v:
        return "hevc"
    if v.startswith("avc") or "h264" in v:
        return "avc"
    return v.split(".")[0][:8] or "?"


CODEC_ALIASES = {
    "av1": "av1", "av01": "av1",
    "vp9": "vp9", "vp09": "vp9",
    "hevc": "hevc", "h265": "hevc", "h.265": "hevc",
    "avc": "avc", "h264": "avc", "h.264": "avc",
}


def mp4_codec_header(url: str, headers: dict, deadline: float) -> bytes:
    """Fetch MP4 sample descriptions, skipping potentially huge sample indexes.

    ffprobe interprets codec configuration from a compact reconstructed header.
    Range support is required; other layouts fall back to ordinary ffprobe.
    """
    children = {
        b"moov": {b"mvhd", b"trak"}, b"trak": {b"tkhd", b"mdia"},
        b"mdia": {b"mdhd", b"hdlr", b"minf"},
        b"minf": {b"vmhd", b"smhd", b"dinf", b"stbl"}, b"stbl": {b"stsd"},
    }
    cache = {}
    boxes = 0

    def read(offset: int, length: int) -> bytes:
        parts = []
        while length:
            base = offset // 32768 * 32768
            if base not in cache:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or len(cache) >= 32:
                    raise ValueError("MP4 header probe budget exhausted")
                request = urllib.request.Request(url, headers={
                    **headers, "Range": f"bytes={base}-{base + 32767}",
                    "Accept-Encoding": "identity",
                })
                with urllib.request.urlopen(request, timeout=min(5, remaining)) as response:
                    if (response.status != 206 or not response.headers.get(
                            "Content-Range", "").startswith(f"bytes {base}-")):
                        raise ValueError("Server does not support byte ranges")
                    cache[base] = response.read(32768)
            chunk = cache[base][offset - base:offset - base + length]
            if not chunk:
                raise ValueError("Truncated MP4 header")
            parts.append(chunk)
            offset += len(chunk)
            length -= len(chunk)
        return b"".join(parts)

    def box(offset: int) -> tuple[int, bytes, int]:
        nonlocal boxes
        boxes += 1
        if boxes > 128:
            raise ValueError("Too many MP4 header boxes")
        size, kind = struct.unpack(">I4s", read(offset, 8))
        header_size = 8
        if size == 1:
            size = struct.unpack(">Q", read(offset + 8, 8))[0]
            header_size = 16
        if size < header_size:
            raise ValueError("Invalid MP4 box size")
        return size, kind, header_size

    def retain(offset: int, size: int, kind: bytes, header_size: int) -> bytes:
        if kind in children:
            parts = []
            child, end = offset + header_size, offset + size
            while child < end:
                child_size, child_kind, child_header = box(child)
                if child + child_size > end:
                    raise ValueError("MP4 box exceeds its container")
                if child_kind in children[kind]:
                    parts.append(retain(child, child_size, child_kind, child_header))
                # Sample descriptions carry the codecs; indexes are unnecessary.
                if kind == b"stbl" and child_kind == b"stsd":
                    break
                child += child_size
            payload = b"".join(parts)
        else:
            if size > 131072:
                raise ValueError("Oversized MP4 codec description")
            payload = read(offset + header_size, size - header_size)
        return struct.pack(">I4s", len(payload) + 8, kind) + payload

    parts, offset = [], 0
    for _ in range(8):
        size, kind, header_size = box(offset)
        if kind in (b"ftyp", b"moov"):
            parts.append(retain(offset, size, kind, header_size))
        if kind == b"moov":
            return b"".join(parts)
        offset += size
    raise ValueError("MP4 codec header not found")


def probe_missing_codecs(info: dict, *, env: dict | None = None) -> None:
    """Fill missing extractor metadata from stream headers; never guess from the container.

    Known codecs and explicit 'none' values remain authoritative. Only format
    listing/interactive selection/codec preferences need this extra network work.
    At most four probes run together, with a shared 20-second probe budget.
    """
    formats = info.get("formats") or ([info] if info.get("url") else [])
    unknown = [f for f in formats if f.get("url") and
               any(f.get(key) in (None, "", "?") for key in ("vcodec", "acodec"))]
    if not unknown:
        return
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        print("NOTE: codec metadata is missing; install ffprobe to detect it.", file=sys.stderr)
        return
    print(f"Detecting missing codecs for {len(unknown)} formats...", file=sys.stderr)
    deadline = time.monotonic() + 20

    def probe(fmt: dict) -> dict:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {}
        cmd = [ffprobe, "-v", "error", "-probesize", "262144",
               "-analyzeduration", "1000000",
               "-show_entries", "stream=codec_type,codec_name", "-of", "json"]
        header = None
        if fmt["url"].startswith(("http://", "https://")):
            cmd += ["-rw_timeout", "5000000"]
            headers = dict(info.get("http_headers") or {})
            headers.update(fmt.get("http_headers") or {})
            if headers:
                cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
            cookies = fmt.get("cookies") or info.get("cookies")
            if cookies:
                cmd += ["-cookies", cookies]
            elif fmt.get("ext") == "mp4" and fmt.get("protocol") in (None, "http", "https"):
                try:
                    header = mp4_codec_header(fmt["url"], headers, deadline)
                except (OSError, ValueError, http.client.HTTPException):
                    pass  # Unsupported range/layout: let ffprobe open the original.
        if header is not None:
            cmd = [ffprobe, "-v", "error", "-nofind_stream_info",
                   "-show_entries", "stream=codec_type,codec_name", "-of", "json", "-i", "pipe:0"]
        else:
            cmd += ["-i", fmt["url"]]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {}
        try:
            result = subprocess.run(cmd, capture_output=True, text=header is None,
                                    input=header, timeout=remaining, env=env)
            if result.returncode:
                return {}
            streams = json.loads(result.stdout).get("streams") or []
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return {}
        codecs = {}
        for kind, key in (("video", "vcodec"), ("audio", "acodec")):
            matches = [s for s in streams if s.get("codec_type") == kind]
            # A partial/unsupported codec stays unknown, rather than being
            # mistaken for an absent track and changing format selection.
            if matches and matches[0].get("codec_name"):
                codecs[key] = matches[0]["codec_name"]
            elif streams and not matches:
                codecs[key] = "none"
        return codecs

    with ThreadPoolExecutor(max_workers=4) as executor:
        for fmt, codecs in zip(unknown, executor.map(probe, unknown)):
            for key, value in codecs.items():
                if fmt.get(key) in (None, "", "?"):
                    fmt[key] = value
    remaining = sum(any(f.get(key) in (None, "", "?")
                        for key in ("vcodec", "acodec")) for f in unknown)
    if remaining:
        print(f"NOTE: codec detection unavailable for {remaining} formats; shown as ?. "
              "Playback can still detect their codecs.", file=sys.stderr)


def fmt_list(info: dict) -> list[dict]:
    fmts = info.get("formats") or []
    if not fmts and info.get("url"):
        fmts = [info]
    out = []
    for f in fmts:
        fid = str(f.get("format_id") or "?")
        w, h = f.get("width"), f.get("height")
        res = f"{w}x{h}" if w and h else (f"{h}p" if h else (f.get("resolution") or "?"))
        vc = f.get("vcodec") or "?"
        out.append({
            "id": fid, "ext": f.get("ext") or "?", "res": res,
            "h": h or 0, "fps": f.get("fps") or 0, "tbr": f.get("tbr") or 0,
            "vcodec": vc[:24], "fam": codec_fam(vc),
            "acodec": (f.get("acodec") or "?")[:16],
            "proto": f.get("protocol") or "?", "note": f.get("format_note") or "",
        })
    # Preserve yt-dlp ranking, including quality, source and codec preferences.
    return out


def print_formats(fmts: list[dict], title: str = "") -> None:
    if title:
        print(title)
    if _RICH and sys.stdout.isatty():
        t = Table(show_header=True, header_style="bold")
        for col in ("#", "ID", "RES", "FPS", "TBR", "CODEC", "VCODEC", "ACODEC", "PROTO"):
            t.add_column(col, justify="right" if col in ("#", "FPS", "TBR") else "left")
        for i, f in enumerate(fmts):
            t.add_row(str(i), f["id"], f["res"],
                      str(f["fps"] or "?"), f"{f['tbr']:.0f}k" if f["tbr"] else "?",
                      f["fam"], f["vcodec"], f["acodec"], f["proto"])
        Console().print(t)
        return
    print(f"{'#':>3}  {'ID':<12} {'RES':<10} {'FPS':>6} {'TBR':>8}  {'CODEC':<6} {'VCODEC':<16} {'ACODEC':<10} PROTO")
    for i, f in enumerate(fmts):
        print(f"{i:>3}  {f['id']:<12} {f['res']:<10} {str(f['fps'] or '?'):>6} "
              f"{(f'{f['tbr']:.0f}k' if f['tbr'] else '?'):>8}  "
              f"{f['fam']:<6} {f['vcodec']:<16} {f['acodec']:<10} {f['proto']}")


DEFAULT_FORMAT = "bestvideo*+bestaudio/best/bestaudio"


def _format_with_audio(fmt: dict) -> str:
    fid = fmt["id"]
    return f"{fid}+bestaudio/{fid}" if fmt["acodec"] == "none" else fid


def _pick_codec_best(fmts: list[dict], fam: str) -> str | None:
    matches = [f for f in fmts if f["fam"] == fam]
    return _format_with_audio(matches[-1]) if matches else None


def resolve_format(fmts: list[dict], want: str | None, prefer_codec: str | None = None,
                   fallback_best: bool = False) -> str:
    """IDs take precedence; #N explicitly selects a row. Attach audio to video-only IDs."""
    if not fmts:
        return want or DEFAULT_FORMAT
    if prefer_codec and not want:
        preferred = prefer_codec.strip().lower()
        if preferred not in CODEC_ALIASES:
            raise SystemExit(f"ERROR: unknown codec {prefer_codec!r}; use av1/vp9/hevc/avc")
        want = CODEC_ALIASES[preferred]
    if want is None and sys.stdin.isatty():
        print_formats(fmts)
        try:
            want = input("Pick [#row / ID / codec / selector; default=best, q=quit]: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(130)
        if want.lower() in ("q", "quit", "exit"):
            raise SystemExit(130)
    w = (want or "best").strip()
    if w == "best":
        return DEFAULT_FORMAT
    if w == "worst":
        return "worstvideo*+worstaudio/worst/worstaudio"
    match = next((f for f in fmts if f["id"] == w), None)
    if match:
        return _format_with_audio(match)
    if w.startswith("#"):
        row = w.removeprefix("#")
        if row.isdigit() and int(row) < len(fmts):
            return _format_with_audio(fmts[int(row)])
        raise SystemExit(f"ERROR: format row {w!r} is out of range")
    if w.lower() in CODEC_ALIASES:
        hit = _pick_codec_best(fmts, CODEC_ALIASES[w.lower()])
        if hit:
            return hit
        if not fallback_best and not prefer_codec:
            raise SystemExit(f"ERROR: no {w} formats. Use -F to list.")
        print(f"WARNING: no {w} formats; using best.", file=sys.stderr)
        return DEFAULT_FORMAT
    stored_video = re.fullmatch(r"([\w.-]+)\+bestaudio/\1", w)
    if fallback_best and stored_video and stored_video[1] not in {f["id"] for f in fmts}:
        print(f"WARNING: stored video format {stored_video[1]!r} gone; using best.", file=sys.stderr)
        return DEFAULT_FORMAT
    if fallback_best and re.fullmatch(r"[\w.-]+", w) and w not in {
            "b", "bv", "ba", "bestaudio", "bestvideo", "worstaudio", "worstvideo",
            "mp4", "webm", "m4a", "mp3", "ogg", "opus", "flv", "wav", "aac", "3gp"}:
        print(f"WARNING: stored format {w!r} gone; using best.", file=sys.stderr)
        return DEFAULT_FORMAT
    return w


def resolve_buffer(want: str | None, need_player: bool) -> str:
    """full = up to 2 GiB demuxer cache for easy back/forth scrub; near = mpv defaults.

    Never forced: ask prompts on a tty, defaults to near when piped or when
    there is no player (--record-only / -F). Direct-live note: full widens
    the local rewind window; reopening still depends on the server timeline.
    Global/env/CLI merging happens before this call, so want is already final.
    """
    w = (want or "ask").strip().lower()
    if w not in ("ask", "full", "near"):
        raise SystemExit("ERROR: --buffer must be ask/full/near")
    if not need_player or w in ("full", "near"):
        return w if w in ("full", "near") else "near"
    if not sys.stdin.isatty():
        return "near"
    print("Buffer: [full] allows up to 2 GiB of demuxer cache for easy back/forth scrubbing "
          "(more RAM); [near] keeps mpv defaults (file stays fully seekable either way).",
          file=sys.stderr)
    try:
        ans = input("Buffer full or near? [near/full, default=near]: ").strip().lower() or "near"
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        raise SystemExit(130)
    if ans in ("full", "near"):
        return ans
    print(f"Unknown {ans!r}, using near.", file=sys.stderr)
    return "near"


def wait_for_file(path: str, proc: subprocess.Popen, timeout: float, min_bytes: int = START_BYTES) -> bool:
    t0 = time.monotonic()
    last_msg = 0.0
    while time.monotonic() - t0 < timeout:
        try:
            have = os.path.getsize(path)
            if have >= min_bytes:
                return True
        except OSError:
            have = 0
        if proc.poll() is not None:  # recorder died: fail fast
            try:
                return os.path.getsize(path) >= min_bytes
            except OSError:
                return False
        if time.monotonic() - last_msg >= 2.0:
            print(f"  recording... {have // 1024}KB / {min_bytes // 1024}KB", file=sys.stderr)
            last_msg = time.monotonic()
        time.sleep(0.5)
    try:
        return os.path.getsize(path) >= min_bytes
    except OSError:
        return False


def join_threshold(fmts: list[dict], choice: str) -> int:
    """Wait for roughly 1.5 seconds of data, with a 256 KiB..2 MiB startup target."""
    tbr = next((f["tbr"] for f in fmts if f["id"] == choice), 0) or 0
    return max(START_BYTES, min(int(tbr * 125 * 1.5), 2 * 1024 * 1024))


# Lua snapshots position at the key press, avoiding stale polling and preserving
# the user's input.conf. Reopening is useful on HLS sources that clamp seeks.
TRAVEL_DELTAS = {91: -60, 92: 60, 93: -600, 94: 600}
TRAVEL_LUA = r"""
local utils = require 'mp.utils'
local dir = utils.join_path(mp.get_script_directory(), '..')
local state = {}
local function snapshot()
    for _, key in ipairs({'time-pos', 'duration', 'speed', 'mute', 'fullscreen'}) do
        local value = mp.get_property_native(key)
        if value ~= nil then state[key] = value end
    end
    local file = io.open(dir .. '/position.json', 'w')
    if file then file:write(utils.format_json(state)); file:close() end
end
mp.observe_property('time-pos', 'number', function(_, value)
    if value then state['time-pos'] = value end
end)
mp.register_event('shutdown', snapshot)
for key, code in pairs({['Ctrl+Left']=91, ['Ctrl+Right']=92,
                        ['Shift+Left']=93, ['Shift+Right']=94}) do
    mp.add_forced_key_binding(key, 'travel-' .. code, function()
        snapshot()
        mp.commandv('quit', code)
    end)
end
"""

# Native file reads retry append stalls for only ~2 seconds. Recover longer
# stalls by reopening at the last played timestamp once new bytes arrive.
FOLLOW_LUA = r"""
local utils = require 'mp.utils'
local dir = utils.join_path(mp.get_script_directory(), '..')
local last_size = 0
local position = 0
local loading = false
mp.register_event('file-loaded', function() loading = false end)
mp.observe_property('time-pos', 'number', function(_, value)
    if value then position = value end
end)
mp.add_periodic_timer(0.5, function()
    if loading or not mp.get_property_native('eof-reached') then return end
    local path = mp.get_property('path')
    local info = path and utils.file_info(path)
    local done = utils.file_info(dir .. '/recorder.done')
    if info and info.size > last_size then
        last_size = info.size
        loading = true
        mp.command_native({name='loadfile', url=path, flags='replace',
                           options={start=tostring(position), speed=tostring(mp.get_property_number('speed', 1))}})
        mp.set_property_native('pause', false)
    elseif done then
        mp.commandv('quit')
    end
end)
"""


def stop_process(proc: subprocess.Popen) -> None:
    """Stop a child and its extractor, then reap it before deleting recordings."""
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()


def resolve_ytdlp() -> str:
    found = shutil.which("yt-dlp")
    if not found:
        raise SystemExit("ERROR: yt-dlp not found in PATH")
    path = str(found)
    if ":" in path:
        raise SystemExit(f"ERROR: yt-dlp path contains ':' ({path}); mpv uses ':' as ytdl_path separator")
    return path


YTDLP_OPT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def parse_ytdlp_option(text: str) -> tuple[str, str | None]:
    key, sep, value = text.partition("=")
    key = key.strip().removeprefix("--")
    if not key or not YTDLP_OPT_RE.fullmatch(key):
        raise SystemExit(f"ERROR: invalid yt-dlp option key: {key!r}")
    return key, value if sep and (value or key == "proxy") else None


def build_raw_opts(cookie_opt: str | None, ignore_config: bool,
                   extra: list[str]) -> list[str]:
    """mpv --ytdl-raw-options entries; duplicates are a hard error (map semantics)."""
    out = ["no-cache-dir="]
    if ignore_config:
        out.append("ignore-config=")
    if cookie_opt:
        out.append(cookie_opt)
    for raw in extra:
        key, value = parse_ytdlp_option(raw)
        out.append(f"{key}=" if value is None else f"{key}={value}")
    seen: set[str] = set()
    for item in out:
        k = item.split("=", 1)[0]
        if k in seen:
            raise SystemExit(f"ERROR: duplicate yt-dlp option {k!r}; ytdl-raw-options is a key/value map")
        seen.add(k)
    return out


def doctor(mpv: str, ytdlp: str) -> int:
    def first(cmd: list[str]) -> str:
        try:
            p = subprocess.run(cmd, text=True, capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return "unavailable"
        text = (p.stdout or p.stderr or "").strip()
        return text.splitlines()[0] if text else f"exit {p.returncode}"

    print(f"python : {sys.version.split()[0]} ({sys.executable})")
    print(f"mpv    : {first([mpv, '--no-config', '--version'])}")
    print(f"         {mpv}")
    print(f"yt-dlp : {first([ytdlp, '--version'])}")
    print(f"         {ytdlp}")
    try:
        p = subprocess.run([mpv, "--no-config", "--list-options"], text=True, capture_output=True, timeout=15)
        options = p.stdout
    except (OSError, subprocess.TimeoutExpired):
        options = ""
    required = {"--ytdl-format", "--ytdl-raw-options", "--stream-record",
                "--demuxer-max-bytes", "--demuxer-max-back-bytes",
                "--scripts-append", "--ytdl-raw-options-append", "--keep-open",
                "--script-opts-append", "--cache-on-disk", "--demuxer-readahead-secs",
                "--save-position-on-quit", "--resume-playback", "--speed",
                "--fullscreen", "--mute", "--input-terminal", "--vo", "--ao", "--start"}
    missing = sorted(o for o in required if o not in options)
    if missing:
        print("ERROR  : mpv lacks required options: " + ", ".join(missing))
        return 1
    print("mpv    : required extraction/recording/cache/script options present")
    configured = subprocess.run([mpv, "--version"], text=True, capture_output=True, timeout=15)
    diagnostics = configured.stderr.strip()
    prefix = configured.stdout.partition("mpv ")[0].strip()
    if prefix:
        diagnostics = prefix + "\n" + diagnostics
    if diagnostics.strip():
        print("config : " + diagnostics.strip()[:1500])
    for cand in CANDIDATE_TMPFS:
        fs = _mount_fstype(cand)
        try:
            free = shutil.disk_usage(cand).free // (1024 * 1024)
        except OSError:
            free = -1
        print(f"tmpfs  : {cand} ({fs or 'missing'}, {free} MiB free)")
    try:
        import rich  # noqa: F401
        print("rich   : available (tables enabled)")
    except ImportError:
        print("rich   : missing (plain-text tables)")
    return 0


class SpaceGuard(threading.Thread):
    """Check free space once per second and interrupt writers below the floor."""

    def __init__(self, pool: str, floor_mb: int, victims: list) -> None:
        super().__init__(daemon=True)
        self.pool = pool
        self.floor_mb = floor_mb
        self.victims = victims
        self.stop_event = threading.Event()
        self.exhausted = threading.Event()

    def run(self) -> None:
        while not self.stop_event.wait(1.0):
            try:
                free = shutil.disk_usage(self.pool).free // (1024 * 1024)
            except OSError:
                return
            if free < self.floor_mb:
                print(f"ERROR: tmpfs free {free} MiB < floor {self.floor_mb} MiB; "
                      f"stopping recording to protect RAM.", file=sys.stderr)
                self.exhausted.set()
                for proc in tuple(self.victims):
                    try:
                        if proc.poll() is None:
                            os.killpg(proc.pid, signal.SIGINT)
                    except ProcessLookupError:
                        pass
                return

    def halt(self) -> None:
        self.stop_event.set()
        self.join(timeout=2)


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        allow_abbrev=False, prog=PROG, description="Watch YouTube/X live in mpv with tmpfs DVR (rewind + 2x).",
        epilog="Precedence: CLI > --replay entry > env > config.toml > builtin. "
               "Player keys: } = 2x, ]/[ = speed, Backspace = reset, Left/Right = seek.",
    )
    ap.add_argument("url", nargs="?",
                    help="youtube.com/watch, youtu.be, x.com/i/broadcasts/..., x.com/.../status/... works for VOD too")
    ap.add_argument("-F", "--list-formats", action="store_true", help="list available resolutions and exit")
    ap.add_argument("-f", "--format", default=None,
                    help="format ID, #row from -F, codec (av1/vp9/hevc/avc), best/worst, "
                         "or raw yt-dlp selector (default: prompt, best if piped)")
    ap.add_argument("--prefer-codec", default=None,
                    help="auto-pick best format with this codec: av1/vp9/hevc/avc (ignored if -f given)")
    ap.add_argument("--buffer", default=None,
                    help="player RAM window: ask/full/near (default: ask on tty, near if piped). "
                         "full = up to 2 GiB back/forth cache; file stays seekable either way")
    ap.add_argument("--speed", type=float, default=None, help="initial player speed, 2 = 2x (default: 1.0)")
    ap.add_argument("--tmpdir", default=None, help="tmpfs dir for recording (default: largest writable tmpfs)")
    ap.add_argument("--cookies", default=None,
                    help="Netscape cookie file for login-walled broadcasts (copied to tmpfs, original untouched)")
    ap.add_argument("--cookies-from-browser", default=None, metavar="BROWSER",
                    help="e.g. chromium, firefox (passed to yt-dlp and mpv)")
    ap.add_argument("--allow-disk", dest="allow_disk", default=None,
                    action=argparse.BooleanOptionalAction, help="allow non-tmpfs --tmpdir (SSD wear)")
    ap.add_argument("--min-free", type=int, default=None, metavar="MB", help="required free tmpfs MB (default: 500)")
    ap.add_argument("--keep", dest="keep", default=None,
                    action=argparse.BooleanOptionalAction, help="keep tmpfs recording on exit")
    ap.add_argument("--show-recorder", dest="show_recorder", default=None,
                    action=argparse.BooleanOptionalAction,
                    help="also show the live recorder window (default: headless)")
    ap.add_argument("--record-only", action="store_true", help="record to tmpfs without launching the player")
    ap.add_argument("--mode", default=None,
                    help="auto = live for current broadcasts, plain for regular videos (default); "
                         "live = play URL with a tmpfs archive; "
                         "file = two-process growing-file DVR (no server window needed); "
                         "plain = play URL, no recording")
    ap.add_argument("--fullscreen", dest="fullscreen", default=None,
                    action=argparse.BooleanOptionalAction, help="start player fullscreen")
    ap.add_argument("--mute", dest="mute", default=None,
                    action=argparse.BooleanOptionalAction, help="start player muted")
    ap.add_argument("--low-latency", dest="low_latency", default=None,
                    action=argparse.BooleanOptionalAction, help="URL playback uses mpv --profile=low-latency")
    ap.add_argument("--timeout", type=float, default=None, help="seconds to wait for recording to start (default: 30)")
    ap.add_argument("--start", default=None,
                    help="open at position: seconds (3600), MM:SS, HH:MM:SS, percent (50%%), #chapter, none, "
                         "or negative seconds from the end (-1800). Live seek availability depends on the server.")
    ap.add_argument("--player-args", default="", help='extra player args, e.g. --player-args="--volume=80"')
    ap.add_argument("--recorder-args", default="", help="extra recorder args (file mode only)")
    ap.add_argument("--ytdlp-option", action="append", default=[], metavar="KEY[=VALUE]",
                    help="pass a yt-dlp option to probe + mpv hook, e.g. --ytdlp-option=socket-timeout=15")
    ap.add_argument("--ignore-ytdlp-config", dest="ignore_ytdlp_config",
                    default=None, action=argparse.BooleanOptionalAction,
                    help="ignore external yt-dlp config files for determinism (default: on)")
    ap.add_argument("--floor-mb", type=int, default=None, metavar="MB",
                    help="stop recording if tmpfs free space falls below this (default: 256)")
    ap.add_argument("--doctor", action="store_true", help="check executables and required mpv options, then exit")
    ap.add_argument("--print-cmds", action="store_true", help="print mpv commands without running them")
    mg = ap.add_argument_group("config + history",
                               f"stored in {os.path.join(_cfg_dir())} (0600, video stays in tmpfs)")
    mg.add_argument("--set-global", action="append", nargs="+", default=[], metavar="KEY=VALUE",
                    help=f"persist global defaults, e.g. --set-global buffer=near speed=2 "
                         f"({', '.join(sorted(GLOBAL_SPEC))})")
    mg.add_argument("--show-config", action="store_true", help="show global defaults and exit")
    mg.add_argument("--history", action="store_true", help="list previously played streams and exit")
    mg.add_argument("--replay", default=None, metavar="N|URL",
                    help="replay a history entry with its stored settings (index, URL, or title match)")
    mg.add_argument("--forget", default=None, metavar="N|URL", help="drop a history entry and exit")
    mg.add_argument("--clear-history", action="store_true", help="drop all history and exit")
    return ap


OPT_ENV = {
    "format": "MPV_DVR_FORMAT", "prefer_codec": "MPV_DVR_CODEC", "buffer": "MPV_DVR_BUFFER",
    "speed": "MPV_DVR_SPEED", "tmpdir": "MPV_DVR_TMPDIR", "cookies": "MPV_DVR_COOKIES",
    "cookies_from_browser": "MPV_DVR_COOKIES_FROM_BROWSER", "mode": "MPV_DVR_MODE",
    "start": "MPV_DVR_START",
}


def _eff(cli: object, entry: dict, key: str, cfg: dict, builtin: object) -> object:
    """Precedence: CLI > replay entry > env > config.toml > builtin."""
    if cli is not None:
        return cli
    if entry.get(key) not in (None, ""):
        return entry[key]
    env = os.environ.get(OPT_ENV[key], "") if key in OPT_ENV else ""
    if env not in (None, ""):
        return env
    if cfg.get(key) not in (None, ""):
        return cfg[key]
    return builtin


def _bool_value(value: object, key: str) -> bool:
    if isinstance(value, bool):
        return value
    raise SystemExit(f"ERROR: {key} must be a TOML boolean, got {value!r}")


def _eff_bool(cli: object | None, entry: dict, key: str, cfg: dict, builtin: bool) -> bool:
    if cli is not None:
        return bool(cli)
    if entry.get(key) is not None:
        return _bool_value(entry[key], key)
    if cfg.get(key) is not None:
        return _bool_value(cfg[key], key)
    return builtin


def _eff_float(cli: object | None, entry: dict, key: str, cfg: dict, builtin: float, env_name: str) -> float:
    for src in (cli, entry.get(key), os.environ.get(env_name), cfg.get(key)):
        if src in (None, ""):
            continue
        try:
            value = float(src)  # type: ignore[arg-type]
            if not math.isfinite(value):
                raise ValueError
            return value
        except (ValueError, TypeError):
            raise SystemExit(f"ERROR: {key} needs a number, got {src!r}")
    return builtin


def show_history() -> None:
    entries = load_history()
    if not entries:
        print("History is empty.")
        return
    if _RICH and sys.stdout.isatty():
        t = Table(show_header=True, header_style="bold")
        for col in ("#", "LAST PLAYED", "TITLE", "FORMAT", "BUF", "SPEED", "PLAYS"):
            t.add_column(col, justify="right" if col in ("#", "SPEED", "PLAYS") else "left")
        for i, e in enumerate(entries):
            ts = time.strftime("%m-%d %H:%M", time.localtime(int(e.get("last_played", 0) or 0)))
            t.add_row(str(i), ts, str(e.get("title") or "?")[:40], str(e.get("format") or "?"),
                      str(e.get("buffer") or "?"), str(e.get("speed") or "?"), str(e.get("plays", 1)))
            t.add_row("", "", f"[dim]{str(e.get('url') or '')[:80]}[/dim]", "", "", "", "")
        Console().print(t)
        return
    for i, e in enumerate(entries):
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(e.get("last_played", 0) or 0)))
        print(f"{i}: [{ts}] {e.get('title')} | f={e.get('format')} buf={e.get('buffer')} "
              f"spd={e.get('speed')} x{e.get('plays', 1)}\n    {e.get('url')}")


def _eff_int(cli: object | None, entry: dict, key: str, cfg: dict, builtin: int) -> int:
    for src in (cli, entry.get(key), cfg.get(key)):
        if src in (None, ""):
            continue
        try:
            return int(src)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            raise SystemExit(f"ERROR: {key} needs an integer, got {src!r}")
    return builtin


def main() -> int:
    args = build_parser().parse_args()
    # Management commands (no URL needed).
    if args.set_global:
        with preferences_lock():
            cfg = load_config()
            for pair in [p for group in args.set_global for p in group]:
                k, v = parse_global_pair(pair)
                cfg[k] = v
            save_config({k: v for k, v in cfg.items() if k in GLOBAL_SPEC})
        print(f"Saved globals to {CONFIG_FILE}")
        return 0
    if args.show_config:
        cfg = load_config()
        print(f"# {CONFIG_FILE}")
        if not cfg:
            print("# (empty — all builtins)")
        for k in sorted(GLOBAL_SPEC):
            if k in cfg:
                print(f"{k} = {_tval(cfg[k])}")
        return 0
    if args.history:
        show_history()
        return 0
    if args.forget is not None:
        with preferences_lock():
            victim = find_entry(args.forget)
            entries = [e for e in load_history() if e.get("url") != victim.get("url")]
            save_history(entries)
        print(f"Forgot: {victim.get('title')} | {victim.get('url')}")
        return 0
    if args.clear_history:
        with preferences_lock():
            save_history([])
        print("History cleared.")
        return 0

    mpv_bin = shutil.which("mpv")
    if mpv_bin is None:
        raise SystemExit("ERROR: mpv not found in PATH")
    ytdlp = resolve_ytdlp()
    if args.doctor:
        return doctor(mpv_bin, ytdlp)

    # Replay supplies URL + per-stream prefs; explicit CLI still wins.
    entry: dict = find_entry(args.replay) if args.replay is not None else {}
    if args.url and entry and args.url != entry.get("url"):
        entry = {}
    if entry:
        print(f"Replaying #{load_history().index(entry)}: {entry.get('title')} "
              f"(stored f={entry.get('format')} buf={entry.get('buffer')} spd={entry.get('speed')})",
              file=sys.stderr)
    url = args.url or entry.get("url")
    if not url:
        raise SystemExit("ERROR: URL required (or use --replay N).")
    cfg = load_config()
    cli_fmt_given = args.format not in (None, "")

    args.url = url
    args.format = _eff(args.format, entry, "format", cfg, None)
    args.prefer_codec = _eff(args.prefer_codec, entry, "prefer_codec", cfg, None)
    args.buffer = _eff(args.buffer, entry, "buffer", cfg, "ask")
    args.speed = _eff_float(args.speed, entry, "speed", cfg, 1.0, "MPV_DVR_SPEED")
    args.tmpdir = _eff(args.tmpdir, entry, "tmpdir", cfg, None)
    cookie_src = _eff(args.cookies, {"cookies": entry.get("cookies")}, "cookies", cfg, None)
    browser = _eff(args.cookies_from_browser, entry, "cookies_from_browser", cfg, None)
    if args.cookies is not None:
        browser = args.cookies_from_browser
    elif args.cookies_from_browser is not None:
        cookie_src = None
    args.min_free = _eff_int(args.min_free, entry, "min_free", cfg, MIN_FREE_MB_DEFAULT)
    args.timeout = _eff_float(args.timeout, entry, "timeout", cfg, 30.0, "MPV_DVR_TIMEOUT")
    args.fullscreen = _eff_bool(args.fullscreen, entry, "fullscreen", cfg, False)
    args.mute = _eff_bool(args.mute, entry, "mute", cfg, False)
    args.low_latency = _eff_bool(args.low_latency, entry, "low_latency", cfg, False)
    args.keep = _eff_bool(args.keep, entry, "keep", cfg, False)
    args.show_recorder = _eff_bool(args.show_recorder, entry, "show_recorder", cfg, False)
    args.allow_disk = _eff_bool(args.allow_disk, entry, "allow_disk", cfg, False)
    ignore_cfg = _eff_bool(args.ignore_ytdlp_config, entry, "ignore_ytdlp_config", cfg, True)
    floor_mb = _eff_int(args.floor_mb, entry, "floor_mb", cfg, 256)
    mode = str(_eff(args.mode, entry, "mode", cfg, "auto")).strip().lower()
    if mode not in ("auto", "live", "file", "plain"):
        raise SystemExit("ERROR: --mode must be auto/live/file/plain")
    if args.record_only:
        if mode == "plain":
            raise SystemExit("ERROR: --record-only requires a recording mode")
        mode = "file"
    start = _eff(args.start, entry, "start", cfg, None)
    start_opt = [f"--start={parse_start(str(start))}"] if start not in (None, "") else []
    if not 0.1 <= args.speed <= 100:
        raise SystemExit("ERROR: --speed must be 0.1..100")
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.min_free <= 0 or floor_mb <= 0:
        raise SystemExit("ERROR: --timeout/--min-free/--floor-mb must be positive")

    # Validate option structure before allocating any session files.
    seen_keys = {"no-playlist", "yes-playlist", "no-cache-dir", "cache-dir",
                 "cookies", "cookies-from-browser", "ignore-config", "no-config",
                 "format", "dump-single-json", "dump-json", "skip-download",
                 "print", "quiet", "no-simulate", "load-info-json"}
    yt_extra = ["--ignore-config"] if ignore_cfg else []
    for raw in args.ytdlp_option:
        key, value = parse_ytdlp_option(raw)
        if key in seen_keys:
            raise SystemExit(f"ERROR: --ytdlp-option {key!r} collides with a built-in flag")
        seen_keys.add(key)
        yt_extra.append(f"--{key}" if value is None else f"--{key}={value}")
    try:
        extra_player = shlex.split(args.player_args)
        extra_rec = shlex.split(args.recorder_args)
    except ValueError as e:
        raise SystemExit(f"ERROR: invalid extra mpv arguments: {e}")

    # TemporaryDirectory also cleans up after extraction failures and Ctrl-C.
    with ExitStack() as stack:
        pool = pick_tmpfs(args.tmpdir, args.allow_disk)
        session = stack.enter_context(tempfile.TemporaryDirectory(prefix="run-", dir=pool))
        env = dict(os.environ, TMPDIR=session, XDG_CACHE_HOME=os.path.join(session, "cache"))
        yt_cookie_flags, mpv_cookie_opt, _ = stage_cookies(cookie_src, browser, session)
        raw_opts = build_raw_opts(mpv_cookie_opt, ignore_cfg, args.ytdlp_option)
        info = run_yt_dlp_json(url, yt_extra + yt_cookie_flags + ["--format", DEFAULT_FORMAT],
                              executable=ytdlp, env=env)
        codec_choice = str(args.format or "").strip().lower() in CODEC_ALIASES
        if (args.list_formats or codec_choice or (args.prefer_codec and not args.format)
                or (args.format is None and sys.stdin.isatty())):
            probe_missing_codecs(info, env=env)
        fmts = fmt_list(info)
        print(f"Title: {info.get('title') or '?'} | uploader: {info.get('uploader') or '?'} | "
              f"live: {info.get('live_status') or info.get('is_live') or '?'}", file=sys.stderr)
        if args.list_formats:
            print_formats(fmts)
            return 0
        if mode == "auto":
            mode = "live" if info.get("is_live") else "plain"
        choice = resolve_format(fmts, args.format, args.prefer_codec,
                                fallback_best=bool(entry) and not cli_fmt_given)
        bufmode = resolve_buffer(args.buffer, need_player=not args.record_only)
        print(f"Mode: {mode} | format: {choice} | buffer: {bufmode}", file=sys.stderr)

        # stream-record only writes the main demuxer. Check the exact selection
        # offline so raw selectors are handled by yt-dlp itself without a second
        # website extraction, URL reimplementation, or missing separate audio.
        record = mode != "plain"
        if record:
            metadata = os.path.join(session, "metadata.json")
            with open(metadata, "w", encoding="utf-8") as f:
                json.dump(info, f)
            selected = subprocess.run(
                [ytdlp, "--ignore-config", "--no-cache-dir", "--skip-download", "-J",
                 "--load-info-json", metadata, "--format", choice],
                capture_output=True, text=True, timeout=30, env=env)
            if selected.returncode:
                raise SystemExit("ERROR: format selection failed: " + selected.stderr[-3000:])
            selected_info = json.loads(selected.stdout)
            tracks = (selected_info.get("requested_formats")
                      or selected_info.get("requested_downloads") or [selected_info])
            fragmented = any(t.get("fragments") for t in tracks)
            if len(tracks) > 1 or fragmented:
                if mode == "file":
                    raise SystemExit("ERROR: file DVR requires a single muxed format "
                                     "(or audio-only stream) without EDL fragments. "
                                     "Pick one with -F/-f, or use --mode plain/live for separate tracks.")
                record = False
                print("NOTE: selected separate tracks or EDL fragments; mpv cannot archive "
                      "this selection reliably with --stream-record. Playback continues with "
                      "the archive disabled.", file=sys.stderr)
            if record:
                check_free(pool, max(args.min_free, floor_mb + 1))

        pin_opt = f"--script-opts-append=ytdl_hook-ytdl_path={ytdlp}"
        url_flags = [pin_opt, f"--ytdl-format={choice}", "--ytdl-raw-options-clr"]
        url_flags += [f"--ytdl-raw-options-append={o}" for o in raw_opts]
        if record:
            url_flags += ["--script-opts-append=ytdl_hook-all_formats=no",
                          "--script-opts-append=ytdl_hook-use_manifests=no"]
        common = ["--no-save-position-on-quit", "--no-resume-playback", "--cache-on-disk=no"]
        player = [mpv_bin] + common + BUFFER_PRESETS[bufmode] + [f"--speed={args.speed}"]
        # Explicit negative CLI booleans must also override mpv.conf.
        for key in ("fullscreen", "mute"):
            player.append(f"--{key}={'yes' if getattr(args, key) else 'no'}")
        if args.low_latency:
            url_flags.append("--profile=low-latency")
        if not args.print_cmds:
            remember({
                "url": url, "title": info.get("title") or "?", "uploader": info.get("uploader") or "?",
                "live_status": str(info.get("live_status") or info.get("is_live") or "?"),
                "format": choice, "buffer": bufmode, "speed": args.speed,
                "prefer_codec": args.prefer_codec or "", "fullscreen": args.fullscreen,
                "mute": args.mute, "low_latency": args.low_latency,
                "cookies_used": bool(cookie_src or browser), "cookies": cookie_src or "",
                "cookies_from_browser": browser or "", "mode": mode,
                "start": parse_start(str(start)) if start not in (None, "") else "",
                "last_played": int(time.time()), "plays": 0,
            })

        def show(cmd: list[str]) -> None:
            print("+ " + shlex.join(cmd), file=sys.stderr)

        def launch(cmd: list[str]) -> subprocess.Popen:
            proc = subprocess.Popen(cmd, env=env, start_new_session=True)
            stack.callback(stop_process, proc)
            return proc

        if mode == "plain":
            cmd = player + url_flags + start_opt + extra_player + ["--", url]
            show(cmd)
            return 0 if args.print_cmds else launch(cmd).wait()

        rec_path = os.path.join(session, "recording.mkv")
        kept_paths: list[str] = []
        def keep_recordings() -> None:
            if args.keep:
                for path in kept_paths:
                    if os.path.isfile(path):
                        fd, dest = tempfile.mkstemp(prefix="mpv-dvr-", suffix=".mkv", dir=pool)
                        os.close(fd)
                        os.replace(path, dest)
                        print(f"Kept recording: {dest}", file=sys.stderr)
        stack.callback(keep_recordings)
        victims: list[subprocess.Popen] = []
        guard = SpaceGuard(pool, floor_mb, victims)
        if record and not args.print_cmds:
            guard.start()
            stack.callback(guard.halt)

        if mode == "live":
            script = os.path.join(session, "travel")
            os.mkdir(script)
            with open(os.path.join(script, "main.lua"), "w", encoding="utf-8") as f:
                f.write(TRAVEL_LUA)
            base_cmd = player + url_flags + [f"--scripts-append={script}"] + extra_player
            open_start = start_opt
            state_path = os.path.join(session, "position.json")
            print("Travel: Ctrl+Left/Right = ±60s; Shift+Left/Right = ±10min. "
                  "Reopens at the current position; available timeline depends on the server.", file=sys.stderr)
            segment = 0
            while True:
                segment_path = os.path.join(session, f"recording-{segment}.mkv")
                cmd = base_cmd + open_start
                if record:
                    cmd += [f"--stream-record={segment_path}"]
                    kept_paths.append(segment_path)
                cmd += ["--", url]
                show(cmd)
                if args.print_cmds:
                    return 0
                try:
                    os.unlink(state_path)
                except FileNotFoundError:
                    pass
                proc = launch(cmd)
                victims[:] = [proc]
                rc = proc.wait()
                victims.clear()
                try:
                    with open(state_path, encoding="utf-8") as f:
                        state = json.load(f)
                except (OSError, ValueError):
                    state = {}
                position = state.get("time-pos")
                edge = state.get("duration")
                if guard.exhausted.is_set():
                    return 1
                if rc not in TRAVEL_DELTAS:
                    if isinstance(position, (int, float)) and math.isfinite(position):
                        with preferences_lock():
                            entries = load_history()
                            for e in entries:
                                if e.get("url") == url:
                                    e["start"] = "" if (edge and position >= edge - 5) else str(max(0, position))
                            save_history(entries)
                    return rc
                if not isinstance(position, (int, float)) or not math.isfinite(position):
                    print("WARNING: playback position unavailable; reopening at the live edge.", file=sys.stderr)
                    open_start = []
                else:
                    target = max(0, position + TRAVEL_DELTAS[rc])
                    open_start = [] if edge and target >= edge - 5 else [f"--start={target}"]
                for key in ("speed", "mute", "fullscreen"):
                    if key in state:
                        value = state[key]
                        value = ("yes" if value else "no") if isinstance(value, bool) else value
                        base_cmd = [arg for arg in base_cmd if not arg.startswith(f"--{key}=")]
                        base_cmd.append(f"--{key}={value}")
                segment += 1
                # Don't accumulate archives when --keep was not requested.
                if record and not args.keep:
                    try:
                        os.unlink(segment_path)
                    except FileNotFoundError:
                        pass

        rec_cmd = [mpv_bin] + common + url_flags + [f"--stream-record={rec_path}", "--keep-open=no"]
        if not args.show_recorder:
            rec_cmd += ["--vo=null", "--ao=null", "--input-terminal=no"]
        # --start controls the recording when there is no separate player.
        rec_cmd += (start_opt if args.record_only else []) + extra_rec + ["--", url]
        follower = os.path.join(session, "follow")
        os.mkdir(follower)
        with open(os.path.join(follower, "main.lua"), "w", encoding="utf-8") as f:
            f.write(FOLLOW_LUA)
        play_cmd = player + start_opt + extra_player + ["--keep-open=yes", f"--scripts-append={follower}", "--", rec_path]
        show(rec_cmd)
        if not args.record_only:
            show(play_cmd)
        if args.print_cmds:
            return 0
        kept_paths.append(rec_path)
        rec = launch(rec_cmd)
        victims[:] = [rec]
        if args.record_only:
            rc = rec.wait()
            return 1 if guard.exhausted.is_set() else rc
        need = join_threshold(fmts, choice)
        if not wait_for_file(rec_path, rec, args.timeout, need):
            # A completed short video may be smaller than the startup threshold.
            if not os.path.isfile(rec_path) or os.path.getsize(rec_path) == 0:
                print("ERROR: recorder produced no data before timeout/exit.", file=sys.stderr)
                return 1
            print("NOTE: starting with less data than the buffer target.", file=sys.stderr)
        play = launch(play_cmd)
        while play.poll() is None:
            if rec.poll() is not None:
                done_path = os.path.join(session, "recorder.done")
                if not os.path.exists(done_path):
                    with open(done_path, "w"):
                        pass
            time.sleep(0.2)
        rc = play.wait()
        if guard.exhausted.is_set() or rec.poll() not in (None, 0):
            return 1
        return rc


if __name__ == "__main__":
    def interrupted(signum: int, frame: object) -> None:
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopping...", file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
