#!/usr/bin/env bash
# Initializes or validates the 'edit_here' user configuration overlay for Hyprland.
#              Ensures all template files exist.
#              Designed for Arch Linux / Hyprland 0.55+ / UWSM environments.
#              All configuration files use Lua syntax (.lua) as of Hyprland 0.55.
#              hyprlang (.conf) is deprecated and will be dropped in a future release.
#
# Usage:       ./005_hypr_custom_config_setup.sh [--force]
#              --force: Backs up existing 'edit_here' dir and regenerates all templates.
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. Strict Mode & Configuration
# ------------------------------------------------------------------------------
set -euo pipefail

# --- ANSI Color Codes ---
readonly RED=$'\033[0;31m'
readonly GREEN=$'\033[0;32m'
readonly YELLOW=$'\033[0;33m'
readonly BLUE=$'\033[0;34m'
readonly RESET=$'\033[0m'

# --- Paths ---
readonly HYPR_DIR="${HOME}/.config/hypr"
readonly EDIT_DIR="${HYPR_DIR}/edit_here"
readonly EDIT_SOURCE_DIR="${EDIT_DIR}/source"
readonly MAIN_CONF="${HYPR_DIR}/hyprland.lua"
readonly NEW_CONF="${EDIT_DIR}/hyprland.lua"

# Lua require() strings that are inserted into / searched for in hyprland.lua.
# These are the EXACT literal strings written to and grepped from the main config.
#
# Dot-separated Lua module paths map to filesystem paths relative to ~/.config/hypr/:
#   "edit_here.source.default_apps"  ->  ~/.config/hypr/edit_here/source/default_apps.lua
#   "edit_here.hyprland"             ->  ~/.config/hypr/edit_here/hyprland.lua
readonly APPS_DEFAULTS_REQUIRE='require("edit_here.source.default_apps")'
readonly OVERLAY_REQUIRE='require("edit_here.hyprland")'

# ==============================================================================
# CONFIG FILE LIST  <<<  EDIT THIS TO ADD / REMOVE FILES  >>>
# ==============================================================================
# Each entry is a .lua filename created inside:
#   ~/.config/hypr/edit_here/source/
#
# The script will automatically:
#   - Create a template file if it does not already exist
#   - Append a require() line for it to ~/.config/hypr/edit_here/hyprland.lua
#     (the loader that is sourced at the bottom of hyprland.lua)
#
# "default_apps.lua" is SPECIAL:
#   It is require()d at the very TOP of hyprland.lua so that its global
#   variables are available to every other file.  If you rename it you must
#   also update the APPS_DEFAULTS_REQUIRE variable above.
#
# FUTURE EXPANSION EXAMPLE — splitting input.lua into sub-files:
#   Remove "input.lua" and add:
#     "keyboard.lua"
#     "touchpad.lua"
#     "cursor.lua"
#   Each new file is automatically picked up on next run.
# ==============================================================================
readonly -a CONFIG_FILES=(
    # --- Core (required at top of hyprland.lua via APPS_DEFAULTS_REQUIRE) ---
    "default_apps.lua"

    # --- Display & Layout ---
    "monitors.lua"
    "appearance.lua"
    "workspace_rules.lua"

    # --- Behavior ---
    "keybinds.lua"
    "input.lua"
    "window_rules.lua"

    # --- Session ---
    "autostart.lua"
    "environment_variables.lua"
    "plugins.lua"

    # --- Future files: add new entries here ---
    # "keyboard.lua"
    # "touchpad.lua"
    # "cursor.lua"
)

# ------------------------------------------------------------------------------
# 2. Helper Functions
# ------------------------------------------------------------------------------
log_info()    { printf '%s[INFO]%s %s\n'    "${BLUE}"   "${RESET}" "${1:-}"; }
log_success() { printf '%s[OK]%s   %s\n'    "${GREEN}"  "${RESET}" "${1:-}"; }
log_warn()    { printf '%s[WARN]%s %s\n'    "${YELLOW}" "${RESET}" "${1:-}"; }
log_error()   { printf '%s[ERR]%s  %s\n'    "${RED}"    "${RESET}" "${1:-}" >&2; }

