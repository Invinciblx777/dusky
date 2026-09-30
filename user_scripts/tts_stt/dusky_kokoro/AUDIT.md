# Dusky Kokoro audit — 2026-09-30

## Result and scope

Updated the source and installed runtime to Dusky Kokoro 5.1.0. Installation,
CUDA synthesis, CPU synthesis, playback, archiving, socket activation and the
regression suite passed on this machine. These results establish the tested
behavior; they do not establish flawless operation on every GPU or language.
This directory implements **text to speech**. The separate Parakeet speech to
text setup was outside this audit.

Read all eight supplied files in full, inspected the installed configuration,
units, runtime and direct TUI/Hyprland call sites, and compared upstream
Kokoro/ONNX Runtime examples and documentation. No security audit was performed.

## Environment and installed outcome

- Python 3.14.7, Bash 5.3.20, systemd 262, Hyprland 0.56.2, uv 0.12.20,
  mpv 0.41.0 and Poppler 26.08.0.
- RTX 3050 Ti Laptop GPU, 4 GiB; NVIDIA driver 615.71.09. An Intel integrated
  GPU is also present. Testing used a Wayland/Hyprland session.
- Development kernel: **7.3.0-rc5-dusky-battery**, rather than a final 7.3 release.
  Final ISO package versions/build features still require release validation.
- Installed ONNX Runtime GPU 1.30.0, NumPy 2.5.3 and kokoro-onnx 0.6.1.
  Exactly one ONNX Runtime distribution is installed in the isolated environment.
- Existing voice, playback and timeout preferences were preserved. The configured
  arena budget remains 2048 MiB. A fresh template is in `config.toml.new`.
- The user socket is enabled; the daemon starts on demand and exits when idle.

## Fixes

| Area | Finding | Change |
| --- | --- | --- |
| Long text | Repeatedly scanning and slicing the remaining paragraph was quadratic; unmatched Markdown brackets also caused excessive work. | Scan with a cursor; restrict link patterns to their actual delimiters; scan Markdown fences linearly; prepare text outside the control loop. |
| Audio buffering | `prefetch_segments = 4` actually allowed 512 queued segments. | Honor the configured count. Audio buffering stays bounded by segment sizes and queue capacity; text storage still scales with document length. |
| Worker lifecycle | Reload reacquired the same lock; interrupt handling could leave unreaped processes; worker configuration could be stale. | Serialize lifecycle and I/O, transfer the complete config and paths, bound startup, and terminate/reap interrupted workers. |
| Runtime failures | Worker errors lost their cause; provider selection could report CUDA despite fallback; invalid waveforms reached silence trimming. | Frame state/errors with PCM, check finite/nonempty model output, report the active backend and retry eligible accelerator inference failures once on CPU. |
| Low memory | The arena setting was advertised as a total VRAM cap; global GPU-zero utilization could trigger repeated reloads. | Clarify the arena budget, disable large cuDNN workspaces by default, constrain TensorRT workspace, and use actual inference failure for CPU fallback. |
| Installation | Stale model sizes, inappropriate Python/backend wheel selection, automatic package changes, weak download validation and successful completion after failed self-tests. | Correct manifests, validate model hashes/voice tensors, recover complete partial downloads, remove invalid partials, require explicit system dependency installation and fail failed self-tests. |
| Offline/repeat installs | Ordinary reruns upgraded dependencies and had no explicit offline contract. | Reuse the lock by default; add `--upgrade`, `--offline` and `--ort-wheel`. Offline installation requires cached dependencies/models and preinstalled system tools. |
| Documents | PDF extraction referenced an unimported module; EPUB chapters followed ZIP order. | Import subprocess and follow the EPUB package spine; report unreadable referenced chapter files. |
| Archives/playback | Same-second archives could collide; archive writes blocked control handling; mpv failures could be reported as completion. | Unique archive names, writes outside the event loop, playback continuation after archive write failure, and check player outcome. |
| CPU threading | Automatic threading used every available CPU despite poorer measured latency. | Cap automatic inference threads at eight; retain explicit overrides. |
| Configuration/TUIs | Invalid types/nonfinite numbers, zero-weight blends, omitted voice three, missing keys written into the wrong TOML section, outdated provider names and stale PID location. | Validate inputs, normalize positive weights, preserve voice three independently, insert keys in the proper section, use modern provider names and runtime PID paths. |
| Paths | Custom install locations were forgotten; quoted systemd working directories and custom control paths were inconsistent. | Persist the install path, quote command arguments correctly, honor custom config/socket paths and validate generated units with spaces. |
| Portability | X11 paths, a fixed zram mount and forced integrated-GPU environment assumptions. | Use the requested Wayland scope and normal XDG archive paths; let the active graphics stack select its rendering device. |
| Diagnostics | Synthesis cleanup crashed when no executor existed; offline benchmarks retained every PCM chunk. | Correct cleanup, stream WAV output, and propagate diagnostic failures. |

## Measured results

Measurements are from this laptop and its current power state, not universal
performance claims. RTF = synthesis time / audio duration; lower is faster.

