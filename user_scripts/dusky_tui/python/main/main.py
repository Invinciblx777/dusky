#!/usr/bin/env python3
import sys
import os
import argparse
import importlib.util
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path

# =============================================================================
# CACHE & IOC SETUP
# =============================================================================
def _setup_cache() -> None:
    try:
        xdg_cache_env = os.environ.get("XDG_CACHE_HOME", "").strip()
        xdg_cache = Path(xdg_cache_env).expanduser().resolve() if xdg_cache_env else Path.home() / ".cache"
        cache_dir = xdg_cache / "dusky_tui"
        cache_dir.mkdir(parents=True, exist_ok=True)
        sys.pycache_prefix = str(cache_dir)
    except OSError:
        pass

_setup_cache()

# Ensure we can import the core modules
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.engines.lua import HyprlandLuaEngine
from python.frontend.ui import DuskyTUI

# =============================================================================
# SCHEMA SEARCH PATHS
# Expand this list in the future to allow loading schemas from new locations.
# =============================================================================
SCHEMA_SEARCH_PATHS = [
    Path("~/user_scripts").expanduser().resolve(),
    Path("~/.config/dusky_schema").expanduser().resolve(),
    Path("~/Documents/schemas").expanduser().resolve(),
]

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================
def setup_logging(module_name: str, enable_logging: bool) -> logging.Logger:
    """Configures logging. Attaches a NullHandler if disabled to prevent TUI corruption."""
    logger = logging.getLogger("dusky_router")
    logger.setLevel(logging.DEBUG if enable_logging else logging.WARNING)
    
    if enable_logging:
        log_dir = Path("~/Documents/logs/tui/").expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{module_name}_runner.log"
        
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s'))
        logger.addHandler(fh)
        print(f"[*] Logging enabled: {log_file}")
    else:
        logger.addHandler(logging.NullHandler())
    
    return logger

def manage_backup(target_file: Path, action: str, logger: logging.Logger) -> bool:
    """Handles creating and restoring backups without hard exiting, allowing CLI composition."""
    backup_dir = Path("~/Documents/dusky_backups/tui_reset/").expanduser()
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{target_file.name}.{timestamp}.bak"
    latest_link = backup_dir / f"{target_file.name}.latest.bak"

    if action == "create":
        if not target_file.exists():
            logger.warning(f"Cannot backup, target does not exist: {target_file}")
            return False
        
        shutil.copy2(target_file, backup_path)
        
        latest_link.unlink(missing_ok=True)
        latest_link.symlink_to(backup_path.name)
        
        logger.info(f"Backup created at: {backup_path}")
        print(f"[+] Backup created: {backup_path}")
        return True

    elif action == "restore":
        if not latest_link.exists():
            print("[-] No backup found to restore.")
            return False
        
        shutil.copy2(latest_link, target_file)
        logger.info(f"Restored from backup: {latest_link}")
        print(f"[+] Successfully restored configuration from backup.")
        return True
    
    return False

