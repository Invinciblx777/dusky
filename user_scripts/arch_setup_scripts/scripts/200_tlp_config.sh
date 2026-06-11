#!/usr/bin/env bash
# configures /etc/tlp.conf for ASUS TUF F15 (personal, dusk)
# -----------------------------------------------------------------------------
# Script: configure_tlp.sh
# Description: Conditionally configures /etc/tlp.conf for ASUS TUF F15.
#              Includes backup logic and strict state detection.
# Author: Elite DevOps (Arch/Hyprland)
# Dependencies: tlp, systemd, bash 5+
# -----------------------------------------------------------------------------

# 1. Strict Safety & Error Handling
set -euo pipefail

# 2. Configuration Content
# This variable holds the EXACT content to be written to /etc/tlp.conf.
mapfile -d '' TLP_CONFIG_CONTENT <<'EOF'
# tlp 1.10
# Do not use, this is custom configured for dusk's FX507ZE asus tuf f15 laptop

TLP_ENABLE=1
TLP_AUTO_SWITCH=1
TLP_PROFILE_AC=BAL
TLP_PROFILE_BAT=SAV
DISK_IDLE_SECS_ON_AC=0
DISK_IDLE_SECS_ON_BAT=2
MAX_LOST_WORK_SECS_ON_AC=30
MAX_LOST_WORK_SECS_ON_BAT=300
CPU_SCALING_GOVERNOR_ON_AC=performance
CPU_SCALING_GOVERNOR_ON_BAT=powersave
CPU_SCALING_GOVERNOR_ON_SAV=powersave
CPU_ENERGY_PERF_POLICY_ON_AC=performance
CPU_ENERGY_PERF_POLICY_ON_BAT=balance_power
CPU_ENERGY_PERF_POLICY_ON_SAV=power
CPU_MIN_PERF_ON_AC=0
CPU_MAX_PERF_ON_AC=100
CPU_MIN_PERF_ON_BAT=0
CPU_MAX_PERF_ON_BAT=50
CPU_MIN_PERF_ON_SAV=0
CPU_MAX_PERF_ON_SAV=30
CPU_BOOST_ON_AC=1
CPU_BOOST_ON_BAT=0
CPU_BOOST_ON_SAV=0
CPU_HWP_DYN_BOOST_ON_AC=1
CPU_HWP_DYN_BOOST_ON_BAT=0
CPU_HWP_DYN_BOOST_ON_SAV=0
PLATFORM_PROFILE_ON_AC=performance
PLATFORM_PROFILE_ON_BAT=balanced
PLATFORM_PROFILE_ON_SAV=quiet
MEM_SLEEP_ON_AC=s2idle
MEM_SLEEP_ON_BAT=s2idle
DISK_DEVICES="nvme-INTEL_SSDPEKNU512GZ_BTKA151410KY512A nvme-Samsung_SSD_980_1TB_S649NL0T857112D"
DISK_IOSCHED="none none"
AHCI_RUNTIME_PM_ON_AC=auto
AHCI_RUNTIME_PM_ON_BAT=auto
AHCI_RUNTIME_PM_TIMEOUT=10
INTEL_GPU_MIN_FREQ_ON_AC=100
INTEL_GPU_MIN_FREQ_ON_BAT=100
INTEL_GPU_MIN_FREQ_ON_SAV=100
INTEL_GPU_MAX_FREQ_ON_AC=1200
INTEL_GPU_MAX_FREQ_ON_BAT=200
INTEL_GPU_MAX_FREQ_ON_SAV=200
INTEL_GPU_BOOST_FREQ_ON_AC=1400
INTEL_GPU_BOOST_FREQ_ON_BAT=400
INTEL_GPU_BOOST_FREQ_ON_SAV=300
WIFI_PWR_ON_AC=off
WIFI_PWR_ON_BAT=on
SOUND_POWER_SAVE_CONTROLLER=Y
PCIE_ASPM_ON_AC=powersupersave
PCIE_ASPM_ON_BAT=powersupersave
PCIE_ASPM_ON_SAV=powersupersave
RUNTIME_PM_ON_AC=auto
RUNTIME_PM_ON_BAT=auto
USB_AUTOSUSPEND=1
DEVICES_TO_DISABLE_ON_BAT="bluetooth"
START_CHARGE_THRESH_BAT1=70
STOP_CHARGE_THRESH_BAT1=75
EOF

