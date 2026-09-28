# Dusky TUI Performance Profiling & Optimization Workspace

This directory (`/mnt/zram1/performance_tui/`) contains the empirical benchmark harness and architectural specification for optimizing Dusky TUI startup latency, eliminating visual opening artifacts, and enabling multi-core system state prefetching.

---

## Directory Contents

| File | Description |
| :--- | :--- |
| **[`gemini_plan.md`](file:///mnt/zram1/performance_tui/gemini_plan.md)** | The comprehensive architectural plan and root-cause analysis intended for handoff to ChatGPT. Delineates the exact bottlenecks in `ui.py`, empirical profiling numbers, multi-core realities vs. myths, and the 4 targeted pillars of optimization. |
| **[`benchmark_startup.py`](file:///mnt/zram1/performance_tui/benchmark_startup.py)** | Isolated, multi-phase performance profiler measuring cold/warm imports, engine state loads, DOM composition, first frame delivery (TTI), tab switch latency, and peak memory (RSS). |

---

## How to Run the Benchmark

### 1. Default Benchmark (UFW 15-Tab Schema)
```bash
python3 /mnt/zram1/performance_tui/benchmark_startup.py
```

### 2. Custom Iterations (e.g. 5 Runs with Averaged Statistics)
```bash
python3 /mnt/zram1/performance_tui/benchmark_startup.py /home/dusk/user_scripts/network_manager/tui_ufw.py --runs 5
```

### 3. Benchmark Another TUI Schema (e.g. Hyprland Input or Appearance)
```bash
python3 /mnt/zram1/performance_tui/benchmark_startup.py /home/dusk/user_scripts/hypr/input/tui_input.py
```

### 4. Machine-Readable JSON Output (For Automation / CI)
```bash
python3 /mnt/zram1/performance_tui/benchmark_startup.py --json
```

---

## Baseline Summary (Pre-Optimization)

Measured on unthrottled hardware against the 15-tab firewall schema (`tui_ufw.py`):
- **DOM Composition & Mount (`compose` -> `mount`):** ~482 ms (42.9% of total startup)
- **First Frame Settled (Time-to-Interactive):** ~762 ms
- **Total Cold Startup:** ~1125 ms (scales to 4.5s–7.0s on 8W throttled hardware)
- **Tab Switch Latency:** ~211 ms
- **Peak RSS:** ~50.6 MB

---

## Target Post-Optimization Metrics
- **DOM Composition & Mount:** < 120 ms (75% reduction via Lazy Tab Mounting)
- **First Frame Settled:** < 250 ms (67% reduction)
- **Visual Opening Artifacts:** **0** (completely eliminated via `with self.batch():`)
- **Total Cold Startup:** < 450 ms on desktop / **sub-second on 8W CPU**
- **Unit Test Suite:** 131 / 131 tests passing (`python3 -m unittest discover -s /home/dusk/user_scripts/dusky_tui/python/tests -p "test_*.py"`)