# ------------------------------------------------------------------------------
# Generates template content for each configuration file.
# All files use Lua syntax — comments are --, not #.
#
# NOTE: We use <<'EOF' (single-quoted) heredocs to prevent shell variable
# expansion, so Lua strings like "edit_here.source.foo" are written literally.
#
# EDIT THIS FUNCTION to update the default template for any file.
# ------------------------------------------------------------------------------
get_file_content() {
    local -r filename="${1:-}"

    case "${filename}" in

        # ======================================================================
        "default_apps.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: default_apps.lua
-- ==============================================================================
-- Override default applications here.
-- These are Lua GLOBALS (defined WITHOUT the 'local' keyword) so that they
-- are accessible in every file require()d after this one in hyprland.lua.
--
-- This file is require()d at the very TOP of hyprland.lua — before all
-- other config files — so these variables are always in scope.
--
-- See: https://wiki.hypr.land/Configuring/Start/
-- ==============================================================================

-- terminal    = "kitty"
-- fileManager = "nemo"
-- menu        = "rofi -show drun"
-- browser     = "firefox"
-- textEditor  = "nvim"
EOF
            ;;

        # ======================================================================
        "monitors.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: monitors.lua
-- ==============================================================================
-- Add your monitor configuration here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
-- This file can also be managed with dusky monitor from the rofi menu or
-- from dusky control center.
--
-- Syntax:
--   hl.monitor({ output = "DP-1", mode = "2560x1440@144", position = "0x0", scale = 1 })
--   hl.monitor({ output = "",     mode = "preferred",     position = "auto", scale = "auto" })
--
-- See: https://wiki.hypr.land/Configuring/Basics/Monitors/
-- ==============================================================================

EOF
            ;;

        # ======================================================================
        "keybinds.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: keybinds.lua
-- ==============================================================================
-- Add your custom keybinds here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
-- This file can also be managed with dusky keybinds manager from the rofi
-- menu or from dusky control center.
--
-- Syntax:
--   local mainMod = "SUPER"
--   hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd(terminal))
--   hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd("kitty"), { description = "Launch terminal" })
--
-- NOTE: 'terminal', 'browser', etc. are globals defined in default_apps.lua.
--
-- See: https://wiki.hypr.land/Configuring/Basics/Binds/
-- ==============================================================================

-- local mainMod = "SUPER"

-- -- File Manager
-- hl.bind(mainMod .. " + E", hl.dsp.exec_cmd("uwsm-app -- " .. fileManager),
--     { description = "File Manager" })

-- -- Browser
-- hl.bind(mainMod .. " + W", hl.dsp.exec_cmd("uwsm-app -- " .. browser),
--     { description = "Launch Browser" })

-- -- Text Editor
-- hl.bind(mainMod .. " + R",
--     hl.dsp.exec_cmd("uwsm-app -- " .. terminal .. " --class nvim -e " .. textEditor),
--     { description = "Open Text Editor" })

-- -- Terminal
-- hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd("uwsm-app -- " .. terminal),
--     { description = "Launch Terminal" })
EOF
            ;;

        # ======================================================================
        "appearance.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: appearance.lua
-- ==============================================================================
-- Add your custom appearance settings here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
-- This file can also be managed with dusky appearance from the rofi menu or
-- from dusky control center.
--
-- Syntax:
--   hl.config({
--       general = {
--           gaps_in  = 6,
--           gaps_out = 12,
--           border_size = 2,
--           col = {
--               active_border   = { colors = {"rgba(33ccffee)", "rgba(00ff99ee)"}, angle = 45 },
--               inactive_border = "rgba(595959aa)",
--           },
--           layout = "dwindle",
--       },
--       decoration = {
--           rounding = 6,
--           shadow = { enabled = false },
--           blur   = { enabled = false },
--       },
--   })
--
-- See: https://wiki.hypr.land/Configuring/Basics/Variables/
-- See: https://wiki.hypr.land/Configuring/Advanced-and-Cool/Animations/
-- ==============================================================================

