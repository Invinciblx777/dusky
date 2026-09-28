# Dusky TUI implementation and verification

Completed 2026-09-28 after the user authorized production changes. The analysis-phase plan is preserved in `plan.md.analysis`; `plan.md` now points to this implementation record.

## Implemented scope

- **UFW read reuse:** one numbered-rule observation per state load supplies all fourteen service checks. Dashboard banned-IP classification reuses its rules observation. The optional explicit rules arguments preserve standalone getter behavior and treat an empty list as a real snapshot.
- **Lazy custom bodies:** hidden custom bodies and their notices mount on first activation. Lightweight tab shells and ordinary/mixed option lists retain the existing warmup contract. Index/name lookup, sparse tabs, Widget classes, supplied Widget instances, notice order, scroll state, selection and help remain supported.
- **Mount completion and focus:** one shared mount task per lazy tab body, marked mounted only after successful completion; failed partial mounts are cleaned up. A late mount cannot switch or focus a newer tab. Search focus follows completed activation. Custom Rich tabs focus their scroll viewport.
- **Active Rich view ownership:** no initial hidden factory calls or hidden timers. Only the current view with loaded dependencies activates. Hidden invalidations mark content dirty without evaluating it. Custom-only tabs explicitly depend on the default engine.
- **Collector/renderer separation:** all six UFW views collect blocking data in a thread under the existing save lock, then render/apply Rich content on the UI thread. One collection per view is in flight; repeated requests coalesce. Generation changes suppress stale results after hide, invalidation or teardown. Shutdown drains blocking collectors before engine shutdown.
- **Retained clean snapshots:** switching away does not invalidate successful collector content by itself. A clean revisit displays retained content and resumes active polling; model/write generations and explicit refresh invalidate it. This removes needless dashboard reads when navigating through tabs. Cheap legacy factories still render on activation, on the UI thread.
- **Stable layout:** footer shortcuts wrap during Textual layout, replacing post-paint absolute positioning and height corrections. Arrow columns reserve their width. Completed option population and tab updates use `batch_update()`; no batch spans backend I/O. Known default-engine telemetry reserves its space during initial mount. Later discovery of a different telemetry engine may still change geometry.
- **Profiler:** collector spans/errors, actual viewport dimensions and retained-content metadata added. The earlier baseline profiler is preserved as `benchmark_startup.py.baseline-profiler`; the original pre-audit script remains `benchmark_startup.py.before`.

Production changes are limited to `python/frontend/ui.py`, `python/engines/ufw.py` and `network_manager/tui_ufw.py`. One new test module was added. The launcher and all existing test files are unchanged. No files were staged or committed.

## 8 W measurements

Three saved before samples (`ufw-8w.json`) and five final after samples (`ufw-8w-after.json`), sequential fresh root processes, UFW schema, headless 120×40, tabs 1/2/14, idle observation 3.2 seconds. Intel RAPL package constraints 0 and 1 read 8,000,000 µW in the final records; MMIO remains 50/60 W. No power settings were changed.

| Measurement, median | Before | After | Outcome |
|---|---:|---:|---|
| First headless compositor callback | 10,649.6 ms | 3,302.6 ms | 69.0% lower |
| Active data + refresh readiness proxy | 20,979.2 ms | 7,166.1 ms | 65.8% lower |
| UFW state load | 10,258.0 ms | 1,367.0 ms | 86.7% lower |
| Startup external commands | 86.0  | 6.0  | 93.0% lower |
| Startup Rich factories | 35.0  | 1.0  | 97.1% lower |
| Custom Rich widgets at boot | 6.0  | 1.0  | 83.3% lower |
| Total widgets at boot | 110.0  | 106.0  | 3.6% lower |

Startup numbered-rule reads: **47 → 2** (one engine observation plus one dashboard observation). Startup has exactly one collector and one renderer in every final sample. Hidden idle factory calls: **6 per before sample → 0 in all five after samples**. Renderer spans run on `MainThread`; collectors run on executor threads. All observed external commands returned zero; all benchmark error lists are empty.

Mounted widget count at boot fell only 3.6%; the large gain comes from removing expensive redundant/hidden work. Do not present lazy mounting as a measured 75% allocation reduction. UI inclusive import time remained about 0.91 seconds, with no attributable import optimization.

### Tab visits

| Visit, median | Before | After | Outcome |
|---|---:|---:|---|
| Controls, first visit | 434 ms | 280 ms | faster |
| Controls, revisit | 212 ms | 211 ms | unchanged in practical terms |
| Sockets, first visit | 1922 ms | 1855 ms | faster |
| Sockets, revisit | 1773 ms | 118 ms | faster |
| Reports, first visit | 789 ms | 894 ms | slower |
| Reports, revisit | 1037 ms | 192 ms | faster |

Clean collector revisits reuse existing data; these timings are **not fresh system-read latency**. Hidden data is not polled. After returning to a clean view, external changes become visible on the resumed polling interval, or through explicit refresh. Model/write generation changes invalidate retained snapshots, and a dirty revisit recollects. This freshness policy is deliberate and tested.

