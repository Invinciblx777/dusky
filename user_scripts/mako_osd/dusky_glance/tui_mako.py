#!/usr/bin/env python3
"""
===============================================================================
DUSKY TUI: MAKO GLANCE CONFIGURATION SCHEMA
Target: ~/.config/mako/config
Paradigm: INI Configuration Engine
===============================================================================
"""

from python.frontend.core_types import ConfigItem

# =============================================================================
# CORE APPLICATION ROUTING
# =============================================================================
ENGINE_TYPE = "ini"                        
TARGET_FILE = "~/.config/mako/config"      
APP_TITLE = "Dusky Glance Config"                 

# =============================================================================
# UI & ENVIRONMENT BEHAVIOR
# =============================================================================
DEFAULT_MODE = "auto"                      
THEME_FILE = "~/.config/matugen/generated/dusky_tui.json" 

ENABLE_USER_PRESETS = True                 
USER_PRESETS_TAB = "Profiles"              

# =============================================================================
# TABS DEFINITION
# =============================================================================
TABS = [
    "Narrow",
    "Wide",
    "Timer",
    "Profiles"
]

# =============================================================================
# SHARED RESOURCES & CONSTRUCTORS
# =============================================================================

COLOR_PALETTE = [
    "__DELETE__",  # Triggers fallback to Matugen global variables
    "#00000000",   # Transparent
    "#000000",     # Black
    "#FFFFFF",     # White
    "#FF3333",     # Red
    "#33FF33",     # Green
    "#3333FF",     # Blue
    "#FFFF33",     # Yellow
    "#33FFFF",     # Cyan
    "#FF33FF",     # Magenta
    "#9933FF",     # Purple
    "#FF9933"      # Orange
]

