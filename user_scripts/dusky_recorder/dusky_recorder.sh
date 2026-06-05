#!/usr/bin/env bash
# ==============================================================================
# ARCH LINUX :: WAYLAND :: ROFI DUSKY RECORDER (PRO EDITION)
# ==============================================================================
# Description: Advanced Rofi interface for gpu-screen-recorder.
#              - State-aware Start/Stop/Replay controls
#              - Multi-tiered configuration submenus
#              - Dynamic Audio Device Discovery (PipeWire)
#              - Intelligent Bitrate/Quality conflict resolution
# ==============================================================================

set -Eeuo pipefail

# --- CONFIGURATION ---
readonly CFG="$HOME/.config/dusky_recorder/config.conf"
readonly ROFI_THEME_STR='window { width: 450px; } listview { lines: 8; }'
readonly INDICATOR_TMP="/tmp/dusky_recorder_notif_id"
readonly INDICATOR_PID="/tmp/dusky_recorder_daemon.pid"

# Ensure config exists and load it
[[ -f "$CFG" ]] && source "$CFG"

# --- FALLBACKS & DEFAULTS ---
fps="${fps:-60}"
cursor="${cursor:-yes}"
show_indicator="${show_indicator:-yes}"

# Video & Encoding
encoder="${encoder:-gpu}"
codec="${codec:-auto}"
quality="${quality:-very_high}"
bitrate_mode="${bitrate_mode:-auto}"
frame_mode="${frame_mode:-vfr}"
color_range="${color_range:-limited}"
container="${container:-mp4}"
output_dir="${output_dir:-$HOME/Videos}"
output_dir="${output_dir/#\~/$HOME}"

# Audio
audio_codec="${audio_codec:-opus}"
audio_bitrate="${audio_bitrate:-128}"

# Replay
replay_buffer="${replay_buffer:-0}"
replay_storage="${replay_storage:-ram}"
restart_replay="${restart_replay:-no}"

# --- AUDIO STATE MIGRATION ---
if [[ -n "${audio:-}" && -z "${audio_output:-}" && -z "${audio_input:-}" ]]; then
    if [[ "$audio" == *"|"* ]]; then
        audio_output="${audio%|*}"
        audio_input="${audio#*|}"
    elif [[ "$audio" == *"input"* ]]; then
        audio_output="none"
        audio_input="$audio"
    elif [[ "$audio" == *"output"* ]]; then
        audio_output="$audio"
        audio_input="none"
    elif [[ "$audio" == "none" ]]; then
        audio_output="none"
        audio_input="none"
    else
        audio_output="default_output"
        audio_input="none"
    fi
    sed -i '/^audio=/d' "$CFG" 2>/dev/null || true
    echo "audio_output=${audio_output}" >> "$CFG"
    echo "audio_input=${audio_input}" >> "$CFG"
fi

audio_output="${audio_output:-default_output}"
audio_input="${audio_input:-none}"

# --- HELPERS ---
run_menu() {
    local prompt="$1"
    shift
    local options=("$@")
    printf '%s\n' "${options[@]}" | rofi -dmenu -i -p "$prompt" -theme-str "$ROFI_THEME_STR" -format s
}

update_config() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" "$CFG"; then
        sed -i "s~^${key}=.*~${key}=${value}~" "$CFG"
    else
        echo "${key}=${value}" >> "$CFG"
    fi
    export "$key"="$value"
}

get_audio_name() {
    local target_id="$1"
    [[ "$target_id" == "none" ]] && echo "None" && return
    [[ "$target_id" == "default_output" ]] && echo "Default Desktop" && return
    [[ "$target_id" == "default_input" ]] && echo "Default Mic" && return
    
    local name
    name=$(gpu-screen-recorder --list-audio-devices 2>/dev/null | grep -F "${target_id}|" | cut -d'|' -f2 | head -n1)
    if [[ -n "$name" ]]; then
        echo "$name"
    else
        echo "Disconnected Device"
    fi
}

