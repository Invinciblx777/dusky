#!/usr/bin/env bash
# ============================================================================
# Platinum-Grade RAM Forensics — Arch Linux + Hyprland 0.55+ / Kernel 7.x
# ============================================================================
# Covers every known RAM sink on a modern Wayland/Hyprland desktop:
#   • Correct full /proc/meminfo accounting (all kernel 7.x fields)
#   • Race-condition immune smaps_rollup PSS engine
#   • Hyprland-specific IPC diagnostics via native XDG_RUNTIME_DIR & Signature
#   • Transparent Hugepage (THP) analysis
#   • ZRAM / ZSWAP efficiency
#   • Wayland/tmpfs shared memory
#   • DMA-BUF GPU buffers (Kernel 6.8+ / 7.x tabular format)
#   • Kernel slab leak detection
#   • Hyprland Headless / Render Leak known vectors
# ============================================================================

set -euo pipefail

# ── 1. PRIVILEGE ESCALATION & ENVIRONMENT ───────────────────────────────────
if [[ "$EUID" -ne 0 ]]; then
    echo -e "\e[1;33m[!] Elevated privileges required. Auto-elevating...\e[0m"
    exec sudo ORIGINAL_USER="$USER" bash "$0" "$@"
fi

TARGET_USER="${ORIGINAL_USER:-${SUDO_USER:-$USER}}"
if [[ "$TARGET_USER" == "root" ]]; then
    TARGET_HOME="/root"
else
    TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
fi

REPORT_DIR="$TARGET_HOME/Documents/logs/ram_audit"
mkdir -p "$REPORT_DIR"
chown -R "$TARGET_USER":"$TARGET_USER" "$TARGET_HOME/Documents/logs" 2>/dev/null || true
REPORT="$REPORT_DIR/report_$(date +%Y%m%d_%H%M%S).md"

# ── 2. DEPENDENCY CHECK ─────────────────────────────────────────────────────
MISSING_PKGS=()
command -v zramctl  >/dev/null 2>&1 || MISSING_PKGS+=("util-linux")
command -v slabtop  >/dev/null 2>&1 || MISSING_PKGS+=("procps-ng")

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    echo -e "\e[1;34m[*] Missing packages: ${MISSING_PKGS[*]}. Installing...\e[0m"
    if [[ "$TARGET_USER" != "root" ]] && command -v paru >/dev/null 2>&1; then
        sudo -u "$TARGET_USER" paru -S --noconfirm --needed "${MISSING_PKGS[@]}"
    elif [[ "$TARGET_USER" != "root" ]] && command -v yay >/dev/null 2>&1; then
        sudo -u "$TARGET_USER" yay -S --noconfirm --needed "${MISSING_PKGS[@]}"
    else
        pacman -S --noconfirm --needed "${MISSING_PKGS[@]}" || true
    fi
fi

# ── 3. HELPERS ───────────────────────────────────────────────────────────────

get_mem() {
    local val
    val=$(awk -v key="$1" '$1 == key ":" {print $2; exit}' /proc/meminfo)
    echo "${val:-0}"
}
to_mb() { awk "BEGIN {printf \"%.0f\", $1 / 1024}"; }

pss_table() {
    local top_n="${1:-20}"
    local tmp
    tmp=$(mktemp)
    
    for pid_dir in /proc/[0-9]*/; do
        local pid="${pid_dir//[^0-9]/}"
        [[ -z "$pid" ]] && continue
        local rollup="${pid_dir}smaps_rollup"
        
        # Safe extraction: process might die mid-read.
        local comm
        comm=$(cat "${pid_dir}comm" 2>/dev/null || echo "?")
        comm="${comm:0:20}" 
        
        # Single awk pass, ignoring errors if process evaporates
        local stats
        if ! stats=$(awk '/^Pss:/ {pss+=$2} /^Private_Clean:/ {pc+=$2} /^Private_Dirty:/ {pd+=$2} /^Rss:/ {rss+=$2} /^Swap:/ {swap+=$2} END {print pc+pd, pss+0, rss+0, swap+0}' "$rollup" 2>/dev/null); then
            continue
        fi
        
        [[ -z "$stats" ]] && continue
        read -r uss pss rss swap <<< "$stats"
        printf '%d\t%s\t%d\t%d\t%d\t%d\n' "$pid" "$comm" "$uss" "$pss" "$rss" "$swap"
    done | sort -t$'\t' -k4 -rn | head -n "$top_n" > "$tmp"

    awk -F'\t' 'BEGIN {
        print "| PID | COMMAND | USS (MB) | PSS (MB) | RSS (MB) | SWAP (MB) |"
        print "|---|---|---|---|---|---|"
    }
    {
        printf "| %d | %s | %.1f | %.1f | %.1f | %.1f |\n", $1, $2, $3/1024, $4/1024, $5/1024, $6/1024
    }' "$tmp"
    
    rm -f "$tmp"
}

