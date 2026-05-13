#!/usr/bin/env python3
# =============================================================================
# DUSKY TUI — APPEARANCE SCHEMA
# =============================================================================

from python.frontend.core_types import ConfigItem

# =============================================================================
# SECTION 1 — FILE TARGETS
# =============================================================================

# Adjust this path to the actual location of your appearance.lua
TARGET_FILE = "~/.config/hypr/source/appearance.lua"
THEME_FILE = "~/.config/matugen/colors.json"

# =============================================================================
# SECTION 2 — APP METADATA
# =============================================================================

APP_TITLE = "Hyprland Appearance"
DEFAULT_MODE = "auto"

# =============================================================================
# SECTION 3 — TABS
# =============================================================================

TABS = [
    "General",      # 0
    "Decoration",   # 1
    "Blur",         # 2
    "Shadow",       # 3
    "Misc & Render" # 4
]

# =============================================================================
# SECTION 4 — SCHEMA
# =============================================================================

SCHEMA: dict[int, list[ConfigItem]] = {

    # -------------------------------------------------------------------------
    # TAB 0 — General
    # -------------------------------------------------------------------------
    0: [
        ConfigItem(
            label="Layout Engine",
            key="layout",
            scope="general",
            type_="cycle",
            default="dwindle",
            options=["dwindle", "master", "scrolling", "monocle"],
            extended_help="Which layout to use for window management.",
        ),
        ConfigItem(
            label="Border Size",
            key="border_size",
            scope="general",
            type_="int",
            default=2,
            min_val=0,
            max_val=20,
            step=1,
            group="Borders",
        ),
        ConfigItem(
            label="Active Border",
            key="col.active_border",
            scope="general",
            type_="color",
            default="primary", # Uses the variable from your dofile
            group="Borders",
        ),
        ConfigItem(
            label="Inactive Border",
            key="col.inactive_border",
            scope="general",
            type_="color",
            default="inverse_on_surface",
            group="Borders",
        ),
        ConfigItem(
            label="Gaps In",
            key="gaps_in",
            scope="general",
            type_="int",
            default=6,
            min_val=0,
            max_val=64,
            step=1,
            group="Gaps",
        ),
        ConfigItem(
            label="Gaps Out",
            key="gaps_out",
            scope="general",
            type_="int",
            default=12,
            min_val=0,
            max_val=64,
            step=1,
            group="Gaps",
        ),
        ConfigItem(
            label="Resize on Border",
            key="resize_on_border",
            scope="general",
            type_="bool",
            default=False,
            extended_help="Enables resizing windows by clicking and dragging on borders.",
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 1 — Decoration
    # -------------------------------------------------------------------------
    1: [
        ConfigItem(
            label="Rounding",
            key="rounding",
            scope="decoration",
            type_="int",
            default=6,
            min_val=0,
            max_val=30,
            step=1,
        ),
        ConfigItem(
            label="Rounding Power",
            key="rounding_power",
            scope="decoration",
            type_="float",
            default=6.0,
            min_val=1.0,
            max_val=10.0,
            step=0.5,
            extended_help="2.0 is circle, 4.0 squircle.",
        ),
        ConfigItem(
            label="Active Opacity",
            key="active_opacity",
            scope="decoration",
            type_="float",
            default=1.0,
            min_val=0.0,
            max_val=1.0,
            step=0.05,
            group="Opacity",
        ),
        ConfigItem(
            label="Inactive Opacity",
            key="inactive_opacity",
            scope="decoration",
            type_="float",
            default=1.0,
            min_val=0.0,
            max_val=1.0,
            step=0.05,
            group="Opacity",
        ),
        ConfigItem(
            label="Dim Inactive",
            key="dim_inactive",
            scope="decoration",
            type_="bool",
            default=True,
            group="Dimming",
        ),
        ConfigItem(
            label="Dim Strength",
            key="dim_strength",
            scope="decoration",
            type_="float",
            default=0.2,
            min_val=0.0,
            max_val=1.0,
            step=0.05,
            group="Dimming",
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 2 — Blur
    # -------------------------------------------------------------------------
    2: [
        ConfigItem(
            label="Enable Blur",
            key="enabled",
            scope="decoration/blur",
            type_="bool",
            default=False,
        ),
        ConfigItem(
            label="Blur Size",
            key="size",
            scope="decoration/blur",
            type_="int",
            default=4,
            min_val=1,
            max_val=20,
            step=1,
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
        ),
        ConfigItem(
            label="New Optimizations",
            key="new_optimizations",
            scope="decoration/blur",
            type_="bool",
            default=True,
            extended_help="Massively improves performance.",
        ),
        ConfigItem(
            label="X-Ray",
            key="xray",
            scope="decoration/blur",
            type_="bool",
            default=False,
            extended_help="Floating windows ignore tiled windows in blur.",
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 3 — Shadow
    # -------------------------------------------------------------------------
    3: [
        ConfigItem(
            label="Enable Shadows",
            key="enabled",
            scope="decoration/shadow",
            type_="bool",
            default=False,
        ),
        ConfigItem(
            label="Shadow Range",
            key="range",
            scope="decoration/shadow",
            type_="int",
            default=35,
            min_val=0,
            max_val=100,
            step=5,
        ),
        ConfigItem(
            label="Render Power",
            key="render_power",
            scope="decoration/shadow",
            type_="int",
            default=2,
            min_val=1,
            max_val=4,
            step=1,
            extended_help="Falloff power (more power = faster falloff).",
        ),
        ConfigItem(
            label="Shadow Color",
            key="color",
            scope="decoration/shadow",
            type_="color",
            default="rgba(1a1a1aee)",
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 4 — Misc & Render
    # -------------------------------------------------------------------------
    4: [
        ConfigItem(
            label="Disable Logo",
            key="disable_hyprland_logo",
            scope="misc",
            type_="bool",
            default=True,
            group="Misc",
        ),
        ConfigItem(
            label="Background Color",
            key="background_color",
            scope="misc",
            type_="color",
            default="0x111111",
            group="Misc",
        ),
        ConfigItem(
            label="Direct Scanout",
            key="direct_scanout",
            scope="render",
            type_="picker",
            default="0",
            options=["0", "1", "2"],
            hints=["Off", "On", "Auto"],
            group="Rendering",
            extended_help="Attempt to reduce lag for single fullscreen apps.",
        ),
        ConfigItem(
            label="Color Management",
            key="cm_enabled",
            scope="render",
            type_="bool",
            default=True,
            group="Rendering",
        ),
    ],
}