manage_indicator() {
    local action="$1"
    
    if [[ "$action" == "start" ]]; then
        [[ "$show_indicator" != "yes" ]] && return 0
        (
            local notif_id
            notif_id=$(notify-send -a "dusky-recorder" -p "" "")
            echo "$notif_id" > "$INDICATOR_TMP"
            
            local visible=true
            while true; do
                sleep 1
                if $visible; then
                    notify-send -a "dusky-recorder" -r "$notif_id" " " ""
                    visible=false
                else
                    notify-send -a "dusky-recorder" -r "$notif_id" "" ""
                    visible=true
                fi
            done
        ) & 
        echo $! > "$INDICATOR_PID"
        
    elif [[ "$action" == "stop" ]]; then
        if [[ -f "$INDICATOR_PID" ]]; then
            kill "$(cat "$INDICATOR_PID")" 2>/dev/null || true
            rm -f "$INDICATOR_PID"
        fi
        
        if [[ -f "$INDICATOR_TMP" ]]; then
            local notif_id
            notif_id=$(cat "$INDICATOR_TMP")
            makoctl dismiss -n "$notif_id" 2>/dev/null || true
            rm -f "$INDICATOR_TMP"
        fi
    fi
}

# --- RECORDING LOGIC ---
stop_recording() {
    local pids
    if pids=$(pidof gpu-screen-recorder || true); then
        if [[ -n "$pids" ]]; then
            for pid in $pids; do
                kill -SIGINT "$pid"
            done
            notify-send -u normal -i media-playback-stop 'Dusky Recorder' '  Recording stopped'
            manage_indicator "stop"
        fi
    fi
}

save_replay() {
    local pids
    if pids=$(pidof gpu-screen-recorder || true); then
        if [[ -n "$pids" ]]; then
            for pid in $pids; do
                kill -SIGUSR1 "$pid"
            done
            notify-send -u normal -i media-record 'Dusky Replay' '  Replay buffer saved'
        fi
    fi
}

start_recording() {
    local target_mode="$1"
    
    local region_coords=""
    if [[ "$target_mode" == "region" ]]; then
        sleep 0.5 
        if ! region_coords=$(slurp -f "%wx%h+%x+%y" 2>/dev/null); then
            notify-send -u critical 'Dusky Recorder Error' 'Region selection cancelled'
            exit 1
        fi
        [[ -z "$region_coords" ]] && exit 1
    fi

    mkdir -p "$output_dir"

    local -a args=(
        gpu-screen-recorder
        -w "$target_mode"
        -c "$container"
        -f "$fps"
    )

    [[ "$target_mode" == "region" && -n "$region_coords" ]] && args+=(-region "$region_coords")
    [[ "$cursor" == "no" ]] && args+=(-cursor "no")
    
    # Audio Routing
    local final_audio=""
    if [[ "$audio_output" != "none" && "$audio_input" != "none" ]]; then
        final_audio="${audio_output}|${audio_input}"
    elif [[ "$audio_output" != "none" ]]; then
        final_audio="${audio_output}"
    elif [[ "$audio_input" != "none" ]]; then
        final_audio="${audio_input}"
    fi
    [[ -n "$final_audio" ]] && args+=(-a "$final_audio")
    
    # Audio Specs
    [[ -n "$audio_codec" ]] && args+=(-ac "$audio_codec")
    [[ -n "$audio_bitrate" && "$audio_bitrate" != "0" ]] && args+=(-ab "$audio_bitrate")

    # Video Encoding Specs
    [[ -n "$encoder" && "$encoder" != "gpu" ]] && args+=(-encoder "$encoder")
    [[ -n "$codec" && "$codec" != "auto" ]] && args+=(-k "$codec")
    [[ -n "$quality" ]] && args+=(-q "$quality")
    [[ -n "$bitrate_mode" && "$bitrate_mode" != "auto" ]] && args+=(-bm "$bitrate_mode")
    [[ -n "$frame_mode" && "$frame_mode" != "vfr" ]] && args+=(-fm "$frame_mode")
    [[ -n "$color_range" && "$color_range" != "limited" ]] && args+=(-cr "$color_range")

    # File Routing
    local OUT=""
    if [[ -n "$replay_buffer" && "$replay_buffer" -gt 0 ]]; then
        args+=(-r "$replay_buffer")
        [[ -n "$replay_storage" ]] && args+=(-replay-storage "$replay_storage")
        [[ "$restart_replay" == "yes" ]] && args+=(-restart-replay-on-save "yes")
        OUT="$output_dir"
    else
        OUT="${output_dir}/Video_$(date +%Y-%m-%d_%H-%M-%S).${container}"
    fi
    args+=(-o "$OUT")

    "${args[@]}" > /tmp/gsr.log 2>&1 &
    local new_pid=$!

    sleep 0.5
    if ! kill -0 "$new_pid" 2>/dev/null; then
        notify-send -u critical 'Dusky Recorder Error' "Failed to start. Check /tmp/gsr.log"
        exit 1
    else
        if [[ -n "$replay_buffer" && "$replay_buffer" -gt 0 ]]; then
            notify-send -u normal -i media-record 'Dusky Recorder' '  Replay daemon started'
        else
            notify-send -u normal -i media-record 'Dusky Recorder' '  Recording started'
        fi
        manage_indicator "start"
    fi
}

