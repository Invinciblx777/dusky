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
# Define your tabs and the configuration items for each tab.
# =============================================================================
TABS = [
    "YOUR_TAB_1",
    "YOUR_TAB_2"
]

SCHEMA = {
    0: [
        # TAB 1 ITEMS
        # Valid type_ strings: "bool", "int", "float", "string", "cycle", "action", "picker", "color"
        ConfigItem(label="Example Bool", key="your_key", scope="your/scope", type_="bool", default=False),
        ConfigItem(label="Example Int", key="your_key2", scope="your/scope", type_="int", default=10, min_val=0, max_val=100, step=5),
        ConfigItem(label="Example Color", key="color_key", scope="your/scope", type_="color", default="rgb(255, 255, 255)"),
    ],
    1: [
        # TAB 2 ITEMS
        ConfigItem(label="Example String", key="your_key3", scope="your/scope2", type_="string", default="default_text"),
        ConfigItem(label="Example Picker", key="your_key4", scope="your/scope2", type_="picker", default="Option A", options=["Option A", "Option B"]),
    ]
}

# =============================================================================
# 4. Bind & Execute
# =============================================================================
if __name__ == "__main__":
    # --- 1. SET TARGET FILE ---
    # The absolute or tilde-expanded path to the Lua file you want to mutate
    TARGET_LUA_FILE = "~/.config/hypr/source/YOUR_FILE.lua"
    
    # --- 2. SET THEME FILE (Optional) ---
    # Path to your Matugen JSON file. Leave as None to use fallback colors.
    THEME_FILE = "~/.config/matugen/generated/dusky_tui.json"
    
    # --- 3. SET WINDOW TITLE ---
    APP_TITLE = "My Custom Configurator"

    # -------------------------------------------------------------------------
    # Do not edit below this line
    # -------------------------------------------------------------------------
    engine = HyprlandLuaEngine(config_path=TARGET_LUA_FILE)
    
    app = DuskyTUI(
        engine=engine, 
        schema=SCHEMA, 
        tabs=TABS, 
        title=APP_TITLE,
        theme_path=THEME_FILE
    )
    
    app.run()
