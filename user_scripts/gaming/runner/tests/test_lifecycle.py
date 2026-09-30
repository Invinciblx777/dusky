#!/usr/bin/env python3.14
"""Lifecycle regression tests. RUNNER_INTEGRATION=1 enables real rootless FUSE/scope tests.

Run: RUNNER_INTEGRATION=1 python3.14 -m unittest discover -s tests -v
Integration tests create disposable games/prefixes and never touch installed games.
"""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).resolve().parents[1] / 'master_runner.py'
spec = importlib.util.spec_from_file_location('master_runner_test', RUNNER)
r = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r
spec.loader.exec_module(r)
r.Log.level = r.Verbosity.QUIET


def profile(root, **extra):
    return r.Profile('fixture', root / 'fixture.toml', r.deep_merge(
        r.tomllib.loads(r.DEFAULT_CONFIG_TOML), r.deep_merge({
            'paths': {'game_dir': str(root), 'dwarfs_image': 'game.dwarfs', 'executable': 'game.sh'},
            'runtime': {'type': 'script'},
            'runner': {'notifications': False, 'inhibit_idle': False, 'enable_io_shim': False,
                       'kill_grace_s': 0.1},
            'performance': {'gamemode': False},
            'storage': {'dwarfs_cache_percent': 1, 'dwarfs_workers': 2},
        }, extra)))