# --- SUBMENU: VIDEO & ENCODING ---
video_menu() {
    while true; do
        # Format the display so users know if they are in CBR or VBR mode
        local q_disp="$quality"
        [[ "$bitrate_mode" == "cbr" ]] && q_disp="${quality} kbps (CBR)"

        local -a opts=(
            "  Back"
            "󰘚  Encoder     [${encoder}]"
            "󰈰  Codec       [${codec}]"
            "󰄬  Quality     [${q_disp}]"
            "󰹑  Frame Mode  [${frame_mode}]"
            "󰃐  Container   [${container}]"
            "󰸱  Color Range [${color_range}]"
        )
        local choice
        choice=$(run_menu "󰕧  Video Settings" "${opts[@]}") || return 0

        case "$choice" in
            "  Back") return 0 ;;
            "󰘚  Encoder"*)
                local new_enc
                new_enc=$(run_menu "Select Encoder" "gpu" "cpu") || continue
                [[ -n "$new_enc" ]] && { encoder="$new_enc"; update_config "encoder" "$encoder"; }
                ;;
            "󰈰  Codec"*)
                local -a codecs=("auto" "h264" "hevc" "av1" "vp8" "vp9" "hevc_10bit" "av1_10bit" "hevc_vulkan" "av1_vulkan")
                local new_codec
                new_codec=$(run_menu "Select Codec" "${codecs[@]}") || continue
                [[ -n "$new_codec" ]] && { codec="$new_codec"; update_config "codec" "$codec"; }
                ;;
            "󰄬  Quality"*)
                local -a q_opts=("󰄬  Ultra (VBR)" "󰄬  Very High (VBR)" "󰄬  High (VBR)" "󰄬  Medium (VBR)" "  Custom Bitrate (CBR)...")
                local q_choice
                q_choice=$(run_menu "󰄬  Quality Mode" "${q_opts[@]}") || continue
                case "$q_choice" in
                    "󰄬  Ultra"*) update_config "quality" "ultra"; update_config "bitrate_mode" "auto" ;;
                    "󰄬  Very High"*) update_config "quality" "very_high"; update_config "bitrate_mode" "auto" ;;
                    "󰄬  High"*) update_config "quality" "high"; update_config "bitrate_mode" "auto" ;;
                    "󰄬  Medium"*) update_config "quality" "medium"; update_config "bitrate_mode" "auto" ;;
                    "  Custom"*)
                        local custom_q
                        custom_q=$(rofi -dmenu -p "Bitrate (kbps, e.g. 40000)" -theme-str "$ROFI_THEME_STR listview { enabled: false; }" < /dev/null) || continue
                        if [[ -n "$custom_q" && "$custom_q" =~ ^[0-9]+$ ]]; then
                            update_config "quality" "$custom_q"
                            # CRITICAL FIX: Custom bitrates demand Constant Bitrate Mode or the backend crashes
                            update_config "bitrate_mode" "cbr"
                        fi
                        ;;
                esac
                ;;
            "󰹑  Frame Mode"*)
                local new_fm
                new_fm=$(run_menu "Select Frame Mode" "vfr" "cfr" "content") || continue
                [[ -n "$new_fm" ]] && { frame_mode="$new_fm"; update_config "frame_mode" "$frame_mode"; }
                ;;
            "󰃐  Container"*)
                local new_cont
                new_cont=$(run_menu "Select Container" "mp4" "mkv" "flv" "webm") || continue
                [[ -n "$new_cont" ]] && { container="$new_cont"; update_config "container" "$container"; }
                ;;
            "󰸱  Color Range"*)
                local new_cr
                new_cr=$(run_menu "Select Color Range" "limited" "full") || continue
                [[ -n "$new_cr" ]] && { color_range="$new_cr"; update_config "color_range" "$color_range"; }
                ;;
        esac
    done
}

