"""Regression tests; Python 3.14+, no GPU, models or third-party packages needed."""
import asyncio
import dataclasses
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dusky", ROOT / "dusky_main.py")
dusky = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dusky
spec.loader.exec_module(dusky)


class TextTests(unittest.TestCase):
    def test_long_paragraph_preserves_words(self):
        text = " ".join(f"word{i}" for i in range(20000))
        parts = dusky.split_long(text, 320)
        self.assertEqual(" ".join(parts).split(), text.split())
        self.assertTrue(all(dusky.wlen(p) <= 320 for p in parts))

    def test_cjk_no_whitespace(self):
        text = "这是一个很长的段落" * 1000
        parts = dusky.split_long(text, 320)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(dusky.wlen(p) <= 320 for p in parts))

    def test_unbroken_word(self):
        text = "a" * 100000
        self.assertEqual("".join(dusky.split_long(text, 320)), text)

    def test_phoneme_guard(self):
        text = "ɑːb word, " * 1000
        parts = dusky.split_phonemes(text, 480)
        self.assertTrue(all(len(p) <= 480 for p in parts))
        self.assertEqual("".join(parts).replace(" ", ""), text.replace(" ", ""))

    def test_abbreviations_and_decimals(self):
        self.assertEqual(dusky.split_sentences("Dr. Smith paid 3.14 dollars. Next!"),
                         ["Dr. Smith paid 3.14 dollars.", "Next!"])

    def test_unmatched_brackets(self):
        text = "[" * 100000
        self.assertEqual(dusky.flatten_paragraphs(dusky.normalize_text(text, dusky.TextConfig())), "(" * 100000)

    def test_markdown(self):
        text = "# Title\n\nRead [this](https://example.org). [12]\n\n```python\nsecret\n```\n"
        flat = dusky.flatten_paragraphs(dusky.normalize_text(text, dusky.TextConfig()))
        self.assertIn("Read this.", flat)
        self.assertNotIn("secret", flat)
        self.assertNotIn("12", flat)

    def test_fence_closer_can_be_longer(self):
        self.assertEqual(dusky.strip_fenced_code("Read.\n```python\nhidden\n````\nEnd.", False), "Read.\n\n\n\n\nEnd.")

    def test_unclosed_fence_respects_read_code(self):
        text = "Read.\n~~~code\nHidden text."
        self.assertNotIn("Hidden", dusky.strip_fenced_code(text, False))
        self.assertIn("Hidden", dusky.strip_fenced_code(text, True))

    def test_many_unmatched_fences(self):
        text = "```python\ncode\n" * 10000
        self.assertEqual(dusky.strip_fenced_code(text, False), "\n\n")

    def test_segments_and_pause(self):
        paragraphs = [["first " * 100], ["Last sentence."]]
        cfg = dusky.TextConfig()
        segments = dusky.segment_text(paragraphs, cfg)
        self.assertLessEqual(dusky.wlen(segments[0].text), cfg.first_segment_max_chars)
        self.assertTrue(all(dusky.wlen(s.text) <= cfg.max_segment_chars for s in segments))
        self.assertEqual(segments[-1].pause_ms, cfg.paragraph_pause_ms)

    def test_epub_spine_order(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "book.epub"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>')
                z.writestr("OEBPS/book.opf", '<package><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>')
                z.writestr("OEBPS/a.xhtml", "<p>Second chapter.</p>")
                z.writestr("OEBPS/b.xhtml", "<p>First chapter.</p>")
            self.assertEqual(dusky.extract_text_from_file(path), "First chapter.\n\nSecond chapter.")

    def test_pdf_uses_poppler(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test.pdf"
            p.write_bytes(b"%PDF")
            with patch.object(dusky.shutil, "which", return_value="/usr/bin/pdftotext"), patch.object(dusky.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "PDF text")) as run:
                self.assertEqual(dusky.extract_text_from_file(p), "PDF text")
                self.assertEqual(run.call_args.args[0], ["pdftotext", str(p), "-"])


class ConfigTests(unittest.TestCase):
    def test_automatic_cpu_threads(self):
        cfg = dusky.Config()
        paths = dusky.resolve_paths(cfg, Path("/none"))
        engine = dusky.Engine(cfg, paths, dusky.VoiceBank(paths.voices_file))
        for available, expected in ((2, 2), (14, 8), (None, 4)):
            with self.subTest(available=available), patch.object(dusky.os, "process_cpu_count", return_value=available):
                self.assertEqual(engine._cpu_threads(), expected)
        engine.cfg = dataclasses.replace(cfg, engine=dataclasses.replace(cfg.engine, intra_op_threads=16))
        self.assertEqual(engine._cpu_threads(), 16)

    def test_client_configured_socket(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config.toml"
            socket = Path(td) / "custom socket/control.sock"
            config.write_text(f'[daemon]\nsocket_path = {json.dumps(str(socket))}\n')
            args = dusky.build_parser().parse_args(["--config", str(config), "status"])
            with patch.dict(dusky.os.environ, {}, clear=True), patch.object(dusky, "client_request", return_value={"ok": True}) as request:
                self.assertEqual(dusky.run_client(args), 0)
                self.assertEqual(request.call_args.args[0], socket)

    def test_template(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.toml"
            p.write_text(dusky.DEFAULT_CONFIG_TOML)
            dusky.load_config(p)

    def test_bad_types(self):
        for data in ({"prefetch_segments": "four"}, {"prefetch_segments": True}, {"extra_args": [1]}, {"window": "true"}):
            with self.subTest(data=data), self.assertRaises(dusky.ConfigError):
                dusky._build_section(dusky.PlaybackConfig, data, "playback")

    def test_bad_limits(self):
        for field, val in (("max_segment_chars", 0), ("target_segment_chars", -1), ("paragraph_pause_ms", -1), ("first_segment_max_chars", 0)):
            with self.subTest(field=field), self.assertRaises(dusky.ConfigError):
                dusky._validate(dataclasses.replace(dusky.Config(), text=dataclasses.replace(dusky.TextConfig(), **{field: val})))

    def test_nonfinite_weights(self):
        for weight in ("nan", "inf", "-inf", "0", "-1"):
            with self.subTest(weight=weight), self.assertRaises(dusky.VoiceError):
                dusky.VoiceBank.parse_spec(f"af_heart:{weight}")

    def test_large_finite_weights(self):
        self.assertEqual(dusky.VoiceBank.parse_spec("af_heart:1e308,af_bella:1e308"), [("af_heart", 0.5), ("af_bella", 0.5)])

    def test_cpu_fallback_model(self):
        with tempfile.TemporaryDirectory() as td:
            for name in dusky.MODEL_FILES.values():
                (Path(td) / name).touch()
            self.assertEqual(dusky.choose_model("auto", "cpu", Path(td))[0], "int8")
            self.assertEqual(dusky.choose_model("auto", "cuda", Path(td))[0], "fp16-gpu")

    def test_provider_fallback(self):
        self.assertEqual(dusky.provider_chain("cuda", ["CPUExecutionProvider"]), ["cpu"])
        self.assertEqual(dusky.provider_chain("auto", ["MIGraphXExecutionProvider", "CPUExecutionProvider"]), ["migraphx", "cpu"])

    def test_wayland_command(self):
        player = dusky.MpvPlayer(dusky.PlaybackConfig(), {"WAYLAND_DISPLAY": "wayland-1"}, "Test")
        cmd = player._command_line(9)
        self.assertIn("--gpu-context=wayland", cmd)
        self.assertFalse(any("x11" in arg for arg in cmd))


class DaemonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cfg = dataclasses.replace(dusky.Config(), daemon=dataclasses.replace(dusky.DaemonConfig(), max_queue=1))
        self.daemon = dusky.Daemon(cfg, dusky.resolve_paths(cfg, Path("/nonexistent")))
        self.messages = []

    async def send(self, writer, message):
        self.messages.append(message)

    async def speak(self, **args):
        with patch.object(self.daemon, "_send", self.send):
            await self.daemon._cmd_speak({"text": "Test sentence.", "mode": "enqueue", **args}, None)
        return self.messages[-1]

    async def test_queue_rejection_does_not_deduplicate_retry(self):
        self.assertEqual((await self.speak())["event"], "accepted")
        self.assertFalse((await self.speak(text="Other sentence."))["ok"])
        self.daemon._clear_queue("test")
        self.assertEqual((await self.speak(text="Other sentence."))["event"], "accepted")

    async def test_voice_changes_are_not_deduplicated(self):
        await self.speak()
        self.daemon._clear_queue("test")
        self.assertEqual((await self.speak(voice="bf_emma"))["event"], "accepted")

    async def test_bad_speed_does_not_drop_connection(self):
        self.assertFalse((await self.speak(speed={}))["ok"])
        self.assertFalse((await self.speak(speed=[1]))["ok"])
        self.assertFalse((await self.speak(speed=float("nan")))["ok"])

    async def test_reload_loaded_worker_no_deadlock(self):
        engine = self.daemon.engine
        class Process:
            returncode = None
        engine._worker_proc = Process()
        engine._loaded = True
        engine.reload_pending = True
        calls = []
        async def unload(reason):
            calls.append(reason)
            engine._loaded = False
            engine._worker_proc = None
            raise dusky.EngineError("test stops before subprocess launch")
        with patch.object(engine, "_unload_worker", unload):
            with self.assertRaises(dusky.EngineError):
                await asyncio.wait_for(engine.ensure_loaded(), 0.5)
        self.assertEqual(calls, ["configuration reload"])


if __name__ == "__main__":
    unittest.main()