# 3. Aesthetics & Logging
readonly C_RESET=$'\033[0m'
readonly C_GREEN=$'\033[1;32m'
readonly C_BLUE=$'\033[1;34m'
readonly C_RED=$'\033[1;31m'
readonly C_YELLOW=$'\033[1;33m'

log_info() { printf "${C_BLUE}[INFO]${C_RESET} %s\n" "$1"; }
log_success() { printf "${C_GREEN}[OK]${C_RESET} %s\n" "$1"; }
log_warn() { printf "${C_YELLOW}[WARN]${C_RESET} %s\n" "$1"; }
log_error() { printf "${C_RED}[ERROR]${C_RESET} %s\n" "$1" >&2; }

# 4. Root Privilege Check (Auto-Elevation)
if [[ $EUID -ne 0 ]]; then
    log_info "Root privileges required. Elevating..."
    exec sudo "$0" "$@"
fi

# 5. Environment Validation
if ! command -v tlp &>/dev/null; then
    log_warn "TLP is not installed. Skipping TLP configuration to prevent Orchestrator failure."
    exit 0
fi

# 6. Main Execution
main() {
    local target_file="/etc/tlp.conf"
    
    # ---------------------------------------------------------
    # A. User Interaction & Warnings
    # ---------------------------------------------------------
    echo ""
    log_warn "You are about to apply a TLP configuration tuned specifically for the:"
    log_warn "ASUS TUF F15 Gaming Laptop"
    echo ""
    printf "  %bIf you do not own this specific device, it is HIGHLY advised not to apply this.%b\n" "${C_RED}" "${C_RESET}"
    printf "  For other laptops, we recommend manually configuring %s to achieve\n" "$target_file"
    printf "  the best battery life for your specific hardware.\n\n"

    read -r -p "Do you want to proceed with applying this configuration? [y/N] " response
    if [[ ! "$response" =~ ^[yY]$ ]]; then
        log_info "Operation cancelled by user."
        exit 0
    fi

    # ---------------------------------------------------------
    # B. Backup Logic
    # ---------------------------------------------------------
    # Detect the real user behind sudo to find the correct Home directory
    local real_user="${SUDO_USER:-$USER}"
    local real_home
    # Use getent to strictly find the home dir (handles edge cases better than $HOME)
    real_home=$(getent passwd "$real_user" | cut -d: -f6)
    
    local backup_dir="${real_home}/Documents"
    local backup_file="${backup_dir}/tlp_backup.conf"
    local file_existed=false

    # Check if target exists before we touch it
    if [[ -f "$target_file" ]]; then
        file_existed=true
        
        # Ensure backup directory exists
        if [[ ! -d "$backup_dir" ]]; then
            log_info "Creating directory ${backup_dir}..."
            mkdir -p "$backup_dir"
            chown "$real_user:$(id -gn "$real_user")" "$backup_dir"
        fi

        # Perform Backup
        log_info "Backing up current config to ${backup_file}..."
        cp "$target_file" "$backup_file"
        
        # Fix permissions so the regular user owns the backup, not root
        chown "$real_user:$(id -gn "$real_user")" "$backup_file"
        log_success "Backup verified."
    fi

    # ---------------------------------------------------------
    # C. Write Configuration
    # ---------------------------------------------------------
    if [[ "$file_existed" == "true" ]]; then
        log_info "Overwriting existing file at ${target_file}..."
    else
        log_info "File did not exist. Creating new file at ${target_file}..."
    fi
    
    if printf "%s" "${TLP_CONFIG_CONTENT}" > "${target_file}"; then
        log_success "Configuration written successfully."
    else
        log_error "Failed to write to ${target_file}."
        exit 1
    fi

    # ---------------------------------------------------------
    # D. Reload Service
    # ---------------------------------------------------------
    log_info "Reloading TLP systemd service..."
    
    if systemctl reload tlp; then
        log_success "TLP reloaded successfully."
    else
        # Fallback check: try to restart if reload fails (service might be stopped)
        log_warn "Reload failed (service might be inactive). Attempting restart..."
        if systemctl enable --now tlp; then
             log_success "TLP enabled and started successfully."
        else
             log_error "Failed to start TLP."
             exit 1
        fi
    fi
}

# Run Main
main
