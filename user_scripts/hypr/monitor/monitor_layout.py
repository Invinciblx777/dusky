#!/usr/bin/env python3
"""
===============================================================================
DUSKY DISPLAY LAYOUT DESIGNER: INTERACTIVE 2D SPATIAL CANVAS
===============================================================================
Interactive terminal-based 2D spatial canvas for multi-monitor placement in
Hyprland / Wayland. Features magnetic edge-snapping, aspect-ratio corrected
rendering, live compositor preview, and direct Lua AST persistence.
"""

import os
import sys
import math
import json
import curses
import shutil
import argparse
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Any

# Connect to Dusky TUI engine framework
_DUSKY_ROOT = Path.home() / "user_scripts" / "dusky_tui"
if str(_DUSKY_ROOT) not in sys.path:
    sys.path.insert(0, str(_DUSKY_ROOT))

try:
    from python.engines.monitor_engine import MonitorLuaEngine, closest_sharp
except ImportError:
    MonitorLuaEngine = None


@dataclass
class MonitorCanvasItem:
    output_id: int
    name: str
    description: str
    width: int
    height: int
    refresh_rate: float
    scale: float
    transform: int
    x: int
    y: int
    initial_x: int
    initial_y: int
    focused: bool
    disabled: bool
    current_mode: str

    @property
    def logical_width(self) -> int:
        eff_w = self.height if (self.transform % 2 == 1) else self.width
        s = self.scale if self.scale > 0 else 1.0
        return max(1, int(round(eff_w / s)))

    @property
    def logical_height(self) -> int:
        eff_h = self.width if (self.transform % 2 == 1) else self.height
        s = self.scale if self.scale > 0 else 1.0
        return max(1, int(round(eff_h / s)))


