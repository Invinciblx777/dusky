# Dusky TUI: architecture and implementation plan

Prepared 2026-09-28; implemented after subsequent user authorization. This replaces the Gemini plan.

**Implementation status:** A–D production changes are implemented, with passing tests and benchmarks. Optical visual acceptance remains unverified. E/F remain conditional and were not justified by this workload. See [implementation.md](implementation.md) for final scope, timings, tests and visual limitations. The original analysis-only document is preserved as `plan.md.analysis`.

## Decision

First eliminate redundant backend queries and hidden custom-view work. Then fix custom-view ownership and opening layout stability. Preserve ordinary option-list warmup to retain all 131 existing tests. Only add bounded I/O concurrency if measurements after those changes still justify it. Import deferral is a later, conditional improvement.

There is no evidence supporting Gemini's promised subsecond startup at 8 W or its guarantee that batching eliminates every visual artifact. Treat those as rejected claims, not acceptance criteria. An 8 W limit is a useful stress condition, but does not reproduce an old processor's IPC, memory, storage, or graphics behavior.

## Verified environment and scope

- `/usr/bin/python3`: CPython 3.14.7, GIL enabled, not a free-threaded build.
- Installed Textual 8.2.8-2, Rich 15.0.0-1, markdown-it-py 4.2.0-1, Pygments 2.21.0-1.
- Installed systemd 262-1, Hyprland 0.56.2-3, kitty 0.49.1-1.
- Running kernel: `7.3.0-rc4-dusky-battery`; separately installed Arch `linux` package: 7.2.7.arch1-1. Neither observation establishes the final ISO's promised released kernel floor. Verify the final ISO package manifest before shipping. No compatibility paths for older platforms are proposed.
- Read all 7,679 lines of `python/frontend/ui.py`, all of the prior plan and original benchmark, and relevant launcher, engine, test, and installed Textual paths.
- Original UI SHA-256: `47686d184956491dec83458d0f2f74cfb6a791fea9ff8e92dccc563e62093271`. Its scoped Git status/diff were clean before investigation.
- Baseline suite: **131 tests passed**, 30.739 seconds before the user enabled the power limit. `tests-baseline.log` records the run.
- User enabled the limit during investigation. Subsequent measurements verified Intel RAPL package constraints 0 and 1 at 8,000,000 µW. MMIO constraints still read 50/60 W; record both interfaces rather than describing every constraint as 8 W. `power-8w.json` records the observed limits. These are configured limits, not a measured energy integral.

## What the previous plan got wrong

| Claim | Finding and consequence |
|---|---|
| `with self.batch()` is the fix | That method does not exist on installed `App`. The supported API is `batch_update()`. Calling Gemini's version fails. |
| Initial mount is unbatched | Textual 8.2.8 `App._process_messages` already encloses Compose, initial Resize, stylesheet application and Mount in `batch_update()`. `ContentSwitcher` also batches its display changes. Wrapping the same mount again is largely redundant. |
| Headless `run_test()` + `pilot.pause()` measures first frame / TTI | Headless mode does not send terminal frames. `run_test()` waits for startup and message processing; `pause()` waits for CPU idle and triggers screen update. Neither is an exact DOM timer or backend-readiness barrier. |
| All latency belongs to DOM construction | The old interval includes arbitrary custom callbacks, subprocess work, layout and test-runner synchronization. It cannot assign that time to widget allocation. |
| Existing engine loading is synchronous UI work | Initial and deferred loads already use `asyncio.to_thread`. Loading is sequential within batches, but already off the UI thread. Custom initial render factories are a different, synchronous path. |
| Parallel engine loading helps the UFW sample | UFW has one engine. Parallelizing across engine keys cannot split that engine's workload. |
| `markdown_it`, `pygments`, `difflib`, `webcolors` are direct UI imports | They are not direct imports in this file. Markdown introduces transitive dependencies; `webcolors` is already locally imported and cached in `core_types._get_css_named`. `ExportDialog` and `ColorPickerDialog` are not classes in this UI. |
| A hidden widget's `display` is false | `DOMNode.display` checks the node's own style/lifecycle, not ancestor visibility. The custom Rich widget inside a hidden tab can still have `display=True`. |
| Full lazy tab mounting preserves all current tests | Two tests explicitly require hidden option lists to be populated before visiting and warmed after deferred discovery. Do not delete, skip, weaken, or silently rewrite them. |
| Process pools / threads universally accelerate parsing | Threads do not give parallel Python bytecode execution in this GIL build. Process startup, serialization and engine ownership make process pools a poor default here. |
| 75% fewer allocations and zero artifacts are guaranteed | Neither claim was established. Screen presentation involves terminal and compositor behavior as well as app layout. |

