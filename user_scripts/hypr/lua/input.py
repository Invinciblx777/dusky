#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# =============================================================================
# CACHE CONFIGURATION
# Redirect __pycache__ creation to a centralized XDG cache directory.
# MUST be done before importing custom modules.
# =============================================================================
def _setup_cache() -> None:
    try:
        xdg_cache_env = os.environ.get("XDG_CACHE_HOME", "").strip()
        xdg_cache = Path(xdg_cache_env) if xdg_cache_env else Path.home() / ".cache"
        cache_dir = xdg_cache / "dusky_tui"
        cache_dir.mkdir(parents=True, exist_ok=True)
        sys.pycache_prefix = str(cache_dir)
    except OSError:
        pass

_setup_cache()

# =============================================================================
# 1. Path Injection (IoC Setup)
# Ensures the runner can find the ecosystem without hardcoded system installs.
# =============================================================================
TEMPLATE_DIR = Path("~/user_scripts/dusky_tui").expanduser().resolve()
if str(TEMPLATE_DIR) not in sys.path:
    sys.path.insert(0, str(TEMPLATE_DIR))

# =============================================================================
# 2. Lazy Import Architectural Components
# =============================================================================
from python.frontend.core_types import ConfigItem
from python.engines.lua import HyprlandLuaEngine
from python.frontend.ui import DuskyTUI

# =============================================================================
# 3. Dynamic Schema Construction
# Defines the exact parameters this specific runner will manage.
# =============================================================================
TABS = ["Keyboard", "Touchpad / Mouse", "Misc"]

SCHEMA = {
    0: [
        ConfigItem(label="Keyboard Layout", key="kb_layout", scope="input", type_="string", default="us"),
        ConfigItem(label="Keyboard Variant", key="kb_variant", scope="input", type_="string", default=""),
        ConfigItem(label="Numlock by Default", key="numlock_by_default", scope="input", type_="bool", default=False),
        ConfigItem(label="Repeat Rate", key="repeat_rate", scope="input", type_="int", default=25, min_val=10, max_val=100, step=5),
        ConfigItem(label="Repeat Delay", key="repeat_delay", scope="input", type_="int", default=600, min_val=100, max_val=1000, step=50),
    ],
    1: [
        ConfigItem(label="Natural Scroll", key="natural_scroll", scope="input/touchpad", type_="bool", default=False),
        ConfigItem(label="Tap to Click", key="tap_to_click", scope="input/touchpad", type_="bool", default=True),
        ConfigItem(label="Mouse Sensitivity", key="sensitivity", scope="input", type_="float", default=0.0, min_val=-1.0, max_val=1.0, step=0.1),
        ConfigItem(label="Follow Mouse", key="follow_mouse", scope="input", type_="cycle", default=1, options=[0, 1, 2, 3]),
    ],
    2: [
        ConfigItem(label="Force No Cursor", key="force_no_wrapper", scope="input", type_="bool", default=False),
    ]
}

# =============================================================================
# 4. Bind & Execute
# =============================================================================
if __name__ == "__main__":
    # Link the backend Engine to the specific target Lua file
    target_file = "~/.config/hypr/source/input.lua"
    engine = HyprlandLuaEngine(config_path=target_file)
    
    # Define the Matugen generated JSON path for hot-reloading native TUI colors
    theme_file = "~/.config/matugen/generated/dusky_tui.json"
    
    # Inject Engine, Schema, and Theme path into the decoupled TUI instance
    app = DuskyTUI(
        engine=engine, 
        schema=SCHEMA, 
        tabs=TABS, 
        title="Hyprland Input Configurator",
        theme_path=theme_file
    )
    
    # Launch application
    app.run()