class MonitorLayoutCanvas:
    """Curses-driven visual spatial layout tool for Hyprland monitors."""

    SNAP_THRESHOLD = 40  # Magnetic pixel snap distance
    NORMAL_STEP = 20     # Step size for arrow keys
    LARGE_STEP = 120     # Step size for Shift+arrows (Hyprland 1/120 quantum)

    def __init__(self, config_path: str | None = None, live_preview_default: bool = False):
        self.config_path = config_path or self._detect_config_path()
        self.live_preview = live_preview_default
        self.monitors: list[MonitorCanvasItem] = []
        self.selected_idx = 0
        self.status_message = "Ready. Use arrows to move, [ / ] to snap, Enter to save."
        self.status_is_error = False
        self.has_unsaved_changes = False
        self.saved_successfully = False

        self._load_monitors()

    def _detect_config_path(self) -> str:
        candidates = [
            Path.home() / ".config" / "hypr" / "edit_here" / "source" / "monitors.lua",
            Path.home() / ".config" / "hypr" / "source" / "monitors.lua",
            Path.home() / "Documents" / "monitors.lua",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return str(candidates[0])

    def _load_monitors(self) -> None:
        """Queries live hardware status from Hyprland and matches with config."""
        try:
            res = subprocess.run(
                ["hyprctl", "-j", "monitors", "all"],
                capture_output=True,
                text=True,
                timeout=3,
                check=True
            )
            data = json.loads(res.stdout.strip())
        except Exception as e:
            data = []
            self.status_message = f"Failed to query hyprctl: {e}"
            self.status_is_error = True

        self.monitors = []
        for idx, m in enumerate(data):
            name = m.get("name", f"Unknown-{idx}")
            w = int(m.get("width", 1920))
            h = int(m.get("height", 1080))
            rr = float(m.get("refreshRate", 60.0))
            s = float(m.get("scale", 1.0))
            t = int(m.get("transform", 0))
            x = int(m.get("x", 0))
            y = int(m.get("y", 0))
            foc = bool(m.get("focused", False))
            dis = bool(m.get("disabled", False))
            desc = m.get("description", "")
            mode = f"{w}x{h}@{rr:.2f}"

            self.monitors.append(
                MonitorCanvasItem(
                    output_id=idx,
                    name=name,
                    description=desc,
                    width=w,
                    height=h,
                    refresh_rate=rr,
                    scale=s,
                    transform=t,
                    x=x,
                    y=y,
                    initial_x=x,
                    initial_y=y,
                    focused=foc,
                    disabled=dis,
                    current_mode=mode
                )
            )

        if not self.monitors:
            # Fallback mock for testing
            self.monitors = [
                MonitorCanvasItem(
                    output_id=0, name="eDP-1", description="Primary Display",
                    width=1920, height=1080, refresh_rate=60.0, scale=1.0,
                    transform=0, x=0, y=0, initial_x=0, initial_y=0,
                    focused=True, disabled=False, current_mode="1920x1080@60.00"
                )
            ]

    def _normalize_origin(self) -> None:
        """Shifts all displays so the top-left coordinate begins at 0, 0."""
        if not self.monitors:
            return
        active = [m for m in self.monitors if not m.disabled]
        if not active:
            return
        min_x = min(m.x for m in active)
        min_y = min(m.y for m in active)
        if min_x != 0 or min_y != 0:
            for m in active:
                m.x -= min_x
                m.y -= min_y
            self.has_unsaved_changes = True
            self.status_message = f"Normalized layout origin to (0, 0) [Shifted by {-min_x}, {-min_y}]."

    def _snap_selected(self, direction: str) -> None:
        """Magnetically snaps the selected monitor flush to its neighbor."""
        if len(self.monitors) < 2:
            self.status_message = "Only one monitor connected; snapping requires at least 2 displays."
            return

        cur = self.monitors[self.selected_idx]
        peers = [m for idx, m in enumerate(self.monitors) if idx != self.selected_idx and not m.disabled]
        if not peers:
            return

        # Pick nearest peer based on euclidean distance between centers
        cur_cx = cur.x + cur.logical_width / 2
        cur_cy = cur.y + cur.logical_height / 2

        def dist(p: MonitorCanvasItem) -> float:
            pcx = p.x + p.logical_width / 2
            pcy = p.y + p.logical_height / 2
            return math.hypot(cur_cx - pcx, cur_cy - pcy)

        peer = min(peers, key=dist)

        old_pos = (cur.x, cur.y)

        if direction == "left":
            cur.x = peer.x - cur.logical_width
            cur.y = peer.y + (peer.logical_height - cur.logical_height) // 2
            self.status_message = f"Snapped {cur.name} to the LEFT of {peer.name} (Centered)."
        elif direction == "right":
            cur.x = peer.x + peer.logical_width
            cur.y = peer.y + (peer.logical_height - cur.logical_height) // 2
            self.status_message = f"Snapped {cur.name} to the RIGHT of {peer.name} (Centered)."
        elif direction == "above":
            cur.y = peer.y - cur.logical_height
            cur.x = peer.x + (peer.logical_width - cur.logical_width) // 2
            self.status_message = f"Snapped {cur.name} ABOVE {peer.name} (Centered)."
        elif direction == "below":
            cur.y = peer.y + peer.logical_height
            cur.x = peer.x + (peer.logical_width - cur.logical_width) // 2
            self.status_message = f"Snapped {cur.name} BELOW {peer.name} (Centered)."
        elif direction == "center":
            # If side-by-side: vertical center. If stacked: horizontal center.
            if abs(cur_cx - (peer.x + peer.logical_width / 2)) >= abs(cur_cy - (peer.y + peer.logical_height / 2)):
                cur.y = peer.y + (peer.logical_height - cur.logical_height) // 2
                self.status_message = f"Aligned vertical center of {cur.name} with {peer.name}."
            else:
                cur.x = peer.x + (peer.logical_width - cur.logical_width) // 2
                self.status_message = f"Aligned horizontal center of {cur.name} with {peer.name}."
        elif direction == "top":
            cur.y = peer.y
            self.status_message = f"Aligned top edge of {cur.name} with {peer.name}."
        elif direction == "bottom":
            cur.y = peer.y + peer.logical_height - cur.logical_height
            self.status_message = f"Aligned bottom edge of {cur.name} with {peer.name}."

        if (cur.x, cur.y) != old_pos:
            self.has_unsaved_changes = True
            if self.live_preview:
                self._dispatch_live_preview()

    def _move_selected(self, dx: int, dy: int) -> None:
        """Moves the selected monitor and automatically magnetic-snaps near adjacent edges."""
        if not self.monitors:
            return
        cur = self.monitors[self.selected_idx]
        new_x = cur.x + dx
        new_y = cur.y + dy

        peers = [m for idx, m in enumerate(self.monitors) if idx != self.selected_idx and not m.disabled]

        # Magnetic snap checks against all peers
        for p in peers:
            # Snap flush right: cur.x close to p.x + p.logical_width
            if abs(new_x - (p.x + p.logical_width)) < self.SNAP_THRESHOLD:
                new_x = p.x + p.logical_width
            # Snap flush left: cur.x + cur.logical_width close to p.x
            elif abs((new_x + cur.logical_width) - p.x) < self.SNAP_THRESHOLD:
                new_x = p.x - cur.logical_width

            # Snap flush bottom: cur.y close to p.y + p.logical_height
            if abs(new_y - (p.y + p.logical_height)) < self.SNAP_THRESHOLD:
                new_y = p.y + p.logical_height
            # Snap flush top: cur.y + cur.logical_height close to p.y
            elif abs((new_y + cur.logical_height) - p.y) < self.SNAP_THRESHOLD:
                new_y = p.y - cur.logical_height

            # Align top edges
            if abs(new_y - p.y) < self.SNAP_THRESHOLD:
                new_y = p.y
            # Align bottom edges
            elif abs((new_y + cur.logical_height) - (p.y + p.logical_height)) < self.SNAP_THRESHOLD:
                new_y = p.y + p.logical_height - cur.logical_height

            # Align left edges
            if abs(new_x - p.x) < self.SNAP_THRESHOLD:
                new_x = p.x
            # Align right edges
            elif abs((new_x + cur.logical_width) - (p.x + p.logical_width)) < self.SNAP_THRESHOLD:
                new_x = p.x + p.logical_width - cur.logical_width

        cur.x = new_x
        cur.y = new_y
        self.has_unsaved_changes = True
        self.status_message = f"Moved {cur.name} to ({cur.x}, {cur.y})."

        if self.live_preview:
            self._dispatch_live_preview()

    def _dispatch_live_preview(self) -> None:
        """Applies monitor placements live via hyprctl keyword dispatch."""
        for m in self.monitors:
            if m.disabled:
                continue
            scale_str = f"{m.scale:.5f}".rstrip("0").rstrip(".") if m.scale % 1 != 0 else str(int(m.scale))
            arg = f"{m.name},{m.current_mode},{m.x}x{m.y},{scale_str},transform,{m.transform}"
            subprocess.run(["hyprctl", "keyword", "monitor", arg], capture_output=True, timeout=1)

    def _revert_live(self) -> None:
        """Restores monitors to their initial positions upon cancel."""
        for m in self.monitors:
            m.x = m.initial_x
            m.y = m.initial_y
        self._dispatch_live_preview()

    def save_and_apply(self) -> bool:
        """Writes coordinates permanently to monitors.lua and dispatches compositor reload."""
        self._normalize_origin()
        success = True

        if MonitorLuaEngine:
            try:
                engine = MonitorLuaEngine(self.config_path)
                engine.load_state()
                changes = []
                for m in self.monitors:
                    scope = f"monitor/{m.name}"
                    pos_str = f"{m.x}x{m.y}"
                    changes.append(("position", scope, pos_str, "string"))
                engine.write_batch(changes)
            except Exception as e:
                self.status_message = f"Failed to write Lua AST: {e}"
                self.status_is_error = True
                return False

        # Live dispatch
        self._dispatch_live_preview()
        subprocess.run(["hyprctl", "reload"], capture_output=True, timeout=2)

        self.has_unsaved_changes = False
        self.saved_successfully = True
        self.status_message = f"Saved {len(self.monitors)} monitors to {Path(self.config_path).name} and reloaded."
        return True

    def run(self, stdscr: curses.window) -> int:
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()

        # Initialize color pairs
        curses.init_pair(1, curses.COLOR_CYAN, -1)     # Selected highlight / header
        curses.init_pair(2, curses.COLOR_WHITE, -1)    # Inactive borders / normal text
        curses.init_pair(3, curses.COLOR_GREEN, -1)    # Success / focused
        curses.init_pair(4, curses.COLOR_YELLOW, -1)   # Warning / uncommitted
        curses.init_pair(5, curses.COLOR_RED, -1)      # Error
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_CYAN) # Inverted selected tag
        curses.init_pair(7, curses.COLOR_MAGENTA, -1)  # Accent dimensions

        stdscr.keypad(True)
        curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)

        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()

            if h < 16 or w < 60:
                stdscr.addstr(0, 0, "Terminal window too small (minimum 60x16 required).", curses.color_pair(5))
                stdscr.refresh()
                key = stdscr.getch()
                if key in (ord('q'), ord('Q'), 27):
                    break
                continue

            self._draw_header(stdscr, w)
            boxes = self._draw_canvas(stdscr, 3, 1, h - 9, w - 2)
            self._draw_status(stdscr, h - 5, w)
            self._draw_footer(stdscr, h - 3, w)
            stdscr.refresh()

            key = stdscr.getch()

            if key in (ord('q'), ord('Q'), 27):  # Quit / Esc
                if self.has_unsaved_changes and self.live_preview:
                    self._revert_live()
                return 0 if self.saved_successfully else 1

            elif key in (10, 13, ord('s'), ord('S')):  # Enter / s = Save
                if self.save_and_apply():
                    curses.napms(700)
                    return 0

            elif key in (9, ord('\t')):  # Tab = cycle monitors
                if self.monitors:
                    self.selected_idx = (self.selected_idx + 1) % len(self.monitors)

            elif key == curses.KEY_BTAB:  # Shift+Tab
                if self.monitors:
                    self.selected_idx = (self.selected_idx - 1) % len(self.monitors)

            elif ord('1') <= key <= ord('9'):  # Number jump
                idx = key - ord('1')
                if idx < len(self.monitors):
                    self.selected_idx = idx

            # Movement (fine step)
            elif key in (curses.KEY_LEFT, ord('h')):
                self._move_selected(-self.NORMAL_STEP, 0)
            elif key in (curses.KEY_RIGHT, ord('l')):
                self._move_selected(self.NORMAL_STEP, 0)
            elif key in (curses.KEY_UP, ord('k')):
                self._move_selected(0, -self.NORMAL_STEP)
            elif key in (curses.KEY_DOWN, ord('j')):
                self._move_selected(0, self.NORMAL_STEP)

            # Movement (large quantum step: Hyprland 120px)
            elif key in (curses.KEY_SLEFT, ord('H')):
                self._move_selected(-self.LARGE_STEP, 0)
            elif key in (curses.KEY_SRIGHT, ord('L')):
                self._move_selected(self.LARGE_STEP, 0)
            elif key in (curses.KEY_SR, ord('K')):
                self._move_selected(0, -self.LARGE_STEP)
            elif key in (curses.KEY_SF, ord('J')):
                self._move_selected(0, self.LARGE_STEP)

            # Magnetic Snap Hotkeys
            elif key == ord('['):
                self._snap_selected("left")
            elif key == ord(']'):
                self._snap_selected("right")
            elif key in (ord('{'), ord('(')):
                self._snap_selected("above")
            elif key in (ord('}'), ord(')')):
                self._snap_selected("below")
            elif key in (ord('c'), ord('C')):
                self._snap_selected("center")
            elif key in (ord('t'), ord('T')):
                self._snap_selected("top")
            elif key in (ord('b'), ord('B')):
                self._snap_selected("bottom")

            # Origin normalization
            elif key == ord('0'):
                self._normalize_origin()

            # Live preview toggle
            elif key in (ord('p'), ord('P')):
                self.live_preview = not self.live_preview
                if self.live_preview:
                    self.status_message = "Live preview ENABLED: Displays adjust on-the-fly."
                    self._dispatch_live_preview()
                else:
                    self.status_message = "Live preview DISABLED."

            # Reset
            elif key in (ord('r'), ord('R')):
                for m in self.monitors:
                    m.x = m.initial_x
                    m.y = m.initial_y
                if self.live_preview:
                    self._dispatch_live_preview()
                self.has_unsaved_changes = False
                self.status_message = "Reset layout to current live coordinates."

            # Mouse click selection
            elif key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                    for idx, (bx, by, bw, bh) in boxes.items():
                        if bx <= mx < bx + bw and by <= my < by + bh:
                            self.selected_idx = idx
                            break
                except Exception:
                    pass

        return 0

    def _draw_header(self, win: curses.window, width: int) -> None:
        title = " DUSKY DISPLAY LAYOUT DESIGNER "
        sep = "─" * (width - 2)
        win.addstr(0, 1, sep, curses.color_pair(1) | curses.A_DIM)
        win.addstr(0, max(2, (width - len(title)) // 2), title, curses.color_pair(1) | curses.A_BOLD)

        tabs_str = " Displays: "
        win.addstr(1, 1, tabs_str, curses.color_pair(2) | curses.A_DIM)
        cur_x = 1 + len(tabs_str)
        for idx, m in enumerate(self.monitors):
            label = f" [{idx + 1}] {m.name} "
            if idx == self.selected_idx:
                win.addstr(1, cur_x, label, curses.color_pair(6) | curses.A_BOLD)
            else:
                win.addstr(1, cur_x, label, curses.color_pair(2))
            cur_x += len(label) + 1

    def _draw_canvas(self, win: curses.window, top: int, left: int, height: int, width: int) -> dict[int, tuple[int, int, int, int]]:
        """
        Renders an aspect-ratio-corrected 2D viewport representing the desktop canvas.
        Returns a mapping of monitor index to screen bounding box (col, row, width, height) for mouse picking.
        """
        # Canvas frame
        for y in range(top, top + height):
            win.addch(y, left, "│", curses.color_pair(2) | curses.A_DIM)
            win.addch(y, left + width - 1, "│", curses.color_pair(2) | curses.A_DIM)
        win.addstr(top - 1, left, "┌" + "─" * (width - 2) + "┐", curses.color_pair(2) | curses.A_DIM)
        win.addstr(top + height, left, "└" + "─" * (width - 2) + "┘", curses.color_pair(2) | curses.A_DIM)

        if not self.monitors:
            return {}

        active = [m for m in self.monitors if not m.disabled]
        if not active:
            win.addstr(top + height // 2, left + max(2, (width - 22) // 2), "No active monitors.", curses.color_pair(4))
            return {}

        # 1. Virtual coordinate bounding box
        min_vx = min(m.x for m in active)
        max_vx = max(m.x + m.logical_width for m in active)
        min_vy = min(m.y for m in active)
        max_vy = max(m.y + m.logical_height for m in active)

        span_vx = max(1, max_vx - min_vx)
        span_vy = max(1, max_vy - min_vy)

        # Available drawing cells inside frame
        draw_w = width - 4
        draw_h = height - 2

        # Aspect correction: terminal cells are ~2x taller than they are wide.
        # So 1 visual unit = 1 row = 2 columns.
        char_aspect = 2.0

        scale_x = draw_w / span_vx
        scale_y = (draw_h * char_aspect) / span_vy
        uniform_scale = min(scale_x, scale_y) * 0.82  # 18% margin for movement headroom

        center_col = left + width // 2
        center_row = top + height // 2

        center_vx = (min_vx + max_vx) / 2.0
        center_vy = (min_vy + max_vy) / 2.0

        screen_boxes: dict[int, tuple[int, int, int, int]] = {}

        for idx, m in enumerate(self.monitors):
            if m.disabled:
                continue

            # Compute terminal box coordinates
            box_w = max(16, int(round(m.logical_width * uniform_scale)))
            box_h = max(5, int(round((m.logical_height * uniform_scale) / char_aspect)))

            # Relative offset from virtual center
            offset_vx = m.x - center_vx
            offset_vy = m.y - center_vy

            box_x = int(round(center_col + (offset_vx * uniform_scale)))
            box_y = int(round(center_row + ((offset_vy * uniform_scale) / char_aspect)))

            # Clamp within canvas window bounds
            box_x = max(left + 1, min(left + width - box_w - 1, box_x))
            box_y = max(top, min(top + height - box_h, box_y))

            screen_boxes[idx] = (box_x, box_y, box_w, box_h)
            is_sel = (idx == self.selected_idx)
            self._render_monitor_box(win, box_x, box_y, box_w, box_h, m, is_sel)

        return screen_boxes

    def _render_monitor_box(
        self,
        win: curses.window,
        x: int,
        y: int,
        w: int,
        h: int,
        m: MonitorCanvasItem,
        is_selected: bool
    ) -> None:
        """Renders an individual display box with borders and information."""
        color = curses.color_pair(1 if is_selected else 2)
        style = curses.A_BOLD if is_selected else curses.A_NORMAL

        # Box characters (Double line for selected, single line for inactive)
        tl, tr, bl, br, hl, vl = ("╔", "╗", "╚", "╝", "═", "║") if is_selected else ("┌", "┐", "└", "┘", "─", "│")

        # Top border
        try:
            win.addstr(y, x, tl + hl * (w - 2) + tr, color | style)
            # Side borders & interior
            for r in range(y + 1, y + h - 1):
                win.addstr(r, x, vl, color | style)
                win.addstr(r, x + 1, " " * (w - 2), curses.color_pair(2))
                win.addstr(r, x + w - 1, vl, color | style)
            # Bottom border
            win.addstr(y + h - 1, x, bl + hl * (w - 2) + br, color | style)
        except curses.error:
            pass

        # Text labels inside box
        try:
            # Header: Name
            name_str = f" {m.name} "
            if is_selected:
                win.addstr(y, x + max(1, (w - len(name_str)) // 2), name_str, curses.color_pair(6) | curses.A_BOLD)
            else:
                win.addstr(y, x + max(1, (w - len(name_str)) // 2), name_str, curses.color_pair(2) | curses.A_BOLD)

            # Line 1: Mode & scale
            line1 = f"{m.width}x{m.height} @{m.scale:g}x"
            if h >= 4 and len(line1) <= w - 2:
                win.addstr(y + 1, x + max(1, (w - len(line1)) // 2), line1, curses.color_pair(7 if is_selected else 2))

            # Line 2: Coordinates
            line2 = f"Pos: {m.x}, {m.y}"
            if h >= 5 and len(line2) <= w - 2:
                win.addstr(y + 2, x + max(1, (w - len(line2)) // 2), line2, curses.color_pair(1 if is_selected else 2) | curses.A_BOLD)

            # Line 3: Logical size
            if h >= 6:
                line3 = f"({m.logical_width}x{m.logical_height}L)"
                if len(line3) <= w - 2:
                    win.addstr(y + 3, x + max(1, (w - len(line3)) // 2), line3, curses.color_pair(2) | curses.A_DIM)

        except curses.error:
            pass

    def _draw_status(self, win: curses.window, top: int, width: int) -> None:
        """Renders the dynamic info and error notification bar."""
        color = curses.color_pair(5 if self.status_is_error else (4 if self.has_unsaved_changes else 3))
        prefix = " ● " if not self.has_unsaved_changes else " ✦ "
        msg = f"{prefix}{self.status_message}"
        try:
            win.addstr(top, 1, msg[:width - 2], color | curses.A_BOLD)
            cur = self.monitors[self.selected_idx] if self.monitors else None
            if cur:
                sub = f" Active: {cur.name} ({cur.width}x{cur.height}, {cur.refresh_rate:.1f}Hz) | Logical: {cur.logical_width}x{cur.logical_height} | Pos: {cur.x}x{cur.y} | Live Preview: {'[ON]' if self.live_preview else '[OFF]'} "
                win.addstr(top + 1, 1, sub[:width - 2], curses.color_pair(2) | curses.A_DIM)
        except curses.error:
            pass

    def _draw_footer(self, win: curses.window, top: int, width: int) -> None:
        """Renders the keyboard shortcuts legend."""
        sep = "─" * (width - 2)
        try:
            win.addstr(top, 1, sep, curses.color_pair(2) | curses.A_DIM)
            shortcuts_1 = " [Tab] Cycle  [Arrows/hjkl] Move  [Shift+Arrows] Quantum 120px  [0] Normalize Origin "
            shortcuts_2 = " [[] Snap Left  []] Snap Right  [{] Snap Above  [}] Snap Below  [C] Center  [Enter/S] Save & Apply  [Q] Exit "
            win.addstr(top + 1, 1, shortcuts_1[:width - 2], curses.color_pair(1))
            win.addstr(top + 2, 1, shortcuts_2[:width - 2], curses.color_pair(2))
        except curses.error:
            pass


def launch_in_floating_terminal(script_path: Path) -> int:
    """Spawns this visual layout designer inside a centered floating terminal window."""
    term = None
    for cand in ["kitty", "foot", "alacritty", "ghostty"]:
        if shutil.which(cand):
            term = cand
            break

    if not term:
        # Fallback to direct curses in current terminal
        return curses.wrapper(lambda scr: MonitorLayoutCanvas().run(scr))

    cmd = []
    if term == "kitty":
        cmd = [
            "hyprctl", "dispatch", "exec",
            f"[float; size 1050 680; center] kitty --class dusky-monitor-layout python3 {script_path}"
        ]
    elif term == "foot":
        cmd = [
            "hyprctl", "dispatch", "exec",
            f"[float; size 1050 680; center] foot -a dusky-monitor-layout python3 {script_path}"
        ]
    else:
        cmd = [
            "hyprctl", "dispatch", "exec",
            f"[float; size 1050 680; center] {term} -e python3 {script_path}"
        ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Dusky Display Layout Designer")
    parser.add_argument("--config", "-c", type=str, default=None, help="Path to monitors.lua")
    parser.add_argument("--live", "-l", action="store_true", help="Enable live compositor preview by default")
    parser.add_argument("--floating", "-f", action="store_true", help="Launch in a centered floating terminal window")
    args = parser.parse_args()

    if args.floating:
        return launch_in_floating_terminal(Path(__file__).resolve())

    canvas = MonitorLayoutCanvas(config_path=args.config, live_preview_default=args.live)
    return curses.wrapper(canvas.run)


if __name__ == "__main__":
    sys.exit(main())
