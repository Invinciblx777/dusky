#!/usr/bin/env python3
"""mpv + yt-dlp live DVR player (YouTube / X / Twitter).

Records a live HLS stream to tmpfs with mpv --stream-record, then plays
the growing file from tmpfs, giving you rewind + 2x on live streams.
Video data never touches disk: startup aborts unless the record dir is tmpfs.

Examples:
  %(prog)s URL                                  # pick format + buffer, DVR play
  %(prog)s URL -F                                # list formats/codecs only
  %(prog)s URL -f 1 --speed 2                    # 2nd listed rendition at 2x
  %(prog)s URL -f live-2750 --fullscreen         # 720p fullscreen DVR
  %(prog)s URL --prefer-codec av1                # best av1/vp9/hevc/avc match
  %(prog)s URL -f "bv*[vcodec^=av01]+ba/b"       # raw yt-dlp selector passthrough
  %(prog)s URL --buffer full                     # large RAM window, easy scrub
  %(prog)s URL --cookies ~/cookies.txt            # login-walled / sensitive posts
  %(prog)s URL --direct -f best                  # no DVR, plain mpv + yt-dlp
  %(prog)s URL --record-only --keep               # timeshift buffer in tmpfs

Player keys: } = 2x, ] / [ = faster/slower, Backspace = reset,
Left/Right = seek, Up/Down = seek 1 min.

Cookies are staged as 0600 copies inside tmpfs; the original jar is untouched.

Env overrides: MPV_DVR_FORMAT, MPV_DVR_SPEED, MPV_DVR_TMPDIR, MPV_DVR_BUFFER,
MPV_DVR_CODEC (same as --prefer-codec), MPV_DVR_COOKIES,
MPV_DVR_COOKIES_FROM_BROWSER.
All mpv/yt-dlp flags used were verified against mpv 0.41 + yt-dlp 2026.08.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

PROG = os.path.basename(sys.argv[0]) or "mpv_yt_dlp_playback_livestream.py"
CANDIDATE_TMPFS = ["/mnt/zram1", "/dev/shm", "/tmp"]
MIN_FREE_MB_DEFAULT = 500
START_BYTES = 256 * 1024
# Player RAM window presets (verified mpv 0.41 option names).
# DVR file itself stays fully seekable on tmpfs either way; this only
# controls how much mpv holds in RAM for instant back/forth scrubbing.
BUFFER_PRESETS = {
    "near": [],
    "full": ["--demuxer-max-bytes=1G", "--demuxer-max-back-bytes=1G",
             "--demuxer-readahead-secs=10"],
}

try:
    from rich.console import Console
    from rich.table import Table

    _RICH = True
except Exception:
    _RICH = False


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
                mnt = pre[4].replace("\\040", " ")
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
    cands: list[str] = []
    if user_dir:
        cands.append(user_dir)
    cands += CANDIDATE_TMPFS
    if os.environ.get("XDG_RUNTIME_DIR"):
        cands.append(os.environ["XDG_RUNTIME_DIR"])
    seen = set()
    ordered = [c for c in cands if not (c in seen or seen.add(c))]
    for d in ordered:
        if allow_disk and user_dir and os.path.realpath(d) == os.path.realpath(user_dir):
            try:
                return secure_dir(d)
            except (OSError, ValueError) as e:
                raise SystemExit(f"ERROR: --tmpdir unusable: {e}")
        if _mount_fstype(d) != "tmpfs":
            continue
        pool = secure_subdir(d, f"mpv-dvr-{os.getuid()}")
        try:
            if os.stat(pool).st_dev != os.stat(d).st_dev:
                continue  # nested mount inside pool: refuse
            fd, name = tempfile.mkstemp(prefix=".write-test-", dir=pool)
            os.close(fd)
            os.unlink(name)
        except (OSError, ValueError):
            continue
        if not os.access(pool, os.W_OK):
            continue
        return pool
    raise SystemExit(
        "ERROR: no writable tmpfs found (tried %s). Refusing disk writes.\n"
        "Use --tmpdir /dev/shm (must be tmpfs) or --allow-disk to override."
        % ", ".join(ordered)
    )


# ---------- cookies (login-walled / sensitive broadcasts) ----------

def stage_cookies(args: argparse.Namespace, ram_dir: str) -> tuple[list[str], str | None, str | None]:
    """Copy the cookie jar into tmpfs; return (yt-dlp flags, mpv raw opt, staged path).

    The original jar is never handed to yt-dlp (it rewrites the file).
    """
    src = args.cookies or os.environ.get("MPV_DVR_COOKIES")
    browser = args.cookies_from_browser or os.environ.get("MPV_DVR_COOKIES_FROM_BROWSER")
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
    try:
        free_mb = shutil.disk_usage(path).free // (1024 * 1024)
    except OSError:
        return
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


def run_yt_dlp_json(url: str, extra_flags: list[str] | None = None) -> dict:
    cmd = ["yt-dlp", "--no-playlist", "--no-cache-dir", "--no-warnings"]
    cmd += extra_flags or []
    cmd += ["-J", "--", url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise SystemExit("ERROR: yt-dlp not found in PATH (need recent yt-dlp for x.com)")
    if p.returncode != 0:
        sys.stderr.write((p.stderr or p.stdout or "yt-dlp failed")[-3000:])
        hint = _failure_hint(p.stderr or p.stdout or "")
        if hint:
            sys.stderr.write("\n" + hint + "\n")
        raise SystemExit(1)
    try:
        info = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise SystemExit("ERROR: could not parse yt-dlp -J output")
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
    out.sort(key=lambda x: (x["h"], x["tbr"] or 0, x["fps"] or 0))
    return out


def print_formats(fmts: list[dict], title: str = "") -> None:
    if title:
        print(title)
    if _RICH and sys.stdout.isatty():
        t = Table(show_header=True, header_style="bold")
        for col in ("#", "ID", "RES", "FPS", "TBR", "CODEC", "VCODEC", "ACODEC", "PROTO"):
            t.add_column(col, justify="right" if col in ("#", "FPS", "TBR") else "left")
        for i, f in enumerate(fmts):
            tag = " ← best" if i == len(fmts) - 1 else (" ← smallest" if i == 0 else "")
            t.add_row(str(i), f["id"], f["res"],
                      str(f["fps"] or "?"), f"{f['tbr']:.0f}k" if f["tbr"] else "?",
                      f["fam"], f["vcodec"], f["acodec"], f["proto"] + tag)
        Console().print(t)
        return
    print(f"{'#':>3}  {'ID':<12} {'RES':<10} {'FPS':>6} {'TBR':>8}  {'CODEC':<6} {'VCODEC':<16} {'ACODEC':<10} PROTO")
    for i, f in enumerate(fmts):
        tag = "  <-- best" if i == len(fmts) - 1 else ""
        print(f"{i:>3}  {f['id']:<12} {f['res']:<10} {str(f['fps'] or '?'):>6} "
              f"{(f'{f['tbr']:.0f}k' if f['tbr'] else '?'):>8}  "
              f"{f['fam']:<6} {f['vcodec']:<16} {f['acodec']:<10} {f['proto']}{tag}")


def _best_of(fmts: list[dict]) -> str:
    return fmts[-1]["id"]


def _pick_codec_best(fmts: list[dict], fam: str) -> str | None:
    m = [f for f in fmts if f["fam"] == fam]
    return m[-1]["id"] if m else None


def resolve_format(fmts: list[dict], want: str | None, prefer_codec: str | None = None) -> str:
    """Return an mpv --ytdl-format value.

    Accepts: number from -F, exact format ID, best/worst, a codec family
    (av1/vp9/hevc/avc, with av01/vp09/h264/h265 aliases), or any raw
    yt-dlp format selector (passed through untouched, e.g.
    "bv*[vcodec^=av01]+ba/b"). Interactive prompt loops: typing a codec
    filters the table, anything else unknown is treated as a raw selector.
    """
    if not fmts:
        return "best"
    if prefer_codec and want is None:
        fam = CODEC_ALIASES.get(prefer_codec.strip().lower(), prefer_codec.strip().lower())
        hit = _pick_codec_best(fmts, fam)
        if hit is None:
            print(f"WARNING: no {fam} formats, falling back to best.", file=sys.stderr)
            return _best_of(fmts)
        return hit
    if want is not None:
        w = want.strip()
        if prefer_codec:
            print("NOTE: ignoring --prefer-codec (explicit -f given).", file=sys.stderr)
    elif not sys.stdin.isatty():
        return _best_of(fmts)
    else:
        pool = fmts
        while True:
            print_formats(pool)
            try:
                w = input("Pick [# / ID / av1 / vp9 / hevc / avc / raw selector, q=quit, default=best]: ").strip() or "best"
            except (EOFError, KeyboardInterrupt):
                print(file=sys.stderr)
                raise SystemExit(130)
            if w.lower() in ("q", "quit", "exit"):
                raise SystemExit("Aborted.")
            wl = w.lower()
            if wl in ("best", "worst"):
                return pool[-1]["id"] if wl == "best" else pool[0]["id"]
            if w.isdigit() and int(w) < len(pool):
                return pool[int(w)]["id"]
            if w in {f["id"] for f in pool}:
                return w
            if wl in CODEC_ALIASES:
                sub = [f for f in pool if f["fam"] == CODEC_ALIASES[wl]]
                if not sub:
                    print(f"No {wl} in this list, try another.", file=sys.stderr)
                    continue
                if len(sub) == 1:
                    return sub[0]["id"]
                pool = sub  # narrow table, pick again
                continue
            # Unknown input: raw yt-dlp format selector passthrough (future-proof).
            print(f"Passing custom yt-dlp format selector to mpv: {w}", file=sys.stderr)
            return w
    wl = w.lower()
    if wl == "best":
        return _best_of(fmts)
    if wl == "worst":
        return fmts[0]["id"]
    if w.isdigit() and int(w) < len(fmts):
        return fmts[int(w)]["id"]
    if w in {f["id"] for f in fmts}:
        return w
    if wl in CODEC_ALIASES:
        hit = _pick_codec_best(fmts, CODEC_ALIASES[wl])
        if hit is None:
            raise SystemExit(f"ERROR: no {wl} formats. Use -F to list.")
        return hit
    # Raw yt-dlp format selector passthrough (e.g. "bv*[height<=720]+ba/b").
    print(f"Passing custom yt-dlp format selector to mpv: {w}", file=sys.stderr)
    return w


def resolve_buffer(want: str | None, need_player: bool) -> str:
    """full = 1G RAM window for easy back/forth scrub; near = mpv defaults.

    Never forced: ask prompts on a tty, defaults to near when piped or when
    there is no player (--record-only / -F). Direct-live note: full widens
    the in-memory rewind window but can't exceed the server sliding window.
    """
    w = (want or os.environ.get("MPV_DVR_BUFFER") or "ask").strip().lower()
    if w not in ("ask", "full", "near"):
        raise SystemExit("ERROR: --buffer must be ask/full/near")
    if not need_player or w in ("full", "near"):
        return w if w in ("full", "near") else "near"
    if not sys.stdin.isatty():
        return "near"
    print("Buffer: [full] keeps a ~1G RAM window for easy back/forth scrubbing "
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


def wait_for_file(path: str, proc: subprocess.Popen, timeout: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if os.path.getsize(path) >= START_BYTES:
                return True
        except OSError:
            pass
        if proc.poll() is not None:  # recorder died: fail fast
            try:
                return os.path.getsize(path) >= START_BYTES
            except OSError:
                return False
        time.sleep(0.5)
    try:
        return os.path.getsize(path) >= START_BYTES
    except OSError:
        return False


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=PROG, description="Watch YouTube/X live in mpv with tmpfs DVR (rewind + 2x).",
        epilog="Player keys: } = 2x, ]/[ = speed, Backspace = reset, Left/Right = seek.",
    )
    ap.add_argument("url", help="youtube.com/watch, youtu.be, x.com/i/broadcasts/..., x.com/.../status/... works for VOD too")
    ap.add_argument("-F", "--list-formats", action="store_true", help="list available resolutions and exit")
    ap.add_argument("-f", "--format", default=os.environ.get("MPV_DVR_FORMAT"),
                    help="format ID, number from -F, codec (av1/vp9/hevc/avc), best/worst, "
                         "or raw yt-dlp selector (default: interactive prompt, best if piped)")
    ap.add_argument("--prefer-codec", default=os.environ.get("MPV_DVR_CODEC"),
                    help="auto-pick best format with this codec: av1/vp9/hevc/avc (ignored if -f given)")
    ap.add_argument("--buffer", default=os.environ.get("MPV_DVR_BUFFER", "ask"),
                    help="player RAM window: ask/full/near (default: ask on tty, near if piped). "
                         "full = 1G back/forth scrub window; file stays seekable either way")
    ap.add_argument("--speed", type=float, default=float(os.environ.get("MPV_DVR_SPEED", "1.0")),
                    help="initial player speed, 2 = 2x (default: 1.0)")
    ap.add_argument("--tmpdir", default=os.environ.get("MPV_DVR_TMPDIR"),
                    help="tmpfs dir for recording (default: /mnt/zram1, /dev/shm, then /tmp)")
    ap.add_argument("--cookies", default=None,
                    help="Netscape cookie file for login-walled broadcasts (copied to tmpfs, original untouched)")
    ap.add_argument("--cookies-from-browser", default=None, metavar="BROWSER",
                    help="e.g. chromium, firefox (passed to yt-dlp and mpv)")
    ap.add_argument("--allow-disk", action="store_true", help="allow non-tmpfs --tmpdir (SSD wear, not recommended)")
    ap.add_argument("--min-free", type=int, default=MIN_FREE_MB_DEFAULT, metavar="MB",
                    help="required free tmpfs MB (default: %(default)s)")
    ap.add_argument("--keep", action="store_true", help="keep tmpfs recording on exit")
    ap.add_argument("--show-recorder", action="store_true", help="also show the live recorder window (default: headless)")
    ap.add_argument("--record-only", action="store_true", help="record to tmpfs without launching the player")
    ap.add_argument("--direct", action="store_true", help="no DVR: plain mpv + yt-dlp (no rewind buffer)")
    ap.add_argument("--fullscreen", action="store_true", help="start player fullscreen")
    ap.add_argument("--mute", action="store_true", help="start player muted")
    ap.add_argument("--low-latency", action="store_true", help="recorder uses mpv --profile=low-latency")
    ap.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for recording to start (default: %(default)s)")
    ap.add_argument("--player-args", default="", help='extra player args, e.g. --player-args="--fullscreen --volume=80"')
    ap.add_argument("--recorder-args", default="", help="extra recorder args, same quoting")
    ap.add_argument("--print-cmds", action="store_true", help="print mpv commands without running them")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.speed < 0.1 or args.speed > 100:
        raise SystemExit("ERROR: --speed must be 0.1..100")
    if shutil.which("mpv") is None:
        raise SystemExit("ERROR: mpv not found in PATH")
    if shutil.which("yt-dlp") is None:
        raise SystemExit("ERROR: yt-dlp not found in PATH")

    info: dict
    tmpfs = pick_tmpfs(args.tmpdir, args.allow_disk)
    if not is_tmpfs(tmpfs) and not args.allow_disk:
        raise SystemExit(f"ERROR: {tmpfs} is not tmpfs. Aborting to avoid disk writes.")
    check_free(tmpfs, args.min_free)
    watch = secure_subdir(tmpfs, "watch-later")
    yt_cookie_flags, mpv_cookie_opt, staged_cookies = stage_cookies(args, tmpfs)
    raw_opts = ["no-cache-dir="] + ([mpv_cookie_opt] if mpv_cookie_opt else [])

    def _drop(path: str | None) -> None:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    info = run_yt_dlp_json(args.url, yt_cookie_flags)
    fmts = fmt_list(info)
    header = (f"Title: {info.get('title') or '?'} | uploader: {info.get('uploader') or '?'} | "
              f"live: {info.get('live_status') or info.get('is_live') or '?'}")
    print(header, file=sys.stderr)

    if args.list_formats:
        print_formats(fmts)
        _drop(staged_cookies)
        return 0

    choice = resolve_format(fmts, args.format, args.prefer_codec)
    print(f"Selected format: {choice}", file=sys.stderr)
    bufmode = resolve_buffer(args.buffer, need_player=not args.record_only)
    buf_flags = BUFFER_PRESETS[bufmode]
    if buf_flags:
        print(f"Buffer mode: {bufmode} ({' '.join(buf_flags)})", file=sys.stderr)
    else:
        print(f"Buffer mode: {bufmode} (mpv defaults)", file=sys.stderr)

    extra_player = shlex.split(args.player_args) if args.player_args else []
    extra_rec = shlex.split(args.recorder_args) if args.recorder_args else []
    std_flags = ["--no-save-position-on-quit", "--no-resume-playback"]

    if args.direct:
        cmd = ["mpv", f"--ytdl-format={choice}", f"--speed={args.speed}"]
        cmd += [f"--ytdl-raw-options={o}" for o in raw_opts]
        cmd += std_flags + buf_flags
        if args.fullscreen:
            cmd.append("--fullscreen")
        if args.mute:
            cmd.append("--mute=yes")
        if args.low_latency:
            cmd.append("--profile=low-latency")
        cmd += extra_player + ["--", args.url]
        print("+ " + " ".join(shlex.quote(c) for c in cmd), file=sys.stderr)
        if args.print_cmds:
            _drop(staged_cookies)
            return 0
        rc = subprocess.call(cmd)
        _drop(staged_cookies)
        return rc

    fd, rec_path = tempfile.mkstemp(prefix="mpv-live-", suffix=".ts", dir=tmpfs)
    os.close(fd)
    try:
        os.unlink(rec_path)  # mpv --stream-record creates it
    except OSError:
        pass
    print(f"Recording to tmpfs: {rec_path}", file=sys.stderr)

    env = dict(os.environ, TMPDIR=tmpfs, XDG_CACHE_HOME=os.path.join(tmpfs, "cache"))
    rec_cmd = ["mpv", f"--ytdl-format={choice}", f"--stream-record={rec_path}"]
    rec_cmd += [f"--ytdl-raw-options={o}" for o in raw_opts]
    rec_cmd += std_flags + [f"--watch-later-dir={watch}"]
    if args.low_latency:
        rec_cmd.append("--profile=low-latency")
    if not args.show_recorder:
        rec_cmd += ["--vo=null", "--ao=null"]
    rec_cmd += extra_rec + ["--", args.url]

    play_cmd = ["mpv", f"--speed={args.speed}"] + std_flags + [f"--watch-later-dir={watch}"] + buf_flags
    if args.fullscreen:
        play_cmd.append("--fullscreen")
    if args.mute:
        play_cmd.append("--mute=yes")
    play_cmd += extra_player + ["--", rec_path]

    print("+ " + " ".join(shlex.quote(c) for c in rec_cmd), file=sys.stderr)
    print("+ " + " ".join(shlex.quote(c) for c in play_cmd), file=sys.stderr)
    if args.print_cmds:
        _drop(staged_cookies)
        try:
            os.rmdir(watch)
        except OSError:
            pass
        return 0

    rec = subprocess.Popen(rec_cmd, env=env)
    try:
        if not wait_for_file(rec_path, rec, args.timeout):
            if rec.poll() is not None:
                print("ERROR: recorder exited before producing data.", file=sys.stderr)
                return 1
            print("WARNING: no data yet, continuing anyway...", file=sys.stderr)
        if args.record_only:
            print("Recording... Ctrl-C to stop.", file=sys.stderr)
            rec.wait()
            return 0 if (rec.returncode == 0) else 1
        print("Keys: } = 2x, ]/[ = speed, Backspace = reset, Left/Right = seek", file=sys.stderr)
        subprocess.call(play_cmd, env=env)
        return 0
    except KeyboardInterrupt:
        print("\nStopping...", file=sys.stderr)
        return 130
    finally:
        try:
            if rec.poll() is None:
                rec.terminate()
                try:
                    rec.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    rec.kill()
        except Exception:
            pass
        _drop(staged_cookies)
        if not args.keep:
            try:
                os.unlink(rec_path)
            except OSError:
                pass
        else:
            print(f"Kept (tmpfs): {rec_path}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
