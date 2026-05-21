#!/usr/bin/env python3
"""
===============================================================================
DUSKY TUI: MAKO MATUGEN TEMPLATE SCHEMA (INI PARADIGM)
===============================================================================
Targeting the Matugen pre-processor template. Allows granular control over 
base geometry, urgency states, and all Dusky custom applet modules.
===============================================================================
"""

from python.frontend.core_types import ConfigItem

# =============================================================================
# 1. CORE APPLICATION ROUTING (REQUIRED)
# =============================================================================
ENGINE_TYPE = "ini"                        
TARGET_FILE = "~/.config/matugen/templates/mako"      
APP_TITLE = "Mako Template Config"                 

# =============================================================================
# 2. UI & ENVIRONMENT BEHAVIOR
# =============================================================================
DEFAULT_MODE = "auto"                      
THEME_FILE = "~/.config/matugen/generated/dusky_tui.json" 

ENABLE_USER_PRESETS = True                 
USER_PRESETS_TAB = "Profiles"              

# =============================================================================
# 3. GLOBAL COLOR PALETTES (MATUGEN + HARDCODED)
# =============================================================================
COLOR_OPTIONS = [
    # Matugen Variables
    "{{colors.primary.default.hex}}", "{{colors.on_primary.default.hex}}",
    "{{colors.primary_container.default.hex}}", "{{colors.on_primary_container.default.hex}}",
    "{{colors.secondary.default.hex}}", "{{colors.on_secondary.default.hex}}",
    "{{colors.secondary_container.default.hex}}", "{{colors.on_secondary_container.default.hex}}",
    "{{colors.tertiary.default.hex}}", "{{colors.on_tertiary.default.hex}}",
    "{{colors.tertiary_container.default.hex}}", "{{colors.on_tertiary_container.default.hex}}",
    "{{colors.surface.default.hex}}", "{{colors.on_surface.default.hex}}",
    "{{colors.surface_variant.default.hex}}", "{{colors.on_surface_variant.default.hex}}",
    "{{colors.outline.default.hex}}", "{{colors.outline_variant.default.hex}}",
    "{{colors.error.default.hex}}", "{{colors.on_error.default.hex}}",
    "{{colors.error_container.default.hex}}", "{{colors.on_error_container.default.hex}}",
    # Hardcoded Common Colors
    "#ff0000", "#00ff00", "#0000ff", "#ffd700", "#39ff14", "#ffffff", "#000000", "#00000000",
    "#800080", "#ffa500", "#90ee90", "#ffffe0", "#00ffff", "#ff00ff", "#ffff00", "#ffc0cb",
    "#008080", "#e6e6fa", "#a52a2a", "#800000", "#808080", "#c0c0c0"
]

COLOR_HINTS = [
    # Matugen Hints
    "Primary", "On Primary", "Primary Container", "On Primary Cont",
    "Secondary", "On Secondary", "Secondary Container", "On Sec Cont",
    "Tertiary", "On Tertiary", "Tertiary Container", "On Ter Cont",
    "Surface", "On Surface", "Surface Variant", "On Surf Var",
    "Outline", "Outline Variant",
    "Error", "On Error", "Error Container", "On Err Cont",
    # Hardcoded Hints
    "Red", "Green", "Blue", "Gold", "Neon Green", "White", "Black", "Transparent",
    "Purple", "Orange", "Light Green", "Barely Yellow", "Cyan", "Magenta", "Yellow", "Pink",
    "Teal", "Lavender", "Brown", "Maroon", "Gray", "Silver"
]

# =============================================================================
# 4. TABS DEFINITION
# =============================================================================
TABS = [
    "Layout",
    "Visuals",
    "Behavior",
    "Urgency",
    "Modules",
    "Profiles"
]

