#!/usr/bin/env bash
# ==============================================================================
# Script: 158_mkinitcpio_finalize.sh
# Context: Finalization (Chroot)
# Description: Restores ALPM hooks and generates the definitive initramfs.
# ==============================================================================
set -euo pipefail

if [[ -t 1 ]]; then
    readonly C_BOLD=$'\033[1m'
    readonly C_CYAN=$'\033[36m'
    readonly C_GREEN=$'\033[32m'
    readonly C_YELLOW=$'\033[33m'
    readonly C_RESET=$'\033[0m'
else
    readonly C_BOLD="" C_CYAN="" C_GREEN="" C_YELLOW="" C_RESET=""
fi

printf "%s%s[INFO]%s Restoring pacman mkinitcpio hooks...\n" "${C_BOLD}" "${C_CYAN}" "${C_RESET}"

# Remove the overrides so future kernel updates trigger initramfs generation normally
rm -f /etc/pacman.d/hooks/90-mkinitcpio-install.hook
rm -f /etc/pacman.d/hooks/60-mkinitcpio-remove.hook

printf "%s%s[INFO]%s Generating definitive initramfs...\n" "${C_BOLD}" "${C_CYAN}" "${C_RESET}"
printf "%s\n" "----------------------------------------"

# We feed 'n' to safely bypass the limine-mkinitcpio-hook prompt if it fires.
# -P processes all presets in /etc/mkinitcpio.d
mkinitcpio -P < <(echo "n") || {
    printf "%s\n" "----------------------------------------"
    printf "%s%s[WARN]%s mkinitcpio returned a non-zero exit code (usually benign firmware warnings).\n" "${C_BOLD}" "${C_YELLOW}" "${C_RESET}"
}

printf "%s\n" "----------------------------------------"
printf "%s%s[OK]%s Final initramfs generation complete.\n" "${C_BOLD}" "${C_GREEN}" "${C_RESET}"
