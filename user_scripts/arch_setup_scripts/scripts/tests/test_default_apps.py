"""Focused default app tests. Run: python3 -m unittest discover -s THIS_DIRECTORY."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / '235_default_apps.py'
spec = importlib.util.spec_from_file_location('default_apps', SCRIPT)
apps = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = apps
spec.loader.exec_module(apps)
VARS = 'terminal = "kitty"\nfileManager = "yazi"\nbrowser = "firefox"\ntextEditor = "nvim"\n'
BINDS = '\n'.join(
    f'hl.bind("{cat.binding}", hl.dsp.exec_cmd("old(" .. {cat.variable}), '
    f'{{ description = "{cat.description}", submap_universal = false }})'
    for cat in apps.CATEGORIES.values()
) + '\n'


class SwitcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.switcher = apps.Switcher(self.home)
        self.switcher.variables.parent.mkdir(parents=True)
        self.switcher.variables.write_text(VARS)
        self.switcher.bindings.write_text(BINDS)
        self.switcher.settings.mkdir(parents=True)
        self.commands = []
        self.mock = patch.object(apps, 'run_command', side_effect=self.command)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.env = patch.dict(os.environ, {'HYPRLAND_INSTANCE_SIGNATURE': 'fixture'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def command(self, argv):
        self.commands.append(argv)
        if argv[:3] == ['xdg-mime', 'query', 'default']:
            kind = next(k for k, mime in apps.PRIMARY_MIME.items() if mime == argv[3])
            return apps.CATEGORIES[kind].app(self.switcher.saved(kind)).desktop + '\n'
        return ''

    def state(self, kind, value, smart=True):
        cat = apps.CATEGORIES[kind]
        path = self.switcher.settings / (cat.state + ('.smart' if smart else ''))
        path.write_text(value + '\n')
        return path

    def test_all_catalog_choices(self):
        for kind, cat in apps.CATEGORIES.items():
            for app in cat.apps:
                with self.subTest(kind=kind, app=app.key):
                    self.switcher.apply({kind: app.key}, [kind])
                    self.assertEqual(self.switcher.current()[kind], app.key)
                    self.assertEqual(self.switcher.saved(kind), app.key)
                    expected = apps.launch_expression(kind, app, self.switcher.current()['terminal'])
                    self.assertIn(expected, self.switcher.bindings.read_text())

    def test_restore_uses_final_terminal(self):
        choices = {'file-manager': 'yazi', 'browser': 'lynx', 'text-editor': 'nvim', 'terminal': 'alacritty'}
        for kind, key in choices.items():
            self.state(kind, key)
        self.switcher.apply(None, list(apps.CATEGORIES))
        text = self.switcher.bindings.read_text()
        self.assertIn('terminal .. " --class " .. textEditor .. " -e " .. textEditor', text)
        self.assertIn('terminal .. " -e " .. fileManager', text)
        self.assertIn('terminal .. " -e " .. browser', text)
        self.assertEqual(self.switcher.current(), choices)
        self.assertEqual([c[0] for c in self.commands], ['xdg-mime'] * 6 + ['hyprctl'])

    def test_terminal_refreshes_existing_tui_apps(self):
        self.switcher.apply({'terminal': 'foot'}, ['terminal'])
        text = self.switcher.bindings.read_text()
        self.assertIn('" --app-id=" .. textEditor', text)
        self.assertNotIn('--class', text)
        self.assertEqual(self.switcher.current()['text-editor'], 'nvim')
        self.assertFalse((self.switcher.settings / 'texteditor_switch.smart').exists())

    def test_all_legacy_states(self):
        for kind, cat in apps.CATEGORIES.items():
            for value, key in zip(('true', 'false'), cat.legacy):
                with self.subTest(kind=kind, value=value):
                    path = self.state(kind, value, False)
                    self.assertEqual(self.switcher.saved(kind), key)
                    path.unlink()

    def test_smart_takes_precedence(self):
        self.state('browser', 'false', False)
        self.state('browser', 'librewolf')
        self.assertEqual(self.switcher.saved('browser'), 'librewolf')

    def test_no_state_no_changes(self):
        original = self.switcher.variables.read_bytes()
        self.switcher.apply(None, list(apps.CATEGORIES))
        self.assertEqual(self.switcher.variables.read_bytes(), original)
        self.assertEqual(self.commands, [])

    def test_invalid_state_prevents_all_changes(self):
        self.state('browser', 'chromium')
        self.state('terminal', 'invalid')
        with self.assertRaises(ValueError):
            self.switcher.apply(None, list(apps.CATEGORIES))
        self.assertEqual(self.switcher.variables.read_text(), VARS)
        self.assertEqual(self.switcher.bindings.read_text(), BINDS)
        self.assertEqual(self.commands, [])

    def test_missing_binding_file_prevents_state_and_config_changes(self):
        self.switcher.bindings.unlink()
        with self.assertRaises(FileNotFoundError):
            self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.assertEqual(self.switcher.variables.read_text(), VARS)
        self.assertFalse((self.switcher.settings / 'browser_switch.smart').exists())

    def test_shared_lock_blocks_other_category(self):
        with apps.config_lock(self.switcher.settings):
            with self.assertRaisesRegex(ValueError, 'busy'):
                self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.assertTrue((self.switcher.settings / '.default_apps.lock').exists())

    def test_rollback_on_failed_config_write(self):
        real = apps.atomic_write
        def fail_once(path, content):
            if path == self.switcher.bindings and content != BINDS.encode():
                raise OSError('fixture failure')
            real(path, content)
        with patch.object(apps, 'atomic_write', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'fixture failure'):
                self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.assertEqual(self.switcher.variables.read_text(), VARS)
        self.assertEqual(self.switcher.bindings.read_text(), BINDS)
        self.assertFalse((self.switcher.settings / 'browser_switch.smart').exists())
        self.assertFalse(list(self.home.rglob('.default-apps-*')))

    def test_state_write_failure_is_reported(self):
        with patch.object(apps, 'atomic_write', side_effect=OSError('state failure')):
            with self.assertRaisesRegex(OSError, 'state failure'):
                self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.assertEqual(self.switcher.variables.read_text(), VARS)

    def test_association_failure_is_reported_but_choice_saved(self):
        with patch.object(apps, 'run_command', side_effect=OSError('fixture MIME failure')):
            with self.assertRaisesRegex(ValueError, 'Choices saved.*incomplete'):
                self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.assertEqual(self.switcher.saved('browser'), 'chromium')

    def test_mime_success_exit_with_wrong_handler_is_reported(self):
        with patch.object(apps, 'run_command', return_value='old.desktop\n'):
            with self.assertRaisesRegex(ValueError, 'expected chromium.desktop, got old.desktop'):
                self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.assertEqual(self.switcher.saved('browser'), 'chromium')

    def test_mode_symlinks_and_idempotence(self):
        target = self.home / 'actual.lua'
        self.switcher.variables.rename(target)
        target.chmod(0o640)
        self.switcher.variables.symlink_to(target)
        self.switcher.apply({'browser': 'chromium'}, ['browser'])
        stamp = target.stat().st_mtime_ns
        self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.assertTrue(self.switcher.variables.is_symlink())
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertEqual(target.stat().st_mtime_ns, stamp)

    def test_cli_categories_and_errors(self):
        for kind in apps.CATEGORIES:
            result = subprocess.run([sys.executable, str(SCRIPT), '--' + kind, '--apply-state'],
                                    env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            parsed = apps.parse_args(['--' + kind, '--set', apps.CATEGORIES[kind].apps[0].key])
            self.assertEqual(parsed.category, kind)
        for argv in (['--set', 'foot'], ['--terminal', '--browser'], ['--terminal', '--set', 'foot', '--auto'], ['--wat'], ['--term'], ['--legacy', 'terminal']):
            with self.subTest(argv=argv), patch('sys.stderr'), self.assertRaises(SystemExit) as error:
                apps.parse_args(argv)
            self.assertEqual(error.exception.code, 2)
        self.assertTrue(apps.parse_args(['--auto']).apply_state)

    def test_old_catalog_keys_use_real_commands(self):
        for kind, key, command in [('file-manager', 'superfile', 'spf'), ('text-editor', 'vscodium', 'codium'), ('browser', 'edge', 'microsoft-edge-stable')]:
            with self.subTest(key=key), patch.object(apps.shutil, 'which', return_value=None):
                self.switcher.apply({kind: key}, [kind])
                self.assertIn(f'= "{command}"', self.switcher.variables.read_text())
                self.assertEqual(self.switcher.current()[kind], key)
                self.assertEqual(self.switcher.saved(kind), key)

    def test_helix_runtime_command_and_desktop_id(self):
        with patch.object(apps.shutil, 'which', side_effect=lambda name: '/usr/bin/hx' if name == 'hx' else None):
            self.switcher.apply({'text-editor': 'helix'}, ['text-editor'])
        self.assertIn('textEditor = "hx"', self.switcher.variables.read_text())
        self.assertEqual(self.switcher.current()['text-editor'], 'helix')
        self.assertIn(['xdg-mime', 'default', 'Helix.desktop', *apps.MIMES['text-editor']], self.commands)

    def test_failure_after_replace_rolls_back(self):
        real = apps.atomic_write
        def fail_after_replace(path, content):
            real(path, content)
            if path == self.switcher.bindings and content != BINDS.encode():
                raise OSError('directory fsync failed')
        with patch.object(apps, 'atomic_write', side_effect=fail_after_replace):
            with self.assertRaisesRegex(OSError, 'directory fsync failed'):
                self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.assertEqual(self.switcher.variables.read_text(), VARS)
        self.assertEqual(self.switcher.bindings.read_text(), BINDS)
        self.assertFalse((self.switcher.settings / 'browser_switch.smart').exists())

    def test_interrupt_rolls_back(self):
        real = apps.atomic_write
        def interrupt(path, content):
            if path == self.switcher.bindings and content != BINDS.encode():
                raise SystemExit(143)
            real(path, content)
        with patch.object(apps, 'atomic_write', side_effect=interrupt):
            with self.assertRaises(SystemExit) as error:
                self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.assertEqual(error.exception.code, 143)
        self.assertEqual(self.switcher.variables.read_text(), VARS)
        self.assertFalse((self.switcher.settings / 'browser_switch.smart').exists())

    def test_cli_does_not_open_menu_without_tty(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--terminal'],
                                env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Menus require a terminal', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_invalid_choice_makes_no_writes(self):
        with self.assertRaises(ValueError):
            self.switcher.apply({'browser': 'invalid'}, ['browser'])
        self.assertEqual(self.switcher.variables.read_text(), VARS)
        self.assertEqual(self.commands, [])

    def test_every_write_checkpoint_rolls_back_and_retry_succeeds(self):
        real = apps.atomic_write
        for checkpoint in range(1, 5):
            with self.subTest(checkpoint=checkpoint):
                self.switcher.variables.write_text(VARS)
                self.switcher.bindings.write_text(BINDS)
                for suffix in ('', '.smart'):
                    (self.switcher.settings / ('browser_switch' + suffix)).unlink(missing_ok=True)
                calls = 0
                def fail_once(path, content):
                    nonlocal calls
                    calls += 1
                    real(path, content)
                    if calls == checkpoint:
                        raise OSError('injected write failure')
                with patch.object(apps, 'atomic_write', side_effect=fail_once):
                    with self.assertRaisesRegex(OSError, 'injected write failure'):
                        self.switcher.apply({'browser': 'chromium'}, ['browser'])
                self.assertEqual(self.switcher.variables.read_text(), VARS)
                self.assertEqual(self.switcher.bindings.read_text(), BINDS)
                self.assertIsNone(self.switcher.saved('browser'))
                self.assertFalse(list(self.home.rglob('.default-apps-*')))
                self.switcher.apply({'browser': 'chromium'}, ['browser'])
                self.assertEqual(self.switcher.saved('browser'), 'chromium')

    def test_reload_failure_preserves_choice_and_retry_succeeds(self):
        def fail_reload(argv):
            if argv[0] == 'hyprctl':
                raise OSError('session unavailable')
            return self.command(argv)
        with patch.object(apps, 'run_command', side_effect=fail_reload):
            with self.assertRaisesRegex(ValueError, 'session unavailable'):
                self.switcher.apply({'browser': 'chromium'}, ['browser'])
        self.assertEqual(self.switcher.saved('browser'), 'chromium')
        self.switcher.apply(None, ['browser'])

    def test_incomplete_rollback_is_reported(self):
        with patch.object(apps, 'atomic_write', side_effect=OSError('read-only filesystem')):
            with self.assertRaisesRegex(OSError, 'rollback was incomplete'):
                apps.write_batch({self.switcher.variables: b'new'})

    def test_invalid_utf8_cli_returns_error_without_traceback(self):
        self.state('browser', 'firefox').write_bytes(b'\xff')
        result = subprocess.run([sys.executable, str(SCRIPT), '--auto'],
                                env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(self.switcher.variables.read_text(), VARS)


class CommandTests(unittest.TestCase):
    def test_unavailable_and_nonzero_commands(self):
        with patch.object(apps.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(OSError, 'unavailable'):
                apps.run_command(['missing'])
        with self.assertRaisesRegex(OSError, 'exited 1'):
            apps.run_command(['false'])

    def test_real_timeout_kills_and_reaps_child(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'pid'
            code = 'import os, pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)'
            with self.assertRaisesRegex(OSError, 'timed out'):
                apps.run_command([sys.executable, '-c', code, str(pidfile)])
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 0)


class LuaTests(unittest.TestCase):
    def test_assignment_preserves_comments(self):
        text = '-- browser = "decoy"\nlocal browser = \'firefox\'; -- my comment\n'
        out = apps.set_default(text, apps.CATEGORIES['browser'], 'chromium')
        self.assertEqual(out, '-- browser = "decoy"\nlocal browser = "chromium"; -- my comment\n')

    def test_duplicate_and_expression_assignments_rejected(self):
        for text in ('browser = "firefox"\nbrowser = "chromium"\n', 'browser = choose()\n', 'browser = "firefox" .. " --private"\n', 'browser = "firefox"\n .. " --private"\n', 'browser =\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                apps.set_default(text, apps.CATEGORIES['browser'], 'chromium')

    def test_unterminated_strings_and_comments_rejected(self):
        for text in ('browser = "unclosed', '--[=[\nbrowser = "decoy"\n', '--[=[ mismatched ]]', 'browser = [[unclosed'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                apps.tokens(text)

    def test_long_comments_nested_calls_and_custom_binding(self):
        text = '''--[=[ hl.bind("BAD", hl.dsp.exec_cmd("bad"), { description = "Launch Browser" }) ]=]
hl.bind(
    "ALT + F2",
    hl.dsp.exec_cmd(format("something )", fn("x"))),
    {
        -- arbitrary spacing and comments
        description = 'Launch Browser',
        submap_universal = false,
        repeatable = true
    }
)
'''
        out = apps.set_binding(text, apps.CATEGORIES['browser'], '"dusky-run " .. browser')
        self.assertIn('"ALT + F2"', out)
        self.assertIn('submap_universal = false', out)
        self.assertIn('repeatable = true', out)
        self.assertIn('exec_cmd("dusky-run " .. browser)', out)
        self.assertIn('hl.dsp.exec_cmd("bad")', out)
        self.assertEqual(apps.set_binding(out, apps.CATEGORIES['browser'], '"dusky-run " .. browser'), out)
        subprocess.run(['luac', '-p', '-'], input=out, text=True, check=True)

    def test_terminal_options_preserved(self):
        app = apps.CATEGORIES['text-editor'].app('nvim')
        expression = apps.launch_expression('text-editor', app, '/usr/bin/kitty --single-instance')
        self.assertEqual(expression, apps.launch_expression('text-editor', app, 'kitty'))
        self.assertIn('.. terminal ..', expression)

    def test_missing_binding_added_once(self):
        text = '-- comment only\n'
        cat = apps.CATEGORIES['terminal']
        out = apps.set_binding(text, cat, '"dusky-run " .. terminal')
        self.assertEqual(out.count('hl.bind('), 1)
        self.assertEqual(apps.set_binding(out, cat, '"dusky-run " .. terminal'), out)

    def test_add_universal_after_trailing_comment(self):
        text = 'hl.bind("ALT + B", hl.dsp.exec_cmd("old"), {description="Launch Browser" -- comment\n})\n'
        out = apps.set_binding(text, apps.CATEGORIES['browser'], 'browser')
        self.assertIn('submap_universal = true -- comment', out)
        subprocess.run(['luac', '-p', '-'], input=out, text=True, check=True)

    def test_multiple_bindings_same_description(self):
        text = '\n'.join(['hl.bind("ALT + B", hl.dsp.exec_cmd("old"), {description="Launch Browser"})'] * 2)
        out = apps.set_binding(text, apps.CATEGORIES['browser'], 'browser')
        self.assertEqual(out.count('exec_cmd(browser)'), 2)

    def test_malformed_binding_rejected(self):
        for text in ('hl.bind("B", callback, {description="Launch Browser"})', 'hl.bind("B", hl.dsp.exec_cmd("old"), {description="Launch Browser"}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                apps.set_binding(text, apps.CATEGORIES['browser'], 'browser')

class MenuTests(unittest.TestCase):
    def setUp(self):
        import pty
        import fcntl
        import termios
        import struct
        self.termios = termios
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        switcher = apps.Switcher(self.home)
        switcher.variables.parent.mkdir(parents=True)
        switcher.variables.write_text(VARS)
        switcher.bindings.write_text(BINDS)
        tools = self.home / 'bin'
        tools.mkdir()
        for name in ['xdg-mime', 'hyprctl']:
            script = tools / name
            script.write_text('#!/bin/sh\ncase "$3" in inode/directory) printf "nemo.desktop\\n";; esac\nexit 0\n')
            script.chmod(0o755)
        self.master, self.slave = pty.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        self.original = termios.tcgetattr(self.slave)
        self.env = {**os.environ, 'HOME': str(self.home), 'TERM': 'xterm-256color', 'PATH': str(tools) + ':' + os.environ['PATH']}
        self.output = b''

    def start(self, *args):
        self.proc = subprocess.Popen([sys.executable, str(SCRIPT), *args], env=self.env,
                                     stdin=self.slave, stdout=self.slave, stderr=self.slave)
        self.addCleanup(self.stop)
        self.wait_for(lambda: b'Dusky' in self.output)
        self.assertFalse(self.termios.tcgetattr(self.slave)[0] & self.termios.IXON)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=3)

    def wait_for(self, predicate):
        import select
        import time
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            if select.select([self.master], [], [], .05)[0]:
                self.output += os.read(self.master, 65536)
        self.assertTrue(predicate(), self.output.decode(errors='replace'))

    def test_mouse_release_retains_status_and_quit_restores_terminal(self):
        self.start('--file-manager')
        os.write(self.master, b'\x1b[<0;45;4M\x1b[<0;45;4m')
        self.wait_for(lambda: b'File Manager: Nemo' in self.output)
        os.write(self.master, b'q')
        self.assertEqual(self.proc.wait(timeout=3), 0)
        self.assertEqual(self.termios.tcgetattr(self.slave), self.original)
        self.assertEqual((self.home / '.config/dusky/settings/filemanager_switch.smart').read_text().strip(), 'nemo')
        self.wait_for(lambda: self.output.count(b'File Manager: Nemo') >= 2)

    def test_menu_failure_returns_nonzero_with_full_message(self):
        self.start('--file-manager')
        # Apply Yazi: fixture query returns Nemo, so the effective handler differs.
        os.write(self.master, b'\n')
        self.wait_for(lambda: b'Error:' in self.output)
        os.write(self.master, b'q')
        self.assertEqual(self.proc.wait(timeout=3), 1)
        self.wait_for(lambda: b'expected yazi.desktop, got nemo.desktop' in self.output)
        self.assertEqual(self.termios.tcgetattr(self.slave), self.original)

    def test_sigterm_restores_terminal_and_returns_143(self):
        import signal
        self.start('--terminal')
        self.proc.send_signal(signal.SIGTERM)
        self.assertEqual(self.proc.wait(timeout=3), 143)
        self.assertEqual(self.termios.tcgetattr(self.slave), self.original)

    def test_hangup_restores_terminal_and_returns_129(self):
        import signal
        self.start('--terminal')
        self.proc.send_signal(signal.SIGHUP)
        self.assertEqual(self.proc.wait(timeout=3), 129)
        self.assertEqual(self.termios.tcgetattr(self.slave), self.original)

    def test_ctrl_c_restores_terminal_and_returns_130(self):
        import signal
        self.start('--terminal')
        self.proc.send_signal(signal.SIGINT)
        self.assertEqual(self.proc.wait(timeout=3), 130)
        self.assertEqual(self.termios.tcgetattr(self.slave), self.original)

    def test_terminal_io_error_is_reported_gracefully(self):
        with patch.object(sys.stdin, 'isatty', return_value=True), patch.object(sys.stdout, 'isatty', return_value=True):
            with patch('curses.wrapper', side_effect=self.termios.error(5, 'Input/output error')):
                with self.assertRaisesRegex(ValueError, 'Cannot use this terminal'):
                    apps.menu(apps.Switcher(self.home), 'terminal')

    def test_resize_and_category_navigation(self):
        import fcntl
        import signal
        import struct
        self.start()
        fcntl.ioctl(self.slave, self.termios.TIOCSWINSZ, struct.pack('HHHH', 6, 25, 0, 0))
        self.proc.send_signal(signal.SIGWINCH)
        self.wait_for(lambda: b'Resize to at least' in self.output)
        fcntl.ioctl(self.slave, self.termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        self.proc.send_signal(signal.SIGWINCH)
        self.wait_for(lambda: self.output.count(b'Default Applications') >= 2)
        os.write(self.master, b'\n')
        self.wait_for(lambda: b'Current: yazi' in self.output)
        titles = self.output.count(b'Default Applications')
        os.write(self.master, b'\x1b')
        self.wait_for(lambda: self.output.count(b'Default Applications') > titles)
        os.write(self.master, b'q')
        self.assertEqual(self.proc.wait(timeout=3), 0)
        self.assertEqual(self.termios.tcgetattr(self.slave), self.original)


if __name__ == '__main__':
    unittest.main()