# =============================================================================
# MAIN CLI ROUTER
# =============================================================================
if __name__ == "__main__":
    help_epilog = """
EXAMPLES:
  1. Launch the TUI normally:
     python main.py hypr.input_tui

  2. Headlessly restore all default values (with a backup first):
     python main.py hypr.input_tui --backup --default

  3. Headlessly change a specific setting (use scope.key if ambiguous):
     python main.py hypr.input_tui --set border_size=3

  4. Generate Markdown documentation for a schema:
     python main.py hypr.input_tui --export-docs > docs.md
    """

    parser = argparse.ArgumentParser(
        description="Dusky TUI Master Router - Advanced Configuration Ecosystem",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=help_epilog
    )
    
    parser.add_argument(
        "module", 
        help="Path, dot-notation, or relative path to the schema file.\n(e.g., 'hypr.input_tui' or '~/user_scripts/hypr/input_tui.py')"
    )
    
    safety_group = parser.add_argument_group("Safety & Backups")
    safety_group.add_argument("--backup", action="store_true", help="Create a backup of the target config before doing anything.")
    safety_group.add_argument("--restore", action="store_true", help="Restore the target config from the latest backup and exit.")
    
    # IMPROVEMENT: Use mutually exclusive group to prevent silent CLI fall-through via hard exits
    headless_group = parser.add_mutually_exclusive_group()
    headless_group.add_argument("--default", action="store_true", help="Headlessly restore all schema items to their default values.")
    headless_group.add_argument("--reset-key", metavar="KEY", type=str, help="Headlessly restore a specific key to its default.")
    headless_group.add_argument("--set", metavar="KEY=VALUE", type=str, help="Headlessly set a value (format: target_key=new_value).")
    headless_group.add_argument("--export-state", action="store_true", help="Print the parsed AST state as JSON to stdout and exit.")
    headless_group.add_argument("--export-docs", action="store_true", help="Generate a Markdown documentation file based on the schema and exit.")

    parser.add_argument("--log", action="store_true", help="Enable file logging to ~/Documents/logs/tui/")

    args = parser.parse_args()

    # --- 1. SMART SCHEMA PATH RESOLUTION ---
    target_arg = args.module
    direct_path = Path(target_arg).expanduser().resolve()
    schema_path = None

    if direct_path.exists() and direct_path.is_file():
        schema_path = direct_path
    else:
        clean_arg = target_arg.replace(".", "/").lstrip("/")
        if not clean_arg.endswith(".py"):
            clean_arg += ".py"
        
        for base_dir in SCHEMA_SEARCH_PATHS:
            potential_path = base_dir / clean_arg
            if potential_path.exists() and potential_path.is_file():
                schema_path = potential_path
                break

    if not schema_path:
        print(f"[-] Schema module '{target_arg}' not found.")
        print("[i] Checked direct path and the following directories:")
        for p in SCHEMA_SEARCH_PATHS:
            print(f"    - {p}")
        sys.exit(1)

    module_name = schema_path.stem
    logger = setup_logging(module_name, args.log)

    spec = importlib.util.spec_from_file_location(module_name, schema_path)
    if spec is None or spec.loader is None:
        print(f"[-] Failed to load schema module: Invalid module spec for '{schema_path}'.")
        sys.exit(1)

    schema_module = importlib.util.module_from_spec(spec)
    
    # IMPROVEMENT: Prefix namespace mapping to strictly prevent silent standard library clobbering
    safe_module_namespace = f"dusky_schema_{module_name}"
    sys.modules[safe_module_namespace] = schema_module
    
    spec.loader.exec_module(schema_module)

    # Extract configuration variables
    try:
        SCHEMA = schema_module.SCHEMA
        TABS = schema_module.TABS
        TARGET_FILE = Path(schema_module.TARGET_FILE).expanduser().resolve()
        THEME_FILE = getattr(schema_module, "THEME_FILE", None)
        APP_TITLE = getattr(schema_module, "APP_TITLE", "Dusky Configurator")
        DEFAULT_MODE = getattr(schema_module, "DEFAULT_MODE", "auto")
    except AttributeError as e:
        print(f"[-] Invalid schema file '{schema_path.name}'. Missing required attribute: {e}")
        sys.exit(1)

    logger.info(f"Loaded schema: {schema_path} | Target: {TARGET_FILE}")

    # --- 2. PRE-FLIGHT CHECKS (Backups / Restores) ---
    is_headless = any([args.default, args.reset_key, args.set, args.export_state, args.export_docs])

    if args.restore:
        if not manage_backup(TARGET_FILE, "restore", logger):
            sys.exit(1)
        if not is_headless and not args.backup:
            sys.exit(0)
            
    if args.backup:
        manage_backup(TARGET_FILE, "create", logger)
        if not is_headless:
            sys.exit(0)

    # --- 3. INSTANTIATE ENGINE ---
    engine = HyprlandLuaEngine(config_path=str(TARGET_FILE))

    # --- 4. HEADLESS OPERATIONS ---
    if is_headless:
        engine.load_state() 

        if args.export_state:
            print(json.dumps(engine.cache, indent=2))
            sys.exit(0)
            
        if args.export_docs:
            print(f"# Configuration Reference: {APP_TITLE}\n")
            for tab_idx, items in SCHEMA.items():
                print(f"## {TABS[tab_idx]}")
                for item in items:
                    if item.type_ == "action": continue
                    print(f"### `{item.key}`")
                    print(f"- **Type:** `{item.type_}`")
                    print(f"- **Default:** `{item.default}`")
                    if item.extended_help:
                        print(f"\n> {item.extended_help.replace('**', '')}\n")
            sys.exit(0)

        # IMPROVEMENT: Prevent data loss via schema flattening collisions. Map both direct & compound keys safely.
        flat_schema = {}
        for items in SCHEMA.values():
            for item in items:
                if item.type_ == "action":
                    continue
                
                scoped_key = f"{item.scope}.{item.key}"
                flat_schema[scoped_key] = item
                
                # Flag collision if multiple scopes share the same key
                if item.key in flat_schema:
                    if flat_schema[item.key] is not item:
                        flat_schema[item.key] = None
                else:
                    flat_schema[item.key] = item

        if args.set:
            if "=" not in args.set:
                print("[-] Format error: Use --set key=value")
                sys.exit(1)
                
            target_key, val_str = args.set.split("=", 1)
            if target_key not in flat_schema:
                print(f"[-] Key '{target_key}' not found in schema.")
                sys.exit(1)
                
            item = flat_schema[target_key]
            if item is None:
                print(f"[-] Key '{target_key}' is ambiguous across multiple scopes. Please specify using 'scope.{target_key}'.")
                sys.exit(1)

            logger.info(f"Headless Injection: {target_key} -> {val_str}")
            success, msg, _ = engine.write_value(item.key, item.scope, val_str)
            print(f"[{'OK' if success else 'FAIL'}] {msg}")
            sys.exit(0 if success else 1)

        if args.reset_key:
            if args.reset_key not in flat_schema:
                print(f"[-] Key '{args.reset_key}' not found in schema.")
                sys.exit(1)
                
            item = flat_schema[args.reset_key]
            if item is None:
                print(f"[-] Key '{args.reset_key}' is ambiguous across multiple scopes. Please specify using 'scope.{args.reset_key}'.")
                sys.exit(1)

            val = "true" if item.default is True else "false" if item.default is False else "nil" if item.default is None else str(item.default)
            logger.info(f"Headless Reset Key: {args.reset_key} -> {val}")
            success, msg, _ = engine.write_value(item.key, item.scope, val)
            print(f"[{'OK' if success else 'FAIL'}] {msg}")
            sys.exit(0 if success else 1)

        if args.default:
            logger.info("Initiating Full Headless Default Restoration")
            success_count, skip_count = 0, 0
            
            # Use id() mapping to ensure we don't duplicate executions for keys vs scoped_keys
            unique_items = {id(item): item for item in flat_schema.values() if item is not None}.values()
            
            for item in unique_items:
                val = "true" if item.default is True else "false" if item.default is False else "nil" if item.default is None else str(item.default)
                success, msg, _ = engine.write_value(item.key, item.scope, val)
                if success: success_count += 1
                else: skip_count += 1
            
            print(f"[*] Restoration Complete. Reset: {success_count} | Skipped: {skip_count}")
            sys.exit(0)

    # --- 5. INTERACTIVE TUI EXECUTION ---
    logger.info("Launching TUI")
    app = DuskyTUI(
        engine=engine, 
        schema=SCHEMA, 
        tabs=TABS, 
        title=APP_TITLE,
        theme_path=THEME_FILE,
        default_mode=DEFAULT_MODE
    )
    
    app.run()
