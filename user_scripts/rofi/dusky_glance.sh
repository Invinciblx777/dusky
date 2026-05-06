#!/usr/bin/env bash
# ==============================================================================
# DUSKY GLANCE - ROFI FRONTEND & SMART WRAPPER
# ==============================================================================

set -euo pipefail

DAEMON_SCRIPT="$HOME/user_scripts/mako_osd/dusky_glance/dusky_glance_daemon.sh"

# --- CONFIGURATION STATE ---
SETTINGS_DIR="$HOME/.config/dusky/settings/dusky_glance"
mkdir -p "$SETTINGS_DIR"
TIMER_STATE="$SETTINGS_DIR/timer.state"
POMO_STATE="$SETTINGS_DIR/pomodoro.state"

# --- HELPER: FORMAT SECONDS FOR MENU ---
fmt_t() {
    local s="${1:-0}"
    local m=$((s / 60))
    local rm=$((s % 60))
    if (( m > 0 && rm > 0 )); then
        echo "${m}m ${rm}s"
    elif (( m > 0 )); then
        echo "${m}m"
    else
        echo "${s}s"
    fi
}

# --- CLI HELP MENU ---
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    printf "\e[1;34m::\e[0m \e[1mDusky Glance\e[0m - Smart HUD Wrapper\n\n"
    printf "\e[1mUSAGE:\e[0m\n  dusky_glance.sh [COMMAND]\n\n"
    printf "\e[1mCOMMANDS:\e[0m\n"
    printf "  \e[32m--pomodoro\e[0m      Start Pomodoro (Runs last saved config natively)\n"
    printf "  \e[32m--timer\e[0m         Start Timer (Runs last saved config natively)\n"
    printf "  \e[32m--stopwatch\e[0m     Start the stopwatch\n"
    printf "  \e[32m--clock\e[0m         Show the live clock\n"
    printf "  \e[32m--cpu\e[0m           Show live CPU usage\n"
    printf "  \e[32m--ram\e[0m           Show live RAM usage\n"
    printf "  \e[32m--temp\e[0m          Show CPU temperature\n"
    printf "  \e[32m--battery\e[0m       Show battery status and power draw\n"
    printf "  \e[32m--network\e[0m       Show live network speed\n"
    printf "  \e[31m--stop\e[0m          Stop any running monitor and clear the screen\n"
    exit 0
fi

# --- HEADLESS PASSTHROUGH (KEYBINDINGS) ---
if (( $# > 0 )); then
    cmd="$1"
    case "$cmd" in
        --pomodoro)
            last_pw=1500; last_pb=300
            [[ -f "$POMO_STATE" ]] && read -r last_pw last_pb < "$POMO_STATE" || true
            "$DAEMON_SCRIPT" --pomodoro "$last_pw" "$last_pb" & disown
            ;;
        --timer)
            last_t=900
            [[ -f "$TIMER_STATE" ]] && last_t=$(<"$TIMER_STATE")
            "$DAEMON_SCRIPT" --timer "$last_t" & disown
            ;;
        *)
            "$DAEMON_SCRIPT" "$@" & disown
            ;;
    esac
    exit 0
fi

# --- GUI EXECUTION ---
declare -agr ROFI_CMD=(rofi -dmenu -i -no-custom -theme-str 'window {width: 20%;} listview {lines: 10;}')
# WIDENED to 35% so the sub-menu text doesn't truncate
declare -agr ROFI_SUB=(rofi -dmenu -i -no-custom -theme-str 'window {width: 35%;} listview {lines: 3;}')

declare -agr MENU_OPTIONS=(
    '🍅  Pomodoro'
    '⏳  Timer'
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
    '🍅  Pomodoro')
        last_pw=1500; last_pb=300
        [[ -f "$POMO_STATE" ]] && read -r last_pw last_pb < "$POMO_STATE" || true
        
        p_opts=(
            "▶️  Start Last ($(fmt_t "$last_pw") Work / $(fmt_t "$last_pb") Break)"
            "⚙️  Set in Minutes"
            "⚙️  Set in Seconds"
        )
        pchoice=$(printf '%s\n' "${p_opts[@]}" | "${ROFI_SUB[@]}" -p "Pomodoro") || exit 0
        
        if [[ "$pchoice" == *"Start Last"* ]]; then
            "$DAEMON_SCRIPT" --pomodoro "$last_pw" "$last_pb" & disown
            
        elif [[ "$pchoice" == *"Minutes"* ]]; then
            w=$(rofi -dmenu -i -p "Work Duration (Mins)" -theme-str 'window {width: 20%;} listview {lines: 0;}') || exit 0
            w=${w//[!0-9]/}; [[ -z "$w" ]] && exit 0
            
            b=$(rofi -dmenu -i -p "Break Duration (Mins) [0 for none]" -theme-str 'window {width: 20%;} listview {lines: 0;}') || exit 0
            b=${b//[!0-9]/}; [[ -z "$b" ]] && b=0
            
            echo "$((w*60)) $((b*60))" > "$POMO_STATE"
            "$DAEMON_SCRIPT" --pomodoro "$((w*60))" "$((b*60))" & disown
            
        elif [[ "$pchoice" == *"Seconds"* ]]; then
            w=$(rofi -dmenu -i -p "Work Duration (Secs)" -theme-str 'window {width: 20%;} listview {lines: 0;}') || exit 0
            w=${w//[!0-9]/}; [[ -z "$w" ]] && exit 0
            
            b=$(rofi -dmenu -i -p "Break Duration (Secs) [0 for none]" -theme-str 'window {width: 20%;} listview {lines: 0;}') || exit 0
            b=${b//[!0-9]/}; [[ -z "$b" ]] && b=0
            
            echo "$w $b" > "$POMO_STATE"
            "$DAEMON_SCRIPT" --pomodoro "$w" "$b" & disown
        fi
        ;;
        
    '⏳  Timer')
        last_t=900
        [[ -f "$TIMER_STATE" ]] && last_t=$(<"$TIMER_STATE")
        
        t_opts=(
            "▶️  Start Last ($(fmt_t "$last_t"))"
            "⚙️  Set in Minutes"
            "⚙️  Set in Seconds"
        )
        tchoice=$(printf '%s\n' "${t_opts[@]}" | "${ROFI_SUB[@]}" -p "Timer") || exit 0
        
        if [[ "$tchoice" == *"Start Last"* ]]; then
            "$DAEMON_SCRIPT" --timer "$last_t" & disown
            
        elif [[ "$tchoice" == *"Minutes"* ]]; then
            val=$(rofi -dmenu -i -p "Duration (Mins)" -theme-str 'window {width: 20%;} listview {lines: 0;}') || exit 0
            val=${val//[!0-9]/}; [[ -z "$val" ]] && exit 0
            
            echo "$((val*60))" > "$TIMER_STATE"
            "$DAEMON_SCRIPT" --timer "$((val*60))" & disown
            
        elif [[ "$tchoice" == *"Seconds"* ]]; then
            val=$(rofi -dmenu -i -p "Duration (Secs)" -theme-str 'window {width: 20%;} listview {lines: 0;}') || exit 0
            val=${val//[!0-9]/}; [[ -z "$val" ]] && exit 0
            
            echo "$val" > "$TIMER_STATE"
            "$DAEMON_SCRIPT" --timer "$val" & disown
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
