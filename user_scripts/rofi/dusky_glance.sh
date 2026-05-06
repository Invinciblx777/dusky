#!/usr/bin/env bash
# ==============================================================================
# DUSKY GLANCE - ROFI FRONTEND & SMART WRAPPER
# ==============================================================================

set -euo pipefail

# Hardcoded absolute path to the daemon
DAEMON_SCRIPT="$HOME/user_scripts/mako_osd/dusky_glance/dusky_glance_daemon.sh"

# --- CLI HELP MENU ---
# Intercept help flags before passing to the daemon to print a clean manual
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    printf "\e[1;34m::\e[0m \e[1mDusky Glance\e[0m - Smart HUD Wrapper\n\n"
    printf "\e[1mUSAGE:\e[0m\n"
    printf "  dusky_glance.sh [COMMAND]\n\n"
    printf "If no command is provided, the Rofi GUI will launch natively.\n\n"
    printf "\e[1mCOMMANDS:\e[0m\n"
    printf "  \e[32m--pomodoro\e[0m      Start a 25-minute Pomodoro timer\n"
    printf "  \e[32m--timer <sec>\e[0m   Start a custom timer for <sec> seconds\n"
    printf "  \e[32m--stopwatch\e[0m     Start the stopwatch\n"
    printf "  \e[32m--clock\e[0m         Show the live clock\n"
    printf "  \e[32m--cpu\e[0m           Show live CPU usage\n"
    printf "  \e[32m--ram\e[0m           Show live RAM usage\n"
    printf "  \e[32m--temp\e[0m          Show CPU temperature\n"
    printf "  \e[32m--battery\e[0m       Show battery status and power draw\n"
    printf "  \e[32m--network\e[0m       Show live network upload/download speed\n"
    printf "  \e[31m--stop\e[0m          Stop any running monitor and clear the screen\n"
    printf "  \e[34m--help, -h\e[0m      Show this help page\n"
    exit 0
fi

# --- HEADLESS PASSTHROUGH ---
# If you pass arguments via a keybind, bypass Rofi entirely
# and send the command directly to the background daemon.
if (( $# > 0 )); then
    "$DAEMON_SCRIPT" "$@" &
    disown
    exit 0
fi

declare -agr ROFI_CMD=(rofi -dmenu -i -no-custom -theme-str 'window {width: 20%;} listview {lines: 10;}')

declare -agr MENU_OPTIONS=(
    '🍅  Pomodoro (25m)'
    '⏳  Custom Timer'
    '⏱️  Stopwatch'
    '🕒  Live Clock'
    '💻  CPU Usage'
    '🧠  Memory (RAM)'
    '🌡️  CPU Temp'
    '🔋  Battery / Power'
    '🌐  Network Speed'
    '🛑  Stop / Clear'
)

choice=$(printf '%s\n' "${MENU_OPTIONS[@]}" | "${ROFI_CMD[@]}" -p "Glance") || exit 0

case "$choice" in
    '🍅  Pomodoro (25m)') "$DAEMON_SCRIPT" --pomodoro & disown ;;
    '⏳  Custom Timer')
        mins=$(rofi -dmenu -i -p "Minutes" -theme-str 'window {width: 15%;} listview {lines: 0;}') || exit 0
        if [[ "$mins" =~ ^[0-9]{1,5}$ ]]; then
            clean_mins=$(( 10#$mins ))
            if (( clean_mins > 0 && clean_mins <= 1440 )); then 
                "$DAEMON_SCRIPT" --timer "$(( clean_mins * 60 ))" & disown
            else
                notify-send -u low "Invalid time entered."
            fi
        else
            notify-send -u low "Invalid format."
        fi
        ;;
    '⏱️  Stopwatch')      "$DAEMON_SCRIPT" --stopwatch & disown ;;
    '🕒  Live Clock')     "$DAEMON_SCRIPT" --clock & disown ;;
    '💻  CPU Usage')      "$DAEMON_SCRIPT" --cpu & disown ;;
    '🧠  Memory (RAM)')   "$DAEMON_SCRIPT" --ram & disown ;;
    '🌡️  CPU Temp')       "$DAEMON_SCRIPT" --temp & disown ;;
    '🔋  Battery / Power')"$DAEMON_SCRIPT" --battery & disown ;;
    '🌐  Network Speed')  "$DAEMON_SCRIPT" --network & disown ;;
    '🛑  Stop / Clear')   "$DAEMON_SCRIPT" --stop & disown ;;
esac