| Check | Before | After | Interpretation |
| --- | --- | --- | --- |
| Split a 500,000-character paragraph | 55.368 s | 0.284 s | About 195× faster in this focused benchmark. |
| Normalize 100,000 unmatched `[` characters | Exceeded a 10 s timeout | 0.077 s | Pathological input now finishes promptly. |
| Normalize 75,000 characters of unmatched code fences | Not a matched timing | 0.0046 s | Linear fence handling, including unclosed blocks and longer closing fences. |
| Matched warm CUDA inference, same model/runtime/texts | RTF 0.081786 | RTF 0.081749 | Essentially unchanged; no meaningful inference speed gain claimed. |
| Shared regression cases | 8/21 pass | 21/21 pass | Thirteen failing cases fixed; final suite has 27 passing tests including six added cases. |
| Configured audio prefetch of four | 512 queued segments allowed | Four queued segments allowed | 128× lower queue capacity by code comparison; not a measured 128× reduction in total RSS. |

Long run: **251 segments, 1366.48 seconds of archived audio, 118.1 seconds of
job wall time**, with a 3.631-second cold first-audio delay. Sampled peak daemon
RSS was 52.0 MiB, peak synthesis-process VRAM was 428 MiB, and maximum observed
status request latency was 2 ms. Headless mpv used its untimed null audio output
for this throughput test; real-time playback naturally takes the audio duration.
The archived sample count was checked against the reported duration. This checks
pipeline completion, not a human transcription of every spoken word.

The actual installed service subsequently completed a real Wayland/audio-device
playback request: 3.62 seconds of audio, cold first audio after 2.473 seconds,
archived WAV, successful final event. Its offline self-test reported CUDA RTF
around 0.0813 and an effective generation speed control.

### Memory budgets and old GPUs

The 256/512/1024/2048 MiB arena tests all completed. The two smaller budgets
fell back to CPU; sampled process VRAM peaks were 380/630 MiB. The 1024 and
2048 MiB tests stayed on CUDA and peaked at 1080 MiB. A separate ONNX Runtime
1.30.0 check at 1024 MiB also stayed on CUDA with a 1080 MiB peak. These tests
cover several segment lengths, including near the configured maximum.

For a **supported 2 GiB NVIDIA GPU**, 1024 MiB is a reasonable starting arena
budget, with CPU fallback enabled and maximum cuDNN workspace disabled. This
is a recommendation based on the measured workload, not a physical 2 GiB card
qualification. Desktop/compositor allocations and other applications also need
space. The CUDA arena budget does **not** cap driver contexts, every library
allocation, or total process VRAM. [ONNX Runtime CUDA options](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)

