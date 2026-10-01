"""Installer recovery fixtures; no models, network or systemd changes."""
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "kokoro_installer.sh"


class InstallerTests(unittest.TestCase):
    def run_download(self, directory, destination=None, partial=None):
        dest = directory / "voices-v1.0.bin"
        tmp = directory / "voices-v1.0.bin.part"
        if destination is not None:
            dest.write_text(destination)
        if partial is not None:
            tmp.write_text(partial)
        script = f'''set -euo pipefail
source <(sed '/^# --- main ---/,$d' {shlex.quote(str(INSTALLER))})
MODEL_DIR={shlex.quote(str(directory))}
OFFLINE=1
model_size() {{ printf '5\\n'; }}
verify_model() {{ [[ $(<"$1") == valid ]]; }}
curl() {{ printf 'network must not be used' >&2; exit 99; }}
download voices
'''
        env = {k: v for k, v in os.environ.items() if not k.startswith("DUSKY_")}
        return subprocess.run([shutil.which("bash"), "-c", script], env=env, capture_output=True, text=True)

    def test_complete_partial_recovers_offline(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            result = self.run_download(p, partial="valid")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((p / "voices-v1.0.bin").read_text(), "valid")
            self.assertFalse((p / "voices-v1.0.bin.part").exists())

    def test_partial_replaces_invalid_destination_offline(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            result = self.run_download(p, destination="bad", partial="valid")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((p / "voices-v1.0.bin").read_text(), "valid")

    def test_invalid_partial_is_preserved_offline(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            result = self.run_download(p, destination="bad", partial="wrong")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual((p / "voices-v1.0.bin").read_text(), "bad")
            self.assertEqual((p / "voices-v1.0.bin.part").read_text(), "wrong")

    def test_valid_destination_ignores_invalid_partial(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            result = self.run_download(p, destination="valid", partial="wrong")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((p / "voices-v1.0.bin.part").read_text(), "wrong")


if __name__ == "__main__":
    unittest.main()
