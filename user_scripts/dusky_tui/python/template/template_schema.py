#!/usr/bin/env python3
# =============================================================================
# DUSKY TUI — SCHEMA TEMPLATE
# =============================================================================
#
# WHAT THIS FILE IS
# -----------------
# This is the schema that drives the entire TUI. It tells the app:
#   1. Which Lua config file to read and write (TARGET_FILE)
#   2. What tabs to show in the UI (TABS)
#   3. What settings live on each tab, their type, and their defaults (SCHEMA)
#
# HOW IT MAPS TO YOUR LUA FILE
# ----------------------------
# Every ConfigItem has a `scope` and a `key`. These map DIRECTLY to the
# nested table path in your Lua config's hl.config({}) call.
#
# Example Lua file:
#
#   hl.config({
#       general = {
#           border_size = 2,          -- scope="general",         key="border_size"
#           gaps_in     = 5,          -- scope="general",         key="gaps_in"
#           col = {
#               active_border = "0xff89b4fa",  -- scope="general/col",  key="active_border"
#           },
#       },
#       decoration = {
#           rounding = 10,            -- scope="decoration",      key="rounding"
#       },
#   })
#
# The engine walks the Lua AST and uses scope/key to find the exact token to
# overwrite in-place — it does NOT regenerate the file from scratch, so all
# your comments and formatting are preserved.
#
# HOW TO LAUNCH THIS SCHEMA
# -------------------------
# From the dusky_tui/python directory, run:
#
#   python main/main.py ~/user_scripts/my_schema.py
#
# Or using dot-notation if placed in a SCHEMA_SEARCH_PATH:
#
#   python main/main.py my_module.my_schema
#
# HOW TO CREATE A NEW SCHEMA
# --------------------------
# 1. Copy this file.
# 2. Set TARGET_FILE to the absolute path of the Lua config you want to edit.
# 3. Set APP_TITLE to a meaningful name.
# 4. Edit TABS to list your section names.
# 5. Edit SCHEMA to map each tab index (0, 1, 2 ...) to a list of ConfigItems.
# 6. Set scope= and key= on each ConfigItem to match your Lua table paths.
# 7. Done. Run it.
#
# =============================================================================

from python.frontend.core_types import ConfigItem

# =============================================================================
# SECTION 1 — FILE TARGETS
# =============================================================================

# Path to the Lua config file this schema reads from and writes to.
# Tilde expansion is handled automatically by main.py.
TARGET_FILE = "~/.config/hypr/edit_here/source/monitors.lua"

# Optional: path to a matugen-generated JSON theme file.
# Set to None if you don't use matugen.
THEME_FILE = "~/.config/matugen/generated/dusky_tui.json"

# =============================================================================
# SECTION 2 — APP METADATA
# =============================================================================

APP_TITLE = "configure monitors"

# Controls the initial save mode of the TUI.
# Options: "auto" (saves on every change) | "batch" (requires Ctrl+S to commit)
DEFAULT_MODE = "auto"

# =============================================================================
# SECTION 3 — TABS
# =============================================================================
# A flat list of strings, one per tab. The list index (0, 1, 2 ...) is the
# tab's ID and must match the keys you use in SCHEMA below.
#
# Example: TABS = ["General", "Decoration", "Animations", "Keybinds"]
# =============================================================================

TABS = [
    "General",       # tab index 0
    "Decoration",    # tab index 1
    "Animations",    # tab index 2
    "Keybinds",      # tab index 3
]

# =============================================================================
# SECTION 4 — SCHEMA
# =============================================================================
# A dict mapping each tab index (int) to a list of ConfigItem objects.
# Items appear in the TUI in the order they are listed here.
#
# ConfigItem reference — every field explained:
#
#   label        (str)        Display name shown in the TUI list.
#
#   key          (str)        The Lua table key to read/write. Must match the
#                             key name exactly as it appears in your Lua file.
#
#   scope        (str)        The slash-separated path of nested Lua tables
#                             leading to this key, e.g. "general" or
#                             "general/col". Use "" (empty string) for keys
#                             sitting at the top level of hl.config({}).
#                             Default is "DEFAULT" — only use that if your Lua
#                             file actually has a table called DEFAULT.
#
#   type_        (str)        One of the following (choose exactly one):
#
#     "bool"     Toggle — true/false. Left/Right arrows flip it. No input box.
#
#     "int"      Integer — Enter key opens a text box. min_val/max_val/step
#                supported. Arrow keys nudge by step (unless options=[] is provided).
#
#     "float"    Float — same as int but fractional. Arrow keys nudge by step 
#                (unless options=[] is provided).
#
#     "string"   Free-form text — Enter opens a text box. No min/max.
#
#     "cycle"    Cycles through a fixed list of strings. Requires options=[].
#                Arrow keys step forward/back through the list.
#
#     "color"    Color value. Arrow keys cycle through named colors (or a custom 
#                options=[] list) while preserving your original format (0xAARRGGBB, 
#                #rrggbb, rgb(), rgba(), hsl(), oklch()). Enter opens a text box.
#
#     "picker"   Opens a pop-up list of options with optional hint text per
#                option. Requires options=[] and optionally hints=[].
#
#     "action"   A non-editable label that triggers a shell command when
#                selected. Set default= to the shell command string.
#
#   default      (Any)        The value the item resets to with `r` or `--default`.
#                             Use Python booleans (True/False), not strings.
#
#   options      (list[Any])  Required for "cycle" and "picker". Optional for "int",
#                             "float", "string", and "color". If provided on these
#                             types, the left/right arrow keys will cycle strictly
#                             through this predefined list instead of doing math or
#                             default cycling.
#
#   hints        (list[str])  Optional for "picker". One hint string per option,
#                             shown as a subtitle in the picker pop-up. Must be
#                             the same length as options if provided.
#
#   min_val      (float|None) Minimum value for "int" and "float". Ignored otherwise.
#   max_val      (float|None) Maximum value for "int" and "float". Ignored otherwise.
#   step         (float|None) Arrow-key step size for "int" and "float".
#
#   group        (str|None)   Optional visual group label. Items with the same
#                             group string are shown together under that heading.
#                             Has no effect on the Lua write logic.
#
#   extended_help (str|None)  Long-form description shown when you run:
#                               python main/main.py my_schema --export-docs
#                             Has no effect at runtime. Use ** for bold.
#
# =============================================================================