Sources: installed Textual `app.py` (`batch_update`, `_process_messages`, `_display`), `pilot.py` (`pause`), `_content_switcher.py`, `dom.py`; [official App API](https://textual.textualize.io/api/app/), [testing guide](https://textual.textualize.io/guide/testing/), and [worker guide](https://textual.textualize.io/guide/workers/). Installed source takes precedence for exact version behavior.

## Measured and demonstrated problems

### 1. UFW repeats expensive reads

`UfwEngine.load_state()` calls `is_service_allowed()` for 14 entries in `COMMON_SERVICES`; each call runs `get_numbered_rules()` again. Status views also independently fetch status, rules, sockets and reports. In the initial root benchmark, startup generated 29 `ufw status numbered` calls and 46 external commands overall per sample. One engine load took about 1.72 seconds even before the 8 W rerun. Its state load is not the 146 ms claimed in Gemini's table.

The original profiler omitted `REQUIRE_ROOT`, swallowed exceptions, and ran commands through `sudo -n` without establishing authentication. UFW getters can return empty/default data on unsuccessful commands without raising. Thus a fast nonroot sample can measure failures instead of the real workload. The replacement runs the actual launcher, rejects its attempted sudo re-exec, and requires the operator to supply privileges. It records subprocess return codes.

### 2. Hidden custom views mount and poll

`DuskyTUI.compose()` builds all six UFW custom views. `CustomRichTabWidget.on_mount()` invokes each factory synchronously; the visible view can run again in `on_show()`. `on_mount()` tests local display before starting the timer, and periodic `_async_refresh()` invokes factories in threads. Hidden views therefore consume subprocess/CPU time independently of option-list warmup.

A separate temporary-file INI fixture with a 30 ms factory and 50 ms interval demonstrated repeated factory calls with a hidden ancestor before its tab was ever visited. Four calls occurred during a 200 ms hidden observation in each of the two initial fixture runs. This is an observed lifecycle defect, not an inferred allocation percentage.

### 3. The existing framework has useful lazy mechanisms

Retain `LazyEnginePool`, per-tab data readiness, `_tab_dirty`, incremental option updates, render cache, preset matrix and off-thread loads. Their presence changes the design priorities. The schema/index/state model already lives independently of widgets; global save/preset correctness must not become dependent on whether a tab was visited.

`_tab_populated` and `_populated_tabs` are parallel bookkeeping sets; `_mounted_tabs` is initialized but unused. Consolidate only as part of the tab changes, with explicit call-site review. Do not add another competing set called `_unmounted_tabs` on top of these.

### 4. Opening layout changes have identifiable candidates

`FlowContainer` initially uses ordinary widget layout, then sets children to absolute positions and computes its height after refresh / resize. `check_tab_overflow()` changes arrow display and available width after refresh. Telemetry becomes displayed after engine boot, changing the content height. These are concrete sources of additional layout passes, but no optical recording from the user's terminal was captured, so their contribution to the reported artifacts is unproven.

## Implementation sequence

### A. Reuse UFW observations within a load/refresh operation

Scope: `python/engines/ufw.py`, with narrowly targeted schema changes where necessary.

1. Read numbered rules once per `load_state()`. Classify all 14 services against that immutable local result. Preserve existing matching semantics; rule matching changes are a different task.
2. Keep `is_service_allowed()` usable by its other callers. A small helper accepting preloaded rules, or an optional explicit rules parameter, is enough. Avoid a global time-based cache as the first solution.
3. For the active dashboard, collect one coherent snapshot of status, rules and other required reads. Pass it to pure Rich rendering code; reuse it within that refresh. Do not repeatedly re-read values in conditional expressions.
4. Invalidate/recollect after an operation changes the firewall; preserve explicit refresh behavior. Never serve an old action outcome as fresh state.
5. Verify with mocked command counts: one numbered-rule read per engine load instead of 14, same derived service states, and failure reporting retained. Measure actual root startup again.

This has a concrete work reduction and is likely more valuable than generic engine concurrency. Do not implement all possible engine optimizations simply because UFW needs this one.

### B. Make custom views active-tab owned; retain option warmup

Scope: `ui.py` composition, tab activation and `CustomRichTabWidget` lifecycle.

1. Keep all lightweight tab containers and tab labels, preserving IDs and sparse tab keys. Keep ordinary `ConfigOptionList` skeletons and their current warmup contract.
2. Defer hidden custom-view bodies and their expensive notices to first activation. Mixed `show_options=True` tabs retain their option list; mount their custom region independently. Preserve top/bottom notice order, scroll wrappers, class styling, integer/name custom-view lookup, renderable factories, widget classes and supplied widget instances. Supplied instances cannot have their constructor cost deferred, but their mounting can be.
3. Use one idempotent tab-body mount operation. Await Textual's mount completion before querying descendants, focusing, populating or marking the body mounted. Do not discard the pending marker before successful completion. Coalesce repeated activation while mounting; a late completion must not steal focus from a newer tab.
4. Retain visited bodies rather than unmounting on every switch. Preserve scroll, selection, tree expansion, help and dirty-state behavior. Hidden bodies do not refresh or poll.
5. Explicitly activate/deactivate the custom body from tab ownership. Do not infer it from the child's `display`. Stop timers when leaving; do not create a timer on mount while hidden. Avoid duplicate `on_mount`/`on_show` first evaluations.
6. Audit `handle_tab_activated`, `_refresh_custom_views`, `_populate_option_list`, `_refresh_single_ui`, `_refresh_all_ui`, `_apply_deferred_tabs`, warmup, focus and search paths. `_refresh_custom_views` currently iterates direct children, while Rich widgets are nested in scroll containers: resolve the actual view, and mark hidden content dirty instead of eagerly evaluating it.
7. Search currently populates the target before switching and schedules focus after refresh. Route search completion through the same activation/mount completion path so search into an unvisited tab cannot silently fail.
8. Keep global model initialization and existing `require_boot_complete()` semantics. Custom-only tabs have no setting-derived engine dependencies; explicitly treat the default engine as a dependency for the current UFW custom-view contract. Do not mistake an empty dependency set for a populated dashboard.

Full lazy mounting of **ordinary** option lists is not in this iteration. If later profiling shows those skeletons dominate, propose that behavior change separately. With the current tests frozen, “all hidden tabs never mount” is not a valid target.

### C. Separate custom data collection from rendering

Removing hidden work alone still leaves the active UFW dashboard blocking the event loop during initial factory invocation.

- Preserve current callable APIs for existing cheap factories, but do not silently send arbitrary `factory(app)` callbacks to a thread. They may query widgets, mutate app state, or use engine methods that call back into the UI. Existing periodic `to_thread(self._invoke_factory)` is not evidence that every factory is thread-safe.
- Introduce a small, explicit opt-in collector/renderer contract for expensive custom views. Snapshot required selection/state on the UI thread, collect blocking system data in a worker, then build/apply the Rich renderable on the UI thread. Start with UFW. Existing renderable and Widget variants retain their public behavior.
- One in-flight collection per view. Coalesce timer/manual requests, with a single pending refresh if needed. A generation/token or task identity rejects results after deactivation, replacement, newer selection or shutdown. Canceling an await does not stop a running blocking thread: suppress its late result and prevent overlapping work on the same engine.
- Serialize operations sharing mutable engine state. Keep saves and refresh reconciliation consistent with existing `_save_lock` and write generations; do not invent independent pools that race them.
- Show a stable, correctly sized loading region while data is pending; apply success/error content once. A loading shell is not reported as ready content. Errors must remain observable and retryable.
- For expensive refreshes, avoid using `repr(renderable)` as proof of content equality: Rich objects may have identity-based representations. If redundant updates are measured, compare explicit snapshot versions/values. Do not add deep renderable hashing.

The [Textual worker guidance](https://textual.textualize.io/guide/workers/) supports doing blocking work outside the UI thread and delivering UI changes back to it. It does not make shared app/engine objects thread-safe.

### D. Stabilize opening geometry and batch completed updates

1. Use `with self.batch_update():` around related **completed UI mutations**, such as applying loaded state, populating options, updating footer and exposing the newly prepared view.
2. Do not hold a global repaint batch across slow I/O, worker waits, a refresh callback, or readiness polling. Waiting for refresh while preventing refresh can deadlock; long batches also hide responsiveness.
3. Initialize static geometry in composition/CSS. Replace footer post-paint repositioning with a layout that produces the intended wrapped rows during layout, if a focused reproduction confirms footer jumps. Use an installed/documented built-in only if it preserves wrapping; otherwise a small explicit Textual layout implementation is preferable to an after-paint feedback loop. Do not invent a CSS flex-wrap property.
4. Coalesce duplicate overflow callbacks, and avoid repeatedly changing arrow visibility around the width threshold. Prefer stable reserved arrow width where acceptable. Test threshold widths, not just 120 columns.
5. Decide telemetry space before revealing content when capability is known. If late discovery requires a visible change, make it one coherent update. Do not reserve a large empty banner in every schema without considering the layout impact.
6. Mount hidden preparation content within the current short update transaction, await mount as required, then expose/focus it. Never mark a tab “ready” while children or state are missing. Explicitly test that asynchronous mounting does not reveal an empty pane or freeze the old pane.
7. Keep terminal output under Textual's ownership. It already probes synchronized-output support (`CSI ?2026$p`) and brackets updates when detected. Do not add handwritten ANSI wrappers, force an unsupported terminal flag, or infer support from `TERM` alone.
8. Validate under the actual Wayland terminal and Hyprland session. Distinguish (a) multiple valid frames with changing geometry, (b) partial ANSI repaint presentation, and (c) font/glyph-width discrepancies. An app batch does not control terminal GPU presentation or fix glyph metrics.

A PTY exercise verified that the terminal benchmark path runs, but that PTY reported no synchronized-output support. It is not an observation of the user's kitty window and cannot prove flicker removal.

### E. Add bounded I/O concurrency only if still warranted

- First measure a real multi-engine schema. The UFW singleton cannot demonstrate cross-engine benefit.
- Prefer a small bounded set of `asyncio.to_thread` loads, with a semaphore and deterministic result/error association. Use one scheduling authority and at most one active operation per engine. Start with a measured comparison of 1, 2 and 4 concurrent operations under 8 W.
- Include the initial `need_now` path; changing `_load_engines_batch_sync` alone does not change the serial initial-tab loop in `run_deferred_boot`.
- Resolve lazy engine creation ownership. `LazyEnginePool.__getitem__` is not synchronized; concurrent lookups can create duplicates. Distinct engine keys may still refer to a shared object/resource. Engine `set_app` can marshal to the UI thread. Do not hold a worker lock while synchronously asking that same UI thread to acquire it.
- Preserve cancellation, teardown, error attribution, default-engine binding, writes and deferred inventory semantics. Avoid nested executors or executor shutdown that blocks the event loop.
- Do not use `ProcessPoolExecutor` for Textual widgets or these small state loads. Only revisit processes if a substantial, isolated pure CPU task is measured and pays for startup/serialization.
- Extra concurrency can worsen a package-power-limited workload by consuming the UI thread's power budget. Require wall-time and responsiveness evidence, not CPU-count rhetoric.

### F. Defer Markdown only if the remaining import cost justifies it

One separate `-X importtime` diagnostic before throttling measured UI import at 269 ms cumulative, including markdown-it at 25.4 ms and `textual.highlight` at 6.4 ms. These overlap and the trace itself adds overhead; they are not promised savings.

`Markdown` is imported through `textual.widgets` and instantiated for the hidden help panel at startup. Simply moving its import into `compose()` changes where the cost occurs, not startup cost. A real deferral must also defer that hidden Markdown widget and import it when help/notice/modal content actually needs it. Schemas with visible Markdown notices/popups still pay legitimately at startup. Preserve formatting, CSS and help behavior. Do not replace documented Markdown content with plain labels just to improve a timer.

Do not split the 7,679-line file into many modules solely for speed; imported module count and dependency closure matter more than file length. Keep public imports and the cheap `core_types` schema boundary intact.

## Benchmark replacement and interpretation

`benchmark_startup.py` now instruments the **actual launcher** using a fresh subprocess per sample. It preserves launcher import order, schema name/options, theme, root requirement, engine overrides, `LazyEnginePool.bind_app`, deferred discovery and preset settings. It performs no extra state preload and has no fake-engine fallback.

The old standalone preload was especially misleading: its result was discarded, then app boot loaded state again. The old total omitted engine import/construction and interpreter startup while adding this redundant read. It also incorrectly enabled default user presets on UFW and omitted the real theme and other schema settings.

The replacement records:

- Parent-spawn-relative milestones, including observer/launcher entry, app run entry, app mount enter/return, compositor callback, after-refresh, active-data refresh, and full boot/discovery refresh. These overlap and must not be added.
- Inclusive selected import spans in production order. These are module execution observations, not exhaustive import accounting. Use separate `-X importtime` diagnostics for the dependency tree.
- Exclusive time advancing the app's composition generator. This is **not** the cost of Textual mounting descendants, CSS or layout. App mount callbacks also do not represent whole-tree mount duration.
- Actual engine-load spans, custom factory spans with thread and ancestor visibility, external command durations/return codes, widget counts, first visits and revisits with preexisting warmup metadata.
- Raw samples, median/mean/min/max; source hashes, interpreter/Textual/kernel, GIL, affinity, power limits, dimensions, terminal metadata and bytecode-cache prefix. No percentile claims from three samples.
- Strict subprocess failure handling, positive run counts and total child timeout. Failed factories/engine loads cannot quietly become successful benchmark records. Engine getters that mask unsuccessful commands remain detectable through command return codes.

`--mode terminal` uses Textual's normal driver and records first driver-flush return. `--mode headless` emits no terminal frames. Neither measures optical presentation. First compositor callback can show a loading/default state. The data-refresh milestones are explicit **readiness proxies**, not proven keyboard-input-to-pixel TTI; startup popups are retained and tab tests are skipped rather than dismissing them silently. Arbitrary custom Widget readiness requires a future explicit application signal.

Instrumentation adds cost, including Python imports before launcher entry; the parent-to-launcher interval is reported separately. Method/command spans are inclusive and can overlap across threads. CPU time/RSS cover the whole observation, including switches and shutdown, not startup alone. Fresh process means cold Python module state, not cold disk: no page-cache eviction was performed. The harness uses private observation points only in this external diagnostic; revalidate them on Textual upgrades. Production code must use public APIs.

## Acceptance and implementation handoff

Original implementation handoff: implement A–D with scoped reviews and measurements; only proceed to E/F when evidence supports them. Implementation and final measurements are now recorded in `implementation.md`. The baseline findings and acceptance criteria below are retained for reference.

1. Keep the original **131 tests passing unchanged**, including `test_ready_tabs_are_warmed_before_switch`, `test_discovered_tab_is_warmed_after_deferred_load`, and sparse-index tests. Add focused tests for new lifecycle behavior; a larger total is expected and does not replace the original tests.
2. New tests: zero hidden custom factory calls before first visit; zero hidden polling after switching away; exactly one initial collection; no overlapping refresh; late result after hide/quit discarded; failed mount/load observable; rapid A→B→A activation; search into an unvisited tab; mixed custom/options; supplied Widget/class; empty/sparse tabs; hidden dirty data and deferred discovery; initial engine failure; save/load ordering if concurrency is introduced.
3. Preserve duplicate-setting synchronization, initial/committed baselines, pending edits, presets, undo/redo, root behavior and F5. Global features must work without visiting every tab.
4. Compare under the same 8 W settings, schema, privileges, dimensions, terminal/font, firewall state and cache condition. Run sequentially with unrelated heavy activity stopped. Use at least five samples for routine comparisons; use more samples for tail behavior. Report first visit and revisit separately, including whether option warmup completed.
5. Desired work-count outcomes: one rules snapshot per UFW load; no hidden custom refresh commands; one initial active custom collection; normal hidden option lists still warm. These are testable acceptance gates even before setting timing targets.
6. Visual acceptance: capture real opening frames at 80×24, 120×40, and around footer/tab-overflow breakpoints under 8 W; inspect after resizing and theme changes. No transient overlap, misaligned boxes, stale focus or blank intermediate tab pane. A coherent loading region is allowed and timed separately. Verify terminal synchronized-output negotiation rather than claiming app-level batching guarantees presentation.
7. Responsiveness acceptance: inject harmless navigation/help input while backend collection is deliberately delayed; confirm it is processed before that collection completes. An eventual passing screen test does not prove responsiveness. Measure event-loop delay/input-to-refresh separately from data readiness.
8. Run syntax checks and the full test suite, then review scoped diffs. Do not stage, commit or publish. Confirm the final ISO versions before relying on this installed environment.

Example repeatable commands (run from an ordinary shell; supply sudo normally for the root schema):

```bash
python3 -m unittest discover -s "$HOME/user_scripts/dusky_tui/python/tests" -p 'test_*.py'
sudo python3 /mnt/zram1/performance_tui/benchmark_startup.py \
  "$HOME/user_scripts/network_manager/tui_ufw.py" \
  --runs 5 --tabs 1,2,14 --observe 3.2 --timeout 180 \
  --label '8 W; before or after; terminal/cache condition' \
  --output /mnt/zram1/performance_tui/ufw-comparison.json
```

For real-driver measurements, add `--mode terminal` and run in the actual terminal window without redirecting stdout. Record a screen capture separately; the JSON file cannot certify flicker. The benchmark reconstructs the invoking user's launcher path under sudo and accepts `--launcher` for other layouts.

## Final 8 W baseline for the implementing model

Use **`ufw-8w.json`**, not the earlier exploratory files. It contains three sequential root runs at 120×40, with a 3.2-second idle observation followed by tabs 1, 2 and 14, each visited twice. All three runs used benchmark SHA-256 `ada2a55c81d0bc6e47ac65e23e20ab0bfe89f477613d22c02eeaca17b196d147`; all observed external commands returned zero. No production changes separate these samples.

| Measurement | Median | Range / interpretation |
|---|---:|---|
| Observer/launcher entry from parent spawn request | 567 ms | 565–570 ms; instrumentation/interpreter setup included |
| App run entry | 1,746 ms | 1,743–1,748 ms |
| First headless compositor callback | 10,650 ms | 10,569–10,672 ms; not a terminal frame |
| First after-refresh callback | 11,108 ms | 11,021–11,120 ms |
| Active data + refresh readiness proxy | 20,979 ms | 20,947–20,988 ms |
| Global boot + refresh proxy | 20,981 ms | 20,949–20,991 ms |
| UFW engine load span | 10,258 ms | 10,246–10,340 ms; overlaps other activity |
| App composition generator execution | 26.8 ms | 26.7–27.2 ms; excludes Textual's mount/layout/CSS |
| UI module execution, inclusive import span | 923 ms | 923–924 ms; includes dependency execution |
| Startup external commands | 86 | 47 are repeated numbered-rule queries; polling included |
| Startup custom factory calls | 35 | All six custom widgets mounted |
| Widgets at boot | 110 | Includes six custom Rich widgets |
| Controls tab: first visit / revisit | 434 / 212 ms | Option list already warmed |
| Sockets tab: first visit / revisit | 1,922 / 1,773 ms | Includes view work and refresh barriers |
| Reports tab: first visit / revisit | 789 / 1,037 ms | Includes view work and refresh barriers |

In every final run, the idle observation recorded hidden callbacks from tabs 2, 4, 6, 9 and 14. This directly confirms that the hidden polling defect affects the real schema, not just the fixture. Inclusive factory time totals about 39 seconds and command time about 47 seconds during startup because multiple threads overlap; **do not add these numbers to wall-clock time**.

These results do not reproduce the user's 5–7 second visual estimate. They describe this root UFW workload, with the real launcher and explicit data-readiness barriers, under an instrumented headless run. Periodic refresh counts grow when startup is slow, producing additional contention. Compare future implementations against the same harness/conditions; do not treat this table as a universal Dusky startup time.

`ufw-baseline.json` predates the final profiler and spans the user's power-setting transition late in the experiment. `ufw-8w-exploratory.json` spans profiler refinements. Keep both for investigation only; neither is the canonical comparison baseline. `benchmark_startup.py.before` preserves the original script and `benchmark-review.diff` records the rewrite.

### Profiler verification and remaining limits

The final profiler completed three headless INI fixture runs and one terminal-driver PTY run under 8 W, all without recorded errors. The PTY driver-flush milestone was 2,852 ms; this verifies instrumentation execution, not optical performance. Invalid run counts, NaN observation duration, nonexistent schemas and redirected terminal mode were rejected. Deliberate schema-import failure propagated; a one-second child timeout failed and terminated the headless process group. Syntax checks passed. See `fixture-8w-final.json`, `fixture-pty-8w.json`, and `benchmark-checks.log`.

Tab timings begin at the application action call; they exclude physical keyboard/PTY input delivery. Inspect captured stderr as well as the errors list: application code can internally catch deferred-discovery errors, and arbitrary custom Widgets do not expose a general readiness contract. The measured successful UFW runs had zero recorded command failures. Terminal-mode timeout kills the application process; the headless mode is the one with process-group timeout cleanup. These diagnostic limits must not become claims of full end-to-end correctness.

Analysis-phase regression verification under the enabled 8 W limit: **131 tests passed in 194.671 seconds** (`tests-8w.log`). Asyncio emitted slow-callback diagnostics; there were no test failures. Production UI SHA-256 remained identical to the original, and scoped Git status/diff checks showed no changes to UI, launcher, UFW engine or tests. No files were staged or committed.

| Area | Before score /100 | After score /100 | Outcome |
|---|---:|---:|---|
| Benchmark validity | N/A | N/A | Better: actual launcher, real privileges, explicit readiness, failures, raw samples and truthful frame labels; exercised in headless and PTY modes |
| Production performance / efficiency | N/A | N/A | Unchanged: analysis only; 8 W baseline saved, no optimization gains claimed |
| Visual reliability | N/A | N/A | Unverified: lifecycle defects demonstrated and acceptance plan specified; no optical before/after capture |

Scores are N/A because no calibrated 1–100 scale exists for these measurements. The table reports observed changes without inventing numerical quality gains.
