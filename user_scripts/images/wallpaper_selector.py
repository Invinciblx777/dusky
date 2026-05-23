#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# ARCH LINUX :: DUSKY THEME :: GTK3 WALLPAPER SELECTOR
# ==============================================================================
# Description: Native, lightning-fast GTK3 replacement for the Rofi wallpaper 
#              selector. Features lazy-loading, instant grid mapping, smart 
#              mtime caching, live search, and full keyboard navigation.
# ==============================================================================

import os
import sys
import re
import fcntl
import hashlib
import threading
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Gio

# --- CONSTANTS & PATHS ---
HOME = Path.home()
WALLPAPER_DIR = HOME / "Pictures/wallpapers"
SETTINGS_DIR = HOME / ".config/dusky/settings"
THEME_DIR = SETTINGS_DIR / "dusky_theme"
FAVORITES_FILE = THEME_DIR / "wal_fav_rofi"
STATE_FILE = THEME_DIR / "state.conf"
FAV_STATE_FILE = THEME_DIR / "current_fav"
TRACK_LIGHT = THEME_DIR / "light_wal"
TRACK_DARK = THEME_DIR / "dark_wal"
THEME_CTL = HOME / "user_scripts/theme_matugen/theme_ctl.sh"

CACHE_DIR = HOME / ".cache/rofi-wallpaper-thumbs/v4-300"
THUMB_DIR = CACHE_DIR / "thumbs"
LOCK_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "gtk-wallpaper-selector.lock"
GTK_CSS_PATH = HOME / ".config/gtk-3.0/gtk.css"

# Optimised image parameters for compact view & dynamic shrinkability
THUMB_SIZE = 240
RENDER_SIZE = 145
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

# Pre-compile regex for ultra-fast sorting operations
_NATURAL_SORT_RE = re.compile(r'(\d+)')

def natural_keys(text: str) -> list:
    """Algorithms for natural/version sorting (matches bash 'sort -V')."""
    return [int(c) if c.isdigit() else c.lower() for c in _NATURAL_SORT_RE.split(text)]

class WallpaperApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='com.dusky.wallpaperselector',
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None
        self.flowbox = None
        self.search_entry = None
        self.stack = None
        
        self.wallpapers = []
        self.favorites = set()
        self.show_only_favorites = False
        self.search_query = ""
        
        self.ui_children = {}
        self.loaded_pixbufs = {}
        self.current_generation = 0
        self.current_selected_child = None
        
        # Concurrency constraints: High enough for speed, low enough to preserve desktop fluidity
        workers = min(os.cpu_count() or 4, 8)
        self.executor = ThreadPoolExecutor(max_workers=workers)

        self.lock_fd = None
        self._acquire_lock()
        self._load_favorites()

    def _acquire_lock(self):
        try:
            LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.lock_fd = open(LOCK_FILE, 'w')
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another instance is already running. Exiting.")
            sys.exit(0)

    def _load_favorites(self):
        self.favorites.clear()
        if FAVORITES_FILE.exists():
            try:
                content = FAVORITES_FILE.read_text(encoding='utf-8')
                self.favorites.update(filter(None, content.splitlines()))
            except Exception as e:
                print(f"Error loading favorites: {e}")

    def _save_favorites(self):
        FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(FAVORITES_FILE, 'w') as f:
                for fav in sorted(list(self.favorites)):
                    f.write(f"{fav}\n")
        except Exception as e:
            print(f"Error saving favorites: {e}")

    def do_activate(self):
        if not self.window:
            self.window = Gtk.ApplicationWindow(application=self)
            self.window.set_title("Wallpaper Selector")
            self.window.set_default_size(800, 600)
            self.window.set_position(Gtk.WindowPosition.CENTER)
            
            # Connect absolute kill-switch to prevent any background zombie processes
            self.window.connect("destroy", self.on_window_destroy)
            self.window.connect("key-press-event", self.on_key_press)

            self.setup_css()

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.window.add(vbox)

            # --- HEADER / ACTION BAR ---
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
            header.set_name("header_bar")
            
            # Left: Search
            self.search_entry = Gtk.SearchEntry()
            self.search_entry.set_placeholder_text("Search... (Press /)")
            # Slim design to prevent blocking horizontal window shrinking
            self.search_entry.set_width_chars(12) 
            self.search_entry.get_style_context().add_class("search-bar")
            self.search_entry.connect("search-changed", self.on_search_changed)
            header.pack_start(self.search_entry, False, False, 0)
            
            # Center: Spacer to push buttons right dynamically
            spacer = Gtk.Box()
            header.pack_start(spacer, True, True, 0)

            # Right: Action Buttons (Shortened labels to reduce width limits)
            action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            
            btn_fast = Gtk.Button(label="Fast Apply [Alt+H]")
            btn_fast.connect("clicked", lambda w: self.trigger_action('fast'))
            
            btn_fav = Gtk.Button(label="Fav [Alt+U]")
            btn_fav.connect("clicked", lambda w: self.trigger_action('fav'))
            
            btn_toggle = Gtk.Button(label="Toggle [Alt+T]")
            btn_toggle.connect("clicked", lambda w: self.trigger_action('toggle'))

            for btn in (btn_fast, btn_fav, btn_toggle):
                btn.get_style_context().add_class("action-btn")
                action_box.pack_start(btn, False, False, 0)

            header.pack_start(action_box, False, False, 0)
            vbox.pack_start(header, False, False, 0)

            # --- SHORTCUT HELPER RIBBON (Aesthetic & Informative) ---
            shortcuts_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            shortcuts_box.set_name("shortcuts_bar")
            
            shortcuts_data = [
                ("Enter", "Apply & Theme"),
                ("Alt+H", "Fast Apply"),
                ("Alt+U", "Favorite"),
                ("Alt+T", "Toggle Favs"),
                ("Alt+Y", "Rebuild Cache"),
                ("Esc", "Reset"),
                ("Q", "Quit")
            ]
            
            markup_parts = []
            for key, desc in shortcuts_data:
                markup_parts.append(
                    f"<span background='#313244' foreground='#cdd6f4' font_family='monospace' size='7500'><b> {key} </b></span> "
                    f"<span size='7800' foreground='#a6adc8'>{desc}</span>"
                )
            
            shortcuts_label = Gtk.Label()
            shortcuts_label.set_use_markup(True)
            shortcuts_label.set_markup("  •  ".join(markup_parts))
            shortcuts_label.set_halign(Gtk.Align.CENTER)
            
            shortcuts_box.pack_start(shortcuts_label, True, True, 0)
            vbox.pack_start(shortcuts_box, False, False, 0)

            # --- STACK CONTAINER (Handles Empty State transitions natively) ---
            self.stack = Gtk.Stack()
            self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.stack.set_transition_duration(150)

            # --- SCROLLED GRID (Inside Stack) ---
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

            # FlowBox with built-in sorting and ultra-fast filtering
            self.flowbox = Gtk.FlowBox()
            self.flowbox.set_valign(Gtk.Align.START)
            self.flowbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
            
            # Allow the grid to explicitly shrink down to minimum 3 children
            self.flowbox.set_min_children_per_line(3) 
            self.flowbox.set_max_children_per_line(30)
            
            self.flowbox.set_sort_func(self.sort_flowbox)
            self.flowbox.set_filter_func(self.filter_flowbox)
            self.flowbox.connect("child-activated", self.on_child_activated)
            self.flowbox.connect("selected-children-changed", self.on_selection_changed)
            
            scrolled.add(self.flowbox)

            # Add states to Stack
            self.stack.add_named(scrolled, "grid")
            self.stack.add_named(self._create_empty_state_placeholder(), "empty")
            
            vbox.pack_start(self.stack, True, True, 0)

            self.window.show_all()
            
            # Kickoff the lazy loading system
            self.refresh_ui()

        self.window.present()
        self.flowbox.grab_focus()

    def on_window_destroy(self, widget):
        """Absolute kill-switch: Cleans threads and locks immediately upon window close."""
        print("Shutting down... killing background workers.")
        # Cancel any pending futures in Python 3.9+ to prevent thread hanging
        self.executor.shutdown(wait=False, cancel_futures=True)
        if self.lock_fd:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                self.lock_fd.close()
                LOCK_FILE.unlink(missing_ok=True)
            except Exception:
                pass

    def _create_empty_state_placeholder(self) -> Gtk.Box:
        """Constructs an aesthetic GTK view that displays when there are no matches."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        
        icon = Gtk.Image.new_from_icon_name("edit-find-symbolic", Gtk.IconSize.DIALOG)
        icon.set_pixel_size(72)
        icon.get_style_context().add_class("placeholder-icon")
        
        title = Gtk.Label(label="No Wallpapers Found")
        title.get_style_context().add_class("placeholder-title")
        
        subtitle = Gtk.Label(label="Try adjusting your search criteria or toggling your favorites view.")
        subtitle.get_style_context().add_class("placeholder-subtitle")
        
        box.pack_start(icon, False, False, 0)
        box.pack_start(title, False, False, 0)
        box.pack_start(subtitle, False, False, 0)
        box.show_all()
        return box

    # --- UI & LOGIC ---

    def setup_css(self):
        """Injects custom UI polish on top of system styles."""
        css_provider = Gtk.CssProvider()
        
        custom_css = """
        window { background-color: @window_bg_color; }
        #header_bar {
            background-color: shade(@window_bg_color, 0.97);
            padding: 10px 14px;
            border-bottom: 1px solid alpha(@window_fg_color, 0.1);
        }
        #shortcuts_bar {
            background-color: shade(@window_bg_color, 0.94);
            padding: 6px 12px;
            border-bottom: 1px solid alpha(@window_fg_color, 0.08);
        }
        .search-bar {
            border-radius: 8px;
            padding: 6px 10px;
            font-size: 0.95em;
        }
        .action-btn {
            padding: 5px 12px;
            border-radius: 8px;
            font-weight: bold;
            font-size: 0.9em;
            background-color: alpha(@window_fg_color, 0.04);
            border: 1px solid alpha(@window_fg_color, 0.08);
            transition: all 0.2s ease;
        }
        .action-btn:hover {
            background-color: alpha(@accent_color, 0.15);
            border-color: @accent_color;
        }
        flowbox {
            background-color: @view_bg_color;
            padding: 10px;
        }
        flowboxchild {
            border-radius: 10px;
            padding: 4px;
            margin: 4px;
            background-color: transparent;
            transition: all 0.2s ease;
        }
        flowboxchild:selected {
            background-color: @accent_bg_color;
            outline: 2px solid @accent_color;
        }
        flowboxchild:hover {
            background-color: alpha(@accent_color, 0.1);
        }
        .placeholder-box {
            background-color: alpha(@window_fg_color, 0.05);
            border-radius: 8px;
        }
        .wallpaper-name-overlay {
            background-color: alpha(@window_bg_color, 0.85);
            color: @window_fg_color;
            border-radius: 4px;
            padding: 3px 6px;
            font-size: 0.75em;
            font-weight: bold;
            box-shadow: 0px 2px 4px rgba(0, 0, 0, 0.3);
        }
        
        /* Empty State Custom Styles */
        .placeholder-icon {
            color: alpha(@window_fg_color, 0.4);
            margin-bottom: 10px;
        }
        .placeholder-title {
            font-size: 1.5em;
            font-weight: 800;
            color: alpha(@window_fg_color, 0.8);
            margin-bottom: 4px;
        }
        .placeholder-subtitle {
            font-size: 1.0em;
            color: alpha(@window_fg_color, 0.5);
        }
        """

        final_css = ""
        if GTK_CSS_PATH.exists():
            try:
                final_css += GTK_CSS_PATH.read_text(encoding='utf-8') + "\n"
            except Exception as e:
                print(f"Warning: Could not read {GTK_CSS_PATH}: {e}")

        final_css += custom_css

        try:
            css_provider.load_from_data(final_css.encode('utf-8'))
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), 
                css_provider, 
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception as e:
            print(f"CSS Error: {e}")

    def sort_flowbox(self, child1, child2):
        key1 = natural_keys(getattr(child1, 'rel_path', ''))
        key2 = natural_keys(getattr(child2, 'rel_path', ''))
        return -1 if key1 < key2 else (1 if key1 > key2 else 0)

    def filter_flowbox(self, child) -> bool:
        """Native GTK fast-filtering for Search and Favorites toggle."""
        rel_path = getattr(child, 'rel_path', '')
        
        if self.show_only_favorites and rel_path not in self.favorites:
            return False
            
        if self.search_query and self.search_query not in rel_path.lower():
            return False
            
        return True

    def _update_visibility_and_selection(self):
        """Intelligently switch stack states and select the top match."""
        first_visible = None
        has_visible = False
        
        for child in self.flowbox.get_children():
            if self.filter_flowbox(child):
                has_visible = True
                first_visible = child
                break
                
        if has_visible:
            self.stack.set_visible_child_name("grid")
            if first_visible:
                self.flowbox.select_child(first_visible)
        else:
            self.stack.set_visible_child_name("empty")
            
        return False

    def on_search_changed(self, widget):
        self.search_query = self.search_entry.get_text().lower()
        self.flowbox.invalidate_filter()
        GLib.idle_add(self._update_visibility_and_selection)

    def on_selection_changed(self, flowbox):
        """Instantly show the wallpaper's name on the selected child, hide from others."""
        selected = flowbox.get_selected_children()
        
        # Hide the label on the previously selected child
        if getattr(self, 'current_selected_child', None):
            if hasattr(self.current_selected_child, 'name_label'):
                self.current_selected_child.name_label.hide()
                
        if selected:
            # Show the label on the newly selected child
            self.current_selected_child = selected[0]
            if hasattr(self.current_selected_child, 'name_label'):
                self.current_selected_child.name_label.show()
        else:
            self.current_selected_child = None

    def refresh_ui(self):
        """Discovers ALL wallpapers, establishes instant placeholders, and offloads rendering."""
        self.current_generation += 1
        
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)
        self.ui_children.clear()

        self.wallpapers.clear()
        if WALLPAPER_DIR.exists():
            for root, dirs, files in os.walk(WALLPAPER_DIR, followlinks=True):
                for f in files:
                    path = Path(root) / f
                    if path.suffix.lower() in IMAGE_EXTENSIONS:
                        rel_path = str(path.relative_to(WALLPAPER_DIR))
                        self.wallpapers.append(rel_path)
        
        self.wallpapers.sort(key=natural_keys)

        for rel_path in self.wallpapers:
            child = Gtk.FlowBoxChild()
            child.rel_path = rel_path
            
            box = Gtk.Box()
            box.set_size_request(RENDER_SIZE, RENDER_SIZE)
            box.get_style_context().add_class("placeholder-box")
            
            spinner = Gtk.Spinner()
            spinner.start()
            spinner.set_halign(Gtk.Align.CENTER)
            spinner.set_valign(Gtk.Align.CENTER)
            box.pack_start(spinner, True, True, 0)
            
            child.add(box)
            self.flowbox.add(child)
            self.ui_children[rel_path] = child

        self.window.show_all()
        
        # Immediately apply filters and update empty state
        self.flowbox.invalidate_filter()
        self._update_visibility_and_selection()

        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        for rel_path in self.wallpapers:
            self.executor.submit(self._process_single_image, rel_path, self.current_generation)

    # --- IMAGE PIPELINE ---

    def get_thumb_path(self, rel_path: str) -> Path:
        digest = hashlib.sha256(rel_path.encode('utf-8')).hexdigest()
        return THUMB_DIR / f"{digest}.png"

    def _process_single_image(self, rel_path: str, generation: int):
        if generation != self.current_generation:
            return

        full_path = WALLPAPER_DIR / rel_path
        thumb_path = self.get_thumb_path(rel_path)

        try:
            needs_gen = not thumb_path.exists() or thumb_path.stat().st_mtime < full_path.stat().st_mtime
            
            if needs_gen:
                subprocess.run([
                    "nice", "-n", "19", "magick", "-limit", "thread", "1",
                    str(full_path), "-auto-orient", "-strip", 
                    "-thumbnail", f"{THUMB_SIZE}x{THUMB_SIZE}^", 
                    "-gravity", "center", "-extent", f"{THUMB_SIZE}x{THUMB_SIZE}", 
                    str(thumb_path)
                ], check=True, stderr=subprocess.DEVNULL)

            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(thumb_path), RENDER_SIZE, RENDER_SIZE, True)
            self.loaded_pixbufs[rel_path] = pixbuf
            
            GLib.idle_add(self._update_ui_child, rel_path, pixbuf, generation)
        except Exception as e:
            print(f"Failed loading {rel_path}: {e}")

    def _update_ui_child(self, rel_path: str, pixbuf: GdkPixbuf.Pixbuf, generation: int = -1):
        if generation != -1 and generation != self.current_generation:
            return False

        child = self.ui_children.get(rel_path)
        if not child: return False

        for c in child.get_children():
            child.remove(c)

        if not pixbuf: return False

        image = Gtk.Image.new_from_pixbuf(pixbuf)
        overlay = Gtk.Overlay()
        overlay.add(image)

        # Favorite Heart Tracker
        if rel_path in self.favorites:
            heart = Gtk.Label(label="<span color='#f38ba8' size='large'>♥</span>")
            heart.set_use_markup(True)
            heart.set_halign(Gtk.Align.END)
            heart.set_valign(Gtk.Align.START)
            heart.set_margin_top(6)
            heart.set_margin_end(6)
            overlay.add_overlay(heart)

        # Base Name Overlay (Initially Hidden)
        name_label = Gtk.Label(label=os.path.basename(rel_path))
        name_label.get_style_context().add_class("wallpaper-name-overlay")
        name_label.set_halign(Gtk.Align.END)
        name_label.set_valign(Gtk.Align.END)
        name_label.set_margin_bottom(6)
        name_label.set_margin_end(6)
        name_label.set_no_show_all(True) # Prevent showing up universally
        
        # Keep a reference injected to manipulate easily on focus
        child.name_label = name_label
        overlay.add_overlay(name_label)

        overlay.show_all()
        child.add(overlay)
        
        # Verify if it should immediately be visible after load
        if getattr(self, 'current_selected_child', None) == child:
            name_label.show()

        return False

    # --- INTERACTION & BINDS ---

    def get_selected_path(self):
        selected = self.flowbox.get_selected_children()
        return getattr(selected[0], 'rel_path', None) if selected else None

    def trigger_action(self, action_type: str):
        """Routing multiplexer for button clicks."""
        path = self.get_selected_path()
        match action_type:
            case 'fast':
                if path: self.apply_wallpaper(path, regen=False)
            case 'fav':
                if path: self.toggle_favorite(path)
            case 'toggle':
                self.show_only_favorites = not self.show_only_favorites
                self.flowbox.invalidate_filter()
                GLib.idle_add(self._update_visibility_and_selection)

    def on_child_activated(self, flowbox, child):
        # A click automatically selects AND triggers applying.
        self.apply_wallpaper(getattr(child, 'rel_path', None), regen=True)

    def on_key_press(self, widget, event):
        keyval = event.keyval
        state = event.state

        is_alt = (state & Gdk.ModifierType.MOD1_MASK) != 0
        is_ctrl = (state & Gdk.ModifierType.CONTROL_MASK) != 0
        
        # Quit Conditions
        if keyval == Gdk.KEY_q and not is_alt and not is_ctrl and not self.search_entry.is_focus():
            self.window.close()
            return True
        if keyval in (Gdk.KEY_c, Gdk.KEY_C) and is_ctrl:
            self.window.close()
            return True

        # Focus trap logic for Search Bar
        if self.search_entry.is_focus():
            if keyval == Gdk.KEY_Escape:
                self.search_entry.set_text("") # Clear search strictly on escape
                self.window.set_focus(None)
                self.flowbox.grab_focus()
                return True
            return False

        # Keybinds avoiding full match-case due to specific combo dependencies
        if keyval == Gdk.KEY_slash and not is_alt and not is_ctrl:
            self.search_entry.grab_focus()
            return True
            
        if keyval in (Gdk.KEY_f, Gdk.KEY_F) and is_ctrl:
            self.search_entry.grab_focus()
            return True
            
        if keyval == Gdk.KEY_Escape:
            self.search_entry.set_text("")
            self.flowbox.invalidate_filter()
            self.window.set_focus(None)
            self.flowbox.grab_focus()
            return True

        if keyval in (Gdk.KEY_t, Gdk.KEY_T) and is_ctrl:
            self.show_only_favorites = not self.show_only_favorites
            self.flowbox.invalidate_filter()
            GLib.idle_add(self._update_visibility_and_selection)
            return True

        rel_path = self.get_selected_path()

        # Modern Python 3.10+ Pattern Matching for action keybinds
        match keyval:
            case Gdk.KEY_Return | Gdk.KEY_KP_Enter:
                if rel_path: self.apply_wallpaper(rel_path, regen=True)
                return True
            
            case Gdk.KEY_h if is_alt:
                if rel_path: self.apply_wallpaper(rel_path, regen=False)
                return True
            
            case Gdk.KEY_u if is_alt:
                if rel_path: self.toggle_favorite(rel_path)
                return True
            
            case Gdk.KEY_t if is_alt:
                self.show_only_favorites = not self.show_only_favorites
                self.flowbox.invalidate_filter()
                GLib.idle_add(self._update_visibility_and_selection)
                return True
            
            case Gdk.KEY_y if is_alt:
                print("Cache rebuild requested. Deleting thumb cache and refreshing...")
                for f in THUMB_DIR.glob("*.png"): f.unlink()
                self.refresh_ui()
                return True

        return False

    def toggle_favorite(self, rel_path: str):
        if rel_path in self.favorites:
            self.favorites.remove(rel_path)
        else:
            self.favorites.add(rel_path)
            
        self._save_favorites()
        
        # In-place UI update for the heart icon
        if rel_path in self.loaded_pixbufs:
            self._update_ui_child(rel_path, self.loaded_pixbufs[rel_path], self.current_generation)
            
        # Instantly cull from view if we are strictly filtering for favorites
        if self.show_only_favorites:
            self.flowbox.invalidate_filter()
            GLib.idle_add(self._update_visibility_and_selection)

    # --- BACKEND EXECUTION ---

    def parse_state_conf(self) -> dict:
        state = {}
        if STATE_FILE.exists():
            with open(STATE_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        state[k.strip()] = v.strip().strip("'").strip('"')
        return state

    def update_trackers(self, rel_path: str, theme_mode: str):
        basename = os.path.basename(rel_path)
        track_file = TRACK_LIGHT if theme_mode == "light" else TRACK_DARK
        
        THEME_DIR.mkdir(parents=True, exist_ok=True)
        with open(track_file, 'w') as f: f.write(f"{basename}\n")
        with open(FAV_STATE_FILE, 'w') as f: f.write(f"{basename}\n")

    def apply_wallpaper(self, rel_path: str, regen: bool):
        if not rel_path: return
        full_path = WALLPAPER_DIR / rel_path
        
        if not full_path.exists():
            print(f"Error: Path {full_path} does not exist.")
            return

        print(f"Applying: {full_path} (Regen: {regen})")
        
        state = self.parse_state_conf()
        theme_mode = state.get('THEME_MODE', 'dark')
        self.update_trackers(rel_path, theme_mode)

        awww_cmd = ["uwsm-app", "--", "awww", "img"]
        
        def add_opt(key, flag):
            val = state.get(key, 'disable')
            if val and val != 'disable':
                awww_cmd.extend([flag, val])

        add_opt('AWWW_TRANS_TYPE', '--transition-type')
        add_opt('AWWW_TRANS_DURATION', '--transition-duration')
        add_opt('AWWW_TRANS_FPS', '--transition-fps')
        add_opt('AWWW_TRANS_BEZIER', '--transition-bezier')
        add_opt('AWWW_TRANS_ANGLE', '--transition-angle')
        add_opt('AWWW_TRANS_POS', '--transition-pos')
        awww_cmd.append(str(full_path))

        def _exec_backend():
            try:
                subprocess.run(awww_cmd, check=True)
                if regen:
                    subprocess.run([str(THEME_CTL), "refresh"], check=True)
            except subprocess.CalledProcessError as e:
                print(f"Backend execution failed: {e}")

        # The daemon thread runs the process completely detached from GTK UI logic
        threading.Thread(target=_exec_backend, daemon=True).start()


if __name__ == "__main__":
    app = WallpaperApp()
    exit_status = app.run(sys.argv)
    sys.exit(exit_status)