# =============================================================================
# 5. SCHEMA DEFINITION
# =============================================================================
SCHEMA = {
    # -------------------------------------------------------------------------
    # TAB 0: LAYOUT (Global Geometry & Positioning)
    # -------------------------------------------------------------------------
    0: [
        ConfigItem(
            label="Anchor",
            key="anchor",
            scope="DEFAULT",       
            type_="cycle",
            default="bottom-left",
            options=["top-right", "top-center", "top-left", "bottom-right", "bottom-center", "bottom-left", "center-right", "center-left", "center"],
            group="Geometry"
        ),
        ConfigItem(
            label="Width",
            key="width",
            scope="DEFAULT",       
            type_="int",
            default=340,
            min_val=100,
            max_val=800,
            step=10,
            group="Geometry"
        ),
        ConfigItem(
            label="Height",
            key="height",
            scope="DEFAULT",       
            type_="int",
            default=150,
            min_val=50,
            max_val=500,
            step=10,
            group="Geometry"
        ),
        ConfigItem(
            label="Outer",
            key="outer-margin",
            scope="DEFAULT",       
            type_="string",
            default="0,0,30,0",
            group="Spacing"
        ),
        ConfigItem(
            label="Margin",
            key="margin",
            scope="DEFAULT",       
            type_="string",
            default="5",
            group="Spacing"
        ),
        ConfigItem(
            label="Padding",
            key="padding",
            scope="DEFAULT",       
            type_="string",
            default="10",
            group="Spacing"
        ),
        ConfigItem(
            label="Radius",
            key="border-radius",
            scope="DEFAULT",       
            type_="int",
            default=18,
            min_val=0,
            max_val=50,
            step=1,
            group="Borders"
        ),
        ConfigItem(
            label="Size",
            key="border-size",
            scope="DEFAULT",       
            type_="int",
            default=1,
            min_val=0,
            max_val=20,
            step=1,
            group="Borders"
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 1: VISUALS (Aesthetics & Typography)
    # -------------------------------------------------------------------------
    1: [
        ConfigItem(
            label="Font",
            key="font",
            scope="DEFAULT",       
            type_="string",
            default="monospace 10",
            group="Text"
        ),
        ConfigItem(
            label="Markup",
            key="markup",
            scope="DEFAULT",       
            type_="bool",
            default=True,
            group="Text"
        ),
        ConfigItem(
            label="Format",
            key="format",
            scope="DEFAULT",       
            type_="string",
            default="<b>%s</b>\\n%b",
            group="Text"
        ),
        ConfigItem(
            label="Enable",
            key="icons",
            scope="DEFAULT",       
            type_="bool",
            default=True,
            group="Icons"
        ),
        ConfigItem(
            label="MaxSize",
            key="max-icon-size",
            scope="DEFAULT",       
            type_="int",
            default=48,
            min_val=16,
            max_val=128,
            step=4,
            group="Icons"
        ),
        ConfigItem(
            label="Radius",
            key="icon-border-radius",
            scope="DEFAULT",       
            type_="int",
            default=8,
            min_val=0,
            max_val=32,
            step=1,
            group="Icons"
        ),
        ConfigItem(
            label="Path",
            key="icon-path",
            scope="DEFAULT",       
            type_="string",
            default="/usr/share/icons/Papirus-Dark:/usr/share/icons/Papirus-Light",
            group="Icons"
        ),
        ConfigItem(
            label="Background",
            key="background-color",
            scope="DEFAULT",       
            type_="color",
            default="{{colors.surface.default.hex}}66",
            options=COLOR_OPTIONS,
            hints=COLOR_HINTS,
            group="Colors"
        ),
        ConfigItem(
            label="Text",
            key="text-color",
            scope="DEFAULT",       
            type_="color",
            default="{{colors.on_surface.default.hex}}",
            options=COLOR_OPTIONS,
            hints=COLOR_HINTS,
            group="Colors"
        ),
        ConfigItem(
            label="Border",
            key="border-color",
            scope="DEFAULT",       
            type_="color",
            default="{{colors.primary.default.hex}}ee",
            options=COLOR_OPTIONS,
            hints=COLOR_HINTS,
            group="Colors"
        ),
        ConfigItem(
            label="Progress",
            key="progress-color",
            scope="DEFAULT",       
            type_="color",
            default="{{colors.primary_container.default.hex}}",
            options=COLOR_OPTIONS,
            hints=COLOR_HINTS,
            group="Colors"
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 2: BEHAVIOR (Timeouts, Sorting, & Stack Limits)
    # -------------------------------------------------------------------------
    2: [
        ConfigItem(
            label="Timeout",
            key="default-timeout",
            scope="DEFAULT",       
            type_="int",
            default=5000,
            min_val=0,
            max_val=30000,
            step=500,
            group="Timers"
        ),
        ConfigItem(
            label="Ignore",
            key="ignore-timeout",
            scope="DEFAULT",       
            type_="bool",
            default=False,
            group="Timers"
        ),
        ConfigItem(
            label="Visible",
            key="max-visible",
            scope="DEFAULT",       
            type_="int",
            default=6,
            min_val=1,
            max_val=20,
            step=1,
            group="Queue"
        ),
        ConfigItem(
            label="MaxHistory",
            key="max-history",
            scope="DEFAULT",       
            type_="int",
            default=50,
            min_val=1,
            max_val=200,
            step=5,
            group="Queue"
        ),
        ConfigItem(
            label="History",
            key="history",
            scope="DEFAULT",       
            type_="bool",
            default=True,
            group="Queue"
        ),
        ConfigItem(
            label="Sort",
            key="sort",
            scope="DEFAULT",       
            type_="cycle",
            default="-time",
            options=["-time", "+time", "-priority", "+priority"],
            group="Queue"
        ),
        ConfigItem(
            label="Actions",
            key="actions",
            scope="DEFAULT",       
            type_="bool",
            default=True,
            group="Clicks"
        ),
        ConfigItem(
            label="LeftBtn",
            key="on-button-left",
            scope="DEFAULT",       
            type_="string",
            default="invoke-default-action",
            group="Clicks"
        ),
        ConfigItem(
            label="MidBtn",
            key="on-button-middle",
            scope="DEFAULT",       
            type_="string",
            default="exec makoctl menu -n \"$MAKO_NOTIFICATION_ID\" -- rofi -dmenu -p Action:",
            group="Clicks"
        ),
        ConfigItem(
            label="RightBtn",
            key="on-button-right",
            scope="DEFAULT",       
            type_="string",
            default="dismiss",
            group="Clicks"
        ),
        ConfigItem(
            label="OnNotify",
            key="on-notify",
            scope="DEFAULT",       
            type_="string",
            default="exec pkill -RTMIN+8 waybar",
            group="Triggers"
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 3: URGENCY (Criteria-based Overrides via Submenus)
    # -------------------------------------------------------------------------
    3: [
        # --- LOW URGENCY ---
        ConfigItem(
            label="Low", key="menu_low", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Levels"
        ),
        ConfigItem(
            label="Timeout", key="default-timeout", scope="urgency=low", type_="int", default=2000, min_val=0, max_val=15000, step=500, parent_ref="menu_low"
        ),
        ConfigItem(
            label="Background", key="background-color", scope="urgency=low", type_="color", default="{{colors.surface.default.hex}}e6", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_low"
        ),
        ConfigItem(
            label="Text", key="text-color", scope="urgency=low", type_="color", default="{{colors.on_surface.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_low"
        ),
        ConfigItem(
            label="Border", key="border-color", scope="urgency=low", type_="color", default="{{colors.outline_variant.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_low"
        ),
        
        # --- NORMAL URGENCY ---
        ConfigItem(
            label="Normal", key="menu_norm", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Levels"
        ),
        ConfigItem(
            label="Timeout", key="default-timeout", scope="urgency=normal", type_="int", default=3000, min_val=0, max_val=15000, step=500, parent_ref="menu_norm"
        ),

        # --- CRITICAL URGENCY ---
        ConfigItem(
            label="Critical", key="menu_crit", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Levels"
        ),
        ConfigItem(
            label="Invisible", key="invisible", scope="urgency=critical", type_="bool", default=False, parent_ref="menu_crit"
        ),
        ConfigItem(
            label="Timeout", key="default-timeout", scope="urgency=critical", type_="int", default=0, min_val=0, max_val=30000, step=500, parent_ref="menu_crit"
        ),
        ConfigItem(
            label="Ignore", key="ignore-timeout", scope="urgency=critical", type_="bool", default=True, parent_ref="menu_crit"
        ),
        ConfigItem(
            label="OnNotify", key="on-notify", scope="urgency=critical", type_="string", default="exec pkill -RTMIN+8 waybar", parent_ref="menu_crit"
        ),
        ConfigItem(
            label="Background", key="background-color", scope="urgency=critical", type_="color", default="{{colors.error_container.default.hex}}e6", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_crit"
        ),
        ConfigItem(
            label="Text", key="text-color", scope="urgency=critical", type_="color", default="{{colors.on_error_container.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_crit"
        ),
        ConfigItem(
            label="Border", key="border-color", scope="urgency=critical", type_="color", default="{{colors.error.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_crit"
        ),

        # --- MODES ---
        ConfigItem(
            label="DND", key="menu_dnd", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Modes"
        ),
        ConfigItem(
            label="Invisible", key="invisible", scope="mode=do-not-disturb", type_="bool", default=True, parent_ref="menu_dnd"
        ),
        ConfigItem(
            label="OnNotify", key="on-notify", scope="mode=do-not-disturb", type_="string", default="none", parent_ref="menu_dnd"
        ),

        ConfigItem(
            label="Silent", key="menu_silent", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Modes"
        ),
        ConfigItem(
            label="OnNotify", key="on-notify", scope="mode=silent", type_="string", default="none", parent_ref="menu_silent"
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 4: MODULES (Dusky App Specific Configurations)
    # -------------------------------------------------------------------------
    4: [
        # --- GLOBAL APP OVERRIDES ---
        ConfigItem(
            label="Apps", key="menu_apps", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Overrides"
        ),
        ConfigItem(
            label="SpotifyInv", key="invisible", scope="app-name=Spotify", type_="bool", default=True, parent_ref="menu_apps"
        ),
        ConfigItem(
            label="VLCTimeout", key="default-timeout", scope='app-name="VLC media player"', type_="int", default=1500, min_val=0, max_val=10000, step=500, parent_ref="menu_apps"
        ),
        ConfigItem(
            label="GrimSize", key="max-icon-size", scope="app-name=grimblast", type_="int", default=84, min_val=16, max_val=200, step=4, parent_ref="menu_apps"
        ),
        ConfigItem(
            label="GrimTimeout", key="default-timeout", scope="app-name=grimblast", type_="int", default=4000, min_val=0, max_val=10000, step=500, parent_ref="menu_apps"
        ),
        ConfigItem(
            label="GrimFormat", key="format", scope="app-name=grimblast", type_="string", default="<b>%s</b>\\n%b", parent_ref="menu_apps"
        ),
        ConfigItem(
            label="GrimClick", key="on-button-left", scope="app-name=grimblast", type_="string", default="exec imv \"$MAKO_NOTIFICATION_BODY\"", parent_ref="menu_apps"
        ),
        ConfigItem(
            label="DotfilesCmd", key="on-button-left", scope='summary="Dusky Dotfiles"', type_="string", default="exec kitty --class update_dusky.sh --hold ~/user_scripts/update_dusky/update_dusky.sh", parent_ref="menu_apps"
        ),

        # --- DUSKY OSD ---
        ConfigItem(
            label="OSD", key="menu_osd", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Widgets"
        ),
        ConfigItem(label="Anchor", key="anchor", scope="app-name=OSD", type_="cycle", default="bottom-center", options=["top-right", "top-center", "top-left", "bottom-right", "bottom-center", "bottom-left", "center-right", "center-left", "center"], parent_ref="menu_osd"),
        ConfigItem(label="Width", key="width", scope="app-name=OSD", type_="int", default=240, min_val=50, max_val=800, step=10, parent_ref="menu_osd"),
        ConfigItem(label="Height", key="height", scope="app-name=OSD", type_="int", default=48, min_val=10, max_val=200, step=2, parent_ref="menu_osd"),
        ConfigItem(label="Outer", key="outer-margin", scope="app-name=OSD", type_="string", default="0,0,30,0", parent_ref="menu_osd"),
        ConfigItem(label="Margin", key="margin", scope="app-name=OSD", type_="string", default="0", parent_ref="menu_osd"),
        ConfigItem(label="Padding", key="padding", scope="app-name=OSD", type_="string", default="0", parent_ref="menu_osd"),
        ConfigItem(label="Radius", key="border-radius", scope="app-name=OSD", type_="int", default=24, min_val=0, max_val=50, step=1, parent_ref="menu_osd"),
        ConfigItem(label="Icons", key="icons", scope="app-name=OSD", type_="bool", default=False, parent_ref="menu_osd"),
        ConfigItem(label="Align", key="text-alignment", scope="app-name=OSD", type_="cycle", default="center", options=["left", "center", "right"], parent_ref="menu_osd"),
        ConfigItem(label="Timeout", key="default-timeout", scope="app-name=OSD", type_="int", default=1000, min_val=0, max_val=10000, step=100, parent_ref="menu_osd"),
        ConfigItem(label="OnClick", key="on-button-left", scope="app-name=OSD", type_="string", default="invoke-default-action", parent_ref="menu_osd"),
        ConfigItem(label="Background", key="background-color", scope="app-name=OSD", type_="color", default="#111110e6", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_osd"),
        ConfigItem(label="Text", key="text-color", scope="app-name=OSD", type_="color", default="#ffffff", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_osd"),
        ConfigItem(label="Border", key="border-color", scope="app-name=OSD", type_="color", default="#555555", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_osd"),

        # --- DUSKY KEYS ---
        ConfigItem(
            label="Keys", key="menu_keys", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Widgets"
        ),
        ConfigItem(label="Anchor", key="anchor", scope="app-name=dusky-keys", type_="cycle", default="bottom-center", options=["top-right", "top-center", "top-left", "bottom-right", "bottom-center", "bottom-left", "center-right", "center-left", "center"], parent_ref="menu_keys"),
        ConfigItem(label="Width", key="width", scope="app-name=dusky-keys", type_="int", default=200, min_val=50, max_val=800, step=10, parent_ref="menu_keys"),
        ConfigItem(label="Height", key="height", scope="app-name=dusky-keys", type_="int", default=40, min_val=10, max_val=200, step=2, parent_ref="menu_keys"),
        ConfigItem(label="Margin", key="margin", scope="app-name=dusky-keys", type_="string", default="0,0,20,0", parent_ref="menu_keys"),
        ConfigItem(label="Padding", key="padding", scope="app-name=dusky-keys", type_="string", default="0", parent_ref="menu_keys"),
        ConfigItem(label="Size", key="border-size", scope="app-name=dusky-keys", type_="int", default=2, min_val=0, max_val=10, step=1, parent_ref="menu_keys"),
        ConfigItem(label="Radius", key="border-radius", scope="app-name=dusky-keys", type_="int", default=20, min_val=0, max_val=50, step=1, parent_ref="menu_keys"),
        ConfigItem(label="Icons", key="icons", scope="app-name=dusky-keys", type_="bool", default=False, parent_ref="menu_keys"),
        ConfigItem(label="Align", key="text-alignment", scope="app-name=dusky-keys", type_="cycle", default="center", options=["left", "center", "right"], parent_ref="menu_keys"),
        ConfigItem(label="Font", key="font", scope="app-name=dusky-keys", type_="string", default="monospace 14", parent_ref="menu_keys"),
        ConfigItem(label="Format", key="format", scope="app-name=dusky-keys", type_="string", default="%s", parent_ref="menu_keys"),
        ConfigItem(label="Timeout", key="default-timeout", scope="app-name=dusky-keys", type_="int", default=1500, min_val=0, max_val=10000, step=100, parent_ref="menu_keys"),
        ConfigItem(label="Background", key="background-color", scope="app-name=dusky-keys", type_="color", default="{{colors.surface_variant.default.hex}}ff", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_keys"),
        ConfigItem(label="Text", key="text-color", scope="app-name=dusky-keys", type_="color", default="{{colors.on_surface_variant.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_keys"),
        ConfigItem(label="Border", key="border-color", scope="app-name=dusky-keys", type_="color", default="{{colors.outline.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_keys"),

        # --- DUSKY CAVA ---
        ConfigItem(
            label="Cava", key="menu_cava", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Widgets"
        ),
        ConfigItem(label="Anchor", key="anchor", scope="app-name=dusky-cava", type_="cycle", default="bottom-center", options=["top-right", "top-center", "top-left", "bottom-right", "bottom-center", "bottom-left", "center-right", "center-left", "center"], parent_ref="menu_cava"),
        ConfigItem(label="Width", key="width", scope="app-name=dusky-cava", type_="int", default=380, min_val=100, max_val=800, step=10, parent_ref="menu_cava"),
        ConfigItem(label="Height", key="height", scope="app-name=dusky-cava", type_="int", default=40, min_val=10, max_val=200, step=2, parent_ref="menu_cava"),
        ConfigItem(label="Margin", key="margin", scope="app-name=dusky-cava", type_="string", default="0,0,20,0", parent_ref="menu_cava"),
        ConfigItem(label="Padding", key="padding", scope="app-name=dusky-cava", type_="string", default="0", parent_ref="menu_cava"),
        ConfigItem(label="Size", key="border-size", scope="app-name=dusky-cava", type_="int", default=2, min_val=0, max_val=10, step=1, parent_ref="menu_cava"),
        ConfigItem(label="Radius", key="border-radius", scope="app-name=dusky-cava", type_="int", default=20, min_val=0, max_val=50, step=1, parent_ref="menu_cava"),
        ConfigItem(label="Icons", key="icons", scope="app-name=dusky-cava", type_="bool", default=False, parent_ref="menu_cava"),
        ConfigItem(label="Align", key="text-alignment", scope="app-name=dusky-cava", type_="cycle", default="center", options=["left", "center", "right"], parent_ref="menu_cava"),
        ConfigItem(label="Font", key="font", scope="app-name=dusky-cava", type_="string", default="monospace 22", parent_ref="menu_cava"),
        ConfigItem(label="Format", key="format", scope="app-name=dusky-cava", type_="string", default="%s", parent_ref="menu_cava"),
        ConfigItem(label="Timeout", key="default-timeout", scope="app-name=dusky-cava", type_="int", default=0, min_val=0, max_val=10000, step=100, parent_ref="menu_cava"),
        ConfigItem(label="Background", key="background-color", scope="app-name=dusky-cava", type_="color", default="{{colors.surface_container.default.hex}}ff", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_cava"),
        ConfigItem(label="Text", key="text-color", scope="app-name=dusky-cava", type_="color", default="{{colors.primary.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_cava"),
        ConfigItem(label="Border", key="border-color", scope="app-name=dusky-cava", type_="color", default="{{colors.primary_container.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_cava"),

        # --- DUSKY CAVA ALERT ---
        ConfigItem(
            label="CavaAlert", key="menu_cava_alert", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Alerts"
        ),
        ConfigItem(label="Anchor", key="anchor", scope="app-name=dusky-cava-alert", type_="cycle", default="bottom-center", options=["top-right", "top-center", "top-left", "bottom-right", "bottom-center", "bottom-left", "center-right", "center-left", "center"], parent_ref="menu_cava_alert"),
        ConfigItem(label="Width", key="width", scope="app-name=dusky-cava-alert", type_="int", default=300, min_val=50, max_val=800, step=10, parent_ref="menu_cava_alert"),
        ConfigItem(label="Height", key="height", scope="app-name=dusky-cava-alert", type_="int", default=40, min_val=10, max_val=200, step=2, parent_ref="menu_cava_alert"),
        ConfigItem(label="Margin", key="margin", scope="app-name=dusky-cava-alert", type_="string", default="0,0,20,0", parent_ref="menu_cava_alert"),
        ConfigItem(label="Padding", key="padding", scope="app-name=dusky-cava-alert", type_="string", default="0", parent_ref="menu_cava_alert"),
        ConfigItem(label="Radius", key="border-radius", scope="app-name=dusky-cava-alert", type_="int", default=20, min_val=0, max_val=50, step=1, parent_ref="menu_cava_alert"),
        ConfigItem(label="Align", key="text-alignment", scope="app-name=dusky-cava-alert", type_="cycle", default="center", options=["left", "center", "right"], parent_ref="menu_cava_alert"),
        ConfigItem(label="Font", key="font", scope="app-name=dusky-cava-alert", type_="string", default="monospace 12", parent_ref="menu_cava_alert"),
        ConfigItem(label="Timeout", key="default-timeout", scope="app-name=dusky-cava-alert", type_="int", default=3000, min_val=0, max_val=10000, step=100, parent_ref="menu_cava_alert"),
        ConfigItem(label="Background", key="background-color", scope="app-name=dusky-cava-alert", type_="color", default="{{colors.tertiary_container.default.hex}}ff", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_cava_alert"),
        ConfigItem(label="Text", key="text-color", scope="app-name=dusky-cava-alert", type_="color", default="{{colors.on_tertiary_container.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_cava_alert"),

        # --- DUSKY GLANCE ---
        ConfigItem(
            label="Glance", key="menu_glance", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Dashboards"
        ),
        ConfigItem(label="Anchor", key="anchor", scope="app-name=dusky-glance", type_="cycle", default="bottom-right", options=["top-right", "top-center", "top-left", "bottom-right", "bottom-center", "bottom-left", "center-right", "center-left", "center"], parent_ref="menu_glance"),
        ConfigItem(label="Width", key="width", scope="app-name=dusky-glance", type_="int", default=174, min_val=50, max_val=500, step=10, parent_ref="menu_glance"),
        ConfigItem(label="Height", key="height", scope="app-name=dusky-glance", type_="int", default=56, min_val=20, max_val=200, step=4, parent_ref="menu_glance"),
        ConfigItem(label="Margin", key="margin", scope="app-name=dusky-glance", type_="string", default="0,20,20,0", parent_ref="menu_glance"),
        ConfigItem(label="Padding", key="padding", scope="app-name=dusky-glance", type_="string", default="0", parent_ref="menu_glance"),
        ConfigItem(label="Size", key="border-size", scope="app-name=dusky-glance", type_="int", default=0, min_val=0, max_val=10, step=1, parent_ref="menu_glance"),
        ConfigItem(label="Radius", key="border-radius", scope="app-name=dusky-glance", type_="int", default=20, min_val=0, max_val=50, step=1, parent_ref="menu_glance"),
        ConfigItem(label="Icons", key="icons", scope="app-name=dusky-glance", type_="bool", default=False, parent_ref="menu_glance"),
        ConfigItem(label="Align", key="text-alignment", scope="app-name=dusky-glance", type_="cycle", default="center", options=["left", "center", "right"], parent_ref="menu_glance"),
        ConfigItem(label="Format", key="format", scope="app-name=dusky-glance", type_="string", default="%b", parent_ref="menu_glance"),
        ConfigItem(label="OnClick", key="on-button-left", scope="app-name=dusky-glance", type_="string", default="exec bash -c \"pkill rofi; uwsm-app -- $HOME/user_scripts/rofi/dusky_glance.sh\"", parent_ref="menu_glance"),
        ConfigItem(label="Timeout", key="default-timeout", scope="app-name=dusky-glance", type_="int", default=0, min_val=0, max_val=10000, step=100, parent_ref="menu_glance"),
        ConfigItem(label="Background", key="background-color", scope="app-name=dusky-glance", type_="color", default="#00000000", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_glance"),
        ConfigItem(label="Text", key="text-color", scope="app-name=dusky-glance", type_="color", default="{{colors.primary.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_glance"),
        ConfigItem(label="Border", key="border-color", scope="app-name=dusky-glance", type_="color", default="{{colors.outline.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_glance"),

        # --- DUSKY GLANCE ALERT ---
        ConfigItem(
            label="GlanceAlert", key="menu_glance_alert", scope="DEFAULT", type_="menu", default=None, is_parent=True, group="Alerts"
        ),
        ConfigItem(label="Anchor", key="anchor", scope="app-name=dusky-glance-alert", type_="cycle", default="top-center", options=["top-right", "top-center", "top-left", "bottom-right", "bottom-center", "bottom-left", "center-right", "center-left", "center"], parent_ref="menu_glance_alert"),
        ConfigItem(label="Width", key="width", scope="app-name=dusky-glance-alert", type_="int", default=300, min_val=100, max_val=800, step=10, parent_ref="menu_glance_alert"),
        ConfigItem(label="Height", key="height", scope="app-name=dusky-glance-alert", type_="int", default=80, min_val=20, max_val=200, step=4, parent_ref="menu_glance_alert"),
        ConfigItem(label="Margin", key="margin", scope="app-name=dusky-glance-alert", type_="string", default="20,0,0,0", parent_ref="menu_glance_alert"),
        ConfigItem(label="Padding", key="padding", scope="app-name=dusky-glance-alert", type_="string", default="10", parent_ref="menu_glance_alert"),
        ConfigItem(label="Size", key="border-size", scope="app-name=dusky-glance-alert", type_="int", default=1, min_val=0, max_val=10, step=1, parent_ref="menu_glance_alert"),
        ConfigItem(label="Radius", key="border-radius", scope="app-name=dusky-glance-alert", type_="int", default=12, min_val=0, max_val=50, step=1, parent_ref="menu_glance_alert"),
        ConfigItem(label="Icons", key="icons", scope="app-name=dusky-glance-alert", type_="bool", default=True, parent_ref="menu_glance_alert"),
        ConfigItem(label="Align", key="text-alignment", scope="app-name=dusky-glance-alert", type_="cycle", default="center", options=["left", "center", "right"], parent_ref="menu_glance_alert"),
        ConfigItem(label="Ignore", key="ignore-timeout", scope="app-name=dusky-glance-alert", type_="bool", default=True, parent_ref="menu_glance_alert"),
        ConfigItem(label="OnClick", key="on-button-left", scope="app-name=dusky-glance-alert", type_="string", default="dismiss", parent_ref="menu_glance_alert"),
        ConfigItem(label="Background", key="background-color", scope="app-name=dusky-glance-alert", type_="color", default="{{colors.secondary_container.default.hex}}ee", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_glance_alert"),
        ConfigItem(label="Text", key="text-color", scope="app-name=dusky-glance-alert", type_="color", default="{{colors.on_secondary_container.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_glance_alert"),
        ConfigItem(label="Border", key="border-color", scope="app-name=dusky-glance-alert", type_="color", default="{{colors.secondary.default.hex}}", options=COLOR_OPTIONS, hints=COLOR_HINTS, parent_ref="menu_glance_alert"),
    ],

    # -------------------------------------------------------------------------
    # TAB 5: PROFILES (Advanced Controls & State Synchronization)
    # -------------------------------------------------------------------------
    5: [
        ConfigItem(
            label="Compile",
            key="action_reload_mako", 
            scope="DEFAULT",          
            type_="action",
            default="bash -c 'matugen image ~/.config/wallpapers/current_wallpaper || matugen && makoctl reload'",
            group="Execution",
            extended_help="**Live Compile**\n\nRuns Matugen to parse the edited template into `~/.config/mako/config`, and then triggers `makoctl reload` to apply it to the live Wayland session."
        ),
        ConfigItem(
            label="Reset",
            key="preset_factory_reset",
            scope="DEFAULT",          
            type_="preset",
            default=None,
            group="Orchestrator",
            preset_payload={
                "__ALL_DEFAULTS__": True
            },
            extended_help="**Nuclear Reset**\n\nReverts every single configuration item across all tabs back to its originally programmed state."
        ),
    ]
}