# ── 4. FORENSICS ─────────────────────────────────────────────────────────────
echo -e "\e[1;32m[*] Commencing Deep Kernel RAM Analysis (Hyprland + Arch Linux)...\e[0m"

{
echo "# Platinum System RAM Forensics Report — Hyprland Edition"
echo "**Date:** $(date)"
echo "**Kernel:** $(uname -r)"
echo "**Host:** $(hostname)"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — COMPLETE /proc/meminfo ACCOUNTING
# ─────────────────────────────────────────────────────────────────────────────
echo "## 1. Complete Memory Accounting (Kernel Absolute Truth)"
echo "---"
echo '> **Understanding this section:** This is the absolute low-level truth of your RAM. Tools like `htop` group these numbers together unpredictably. Here, you see exactly what the kernel is allocating.'
echo '> * **AnonPages:** Your running apps, browsers, and game memory.'
echo '> * **Cached:** Files kept in RAM to make the system fast. *This is automatically freed if apps need more RAM.*'
echo '> * **Shmem:** Shared Memory. On Wayland, this includes the literal pixel buffers of your visible windows.'
echo ""

MEM_TOTAL=$(get_mem MemTotal)
MEM_FREE=$(get_mem MemFree)
MEM_AVAIL=$(get_mem MemAvailable)
BUFFERS=$(get_mem Buffers)
CACHED=$(get_mem Cached)
SWAP_CACHED=$(get_mem SwapCached)
ANON_PAGES=$(get_mem AnonPages)
SHMEM=$(get_mem Shmem)
MAPPED=$(get_mem Mapped)
UNEVICTABLE=$(get_mem Unevictable)

SLAB=$(get_mem Slab)
S_RECLAIMABLE=$(get_mem SReclaimable)
S_UNRECLAIM=$(get_mem SUnreclaim)
K_RECLAIMABLE=$(get_mem KReclaimable)
K_STACK=$(get_mem KernelStack)
PAGE_TABLES=$(get_mem PageTables)
SEC_PAGE_TABLES=$(get_mem SecPageTables)
PERCPU=$(get_mem Percpu)
VMALLOC_USED=$(get_mem VmallocUsed)

ANON_HUGE=$(get_mem AnonHugePages)
SHMEM_HUGE=$(get_mem ShmemHugePages)
FILE_HUGE=$(get_mem FileHugePages)

SWAP_TOTAL=$(get_mem SwapTotal)
SWAP_FREE=$(get_mem SwapFree)
ZSWAP=$(get_mem Zswap)
ZSWAPPED=$(get_mem Zswapped)
DIRTY=$(get_mem Dirty)
WRITEBACK=$(get_mem Writeback)
COMMITTED=$(get_mem Committed_AS)
COMMIT_LIMIT=$(get_mem CommitLimit)
HW_CORRUPTED=$(get_mem HardwareCorrupted)

ACCOUNTED_KB=$(( ANON_PAGES + BUFFERS + CACHED + K_RECLAIMABLE + K_STACK \
               + PAGE_TABLES + SEC_PAGE_TABLES + SWAP_CACHED + S_UNRECLAIM \
               + UNEVICTABLE + PERCPU + VMALLOC_USED + MEM_FREE ))
UNACCOUNTED_KB=$(( MEM_TOTAL - ACCOUNTED_KB ))

echo "\`\`\`text"
printf "%-45s %8s MB\n" "Total Usable RAM (MemTotal):"       "$(to_mb $MEM_TOTAL)"
printf "%-45s %8s MB\n" "Truly Available (MemAvailable):"    "$(to_mb $MEM_AVAIL)"
printf "%-45s %8s MB\n" "Raw Free (MemFree):"                "$(to_mb $MEM_FREE)"
echo ""
echo "[ NAMED ALLOCATIONS ]"
printf "%-45s %8s MB\n" "  Userspace Anon (AnonPages):"        "$(to_mb $ANON_PAGES)"
printf "%-45s %8s MB\n" "  Page Cache / File-backed (Cached):" "$(to_mb $CACHED)"
printf "%-45s %8s MB\n" "  Shared Memory/Tmpfs (Shmem):"       "$(to_mb $SHMEM)"
printf "%-45s %8s MB\n" "  Buffer Cache (Buffers):"            "$(to_mb $BUFFERS)"
printf "%-45s %8s MB\n" "  Swap Cache (SwapCached):"           "$(to_mb $SWAP_CACHED)"
printf "%-45s %8s MB\n" "  Mapped (file+anon mmap'd):"         "$(to_mb $MAPPED)"
printf "%-45s %8s MB\n" "  Unevictable / Mlocked:"             "$(to_mb $UNEVICTABLE)"
echo ""
echo "[ KERNEL STRUCTURES ]"
printf "%-45s %8s MB\n" "  Slab Total (Slab):"                 "$(to_mb $SLAB)"
printf "%-45s %8s MB\n" "    └─ Reclaimable (KReclaimable):"   "$(to_mb $K_RECLAIMABLE)"
printf "%-45s %8s MB\n" "    └─ Unreclaimable (SUnreclaim):"   "$(to_mb $S_UNRECLAIM)"
printf "%-45s %8s MB\n" "  Kernel Stacks (KernelStack):"       "$(to_mb $K_STACK)"
printf "%-45s %8s MB\n" "  Page Tables (PageTables):"          "$(to_mb $PAGE_TABLES)"
printf "%-45s %8s MB\n" "  Secondary Page Tables (KVM/arm):"   "$(to_mb $SEC_PAGE_TABLES)"
printf "%-45s %8s MB\n" "  Per-CPU Allocations (Percpu):"      "$(to_mb $PERCPU)"
printf "%-45s %8s MB\n" "  vmalloc Used (VmallocUsed):"        "$(to_mb $VMALLOC_USED)"
echo ""
echo "[ SUMMARY ]"
printf "%-45s %8s MB\n" "  All Named Fields (Accounted):"     "$(to_mb $ACCOUNTED_KB)"
printf "%-45s %8s MB\n" "  Unaccounted (firmware/drivers):"   "$(to_mb $UNACCOUNTED_KB)"
echo "\`\`\`"

echo "> **Diagnostic Note:**"
echo "> * Unaccounted < 300 MB → Healthy (Standard firmware hardware-reserved limits)."
echo '> * Unaccounted > 600 MB → **ALERT:** A GPU driver (e.g., `amdgpu` GTT) or a rogue kernel module is leaking anonymous memory bypassing tracking.'
echo "> * SUnreclaim > 500 MB → **ALERT:** Kernel slab leak (See Section 7)."
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — SWAP & ZRAM
# ─────────────────────────────────────────────────────────────────────────────
echo "## 2. Compressed RAM (ZRAM / ZSWAP)"
echo "---"
echo '> **Understanding this section:** ZRAM/ZSWAP acts as a hyper-fast SSD inside your RAM by compressing inactive memory. The "TOTAL" column shows exactly how much physical RAM this compression pool is eating.'
echo ""
if zramctl --raw 2>/dev/null | grep -q '/dev/zram'; then
    echo "\`\`\`text"
    zramctl --output NAME,ALGORITHM,DISKSIZE,DATA,COMPR,TOTAL,STREAMS 2>/dev/null || \
    zramctl --output NAME,ALGORITHM,DISKSIZE,DATA,COMPR,TOTAL 2>/dev/null
    echo "\`\`\`"
else
    echo "ZRAM is not active."
fi
echo ""
if [[ "$ZSWAP" -gt 0 ]]; then
    echo "Zswap is active: **$(to_mb $ZSWAP) MB** physical pool, storing **$(to_mb $ZSWAPPED) MB** of decompressed data."
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — NATIVE PSS TABLE
# ─────────────────────────────────────────────────────────────────────────────
echo "## 3. True Process Isolation (Top 25 by PSS)"
echo "---"
echo '> **Understanding this section:** Standard system monitors look at `RSS` which wildly exaggerates memory usage by double-counting shared libraries. This table uses `PSS` (Proportional Set Size) which perfectly splits shared memory to give you the truest representation of what apps are heavy.'
echo '> * **USS:** Memory 100% unique to this app. If you kill the app, this exact amount of RAM is freed instantly.'
echo '> * **PSS:** The most accurate metric. USS plus the fair mathematical share of shared libraries for this app.'
echo ""
pss_table 25
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — HYPRLAND-SPECIFIC DIAGNOSTICS
# ─────────────────────────────────────────────────────────────────────────────
echo "## 4. Hyprland Specific Diagnostics"
echo "---"
echo '> **Understanding this section:** Interrogates the Wayland compositor directly to see if window surfaces, unmapped layers, or headless monitors are building up in the background.'
echo ""
HYPR_PID=$(pgrep -x Hyprland 2>/dev/null | head -1 || true)
if [[ -n "$HYPR_PID" ]]; then
    HYPR_USER=$(ps -o user= -p "$HYPR_PID" 2>/dev/null | tr -d ' ' || true)
    HYPR_UID=$(id -u "$HYPR_USER" 2>/dev/null || echo 1000)
    HYPR_RSS=$(awk '/^VmRSS:/{print $2}' /proc/"$HYPR_PID"/status 2>/dev/null || echo 0)
    HYPR_PSS=$(awk '/^Pss:/{sum+=$2} END{print sum+0}' /proc/"$HYPR_PID"/smaps_rollup 2>/dev/null || echo 0)
    
    echo "- **Hyprland PID:** \`$HYPR_PID\`"
    echo "- **Session User:** \`$HYPR_USER\` (UID: $HYPR_UID)"
    echo "- **Hyprland RSS:** $(to_mb $HYPR_RSS) MB"
    echo "- **Hyprland PSS:** $(to_mb $HYPR_PSS) MB"
    
    echo ""
    echo "### Open Clients (Windows)"
    
    # Inject Signature to bypass hyprctl IPC blocks
    HYPR_SIG=$(ls -1 /run/user/"$HYPR_UID"/hypr/ 2>/dev/null | head -1 || true)
    HYPR_ENV="XDG_RUNTIME_DIR=/run/user/$HYPR_UID"
    [[ -n "$HYPR_SIG" ]] && HYPR_ENV="$HYPR_ENV HYPRLAND_INSTANCE_SIGNATURE=$HYPR_SIG"

    sudo -u "$HYPR_USER" env $HYPR_ENV hyprctl clients 2>/dev/null \
        | awk '/^Window/{if(w!="") printf "- **%s** (`%s`) — Size: %s, Mapped: %s\n", c, w, s, m; w=$2; c="?"; s="?"; m="?"} /class:/{c=$2} /size:/{s=$2" "$3} /mapped:/{m=$2} END{if(w!="") printf "- **%s** (`%s`) — Size: %s, Mapped: %s\n", c, w, s, m}' \
        || echo "  (hyprctl clients unavailable)"
    
    echo ""
    echo "### Layer-shell Surfaces (Waybar, overlays, backgrounds)"
    sudo -u "$HYPR_USER" env $HYPR_ENV hyprctl layers 2>/dev/null \
        | awk '/^Layer/{if(n!="") printf "- Layer **%s** — Size: %s\n", n, s; n="?"; s="?"} /namespace:/{n=$2} /size:/{s=$2" "$3} END{if(n!="") printf "- Layer **%s** — Size: %s\n", n, s}' \
        || echo "  (hyprctl layers unavailable)"
else
    echo "**Hyprland process not found.**"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — SHARED MEMORY / TMPFS
# ─────────────────────────────────────────────────────────────────────────────
echo "## 5. Wayland Shared Memory & Tmpfs"
echo "---"
echo '> **Understanding this section:** Temporary filesystems (tmpfs) and `/dev/shm` live entirely inside your physical RAM. If an app crashes but fails to delete its shared memory buffer, it creates a silent memory leak here.'
echo ""
echo "### Overall Tmpfs Mounts"
echo "\`\`\`text"
df -h -t tmpfs 2>/dev/null | awk 'NR==1 || ($3+0 > 0 || $3 ~ /[0-9]/)' || true
echo "\`\`\`"
echo ""
echo "### /dev/shm Contents (Top 20 by Size)"
echo "\`\`\`text"
ls -laSh /dev/shm/ 2>/dev/null | head -20 || echo "  Empty"
echo "\`\`\`"
echo '> **Note:** If `Hyprland` PSS is high AND `/dev/shm` is huge, a rogue Wayland client is leaking `wl_shm` texture buffers.'
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — DMA-BUF GPU BUFFERS (AQUAMARINE)
# ─────────────────────────────────────────────────────────────────────────────
echo "## 6. GPU DMA-BUF Allocations (Aquamarine / Graphics)"
echo "---"
echo '> **Understanding this section:** DMA-BUFs are chunks of physical system RAM pinned securely for the GPU (for rendering the desktop, gaming, and screen-sharing). **These are completely invisible to standard tools like `htop` or `ps`.** If your RAM is disappearing without a trace, this is often the culprit.'
echo ""

MOUNTED_DEBUGFS=false
if ! mountpoint -q /sys/kernel/debug 2>/dev/null; then
    if mount -t debugfs none /sys/kernel/debug 2>/dev/null; then
        MOUNTED_DEBUGFS=true
    fi
fi

DMABUF_INFO=/sys/kernel/debug/dma_buf/bufinfo
if [[ -r "$DMABUF_INFO" ]]; then
    # Pipefail-immune counting mechanism
    BUF_COUNT=$(grep -E -c '^[0-9]+' "$DMABUF_INFO" 2>/dev/null || true)
    TOTAL_BYTES=$(awk '/^[0-9]+/ {sum+=$1} END{print sum+0}' "$DMABUF_INFO" 2>/dev/null || echo 0)
    
    if [[ "$BUF_COUNT" -gt 0 ]]; then
        echo "- **Active DMA-BUF Count:** \`$BUF_COUNT\`"
        echo "- **Total DMA-BUF RAM:** **$(awk "BEGIN {printf \"%.1f\", $TOTAL_BYTES/1048576}") MB**"
        
        echo ""
        echo "### Top 10 Largest Individual GPU Buffers"
        echo "| Size (MB) | Exporter |"
        echo "|---|---|"
        awk '/^[0-9]+/ {print $1, $5}' "$DMABUF_INFO" 2>/dev/null | sort -k1 -rn | head -10 | awk '{printf "| %.1f | %s |\n", $1/1048576, $2}' || true
        
        echo ""
        echo "### Buffer Breakdown by Exporter"
        echo "| Exporter Driver | Object Count |"
        echo "|---|---|"
        awk '/^[0-9]+/ {print $5}' "$DMABUF_INFO" 2>/dev/null | sort | uniq -c | sort -rn | awk '{printf "| %s | %d |\n", $2, $1}' || true
    else
        echo "**No active DMA-BUFs tracked.** (Format mismatch or idle system)."
    fi
else
    echo "**DMA-BUF trace unavailable.** (debugfs blocked or lockdown=integrity)."
fi

if [[ "$MOUNTED_DEBUGFS" == true ]]; then
    umount /sys/kernel/debug 2>/dev/null || true
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — KERNEL SLAB LEAK DETECTION
# ─────────────────────────────────────────────────────────────────────────────
echo "## 7. Kernel Slab Objects (Top 15 by Total Memory)"
echo "---"
echo '> **Understanding this section:** The Linux Kernel maintains its own internal RAM caches (Slabs) for things like file structures, network sockets, and inodes. If a kernel driver is faulty, a specific object here will infinitely balloon in size.'
echo ""
if [[ -r /proc/slabinfo ]]; then
    echo "\`\`\`text"
    echo "NAME                       NUM_OBJS  OBJSIZE  TOTAL_MB"
    echo "------------------------------------------------------"
    awk 'NR>2 && NF>=4 {
        total_bytes = $3 * $4
        printf "%-26s %9d  %7d  %7.1f\n", $1, $3, $4, total_bytes/1048576
    }' /proc/slabinfo | sort -k4 -rn | head -15 || true
    echo "\`\`\`"
    
    SLAB_TOTAL_MB=$(awk 'NR>2 && NF>=4 {total += $3 * $4} END {printf "%.0f", total/1048576}' /proc/slabinfo)
    echo "> **Calculated Slab Total:** $SLAB_TOTAL_MB MB"