-- -------------------------------------------------------------------------------------------------
-- THEME SOURCE
-- -------------------------------------------------------------------------------------------------
-- Sourcing colors generated by Matugen.
-- In Lua configs, external Lua files can be require()d; plain shell-style
-- 'source =' is no longer valid.  If matugen generates a .lua file, use:
--   require("matugen.generated.hyprland-colors")
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 1. GENERAL APPEARANCE
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 2. DECORATION (rounding, opacity, shadows, blur)
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 3. ANIMATIONS
-- -------------------------------------------------------------------------------------------------
-- require("source.animations.active.active")

-- -------------------------------------------------------------------------------------------------
-- 4. LAYOUTS (dwindle / master)
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 5. MISCELLANEOUS & PERFORMANCE
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 6. BINDS (visual / appearance-specific bind options)
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 7. SMART GAPS (single-window override)
-- -------------------------------------------------------------------------------------------------
-- hl.workspace_rule({ workspace = "w[tv1]", gaps_out = 10, gaps_in = 0 })
-- hl.workspace_rule({ workspace = "f[1]",   gaps_out = 10, gaps_in = 0 })
EOF
            ;;

        # ======================================================================
        "autostart.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: autostart.lua
-- ==============================================================================
-- Add your custom autostart entries here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
--
-- Syntax:
--   hl.on("hyprland.start", function()
--       hl.exec_cmd("waybar")
--       hl.exec_cmd("nm-applet")
--   end)
--
-- See: https://wiki.hypr.land/Configuring/Basics/Autostart/
-- ==============================================================================

-- hl.on("hyprland.start", function()
--     -- EG: dusky glance (uncomment any one)
--     -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --cpu")
--     -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --ram")
--     -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --temp")
--     -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --battery")
--     -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --network")
--     -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --uptime")
--     -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --workspace")
--     -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --clock")
-- end)
EOF
            ;;

        # ======================================================================
        "plugins.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: plugins.lua
-- ==============================================================================
-- Add your plugin configuration here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
--
-- See: https://wiki.hypr.land/Plugins/Using-Plugins/
-- ==============================================================================

EOF
            ;;

        # ======================================================================
        "window_rules.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: window_rules.lua
-- ==============================================================================
-- Add your custom window rules here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
--
-- Syntax:
--   hl.window_rule({
--       name  = "my-rule-name",            -- unique identifier (required)
--       match = { class = "^kitty$" },     -- match table
--       float = true,
--   })
--
--   hl.layer_rule({
--       name  = "my-layer-rule",
--       match = { namespace = "^waybar$" },
--       blur  = true,
--   })
--
-- See: https://wiki.hypr.land/Configuring/Basics/Window-Rules/
-- ==============================================================================

EOF
            ;;

        # ======================================================================
        "workspace_rules.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: workspace_rules.lua
-- ==============================================================================
-- Add your custom workspace rules here.
-- These will override or add to the defaults found in:
--   ~/.config/hypr/source/workspace_rules.lua
--
-- This file can also be managed with dusky workspace manager TUI,
-- which can be found in dusky control center.
--
-- Syntax:
--   hl.workspace_rule({ workspace = "1",       layout = "dwindle" })
--   hl.workspace_rule({ workspace = "r[11-99]", layout = "dwindle" })
--
-- NOTE: layoutopt keys (orientation, direction) are passed inside layout_opts:
--   hl.workspace_rule({
--       workspace   = "2",
--       layout      = "master",
--       layout_opts = { orientation = "top" },
--   })
--
-- See: https://wiki.hypr.land/Configuring/Basics/Workspace-Rules/
-- ==============================================================================

-- --- Global Rules ---
-- hl.workspace_rule({ workspace = "r[11-99]", layout = "dwindle" })

-- --- Individual Workspaces (1-10) ---
-- for i = 1, 10 do
--     hl.workspace_rule({ workspace = tostring(i), layout = "dwindle" })
-- end
EOF
            ;;

        # ======================================================================
        "environment_variables.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: environment_variables.lua
-- ==============================================================================
-- Add your custom environment variables here.
-- These will override or add to the defaults found in:
--   ~/.config/hypr/source/environment_variables.lua
--
-- NOTE: It is strongly recommended to place environment variables in the
-- UWSM files at ~/.config/uwsm/{env,env-hyprland} instead, as those are
-- sourced before Hyprland starts and apply to the full session.
--
-- Syntax:
--   hl.env("XCURSOR_SIZE",    "24")
--   hl.env("HYPRCURSOR_SIZE", "24")
--
-- See: https://wiki.hypr.land/Configuring/Advanced-and-Cool/Environment-variables/
-- ==============================================================================