SCHEMA: dict[int, list[ConfigItem]] = {

    # -------------------------------------------------------------------------
    # TAB 0 — General
    # Maps to hl.config({ general = { ... } }) in your Lua file.
    # -------------------------------------------------------------------------
    0: [
        # --- BOOL EXAMPLE ---------------------------------------------------
        # Lua:  general = { no_focus_fallback = false }
        ConfigItem(
            label="No Focus Fallback",
            key="no_focus_fallback",
            scope="general",
            type_="bool",
            default=False,
            extended_help="If true, focus will not fall back to the desktop "
                          "when clicking on an empty area.",
        ),

        # --- INT EXAMPLE ----------------------------------------------------
        # Lua:  general = { border_size = 2 }
        ConfigItem(
            label="Border Size",
            key="border_size",
            scope="general",
            type_="int",
            default=2,
            min_val=0,
            max_val=20,
            step=1,
            extended_help="Width of window borders in pixels.",
        ),
        
        # --- PREDEFINED OPTIONS EXAMPLE (Overrides math logic) --------------
        ConfigItem(
            label="Locked Border Size",
            key="locked_border",
            scope="general",
            type_="int",
            default=2,
            options=[0, 2, 5, 8, 15], # Left/right arrows will cycle exactly these values
            extended_help="Cycles precisely between 0, 2, 5, 8, and 15.",
        ),

        # --- FLOAT EXAMPLE --------------------------------------------------
        # Lua:  general = { sensitivity = 1.0 }
        ConfigItem(
            label="Pointer Sensitivity",
            key="sensitivity",
            scope="general",
            type_="float",
            default=1.0,
            min_val=-1.0,
            max_val=1.0,
            step=0.1,
            extended_help="Mouse/touchpad sensitivity. 0 = unmodified.",
        ),

        # --- INT with GROUP -------------------------------------------------
        # Visually grouped under "Gaps" in the TUI.
        # Lua:  general = { gaps_in = 5, gaps_out = 10 }
        ConfigItem(
            label="Gaps In",
            key="gaps_in",
            scope="general",
            type_="int",
            default=5,
            min_val=0,
            max_val=100,
            step=1,
            group="Gaps",
        ),
        ConfigItem(
            label="Gaps Out",
            key="gaps_out",
            scope="general",
            type_="int",
            default=10,
            min_val=0,
            max_val=100,
            step=1,
            group="Gaps",
        ),

        # --- COLOR EXAMPLE --------------------------------------------------
        # Lua:  general = { col = { active_border = "0xff89b4fa" } }
        # NOTE: the scope is "general/col" — a slash-joined nested path.
        ConfigItem(
            label="Active Border Color",
            key="active_border",
            scope="general/col",
            type_="color",
            default="0xff89b4fa",
            extended_help="Color of the active window's border. Accepts "
                          "0xAARRGGBB, #rrggbb, rgb(), rgba(), hsl(), oklch().",
        ),
        ConfigItem(
            label="Inactive Border Color",
            key="inactive_border",
            scope="general/col",
            type_="color",
            default="0xff414453",
            options=["background", "error", "primary", "secondary"], # Constrains to theme values
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 1 — Decoration
    # Maps to hl.config({ decoration = { ... } }) in your Lua file.
    # -------------------------------------------------------------------------
    1: [
        # --- INT EXAMPLE ----------------------------------------------------
        ConfigItem(
            label="Rounding",
            key="rounding",
            scope="decoration",
            type_="int",
            default=10,
            min_val=0,
            max_val=50,
            step=1,
            extended_help="Corner rounding radius in pixels.",
        ),

        # --- FLOAT EXAMPLE --------------------------------------------------
        # Lua:  decoration = { active_opacity = 1.0 }
        ConfigItem(
            label="Active Opacity",
            key="active_opacity",
            scope="decoration",
            type_="float",
            default=1.0,
            min_val=0.0,
            max_val=1.0,
            step=0.05,
        ),
        ConfigItem(
            label="Inactive Opacity",
            key="inactive_opacity",
            scope="decoration",
            type_="float",
            default=0.9,
            min_val=0.0,
            max_val=1.0,
            step=0.05,
        ),

        # --- BOOL EXAMPLE ---------------------------------------------------
        ConfigItem(
            label="Drop Shadow",
            key="drop_shadow",
            scope="decoration",
            type_="bool",
            default=True,
        ),

        # --- INT in sub-table -----------------------------------------------
        # Lua:  decoration = { shadow = { range = 15 } }
        ConfigItem(
            label="Shadow Range",
            key="range",
            scope="decoration/shadow",
            type_="int",
            default=15,
            min_val=0,
            max_val=100,
            step=5,
            group="Shadow",
        ),
        ConfigItem(
            label="Shadow Render Power",
            key="render_power",
            scope="decoration/shadow",
            type_="int",
            default=3,
            min_val=1,
            max_val=4,
            step=1,
            group="Shadow",
        ),

        # --- FLOAT Blur sub-table -------------------------------------------
        # Lua:  decoration = { blur = { size = 8, passes = 2, new_optimizations = true } }
        ConfigItem(
            label="Blur Size",
            key="size",
            scope="decoration/blur",
            type_="int",
            default=8,
            min_val=1,
            max_val=30,
            step=1,
            group="Blur",
        ),
        ConfigItem(
            label="Blur Passes",
            key="passes",
            scope="decoration/blur",
            type_="int",
            default=2,
            min_val=1,
            max_val=10,
            step=1,
            group="Blur",
        ),
        ConfigItem(
            label="Blur New Optimizations",
            key="new_optimizations",
            scope="decoration/blur",
            type_="bool",
            default=True,
            group="Blur",
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 2 — Animations
    # -------------------------------------------------------------------------
    2: [
        # --- BOOL EXAMPLE ---------------------------------------------------
        ConfigItem(
            label="Enable Animations",
            key="enabled",
            scope="animations",
            type_="bool",
            default=True,
        ),

        # --- CYCLE EXAMPLE --------------------------------------------------
        # options= is required. Arrow keys cycle through them.
        # Lua:  animations = { first_launch_animation = "slide" }
        ConfigItem(
            label="First Launch Animation",
            key="first_launch_animation",
            scope="animations",
            type_="cycle",
            default="fade",
            options=["fade", "slide", "popin", "none"],
            extended_help="Animation played when a window first appears after "
                          "compositor startup.",
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 3 — Keybinds
    # -------------------------------------------------------------------------
    3: [
        # --- STRING EXAMPLE -------------------------------------------------
        # Lua:  hl.config({ binds = { scroll_event_delay = 300 } })
        # Use "string" when the value is an arbitrary identifier or path.
        ConfigItem(
            label="Scroll Event Delay",
            key="scroll_event_delay",
            scope="binds",
            type_="int",
            default=300,
            min_val=0,
            max_val=2000,
            step=50,
        ),

        # --- PICKER EXAMPLE -------------------------------------------------
        # options= is required. hints= is optional (one line per option).
        ConfigItem(
            label="Mouse Focus Mode",
            key="follow_mouse",
            scope="input",
            type_="picker",
            default="1",
            options=["0", "1", "2", "3"],
            hints=[
                "0 — Focus follows mouse (aggressive)",
                "1 — Focus follows mouse, no switch on click",
                "2 — Focus follows mouse, click moves cursor",
                "3 — Focus only on click",
            ],
            extended_help="Controls how the mouse interacts with window focus.",
        ),

        # --- ACTION EXAMPLE -------------------------------------------------
        # "action" items run a shell command when Enter is pressed.
        # The default= field holds the shell command to execute.
        # These items are excluded from --export-docs and --default resets.
        ConfigItem(
            label="Reload Hyprland Config",
            key="reload_action",          # key is arbitrary for actions
            scope="actions",              # scope is arbitrary for actions
            type_="action",
            default="hyprctl reload",
        ),
    ],
}


# =============================================================================
# QUICK-REFERENCE: ALL ConfigItem FIELDS IN ONE PLACE
# =============================================================================
#
# ConfigItem(
#     label         = "Human-readable name shown in the TUI",
#     key           = "lua_key_name",
#     scope         = "lua/table/path",   # "" for top-level, "/" separates nesting
#     type_         = "bool",             # bool | int | float | string | cycle |
#                                         # color | picker | action
#     default       = ...,               # Python value: True/False, int, float, str
#     options       = [],                # Overrides arrow-key behavior for int/color/etc.
#     hints         = [],                # Optional for picker (must match len(options))
#     min_val       = None,              # int/float lower bound
#     max_val       = None,              # int/float upper bound
#     step          = None,              # arrow-key step size for int/float
#     group         = None,              # Visual grouping label in the TUI
#     extended_help = None,              # Shown in --export-docs output
# )
#
# =============================================================================