else
    echo "`/proc/slabinfo` not readable. Falling back to slabtop:"
    echo "\`\`\`text"
    slabtop -o -s c 2>/dev/null | head -20 || echo "slabtop unavailable."
    echo "\`\`\`"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — TRANSPARENT HUGEPAGES (THP)
# ─────────────────────────────────────────────────────────────────────────────
echo "## 8. Transparent Hugepages (THP) Inflation"
echo "---"
echo '> **Understanding this section:** To increase CPU cache hits, the kernel sometimes bundles memory into massive 2MB "Hugepages". If an app only needs 50KB but gets a 2MB Hugepage, system monitors will report it as using 2MB. This heavily distorts `RSS` readings.'
echo ""
THP_DIR=/sys/kernel/mm/transparent_hugepage
echo "- **THP Policy (Enabled):** \`$(cat $THP_DIR/enabled 2>/dev/null || echo 'N/A')\`"
echo "- **AnonHugePages (2MB chunks):** $(to_mb $ANON_HUGE) MB"
echo "- **ShmemHugePages:** $(to_mb $SHMEM_HUGE) MB"
echo ""
echo '> **Note:** If **AnonHugePages** is extremely large (> 1 GB), standard tools will show vastly inflated RAM usage for apps like Electron and Chromium. The PSS table (Section 3) calculates this away to give you the real number.'
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9 — HYPRLAND MEMORY LEAK CHECKLIST
# ─────────────────────────────────────────────────────────────────────────────
echo "## 9. Hyprland Known Memory Leak Checklist"
echo "---"