# --- SUBMENU: AUDIO & ROUTING ---
audio_menu() {
    while true; do
        local disp_out; disp_out=$(get_audio_name "$audio_output")
        [[ ${#disp_out} -gt 18 ]] && disp_out="${disp_out:0:15}..."
        
        local disp_in; disp_in=$(get_audio_name "$audio_input")
        [[ ${#disp_in} -gt 18 ]] && disp_in="${disp_in:0:15}..."

        local -a opts=(
            "  Back"
            "󰓃  Output      [${disp_out}]"
            "  Input       [${disp_in}]"
            "󰎆  Codec       [${audio_codec}]"
            "󰡰  Bitrate     [${audio_bitrate}k]"
        )
        local choice
        choice=$(run_menu "󰎆  Audio Settings" "${opts[@]}") || return 0

        case "$choice" in
            "  Back") return 0 ;;
            "󰓃  Output"*)
                local -a rofi_out_list=("  None" "  Default Desktop Audio")
                local -A out_map=(["  None"]="none" ["  Default Desktop Audio"]="default_output")

                while IFS='|' read -r dev_id dev_name; do
                    [[ -z "$dev_id" || "$dev_id" == "default_output" || "$dev_id" == "default_input" ]] && continue
                    [[ -z "$dev_name" ]] && dev_name="$dev_id"
                    
                    if [[ "$dev_id" == *"output"* ]]; then
                        local entry="  $dev_name"
                        local count=2
                        while [[ -n "${out_map[$entry]:-}" ]]; do
                            entry="  $dev_name ($count)"
                            ((count++))
                        done
                        rofi_out_list+=("$entry")
                        out_map["$entry"]="$dev_id"
                    fi
                done < <(gpu-screen-recorder --list-audio-devices 2>/dev/null)

                local choice_out
                choice_out=$(run_menu "Desktop Audio (Output)" "${rofi_out_list[@]}") || continue
                if [[ -n "$choice_out" && -n "${out_map[$choice_out]:-}" ]]; then
                    audio_output="${out_map[$choice_out]}"; update_config "audio_output" "$audio_output"
                fi
                ;;
            "  Input"*)
                local -a rofi_in_list=("  None" "  Default Microphone")
                local -A in_map=(["  None"]="none" ["  Default Microphone"]="default_input")

                while IFS='|' read -r dev_id dev_name; do
                    [[ -z "$dev_id" || "$dev_id" == "default_output" || "$dev_id" == "default_input" ]] && continue
                    [[ -z "$dev_name" ]] && dev_name="$dev_id"
                    
                    if [[ "$dev_id" == *"input"* ]]; then
                        local entry="  $dev_name"
                        local count=2
                        while [[ -n "${in_map[$entry]:-}" ]]; do
                            entry="  $dev_name ($count)"
                            ((count++))
                        done
                        rofi_in_list+=("$entry")
                        in_map["$entry"]="$dev_id"
                    fi
                done < <(gpu-screen-recorder --list-audio-devices 2>/dev/null)

                local choice_in
                choice_in=$(run_menu "Microphone (Input)" "${rofi_in_list[@]}") || continue
                if [[ -n "$choice_in" && -n "${in_map[$choice_in]:-}" ]]; then
                    audio_input="${in_map[$choice_in]}"; update_config "audio_input" "$audio_input"
                fi
                ;;
            "󰎆  Codec"*)
                local new_ac
                new_ac=$(run_menu "Audio Codec" "opus" "aac" "flac") || continue
                [[ -n "$new_ac" ]] && { audio_codec="$new_ac"; update_config "audio_codec" "$audio_codec"; }
                ;;
            "󰡰  Bitrate"*)
                local new_ab
                new_ab=$(run_menu "Audio Bitrate (kbps)" "0 (Auto)" "128" "192" "256" "320") || continue
                new_ab="${new_ab%% *}" # Strip the (Auto) text if present
                [[ -n "$new_ab" ]] && { audio_bitrate="$new_ab"; update_config "audio_bitrate" "$audio_bitrate"; }
                ;;
        esac
    done
}

# --- SUBMENU: CAPTURE & INTERFACE ---
capture_menu() {
    while true; do
        local -a opts=(
            "  Back"
            "󰣖  FPS         [${fps}]"
            "󰇀  Cursor      [${cursor}]"
            "󰂚  Indicator   [${show_indicator}]"
        )
        local choice
        choice=$(run_menu "󰆋  Capture Settings" "${opts[@]}") || return 0

        case "$choice" in
            "  Back") return 0 ;;
            "󰣖  FPS"*)
                local new_fps
                new_fps=$(run_menu "Select FPS" "30" "60" "120" "144") || continue
                [[ -n "$new_fps" ]] && { fps="$new_fps"; update_config "fps" "$fps"; }
                ;;
            "󰇀  Cursor"*)
                local new_cursor
                new_cursor=$(run_menu "Record Cursor?" "yes" "no") || continue
                [[ -n "$new_cursor" ]] && { cursor="$new_cursor"; update_config "cursor" "$cursor"; }
                ;;
            "󰂚  Indicator"*)
                local new_ind
                new_ind=$(run_menu "Show Red Dot Indicator?" "yes" "no") || continue
                [[ -n "$new_ind" ]] && { show_indicator="$new_ind"; update_config "show_indicator" "$show_indicator"; }
                ;;
        esac
    done
}