class MountTransactions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='runner-unit-')
        self.addCleanup(self.temp.cleanup)
        self.p = profile(Path(self.temp.name))
        self.paths = r.resolve_paths(self.p)
        self.table = r.MountTable()
        self.table._by_target = {}
        self.mounts = self.table._by_target
        self.counter = 0
        self.patch = patch.object(r, 'mount_table', return_value=self.table)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def add(self, mp, kind='fuse.dwarfs'):
        self.counter += 1
        self.mounts[str(mp)] = r.MountEntry(self.counter, 1, '0:0', '/', mp, '', kind, 'dwarfs', '')

    def detach(self, mp, **kw):
        self.mounts.pop(str(mp), None)
        return True

    def test_failure_after_publishing_rolls_back_both_in_order(self):
        calls = []
        def attempt(*a, **kw):
            self.add(self.paths.dwarfs_mount)
            self.add(self.paths.overlay_dir, 'fuse.fuse-overlayfs')
            raise KeyboardInterrupt()
        def detach(mp, **kw):
            calls.append(mp)
            return self.detach(mp)
        with patch.object(r.MountEngine, '_mount_impl', side_effect=attempt), \
             patch.object(r.MountEngine, '_detach', side_effect=detach):
            with self.assertRaises(KeyboardInterrupt):
                r.MountEngine.mount(self.p, self.paths)
        self.assertEqual(calls, [self.paths.overlay_dir, self.paths.dwarfs_mount])
        self.assertFalse(self.mounts)

    def test_failed_attempt_preserves_existing_lower(self):
        self.add(self.paths.dwarfs_mount)
        def attempt(*a, **kw):
            self.add(self.paths.overlay_dir, 'fuse.fuse-overlayfs')
            return False
        with patch.object(r.MountEngine, '_mount_impl', side_effect=attempt), \
             patch.object(r.MountEngine, '_detach', side_effect=self.detach):
            self.assertFalse(r.MountEngine.mount(self.p, self.paths))
        self.assertEqual(set(self.mounts), {str(self.paths.dwarfs_mount)})

    def test_busy_union_keeps_lower_and_workdir(self):
        self.add(self.paths.dwarfs_mount)
        self.add(self.paths.overlay_dir, 'fuse.fuse-overlayfs')
        with patch.object(r.MountEngine, '_detach', return_value=False) as detach, \
             patch.object(r.MountEngine, '_purge_workdir') as purge:
            self.assertFalse(r.MountEngine.unmount(self.p, self.paths))
        detach.assert_called_once_with(self.paths.overlay_dir)
        purge.assert_not_called()

    def test_detach_checks_kernel_even_on_helper_success(self):
        self.add(self.paths.dwarfs_mount)
        with patch.object(r, 'run_cmd', return_value=r.Ran(0, '', '')) as run:
            self.assertFalse(r.MountEngine._detach(self.paths.dwarfs_mount))
        self.assertEqual(run.call_count, 2)

    def test_foreign_mount_is_not_detached(self):
        self.add(self.paths.overlay_dir, 'tmpfs')
        with patch.object(r.MountEngine, '_detach') as detach:
            with self.assertRaises(r.ConfigError):
                r.MountEngine.unmount(self.p, self.paths)
        detach.assert_not_called()

    def test_shared_lower_conflicts_even_with_different_overlay(self):
        other = r.replace(self.paths, overlay_dir=self.paths.game_dir / 'other-root',
                          overlay_upper=self.paths.game_dir / 'other-upper',
                          overlay_work=self.paths.game_dir / 'other-work')
        self.assertTrue(set(r.mount_lock_keys(self.paths)) & set(r.mount_lock_keys(other)))

    def test_deferred_signal_is_delivered_after_registration(self):
        registered = []
        with self.assertRaises(r.SessionInterrupted) as exc:
            with r.fatal_signal_guard(defer=True):
                os.kill(os.getpid(), signal.SIGTERM)
                registered.append(True)
        self.assertEqual(exc.exception.signum, signal.SIGTERM)
        self.assertEqual(registered, [True])

    def test_waitpid_fallback_waits_for_real_child(self):
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.1)'],
                                process_group=0)
        try:
            with patch.object(r.os, 'pidfd_open', side_effect=OSError('injected failure')):
                self.assertEqual(r.Supervisor(proc).wait(), 0)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    def test_nonfinite_timeout_rejected(self):
        cfg = Path(self.temp.name)/'config.toml'
        cfg.write_text('[runner]\nkill_grace_s = nan\n')
        profiles = cfg.parent/'profiles'
        profiles.mkdir()
        (profiles/'fixture.toml').write_text('[paths]\ngame_dir = "/tmp/example"\n')
        with self.assertRaises(r.ConfigError):
            r.ProfileManager(cfg.parent).load('fixture')

    def test_overlapping_storage_rejected(self):
        bad = r.replace(self.p, cfg=r.deep_merge(self.p.cfg,
                          {'paths': {'overlay_storage': '.mnt/root/upper'}}))
        with self.assertRaises(r.ConfigError):
            r.resolve_paths(bad)

    def test_repeated_signals_do_not_interrupt_cleanup(self):
        session = r.GameSession(r.ProfileManager(), self.p, r.RunOptions())
        order = []
        session.stack.callback(lambda: order.append('released'))
        def cleanup():
            for signum in r._FATAL_SIGNALS:
                os.kill(os.getpid(), signum)
            order.append('unmounted')
        session.stack.callback(cleanup)
        with session._lifecycle():
            pass
        self.assertEqual(order, ['unmounted', 'released'])

    def test_zero_grace_and_scope_arguments(self):
        pipe = r.PipelineBuilder(self.p, self.paths, [])
        argv = pipe.scope_argv()
        self.assertIn('--expand-environment=no', argv)
        self.assertIn('--unit=' + pipe.scope_unit, argv)
        self.assertTrue(pipe.scope_unit.endswith('.scope'))