echo "### A. Headless Monitor Bug"
if [[ -n "${HYPR_USER:-}" ]]; then
    # Pipefail-immune regex match block
    HYPR_SIG=$(ls -1 /run/user/"$HYPR_UID"/hypr/ 2>/dev/null | head -1 || true)
    HYPR_ENV="XDG_RUNTIME_DIR=/run/user/$HYPR_UID"
    [[ -n "$HYPR_SIG" ]] && HYPR_ENV="$HYPR_ENV HYPRLAND_INSTANCE_SIGNATURE=$HYPR_SIG"
    
    HEADLESS=$(sudo -u "$HYPR_USER" env $HYPR_ENV hyprctl monitors all -j 2>/dev/null | grep -i -c 'headless' || true)
    
    if [[ "$HEADLESS" -gt 0 ]]; then
        echo "🚨 **ALERT: HEADLESS MONITOR DETECTED ($HEADLESS entries).**"
        echo "This causes a catastrophic, infinite DMA-BUF leak in older Hyprland iterations."
        echo "Fix immediately: \`hyprctl output remove HEADLESS-1\`"
    else
        echo "✅ No headless monitors detected."
    fi
else
    echo "⚠️ Cannot check headless outputs (Hyprland user context missing)."
fi

echo ""
echo "### B. Screencopy / OBS / Portals"
SC_PIDS=$(pgrep -f 'screencopy\|wlr-randr\|obs\|pipewire\|sunshine\|xdg-desktop-portal' 2>/dev/null || true)
if [[ -n "$SC_PIDS" ]]; then
    echo "Active screencasting/portal processes pin multiple 4K/1440p DMA-BUFs:"
    echo "\`\`\`text"
    for p in $SC_PIDS; do
        comm=$(cat /proc/"$p"/comm 2>/dev/null || echo '?')
        echo "  [PID $p] $comm"
    done
    echo "\`\`\`"
