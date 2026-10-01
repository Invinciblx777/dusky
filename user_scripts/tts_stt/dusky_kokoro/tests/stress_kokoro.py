"""Exercise a real isolated daemon, models and mpv; run with the installed venv.

Example: python tests/stress_kokoro.py --models-dir "$DUSKY_HOME/models"
Uses mpv's untimed null audio output, preserving your installed preferences.
"""
import argparse
import asyncio
import json
import os
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"finished", "cancelled", "error", "deduplicated"}


async def run(args):
    directory = args.output or Path(tempfile.mkdtemp(prefix="kokoro-stress-"))
    directory.mkdir(parents=True, exist_ok=True)
    socket = directory / "control.sock"
    config = directory / "config.toml"
    config.write_text(f'''[engine]
provider = {json.dumps(args.provider)}
precision = {json.dumps(args.precision)}
models_dir = {json.dumps(str(args.models_dir.resolve()))}
warmup = false
gpu_mem_limit_mb = {args.arena_mb}
model_idle_timeout_s = 120.0
[playback]
window = false
cache_max_mb = 8
extra_args = ["--ao=null", "--ao-null-untimed"]
prefetch_segments = 4
[archive]
enabled = true
dir = {json.dumps(str((directory / "audio").resolve()))}
max_files = 8
[daemon]
exit_when_idle = false
dedup_window_s = 0.0
desktop_notifications = false
''')
    # Test profiles must not inherit backend/voice overrides from a desktop shell.
    env = {k: v for k, v in os.environ.items() if not k.startswith("DUSKY_")}
    command = [os.sys.executable, str(ROOT / "dusky_main.py"), "--config", str(config), "--socket", str(socket)]
    log = (directory / "daemon.log").open("wb")
    proc = await asyncio.create_subprocess_exec(*command, "daemon", stdout=log, stderr=log, env=env)
    worker_pids = set()

    async def request(cmd, **fields):
        reader, writer = await asyncio.open_unix_connection(socket)
        try:
            writer.write(json.dumps({"cmd": cmd, **fields}).encode() + b"\n")
            await writer.drain()
            return json.loads(await asyncio.wait_for(reader.readline(), 20))
        finally:
            writer.close()
            await writer.wait_closed()

    async def speak(text, **fields):
        reader, writer = await asyncio.open_unix_connection(socket)
        try:
            writer.write(json.dumps({"cmd": "speak", "text": text, "wait": "done", **fields}).encode() + b"\n")
            await writer.drain()
            while line := await asyncio.wait_for(reader.readline(), 600):
                reply = json.loads(line)
                if reply.get("event") in TERMINAL or not reply.get("ok", True):
                    return reply
            raise AssertionError("client disconnected without a terminal event")
        finally:
            writer.close()
            await writer.wait_closed()

    def collect_workers():
        try:
            children = Path(f"/proc/{proc.pid}/task/{proc.pid}/children").read_text().split()
            for child in children:
                if b"synth-worker" in Path(f"/proc/{child}/cmdline").read_bytes():
                    worker_pids.add(int(child))
        except FileNotFoundError:
            pass

    try:
        async with asyncio.timeout(20):
            while True:
                if proc.returncode is not None:
                    raise AssertionError(f"daemon exited: {proc.returncode}; see {log.name}")
                try:
                    assert (await request("ping"))["ok"]
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    await asyncio.sleep(.05)
        for malformed in ([], {"text": "Test.", "speed": []}, {"text": "Test.", "speed": True}):
            reader, writer = await asyncio.open_unix_connection(socket)
            try:
                data = {"cmd": "speak", **malformed} if isinstance(malformed, dict) else malformed
                writer.write(json.dumps(data).encode() + b"\n"); await writer.drain()
                assert not json.loads(await reader.readline())["ok"]
            finally:
                writer.close(); await writer.wait_closed()
        first = await speak("The first request must finish and save an archive.")
        assert first["event"] == "finished", first
        collect_workers()
        assert (await request("reload"))["ok"]
        assert (await speak("The request after reload also completes."))["event"] == "finished"
        long_text = ("This is a complete stress test paragraph. Every sentence must reach the final archive.\n\n" * args.paragraphs) + "The final marker has been reached."
        task = asyncio.create_task(speak(long_text))
        peak_rss, max_latency, samples = 0, 0, 0
        while not task.done():
            start = time.perf_counter(); status = await request("status")
            assert status["ok"], status
            max_latency = max(max_latency, time.perf_counter() - start)
            peak_rss = max(peak_rss, status["rss_mb"]); samples += 1
            collect_workers()
            await asyncio.sleep(.1)
        completed = await task
        assert completed["event"] == "finished", completed
        assert completed["segments"] >= args.paragraphs, completed
        with wave.open(completed["archive"]) as wav:
            duration = wav.getnframes() / wav.getframerate()
            assert abs(duration - completed["audio_s"]) < .011
        assert all(r["ok"] for r in await asyncio.gather(*(request("status") for _ in range(20))))
        for index in range(args.cycles):
            task = asyncio.create_task(speak(long_text + str(index)))
            await asyncio.sleep(.03)
            assert (await request("unload" if index % 3 == 0 else "stop"))["ok"]
            assert (await task)["event"] == "cancelled"
        # Stop and a newer interrupt must also supersede a request preparing text.
        for action in ("stop", "new"):
            task = asyncio.create_task(speak("word " * 800000))
            await asyncio.sleep(.1)
            if action == "stop":
                await request("stop")
            else:
                assert (await speak("A newer request wins."))["event"] == "finished"
            assert (await task)["event"] == "cancelled"
        final = await speak("All recovery cycles passed. The final job is healthy.")
        assert final["event"] == "finished", final
        status = await request("status")
        collect_workers()
        assert (await request("shutdown"))["ok"]
        await asyncio.wait_for(proc.wait(), 10)
        assert proc.returncode == 0
        await asyncio.sleep(.1)
        assert not [pid for pid in worker_pids if Path(f"/proc/{pid}").exists()], worker_pids
        result = {"completed": completed, "peak_daemon_rss_mb": peak_rss,
                  "max_status_latency_s": round(max_latency, 4), "status_samples": samples,
                  "recovery_cycles": args.cycles, "workers_observed": len(worker_pids),
                  "final_engine": status["engine"], "orphan_workers": 0}
        (directory / "results.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 10)
            except TimeoutError:
                proc.kill(); await proc.wait()
        log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--provider", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--precision", default="auto", choices=("auto", "fp16-gpu", "f32", "int8", "fp16"))
    parser.add_argument("--arena-mb", type=int, default=1024)
    parser.add_argument("--paragraphs", type=int, default=250)
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--output", type=Path)
    asyncio.run(run(parser.parse_args()))