EOF
            ;;

        # ======================================================================
        "input.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: input.lua
-- ==============================================================================
-- Add your custom input settings here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
-- This file can also be managed with dusky input from the rofi menu or
-- from dusky control center.
--
-- Syntax:
--   hl.config({
--       input = {
--           kb_layout  = "us",
--           kb_options = "",
--           follow_mouse = 1,
--           sensitivity  = 0,
--           touchpad = {
--               natural_scroll   = true,
--               tap_to_click     = true,
--               disable_while_typing = true,
--           },
--       },
--       cursor = {
--           no_hardware_cursors = 2,
--           sync_gsettings_theme = true,
--       },
--   })
--
-- For per-device configuration (overrides globals for a specific device):
--   hl.device({
--       name        = "my-epic-mouse-v1",   -- from: hyprctl devices
--       sensitivity = -0.5,
--   })
--
-- See: https://wiki.hypr.land/Configuring/Basics/Variables/
-- See: https://wiki.hypr.land/Configuring/Advanced-and-Cool/Devices/
-- ==============================================================================

-- -------------------------------------------------------------------------------------------------
-- 1. KEYBOARD & LANGUAGE
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 2. MOUSE & POINTER ACCELERATION
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 3. SCROLLING & TRACKBALLS
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 4. TOUCHPAD
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 5. CURSOR BEHAVIOR & RENDERING
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 6. GESTURE PHYSICS (Tuning)
-- -------------------------------------------------------------------------------------------------
-- hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })

-- -------------------------------------------------------------------------------------------------
-- 7. TABLET CONFIGURATION
-- -------------------------------------------------------------------------------------------------
-- hl.device({
--     name   = "wacom-intuos-s-2-pen",
--     output = "DP-1",
-- })
EOF
            ;;

        # ======================================================================
        *)
            # Fallback for any future files added to CONFIG_FILES
            printf '-- ==============================================================================\n'
            printf '-- USER CONFIGURATION: %s\n' "${filename}"
            printf '-- ==============================================================================\n'
            printf '-- Add your custom settings here.\n'
            printf '-- ==============================================================================\n\n'
            ;;
    esac
}

# ------------------------------------------------------------------------------
# 3. Privilege & Pre-flight Checks
# ------------------------------------------------------------------------------
if [[ "${EUID}" -eq 0 ]]; then
    log_error "This script must NOT be run as root."
    log_error "It modifies user configuration files in ${HOME}."
    exit 1
fi

# Ensure base directory structure exists FIRST
if [[ ! -d "${HYPR_DIR}" ]]; then
    log_info "Creating Hyprland config directory: ${HYPR_DIR}"
    mkdir -p -- "${HYPR_DIR}"
fi

if [[ ! -f "${MAIN_CONF}" ]]; then
    log_warn "Main Hyprland config not found at ${MAIN_CONF}."
    log_warn "Creating empty file. You will need to populate it with your base config."
    touch -- "${MAIN_CONF}"
fi

# ------------------------------------------------------------------------------
# 4. Handle Arguments
# ------------------------------------------------------------------------------
force_mode=false

while [[ $# -gt 0 ]]; do
    case "${1}" in
        --force)
            force_mode=true
            shift
            ;;
        *)
            log_error "Unknown argument: ${1}"
            log_error "Usage: ${0##*/} [--force]"
            exit 1
            ;;
    esac
done

if [[ "${force_mode}" == true && -d "${EDIT_DIR}" ]]; then
    # Bash 5.0+ builtin timestamp (no external 'date' command needed)
    printf -v backup_timestamp '%(%Y%m%d_%H%M%S)T' -1
    backup_name="edit_here.bak_${backup_timestamp}"

    log_warn "Force mode: Backing up '${EDIT_DIR}' to '${HYPR_DIR}/${backup_name}'..."
    mv -- "${EDIT_DIR}" "${HYPR_DIR}/${backup_name}"
    log_success "Backup complete. Proceeding with clean regeneration."