Current CUDA 13 dropped Maxwell, Pascal and Volta support. Automatic installation
therefore selects CPU on detected NVIDIA cards below compute capability 7.5;
a larger arena cannot make those cards supported. CPU installations require
no NVIDIA runtime. [NVIDIA CUDA 13 release notes](https://docs.nvidia.com/cuda/archive/13.0.0/cuda-toolkit-release-notes/index.html)

CPU fallback completes the work, but real-time narration is not guaranteed:
the tested 92 MB INT8 model needed roughly 8.1–8.7 seconds for about 5.1 seconds
of audio at four threads. Automatic CPU threads are now limited to eight available CPUs (explicit settings
remain authoritative). On this 14-CPU system, the short-phrase eight-thread
runs took 3.53–3.59 seconds; the automatic 14-thread runs took 3.93–6.29 seconds.
Four threads took 3.61–3.63 seconds, two took 4.14–4.16, and one took 5.18–5.21.
This measured comparison motivated the cap; it is not a universal optimum.
CPU thread count and model choice still need measurements on each ISO hardware
class. The repeated offline CPU install self-test completed the same 9.297
seconds of audio in 12.959 seconds with the cap, versus 16.592 seconds with
the original uncapped automatic thread count (about 22% less synthesis time).

### Model and backend selection

- Default GPU export remains the tested `model-files-v1.0` FP16 GPU model
  (177,464,787 bytes). The newer v1.1 generic FP16 export produced **NaN audio**
  on the tested CUDA backend. It remains an explicit experimental selection,
  protected by waveform validation and fallback.
- Default CPU/fallback export remains v1.0 INT8 (92,361,271 bytes). In the same
  four-thread comparison, the newer v1.1 INT8 export took about 11.1–11.3 seconds
  versus 8.1–8.7 seconds for v1.0, with slightly different audio durations.
  The latest export was therefore not made the default.
- The newer v1.1 full precision model passed CUDA synthesis and speed-control
  verification (sample RTF 0.0978). It is larger and remains optional.
- Model hashes are recorded in the installer. v1.1 asset/voices hashes came from
  release metadata; the older default export hashes were calculated from the
  tested installed artifacts. Voice tensors were all validated as finite with
  shape `(510, 1, 256)`.
- CPU and CUDA installs were exercised. TensorRT, AMD MIGraphX, Intel OpenVINO
  and physical older/low-VRAM cards were **not hardware-qualified**.
- ROCmExecutionProvider was removed upstream from ONNX Runtime 1.23 onward.
  AMD now uses MIGraphX with an explicitly supplied matching Python/runtime build.
  [ROCm notice](https://onnxruntime.ai/docs/execution-providers/ROCm-ExecutionProvider.html),
  [MIGraphX documentation](https://onnxruntime.ai/docs/execution-providers/MIGraphX-ExecutionProvider.html)
- The examined PyPI OpenVINO runtime did not provide a Python 3.14 Linux wheel.
  Explicit Intel installs need a matching `--ort-wheel`; automatic selection
  uses CPU. Its provider settings now use documented `load_config` properties.
  [OpenVINO provider documentation](https://onnxruntime.ai/docs/execution-providers/OpenVINO-ExecutionProvider.html)

Upstream comparisons: [kokoro-onnx source/examples](https://github.com/thewh1teagle/kokoro-onnx),
[model-files-v1.0](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0),
[model-files-v1.1](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1),
[uv metadata overrides](https://docs.astral.sh/uv/concepts/resolution/).
The existing ONNX design provides fast measured CUDA inference without adding a
PyTorch runtime or another daemon layer; the audit retained that design.

## Verification coverage

- Python regression suite: 27 passing cases; Python compilation, Bash syntax
  checks and ShellCheck passed.
- Fresh CPU and NVIDIA installations; repeated offline CPU/NVIDIA installations
  with populated caches; installation paths containing spaces.
- Complete partial download recovery, corrupt complete partial replacement,
  invalid final download rejection/removal, and offline corruption rejection
  without deleting the existing artifact. Corruption tests used local download
  fixtures; fresh installs exercised actual package/model acquisition.
- Actual systemd cold activation, synthesis, idle exit and reactivation.
  Generated units passed `systemd-analyze --user verify`; generated custom
  install/config/socket paths with spaces passed activation, trigger routing
  and PID checks using temporary user units.
- Pause/resume, stop, unload during synthesis, reload followed by another job,
  malformed requests, ten stop/restart cycles, concurrent status requests and
  clean shutdown.
- Long text, CJK text without spaces, unbroken words, abbreviations, Markdown,
  token limits, voice weights, queue rejection and deduplication regression cases.
- Real PDF/Poppler and EPUB extraction through CLI submission, synthesis,
  headless playback and WAV archiving. EPUB spine order checked independently.
- All 54 voice styles produced finite CUDA audio: aggregate 102.209 seconds of
  audio generated in 13.778 seconds. This is numerical/runtime validation,
  **not perceptual language or pronunciation certification**.
- Both TUI blending implementations exercised, including voice two at zero
  weight with an active third voice. Python TUI template and actual TOML writes
  loaded successfully through the daemon configuration parser.

## Remaining limits

Unclosed fenced code now extends to the document end, as Markdown specifies.
With `read_code_blocks = false`, that content is omitted; enable the setting
if code should be narrated. Closing fences may be longer than their opener.

Japanese Kanji pronunciation is inadequate with the bundled espeak path: tested
characters can be verbalized as “Chinese letter”. A dedicated supported Japanese
G2P path would be required before claiming correct Japanese book narration.
Other languages, names, abbreviations, unusual Unicode and voice blends also
need perceptual checks. Upstream itself documents uneven language/voice support.
[Upstream voice guidance](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)

Misaki was examined, but its published Python requirement did not match this
Python 3.14 baseline. It was not introduced as an untested dependency override.

Very long documents still consume memory proportional to prepared text and
segments, and WAV archiving consumes disk proportional to audio duration.
Standard WAV size limits and archive write failures disable the archive for that
job while playback continues; this is not unlimited archival capacity. Archive
retention removes older files according to the existing configured policy.

An empty dependency cache or missing models cannot support offline bootstrap.
The ISO must include the system tools, Python, model files and the matching
uv cache/lock for its selected backend. Final ISO versions, alternative
architectures and actual hardware classes need validation before distribution.

## Reproduction

From this directory:

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile dusky_main.py tui_kokoro.py
bash -n kokoro_installer.sh trigger.sh tui/kokoro_tui.sh
shellcheck kokoro_installer.sh trigger.sh tui/kokoro_tui.sh
./trigger.sh --doctor-synth
systemd-analyze --user verify "$HOME/.config/systemd/user/dusky-kokoro.service" "$HOME/.config/systemd/user/dusky-kokoro.socket"
```

Ordinary rerun: `./kokoro_installer.sh --yes`; intentional dependency refresh:
`./kokoro_installer.sh --upgrade --yes`; cached deployment:
`./kokoro_installer.sh --offline --yes`. Use `--hw cpu` for the portable CPU
profile and `--hw nvidia` for a supported NVIDIA installation. System tools must
already exist unless `--install-system-deps` is explicitly supplied online.

Detailed local fixtures, benchmark JSON, WAVs and logs from this audit are in
`/tmp/dusky-kokoro-audit`; they are temporary evidence and are not part of the ISO.
No Git add, commit, push, reset or restore was performed. Unrelated concurrent
workspace/index changes were left alone.