Reports' first visit is about 105 ms slower than the before median. It now pays for lazy mount and a fresh worker read, whereas the before implementation mounted and polled it while hidden. Controls revisit is essentially unchanged. The initial implementation accidentally started expensive dashboard work on every return, increasing Sockets visits to ~4.3 seconds; the final retained-snapshot change removes that regression. `ufw-8w-after-first-pass.json` preserves the diagnostic evidence; it is not the final result.

### Interpretation limits

Headless compositor callbacks are not optical frames; data readiness is a refresh proxy, not keyboard-input-to-pixel TTI. Milestones overlap. Filesystem/bytecode caches are uncontrolled. There are only three before and five after samples; no percentile or tail guarantees are claimed. The profiler gained small collector and viewport observations after the baseline revision; primary milestone definitions and launcher behavior stayed the same. Results establish this UFW workload, not a universal startup time for every schema.

## Verification

- Original 131 tests retained unchanged. A full run with the retained-snapshot implementation passed **143 tests in 229.643 seconds** (`tests-final-retained-8w.log`).
- After the final banned-rule reuse change, all **13 new tests passed in 35.023 seconds** (`implementation-tests-final.log`), and all **14 original UFW engine tests passed in 0.367 seconds** (`ufw-tests-final.log`). Together these cover the original 131 plus all thirteen additions; a single final 144-test run was not repeated after that narrow getter change.
- Earlier full implementation run: 141 tests passed (`tests-final-8w.log`). Early failures in exploratory logs are retained; they are superseded by the final passing runs.
- New coverage: hidden factories/polling, sparse lazy tabs and notices, repeat/rapid activation, supplied Widget/class, footer wrap at 48/80/120 columns, mixed-tab search, retry after failed body creation, initial load failure, coalesced collection, UI-thread/worker separation, late-result suppression, cancellation drain/lock lifetime, cached revisit/invalidation, one rules read per load, banned-IP reuse, pure UFW rendering and actual report text.
- Syntax checks passed for all changed Python files. Scoped Git diff review and `diff --check` passed. An AST comparison confirms option population logic is unchanged beneath its new batch context.
- A real kitty Wayland driver run completed with zero errors and synchronized-output negotiation **enabled** (`kitty-final-8w.json`). Its actual viewport was 62×31, independently recorded rather than assumed from requested dimensions. The first driver-flush return was 2830 ms for the nonroot INI fixture. This is a driver exercise, not a UFW timing comparison or a video of physical presentation.
- An intentional collector exception was reported and rejected by the profiler (`benchmark-collector-failure.log`). Exceptions displayed by the UI cannot silently become successful collector benchmarks.

Application layout feedback loops and unsafe Rich worker rendering have been removed. **Complete optical flicker/tearing elimination remains unverified:** no opening-frame video was captured. Terminal GPU presentation and glyph metrics are outside an app repaint batch. Generic supplied Widget classes retain responsibility for their own private workers/timers; the framework's polling guarantees apply to its Rich view/collector lifecycle.

## Conditional plan steps

- **Cross-engine concurrency:** not added. The measured UFW workload has one engine, so cross-engine scheduling cannot shorten it. Existing off-thread engine loading remains. Parallel mutable-engine operations would add ordering risk without measured benefit here.
- **Markdown deferral:** not added. The separate throttled `-X importtime` trace (`importtime-after-8w.log`) reports UI cumulative 1,484 ms, markdown-it 141 ms and Textual highlight 34 ms. This traced direct import has different order/overhead from the launcher and does not prove equivalent savings. Deferring the help widget/import changes its lifecycle, while visible Markdown schemas still pay legitimately. No demonstrated net gain justifies that extra behavior change in this iteration.
- No process pool, forced ANSI batching, invented Textual API, hardware-specific production paths, or older-platform fallback was introduced. The final ISO package manifest still needs its planned version-floor verification before shipping, as stated in the original analysis.

## Collector contract for future expensive views

```python
CUSTOM_VIEWS = {
    0: {
        "view": render_snapshot,       # snapshot -> Rich content, UI thread
        "prepare": capture_selection, # app -> inputs/engine handle, UI thread
        "collect": read_system_data,  # prepared inputs -> data, worker thread
        "interval": 2.0,
        "show_options": False,
    },
}
```

The collector must not query or mutate Textual widgets. Rendering must perform no blocking engine/system reads. Capturing a bound engine handle is allowed; its operations share the framework save lock. Legacy zero-argument and `factory(app)` APIs remain available for cheap UI work. Rendering errors are logged/displayed and collection errors are observable in the profiler.

## Review artifacts

`implementation.diff`, `benchmark-collector-review.diff`, `implementation-sha256.txt`, `comparison.json`, the raw benchmark JSON files and final test logs are in this directory. Original production files are preserved in `implementation-before/`.

| Area | Before score /100 | After score /100 | Outcome |
|---|---:|---:|---|
| Performance | N/A | N/A | Better: first headless render 69% lower; data readiness 66% lower |
| Efficiency | N/A | N/A | Better: 86 → 6 startup commands; no hidden Rich polling observed |
| Reliability | N/A | N/A | Better in tested lifecycle/layout behavior; original tests pass; optical artifacts unverified |

Scores are N/A because there is no calibrated 1–100 quality scale. Timing/count improvements are measured; optical presentation is not.
