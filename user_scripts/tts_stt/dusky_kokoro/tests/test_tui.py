"""Custom-path and hardware telemetry fixtures; no GUI or hardware required."""
import importlib.util
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TUI_ROOT = ROOT.parents[1] / "dusky_tui"
sys.path.insert(0, str(TUI_ROOT))
from python.engines.kokoro import KokoroEngine


class TuiTests(unittest.TestCase):
    def test_bash_custom_install_and_socket(self):
        with tempfile.TemporaryDirectory(prefix="kokoro tui ") as td:
            p = Path(td)
            config_dir = p / "dusky-kokoro"
            config_dir.mkdir()
            (config_dir / "install-path").write_text(str(p / "custom install"))
            config = config_dir / "config.toml"
            config.write_text(f'[daemon]\nsocket_path = "{p}/custom runtime/control.sock"\n')
            env = {k: v for k, v in os.environ.items() if not k.startswith("DUSKY_")}
            env["XDG_CONFIG_HOME"] = td
            fixture = p / "tui/kokoro_tui.sh"
            fixture.parent.mkdir()
            fixture.write_text((ROOT / "tui/kokoro_tui.sh").read_text().replace('main "$@"', ""))
            link = p / "bin/kokoro-tui"
            link.parent.mkdir()
            link.symlink_to(fixture)
            script = f'''source {shlex.quote(str(link))}
trap - EXIT
[[ "$CONTAINED_DIR" == {shlex.quote(str(p / "custom install"))} ]]
[[ "$TRIGGER_SCRIPT" == {shlex.quote(str(p / "trigger.sh"))} ]]
[[ $(resolve_daemon_pid_file) == {shlex.quote(str(p / "custom runtime/daemon.pid"))} ]]
DUSKY_SOCKET={shlex.quote(str(p / "override/control.sock"))}; export DUSKY_SOCKET
[[ $(resolve_daemon_pid_file) == {shlex.quote(str(p / "override/daemon.pid"))} ]]
unset DUSKY_SOCKET
printf '[invalid' > "$CONFIG_FILE"
[[ $(resolve_daemon_pid_file) == {shlex.quote(str(Path(env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "dusky-kokoro/daemon.pid"))} ]]
'''
            result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_python_custom_socket_pid_and_gpu_selection(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            config = p / "config.toml"
            config.write_text(f'[daemon]\nsocket_path="{p}/control.sock"\n[engine]\nprovider="cuda"\n')
            (p / "daemon.pid").write_text(str(os.getpid()))
            devices=[]
            for card, vendor, state in [("card7", "0x8086", "D0"), ("card12", "0x10de", "D3cold")]:
                d = p / card / "device";d.mkdir(parents=True)
                (d / "vendor").write_text(vendor);(d / "power_state").write_text(state);devices.append(d)
            with patch.dict(os.environ, {"DUSKY_SOCKET": ""}), patch.object(KokoroEngine, "_ensure_virgin_config"), patch.object(Path, "glob", return_value=devices):
                state=KokoroEngine(str(config)).load_state()
            self.assertIn("RUNNING", state["daemon.status"])
            self.assertEqual(state["daemon.gpu_power_state"], "card12: D3cold")

    def test_python_schema_quotes_custom_trigger(self):
        with tempfile.TemporaryDirectory(prefix="kokoro tui ") as td:
            source=Path(td)/"tui_kokoro.py";source.write_text((ROOT/"tui_kokoro.py").read_text())
            spec=importlib.util.spec_from_file_location("kokoro_schema_fixture", source)
            schema=importlib.util.module_from_spec(spec);spec.loader.exec_module(schema)
            self.assertEqual(shlex.split(schema._TRIGGER_CMD), [str(source.with_name("trigger.sh"))])

    def test_python_reload_uses_installed_custom_trigger(self):
        engine = KokoroEngine("/unused/config.toml")
        with patch.object(Path, "exists", side_effect=[False, True]), patch.object(
            os, "access", return_value=True
        ), patch("python.engines.kokoro.shutil.which", return_value="/custom path/trigger"), patch(
            "python.engines.kokoro.subprocess.Popen"
        ) as launch:
            engine._trigger_reload()
        self.assertEqual(launch.call_args.args[0], ["/custom path/trigger", "--reload"])


if __name__ == "__main__":
    unittest.main()