else
    echo "✅ No screen capturing software detected."
fi

echo ""
echo "### C. Decorations & Shadows"
HYPR_CONF_PATHS=(
    "$TARGET_HOME/.config/hypr/hyprland.conf"
    "$TARGET_HOME/.config/hypr/hyprland.lua"
)
for cfg in "${HYPR_CONF_PATHS[@]}"; do
    [[ -r "$cfg" ]] || continue
    BLUR=$(grep -iE '^\s*(blur\s*=\s*true|blur\s*\{|blurSize)' "$cfg" 2>/dev/null | head -1 || true)
    SHADOW=$(grep -iE '^\s*drop_shadow\s*=\s*true' "$cfg" 2>/dev/null | head -1 || true)
    
    [[ -n "$BLUR" ]]   && echo "⚠️ **Blur enabled:** \`$cfg\`. (Requires massive GPU/RAM framebuffers for Aquamarine)."
    [[ -n "$SHADOW" ]] && echo "⚠️ **Shadows enabled:** \`$cfg\`. (Requires additional surface FBOs per window)."
    [[ -z "$BLUR" && -z "$SHADOW" ]] && echo "✅ No blur/shadow detected in \`$cfg\`."
done

echo ""
echo "***"
echo "**END OF FORENSICS REPORT**"
echo "***"

} 2>&1 | tee "$REPORT"

chown "$TARGET_USER":"$TARGET_USER" "$REPORT" 2>/dev/null || true

echo -e "\n\e[1;32m[✓] Analysis complete. Markdown report safely written to:\e[0m"
echo -e "\e[1;36m$REPORT\e[0m"