fi

# ------------------------------------------------------------------------------
# 5. Main Logic: Create or Verify Overlay
# ------------------------------------------------------------------------------
log_info "Initializing/Verifying Hyprland user configuration overlay..."

# Ensure directory structure exists
if [[ ! -d "${EDIT_SOURCE_DIR}" ]]; then
    log_info "Creating directory: ${EDIT_SOURCE_DIR}"
    mkdir -p -- "${EDIT_SOURCE_DIR}"
else
    log_info "Directory exists: ${EDIT_SOURCE_DIR} (verifying contents...)"
fi

# Iterate and create missing files using the content function
for file in "${CONFIG_FILES[@]}"; do
    target_file="${EDIT_SOURCE_DIR}/${file}"

    if [[ -f "${target_file}" ]]; then
        log_info "  - Exists: ${file}"
    else
        log_warn "  - Missing: ${file} -> Creating with default template..."
        get_file_content "${file}" > "${target_file}"
        log_success "    Created: ${file}"
    fi
done

# Generate the user overlay loader: edit_here/hyprland.lua
# Dynamically built from CONFIG_FILES to prevent list drift.
if [[ -f "${NEW_CONF}" ]]; then
    log_info "Loader file exists: ${NEW_CONF}"
else
    log_warn "Loader file missing: ${NEW_CONF} -> Creating..."

    # Write header
    cat > "${NEW_CONF}" <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION OVERLAY LOADER
-- ==============================================================================
-- This file is require()d at the bottom of hyprland.lua.
-- It loads all your custom configuration files from 'source/'.
-- Edit the specific files in 'source/' to apply your changes.
--
-- NOTE: 'default_apps.lua' is intentionally excluded here — it is require()d
-- directly at the top of hyprland.lua so its globals are available first.
-- ==============================================================================

EOF

    # Dynamically append require() lines (skip default_apps — handled separately)
    for file in "${CONFIG_FILES[@]}"; do
        if [[ "${file}" == "default_apps.lua" ]]; then
            continue
        fi
        # Strip .lua extension to form the Lua module path
        module_name="${file%.lua}"
        printf 'require("edit_here.source.%s")\n' "${module_name}" >> "${NEW_CONF}"
    done

    log_success "Created loader: ${NEW_CONF}"
fi

# ------------------------------------------------------------------------------
# 6. Modify Main Configuration (hyprland.lua)
# ------------------------------------------------------------------------------
log_info "Verifying main configuration at '${MAIN_CONF}'..."

# A. Insert default_apps require() at the TOP of the file (priority — globals first)
#    Uses grep -Fq (fixed-string, quiet) to match the exact require() string.
if grep -Fq "${APPS_DEFAULTS_REQUIRE}" "${MAIN_CONF}"; then
    log_success "Main config already contains default_apps require()."
else
    # Robust prepend via temp file — handles empty files safely
    temp_file=$(mktemp)
    {
        printf '%s\n' "${APPS_DEFAULTS_REQUIRE}"
        cat "${MAIN_CONF}"
    } > "${temp_file}" && mv -- "${temp_file}" "${MAIN_CONF}"

    log_success "Prepended '${APPS_DEFAULTS_REQUIRE}' to the top of '${MAIN_CONF}'."
fi

# B. Insert overlay loader require() at the BOTTOM of the file (last override wins)
if grep -Fq "${OVERLAY_REQUIRE}" "${MAIN_CONF}"; then
    log_success "Main config already contains the overlay loader require()."
else
    printf '\n-- Source User Custom Config Overlay\n%s\n' "${OVERLAY_REQUIRE}" >> "${MAIN_CONF}"
    log_success "Appended '${OVERLAY_REQUIRE}' to '${MAIN_CONF}'."
fi

# ------------------------------------------------------------------------------
# 7. Completion
# ------------------------------------------------------------------------------
printf '\n'
log_success "Setup/Verification complete!"
log_info  "Your custom configs are located in: ${EDIT_DIR}"
log_info  "To apply changes, save any .lua file (auto-reload) or run 'hyprctl reload'."