# --- SUBMENU: REPLAY BUFFER ---
replay_menu() {
    while true; do
        local -a opts=(
            "  Back"
            "  Duration    [${replay_buffer}s]"
            "󰋊  Storage     [${replay_storage}]"
            "  Restart     [${restart_replay}]"
        )
        local choice
        choice=$(run_menu "  Replay Settings" "${opts[@]}") || return 0

        case "$choice" in
            "  Back") return 0 ;;
            "  Duration"*)
                local new_buf
                new_buf=$(run_menu "Replay Buffer (0 to disable)" "0" "30" "60" "120" "300") || continue
                [[ -n "$new_buf" ]] && { replay_buffer="$new_buf"; update_config "replay_buffer" "$replay_buffer"; }
                ;;
            "󰋊  Storage"*)
                local new_store
                new_store=$(run_menu "Buffer Medium" "ram" "disk") || continue
                [[ -n "$new_store" ]] && { replay_storage="$new_store"; update_config "replay_storage" "$replay_storage"; }
                ;;
            "  Restart"*)
                local new_rest
                new_rest=$(run_menu "Restart after save?" "yes" "no") || continue
                [[ -n "$new_rest" ]] && { restart_replay="$new_rest"; update_config "restart_replay" "$restart_replay"; }
                ;;
        esac
    done
}

# --- SETTINGS HUB (ROUTER) ---
settings_hub() {
    while true; do
        local -a opts=(
            "  Back"
            "󰕧  Video & Encoding"
            "󰎆  Audio & Routing"
            "󰆋  Capture & Interface"
            "  Replay Buffer"
        )
        local choice
        choice=$(run_menu "  Settings Hub" "${opts[@]}") || return 0
        case "$choice" in
            "  Back") return 0 ;;
            "󰕧  Video"*) video_menu ;;
            "󰎆  Audio"*) audio_menu ;;
            "󰆋  Capture"*) capture_menu ;;
            "  Replay"*) replay_menu ;;
        esac
    done
}

# --- MAIN LOOP ---
main() {
    local is_running=false
    local is_replay=false
    local pids
    
    if pids=$(pidof gpu-screen-recorder || true); then
        if [[ -n "$pids" ]]; then
            is_running=true
            if grep -zqxa -- '-r' "/proc/$(echo "$pids" | awk '{print $1}')/cmdline" 2>/dev/null; then
                is_replay=true
            fi
        fi
    fi

    local -a main_opts=()
    if $is_running; then
        $is_replay && main_opts+=("  Save Replay Buffer")
        main_opts+=("  Stop Recording")
        main_opts+=("  Cancel")
    else
        main_opts+=("  Record Full Screen")
        main_opts+=("  Record Region")
        main_opts+=("  Settings Hub")
        main_opts+=("  Cancel")
    fi

    local choice
    choice=$(run_menu "Dusky Recorder" "${main_opts[@]}") || exit 0

    case "$choice" in
        "  Stop"*) stop_recording ;;
        "  Save"*) save_replay ;;
        "  Record"*) start_recording "screen" ;;
        "  Record"*) start_recording "region" ;;
        "  Settings"*) settings_hub; main ;;
        "  Cancel"*) exit 0 ;;
    esac
}

main