def build_glance(scope_name: str, def_width: int, def_height: int, def_bg: str = "__DELETE__") -> list:
    """
    Dynamically constructs a strictly organized, folder-driven configuration 
    tab isolated purely to visual and spatial properties for a specific Glance module.
    """
    return [
        # --- POSITIONING ---
        ConfigItem(
            label="Anchor",
            key="anchor",
            scope=scope_name,
            type_="cycle",
            default="bottom-right",
            options=["top-right", "top-center", "top-left", "bottom-right", "bottom-center", "bottom-left", "center"],
            group="Position",
            extended_help="**Screen Placement**\n\nDetermines which corner or edge the glance module snaps to."
        ),
        ConfigItem(
            label="Layer",
            key="layer",
            scope=scope_name,
            type_="cycle",
            default="overlay",
            options=["background", "bottom", "top", "overlay"],
            group="Position",
            extended_help="**Wayland Layer Shell**\n\nDefines Z-axis stacking. `overlay` punches through fullscreen apps."
        ),
        ConfigItem(
            label="Margin",
            key="margin",
            scope=scope_name,
            type_="string",
            default="0,20,20,0",
            group="Position",
            extended_help="**Outer Spacing**\n\nCSS-style margins: Top, Right, Bottom, Left."
        ),

        # --- GEOMETRY (HYBRID FOLDER) ---
        ConfigItem(
            label="Dimensions",
            key="menu_dim",
            scope=scope_name,       
            type_="menu",
            default=None,
            is_parent=True,
            group="Geometry",
            extended_help="**Spatial Footprint**\n\nExpand to configure exact pixel dimensions and internal padding."
        ),
        ConfigItem(
            label="Width",
            key="width",
            scope=scope_name,
            type_="int",
            default=def_width,
            min_val=10, max_val=1000, step=2,
            parent_ref=f"{scope_name}.menu_dim",
            group="Geometry"
        ),
        ConfigItem(
            label="Height",
            key="height",
            scope=scope_name,
            type_="int",
            default=def_height,
            min_val=10, max_val=500, step=2,
            parent_ref=f"{scope_name}.menu_dim",
            group="Geometry"
        ),
        ConfigItem(
            label="Padding",
            key="padding",
            scope=scope_name,
            type_="int",
            default=0,
            min_val=0, max_val=100, step=1,
            parent_ref=f"{scope_name}.menu_dim",
            group="Geometry"
        ),

        # --- VISUALS : BORDERS (HYBRID FOLDER) ---
        ConfigItem(
            label="Borders",
            key="menu_borders",
            scope=scope_name,
            type_="menu",
            default=None,
            is_parent=True,
            group="Visuals",
            extended_help="**Edge Styling**\n\nControl the thickness and rounding of the notification container."
        ),
        ConfigItem(
            label="Radius",
            key="border-radius",
            scope=scope_name,
            type_="int",
            default=20,
            min_val=0, max_val=100, step=1,
            parent_ref=f"{scope_name}.menu_borders",
            group="Visuals"
        ),
        ConfigItem(
            label="Size",
            key="border-size",
            scope=scope_name,
            type_="int",
            default=0,
            min_val=0, max_val=20, step=1,
            parent_ref=f"{scope_name}.menu_borders",
            group="Visuals"
        ),

        # --- VISUALS : COLORS (HYBRID FOLDER) ---
        ConfigItem(
            label="Colors",
            key="menu_colors",
            scope=scope_name,
            type_="menu",
            default=None,
            is_parent=True,
            group="Visuals",
            extended_help="**Theming Overrides**\n\nOverride Matugen globals with hardcoded hex colors for this specific module."
        ),
        ConfigItem(
            label="Background",
            key="background-color",
            scope=scope_name,
            type_="color",
            default=def_bg,
            options=COLOR_PALETTE,
            parent_ref=f"{scope_name}.menu_colors",
            group="Visuals"
        ),
        ConfigItem(
            label="Text",
            key="text-color",
            scope=scope_name,
            type_="color",
            default="__DELETE__",
            options=COLOR_PALETTE,
            parent_ref=f"{scope_name}.menu_colors",
            group="Visuals"
        ),
        ConfigItem(
            label="Border",
            key="border-color",
            scope=scope_name,
            type_="color",
            default="__DELETE__",
            options=COLOR_PALETTE,
            parent_ref=f"{scope_name}.menu_colors",
            group="Visuals"
        ),

        # --- BEHAVIOR ---
        ConfigItem(
            label="Icons",
            key="icons",
            scope=scope_name,
            type_="cycle",
            default="0",
            options=["0", "1"],
            group="Behavior",
            extended_help="**Icon Rendering**\n\n0 to disable, 1 to enable notification icon rendering."
        ),
        ConfigItem(
            label="Alignment",
            key="text-alignment",
            scope=scope_name,
            type_="cycle",
            default="center",
            options=["left", "center", "right"],
            group="Behavior",
            extended_help="**Text Justification**\n\nAlignment of the payload text within the bounding box."
        ),
    ]

# =============================================================================
# SCHEMA DEFINITION
# =============================================================================
SCHEMA = {
    # Isolate targets strictly to the Dusky Glance modules
    0: build_glance("app-name=dusky-glance-narrow", 174, 56, "__DELETE__"),
    1: build_glance("app-name=dusky-glance-wide", 210, 56, "#00000000"),
    2: build_glance("app-name=dusky-glance-timer", 240, 56, "#00000000"),

    # -------------------------------------------------------------------------
    # TAB 3: PROFILES (Daemon Controls & Resets)
    # -------------------------------------------------------------------------
    3: [
        ConfigItem(
            label="Reload",
            key="action_mako_reload",
            scope="DEFAULT",          
            type_="action",
            default="makoctl reload && echo 'Mako Reloaded'",
            group="Daemon",
            extended_help="**Hot Reload**\n\nForces Mako to parse the configuration file instantly."
        ),
        ConfigItem(
            label="Kill",
            key="action_mako_kill",
            scope="DEFAULT",          
            type_="action",
            default="pkill mako ; mako & echo 'Mako Restarted'",
            group="Daemon",
            extended_help="**Hard Restart**\n\nKills the daemon and restarts it in the background."
        ),
        ConfigItem(
            label="Wipe",
            key="preset_factory_reset",
            scope="DEFAULT",          
            type_="preset",
            default=None,
            group="Orchestrator",
            preset_payload={
                "__ALL_DEFAULTS__": True
            },
            extended_help="**Factory Reset**\n\nReverts all Dusky Glance modules to their originally programmed default states, handing control back to Matugen."
        ),
    ]
}