@unittest.skipUnless(os.environ.get('RUNNER_INTEGRATION') == '1', 'opt-in real FUSE/systemd integration')
class RealLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='runner-integration-')
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / 'source'
        cls.source.mkdir()
        (cls.source / 'game.sh').write_text('#!/bin/bash\nexec python3.14 "$(dirname "$0")/entry.py" "$@"\n')
        (cls.source / 'game.sh').chmod(0o755)
        (cls.source / 'entry.py').write_text('''import os,sys,time,signal,subprocess,json
from pathlib import Path
mode=sys.argv[1] if len(sys.argv)>1 else "exit"
base=Path(os.environ["AUDIT_STATE"])
(base/"argv.json").write_text(json.dumps(sys.argv[2:]))
(base/"ready").write_text(str(os.getpid()))
if mode=="sleep": time.sleep(30)
elif mode=="stubborn":
 signal.signal(signal.SIGTERM,signal.SIG_IGN)
 (base/"stubborn-ready").touch()
 time.sleep(30)
elif mode=="descendant":
 child=subprocess.Popen([sys.executable,__file__,"child"],start_new_session=True)
 (base/"child-pid").write_text(str(child.pid))
elif mode=="child":
 time.sleep(.5)
 (base/"child-done").touch()
elif mode=="save":
 Path(__file__).with_name("saved.txt").write_text("persistent")
elif mode=="error": sys.exit(17)
''')
        cls.p = profile(cls.root)
        cls.paths = r.resolve_paths(cls.p)
        result = r.run_cmd(['mkdwarfs', '-i', str(cls.source), '-o', str(cls.root / 'game.dwarfs'), '-l', '0'])
        if not result.ok:
            cls.temp.cleanup()
            raise RuntimeError(result.message)
        cls.config = cls.root / 'config'
        (cls.config / 'profiles').mkdir(parents=True)
        (cls.config / 'profiles' / 'fixture.toml').write_text(f'''[paths]
game_dir = {json.dumps(str(cls.root))}
dwarfs_image = "game.dwarfs"
executable = "game.sh"
[runtime]
type = "script"
[runner]
notifications = false
inhibit_idle = false
enable_io_shim = false
kill_grace_s = 0.1
[performance]
gamemode = false
[storage]
dwarfs_cache_percent = 1
dwarfs_workers = 2
''')
        cls.env = dict(os.environ, MASTER_RUNNER_PLAIN='1',
                       XDG_CACHE_HOME=str(cls.root / 'cache'),
                       XDG_STATE_HOME=str(cls.root / 'state'),
                       XDG_CONFIG_HOME=str(cls.root / 'xdg-config'), AUDIT_STATE=str(cls.root))
        cls.active = []

    @classmethod
    def tearDownClass(cls):
        for proc in cls.active:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try: proc.wait(timeout=8)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        r.MountEngine.unmount(cls.p, cls.paths, quiet=True)
        cls.temp.cleanup()

    def setUp(self):
        self.assertTrue(r.MountEngine.unmount(self.p, self.paths, quiet=True))
        for name in ('ready', 'child-pid', 'child-done', 'stubborn-ready', 'hook-ready'):
            (self.root / name).unlink(missing_ok=True)

    def tearDown(self):
        self.assertTrue(r.MountEngine.unmount(self.p, self.paths, quiet=True))

    def launch(self, mode='exit', *, flags=(), args=()):
        cmd = [sys.executable, str(RUNNER), '--plain', '-q', '--root', str(self.config),
               'run', 'fixture', *flags, '--', mode, *args]
        proc = subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        self.active.append(proc)
        return proc

    def finish(self, proc, expected=0):
        out, err = proc.communicate(timeout=15)
        self.assertEqual(proc.returncode, expected, out + err)
        self.assertUnmounted()
        return out, err

    def assertUnmounted(self):
        table = r.mount_table(force=True)
        self.assertFalse(table.is_mount(self.paths.overlay_dir))
        self.assertFalse(table.is_mount(self.paths.dwarfs_mount))

    def ready(self, name='ready'):
        end = time.monotonic() + 10
        while not (self.root / name).exists():
            if time.monotonic() > end:
                self.fail(f'timeout waiting for {name}')
            time.sleep(.01)

    def test_fresh_and_premounted_exit(self):
        for premounted in (False, True):
            with self.subTest(premounted=premounted):
                if premounted:
                    self.assertTrue(r.MountEngine.mount(self.p, self.paths))
                self.finish(self.launch())

    def test_game_error_and_missing_executable(self):
        self.finish(self.launch('error'), 17)
        self.finish(self.launch(flags=('--set', 'paths.executable=absent.file')), 78)

    def test_fatal_signals_and_kill_escalation(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
            for mode in ('sleep', 'stubborn'):
                with self.subTest(signal=sig, mode=mode):
                    (self.root/'ready').unlink(missing_ok=True)
                    (self.root/'stubborn-ready').unlink(missing_ok=True)
                    proc = self.launch(mode)
                    self.ready('stubborn-ready' if mode == 'stubborn' else 'ready')
                    pid = int((self.root/'ready').read_text())
                    proc.send_signal(sig)
                    self.finish(proc, 128 + sig)
                    self.assertFalse(r._pid_running(pid))

    def test_startup_hook_signal(self):
        for phase in ('post_mount', 'pre_launch'):
            with self.subTest(phase=phase):
                (self.root/'hook-ready').unlink(missing_ok=True)
                hook = f'touch {self.root}/hook-ready; sleep 30'
                proc = self.launch(flags=('--set', f'hooks.{phase}=["{hook}"]'))
                self.ready('hook-ready')
                proc.send_signal(signal.SIGTERM)
                self.finish(proc, 143)

    def test_detached_descendant_survives_leader_then_finishes(self):
        self.finish(self.launch('descendant'))
        self.assertTrue((self.root/'child-done').is_file())
        self.assertFalse(r._pid_running(int((self.root/'child-pid').read_text())))

    def test_no_scope_process_group(self):
        proc = self.launch('sleep', flags=('--set', 'runner.use_systemd_scope=false'))
        self.ready()
        proc.send_signal(signal.SIGTERM)
        self.finish(proc, 143)

    def test_keep_mounted_and_no_mount_cleanup(self):
        for flags in (('--keep-mounted',), ('--set', 'runner.auto_unmount_on_exit=false')):
            proc = self.launch(flags=flags)
            out, err = proc.communicate(timeout=15)
            self.assertEqual(proc.returncode, 0, out+err)
            self.assertIs(r.MountEngine.status(self.paths, refresh=True).state, r.MountState.MOUNTED)
            self.assertTrue(r.MountEngine.unmount(self.p, self.paths, quiet=True))
        self.assertTrue(r.MountEngine.mount(self.p, self.paths))
        self.finish(self.launch(flags=('--no-mount',)))

    def test_persistent_upper(self):
        self.finish(self.launch('save'))
        self.assertEqual((self.paths.overlay_upper/'saved.txt').read_text(), 'persistent')
        self.assertTrue(r.MountEngine.mount(self.p, self.paths))
        self.assertEqual((self.paths.overlay_dir/'saved.txt').read_text(), 'persistent')

    def test_busy_union_reports_failure_without_detaching_lower(self):
        self.assertTrue(r.MountEngine.mount(self.p, self.paths))
        holder = subprocess.Popen(['sleep', '30'], cwd=self.paths.overlay_dir)
        deadline = time.monotonic() + 3
        while os.readlink(f'/proc/{holder.pid}/cwd') != str(self.paths.overlay_dir):
            if time.monotonic() > deadline:
                self.fail('holder did not enter mount')
            time.sleep(.01)
        try:
            self.assertFalse(r.MountEngine.unmount(self.p, self.paths, quiet=True))
            self.assertTrue(r.mount_table(force=True).is_mount(self.paths.dwarfs_mount))
            proc = self.launch()
            out, err = proc.communicate(timeout=15)
            self.assertEqual(proc.returncode, 74, out+err)
            self.assertIn('mount cleanup incomplete', err)
        finally:
            holder.terminate(); holder.wait(timeout=5)
        self.assertTrue(r.MountEngine.unmount(self.p, self.paths, quiet=True))

    def test_literal_arguments(self):
        args = ['$HOME', '${USER}', '--', '--flag', 'a b']
        self.finish(self.launch(args=args))
        self.assertEqual(json.loads((self.root/'argv.json').read_text()), args)

    def test_concurrent_launches_serialize(self):
        first = self.launch('sleep')
        self.ready()
        second = self.launch()
        time.sleep(.15)
        self.assertIsNone(second.poll())
        first.send_signal(signal.SIGTERM)
        # Second may mount after first cleanup, so examine final state only.
        out, err = first.communicate(timeout=15)
        self.assertEqual(first.returncode, 143, out+err)
        self.finish(second)

    def test_real_failure_after_mount_published(self):
        original = r.run_cmd
        for layer in ('dwarfs', 'fuse-overlayfs'):
            with self.subTest(layer=layer):
                def fail_after_publish(argv, **kw):
                    result = original(argv, **kw)
                    if argv[0] == layer and result.ok:
                        return r.Ran(1, '', 'injected failure after successful mount')
                    return result
                with patch.object(r, 'run_cmd', side_effect=fail_after_publish):
                    self.assertFalse(r.MountEngine.mount(self.p, self.paths))
                self.assertUnmounted()

    def test_real_readiness_failure_rolls_back(self):
        with patch.object(r.MountEngine, '_wait_ready', return_value=False):
            self.assertFalse(r.MountEngine.mount(self.p, self.paths))
        self.assertUnmounted()

    def test_partial_stack_remount(self):
        self.assertTrue(r.MountEngine.mount(self.p, self.paths))
        lower_id = r.mount_table(force=True).get(self.paths.dwarfs_mount).mount_id
        self.assertTrue(r.MountEngine._detach(self.paths.overlay_dir))
        (self.paths.overlay_work/'disposable').write_text('leftover')
        self.assertTrue(r.MountEngine.mount(self.p, self.paths))
        self.assertEqual(r.mount_table(force=True).get(self.paths.dwarfs_mount).mount_id, lower_id)
        self.assertFalse((self.paths.overlay_work/'disposable').exists())

    def test_crashed_overlay_recovers(self):
        self.assertTrue(r.MountEngine.mount(self.p, self.paths))
        daemon = None
        for procdir in Path('/proc').iterdir():
            if not procdir.name.isdecimal():
                continue
            try:
                args = (procdir/'cmdline').read_bytes().split(b'\0')
            except OSError:
                continue
            if args and args[0].endswith(b'fuse-overlayfs') and os.fsencode(self.paths.overlay_dir) in args:
                daemon = int(procdir.name)
                break
        self.assertIsNotNone(daemon, 'cannot locate the fixture overlay daemon')
        os.kill(daemon, signal.SIGKILL)
        deadline = time.monotonic() + 3
        while r._pid_running(daemon) and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIs(r.MountEngine.status(self.paths, refresh=True).state, r.MountState.STALE)
        self.assertTrue(r.MountEngine.mount(self.p, self.paths))
        self.assertTrue((self.paths.overlay_dir/'game.sh').is_file())

    def test_sandbox_scope_exit_and_signal(self):
        self.finish(self.launch(flags=('--sandbox',)))
        (self.root/'ready').unlink(missing_ok=True)
        proc = self.launch('sleep', flags=('--sandbox',))
        self.ready()
        proc.send_signal(signal.SIGTERM)
        self.finish(proc, 143)

    def test_unusual_and_symlinked_game_paths(self):
        for name in ('space game', 'comma,game', 'colon:game', r'back\slash', 'unicode-λ'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix='runner-path-') as tmp:
                base = Path(tmp)/name
                base.mkdir()
                (base/'game.dwarfs').symlink_to(self.root/'game.dwarfs')
                alias = Path(tmp)/'game-link'
                alias.symlink_to(base, target_is_directory=True)
                prof = profile(alias)
                paths = r.resolve_paths(prof)
                try:
                    self.assertTrue(r.MountEngine.mount(prof, paths))
                    self.assertTrue((paths.overlay_dir/'entry.py').is_file())
                finally:
                    self.assertTrue(r.MountEngine.unmount(prof, paths, quiet=True))
                self.assertFalse(r.mount_table(force=True).is_mount(paths.overlay_dir))
                self.assertFalse(r.mount_table(force=True).is_mount(paths.dwarfs_mount))

    def test_20_repeated_launches(self):
        for n in range(20):
            with self.subTest(iteration=n):
                self.finish(self.launch())


if __name__ == '__main__':
    unittest.main()
