#!/usr/bin/env python3
"""
===============================================================================
DUSKY TUI: MAKO DAEMON CONFIGURATION SCHEMA
===============================================================================
Engine mapping for Arch Linux/Hyprland Notification Daemon.
Automatically binds to ~/.config/mako/config to control global properties, 
urgency overrides, and app-specific geometry (Glance, Cava, OSD).
===============================================================================
"""

from python.frontend.core_types import ConfigItem

# =============================================================================
# 1. CORE APPLICATION ROUTING 
# =============================================================================
ENGINE_TYPE = "ini"                        
TARGET_FILE = "~/.config/mako/config"      
APP_TITLE = "Mako Daemon"                 

# =============================================================================
# 2. UI & ENVIRONMENT BEHAVIOR
# =============================================================================
DEFAULT_MODE = "auto"                      
THEME_FILE = "~/.config/matugen/generated/dusky_tui.json" 
ENABLE_USER_PRESETS = True                 
USER_PRESETS_TAB = "Profiles"              

# =============================================================================
# 3. TABS DEFINITION
# =============================================================================
TABS = [
    "Global",
    "Urgency",
    "Modules",
    "Profiles"
]

# =============================================================================
# 4. SCHEMA DEFINITION
# =============================================================================
SCHEMA = {
    # -------------------------------------------------------------------------
    # TAB 0: GLOBAL (Root daemon geometry and default behaviors)
    # -------------------------------------------------------------------------
    0: [
        ConfigItem(
            label="Anchor",
            key="anchor",
            scope="DEFAULT",
            type_="picker",
            default="bottom-left",
            options=["top-right", "top-center", "top-left", "bottom-right", "bottom-center", "bottom-left", "center"],
            hints=["Corner", "Top", "Corner", "Corner", "Bottom", "Corner", "Middle"],
            group="Geometry",
            extended_help="**Screen Position**\n\nDefines where standard un-scoped notifications spawn on your Wayland compositor."
        ),
        ConfigItem(
            label="Width",
            key="width",
            scope="DEFAULT",
            type_="int",
            default=350,
            min_val=100,
            max_val=800,
            step=10,
            group="Geometry",
            extended_help="**Global Width**\n\nMaximum width of the standard notification bubble in pixels."
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
            group="Geometry",
            extended_help="**Global Height**\n\nMaximum height of the standard notification bubble in pixels."
        ),
        ConfigItem(
            label="Radius",
            key="border-radius",
            scope="DEFAULT",
            type_="int",
            default=18,
            min_val=0,
            max_val=50,
            step=2,
            group="Styling",
            extended_help="**Border Radius**\n\nControls the curvature of the notification corners."
        ),
        ConfigItem(
            label="Border",
            key="border-size",
            scope="DEFAULT",
            type_="int",
            default=2,
            min_val=0,
            max_val=10,
            step=1,
            group="Styling",
            extended_help="**Border Thickness**\n\nThickness of the outer border ring in pixels."
        ),
        ConfigItem(
            label="Icons",
            key="icons",
            scope="DEFAULT",
            type_="bool",
            default=True,
            group="Media",
            extended_help="**Render Icons**\n\nToggle to allow application icons to be rendered within the payload."
        ),
        ConfigItem(
            label="IconSize",
            key="max-icon-size",
            scope="DEFAULT",
            type_="int",
            default=48,
            min_val=16,
            max_val=128,
            step=8,
            group="Media",
            extended_help="**Maximum Icon Size**\n\nCaps the rendering dimension of application vector/raster icons."
        ),
        ConfigItem(
            label="Timeout",
            key="default-timeout",
            scope="DEFAULT",
            type_="int",
            default=5000,
            min_val=0,
            max_val=15000,
            step=500,
            group="Behavior",
            extended_help="**Default Expiration**\n\nTime in milliseconds before an un-classified notification automatically dismisses."
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
            group="Behavior",
            extended_help="**Visibility Cap**\n\nMaximum number of notifications to stack on the screen concurrently."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 1: URGENCY (Criteria timeouts and Do-Not-Disturb modes)
    # -------------------------------------------------------------------------
    1: [
        # HYBRID FOLDER: DND Matrix Toggle
        ConfigItem(
            label="DND",
            key="invisible",
            scope="mode=do-not-disturb",  # UID = "mode=do-not-disturb.invisible"
            type_="bool",
            default=True,
            is_parent=True,
            expanded=True,
            group="Matrices",
            extended_help="**Do Not Disturb (Master)**\n\nWhen toggled ON, intercepts incoming notifications and routes them invisibly to the history buffer."
        ),
        ConfigItem(
            label="Bypass",
            key="invisible",
            scope="mode=do-not-disturb urgency=critical",  # UID = "mode=do-not-disturb urgency=critical.invisible"
            type_="bool",
            default=False, 
            parent_ref="mode=do-not-disturb.invisible",
            extended_help="**Critical Bypass**\n\nIf False, critical alerts will 'punch through' the Do Not Disturb shield and display visibly."
        ),
        # STANDARD URGENCY OVERRIDES
        ConfigItem(
            label="Low",
            key="default-timeout",
            scope="urgency=low",
            type_="int",
            default=2000,
            min_val=0,
            max_val=10000,
            step=500,
            group="Timeouts",
            extended_help="**Low Urgency Timeout**\n\nLifespan (in ms) for minor background alerts."
        ),
        ConfigItem(
            label="Normal",
            key="default-timeout",
            scope="urgency=normal",
            type_="int",
            default=3000,
            min_val=0,
            max_val=10000,
            step=500,
            group="Timeouts",
            extended_help="**Normal Urgency Timeout**\n\nLifespan (in ms) for standard application alerts."
        ),
        ConfigItem(
            label="Critical",
            key="default-timeout",
            scope="urgency=critical",
            type_="int",
            default=5000,
            min_val=0,
            max_val=20000,
            step=1000,
            group="Timeouts",
            extended_help="**Critical Urgency Timeout**\n\nLifespan (in ms) for severe system/battery alerts."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 2: MODULES (Dusky specific widget overrides via app-name)
    # -------------------------------------------------------------------------
    2: [
        # HYBRID FOLDER: OSD
        ConfigItem(
            label="OSD",
            key="anchor",
            scope="app-name=OSD",
            type_="cycle",
            default="bottom-center",
            options=["bottom-center", "top-center", "center"],
            is_parent=True,
            expanded=False,
            group="Hardware",
            extended_help="**On-Screen Display Anchor**\n\nPositioning for volume/brightness overlay widgets."
        ),
        ConfigItem(
            label="Width",
            key="width",
            scope="app-name=OSD",
            type_="int",
            default=240,
            min_val=100,
            max_val=500,
            step=10,
            parent_ref="app-name=OSD.anchor",
            extended_help="**OSD Width**\n\nHorizontal dimensions of the hardware overlay."
        ),
        ConfigItem(
            label="Radius",
            key="border-radius",
            scope="app-name=OSD",
            type_="int",
            default=24,
            min_val=0,
            max_val=40,
            step=2,
            parent_ref="app-name=OSD.anchor",
            extended_help="**OSD Pill Radius**\n\nRadius mapping to create the pill structure. Should ideally be exactly half the height."
        ),

        # HYBRID FOLDER: Dusky Cava
        ConfigItem(
            label="Cava",
            key="anchor",
            scope="app-name=dusky-cava",
            type_="cycle",
            default="bottom-center",
            options=["bottom-center", "top-center"],
            is_parent=True,
            expanded=False,
            group="Visualizers",
            extended_help="**Cava Audio Visualizer Anchor**\n\nPositioning for the embedded CLI audio spectrum."
        ),
        ConfigItem(
            label="Width",
            key="width",
            scope="app-name=dusky-cava",
            type_="int",
            default=380,
            min_val=200,
            max_val=800,
            step=20,
            parent_ref="app-name=dusky-cava.anchor",
            extended_help="**Cava Width**\n\nExtend width to prevent textual truncation (...)."
        ),
        ConfigItem(
            label="Margin",
            key="margin",
            scope="app-name=dusky-cava",
            type_="string",
            default="0,0,20,0",
            parent_ref="app-name=dusky-cava.anchor",
            extended_help="**Cava Margins**\n\nStandard CSS directional margins: top,right,bottom,left."
        ),

        # HYBRID FOLDER: Dusky Glance Wide
        ConfigItem(
            label="Glance",
            key="anchor",
            scope="app-name=dusky-glance-wide",
            type_="cycle",
            default="bottom-right",
            options=["bottom-right", "top-right", "bottom-left", "top-left"],
            is_parent=True,
            expanded=False,
            group="Monitors",
            extended_help="**System Glance Anchor**\n\nPositioning for network, battery, and CPU overlay widgets."
        ),
        ConfigItem(
            label="Width",
            key="width",
            scope="app-name=dusky-glance-wide",
            type_="int",
            default=210,
            min_val=100,
            max_val=400,
            step=10,
            parent_ref="app-name=dusky-glance-wide.anchor",
            extended_help="**Glance Width**\n\nBase width for the wide-variant modules."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 3: PROFILES (System state overrides & daemon controls)
    # -------------------------------------------------------------------------
    3: [
        ConfigItem(
            label="Reload",
            key="action_mako_reload", 
            scope="DEFAULT",          
            type_="action",
            default="makoctl reload && pkill -RTMIN+8 waybar",
            group="Daemon",
            extended_help="**Hot Reload Mako**\n\nSends an instruction to makoctl to instantly reload the `mako/config` file and signals Waybar for sync."
        ),
        ConfigItem(
            label="Dismiss",
            key="action_mako_dismiss", 
            scope="DEFAULT",          
            type_="action",
            default="makoctl dismiss -a",
            group="Daemon",
            extended_help="**Clear All**\n\nInstantly clears all active notifications off the screen."
        ),
        ConfigItem(
            label="Compact",
            key="preset_compact_ui",     
            scope="DEFAULT",          
            type_="preset",
            default=None,
            group="Orchestrator",
            preset_payload={
                "margin": 10,
                "padding": 8,
                "border-size": 1,
                "border-radius": 8,
                "max-icon-size": 32,
                "width": 300,
                "height": 100
            },
            extended_help="**Compact Mode Preset**\n\nShrinks global margins, padding, and widths to provide a high-density, minimalistic notification stack. Unlisted keys revert to defaults."
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
            extended_help="**Factory Reset**\n\nReverts every single configuration item across all criteria blocks back to your initially hardcoded values."
        ),
    ]
}
