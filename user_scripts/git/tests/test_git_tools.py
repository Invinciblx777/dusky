"""Isolated regression tests: python -B -m unittest discover -s tests -v.

All commits, resets and pushes are confined to temporary local repositories.
"""
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
saved_environment = os.environ.copy()
spec = importlib.util.spec_from_file_location('manager', ROOT / 'git_dusky.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
os.environ.clear()
os.environ.update(saved_environment)
from rich.console import Console
m.console = Console(file=io.StringIO(), color_system=None)

class BareRepoCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dusky-test-')
        self.root = Path(self.tmp.name)
        self.w = self.root / 'home'
        self.w.mkdir()
        self.g = self.root / 'repo'
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(HOME=str(self.root / 'config-home'), XDG_CONFIG_HOME=str(self.root / 'config-home/.config'), GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1', GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid', GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid')
        subprocess.run(['git', 'init', '--bare', '--initial-branch=main', str(self.g)], env=self.env, check=True, stdout=subprocess.DEVNULL)
        (self.root / 'config-home').mkdir()
        self.env.update(GIT_DIR=str(self.g), GIT_WORK_TREE=str(self.w))
        self.envpatch = patch.dict(os.environ, self.env, clear=True)
        self.envpatch.start()
        m.GIT_DIR = self.g
        m.WORK_TREE = self.w
        m.DOTFILES_LIST = self.w / '.manifest'
        self.write('a', 'base\n')
        self.write('b', 'base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')

    def tearDown(self):
        self.envpatch.stop()
        self.tmp.cleanup()

    def git(self, *a, check=True):
        return subprocess.run(['git', *a], env=self.env, cwd=self.w, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def write(self, n, t):
        p = self.w / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t)

    def commit(self, entries):
        with patch.object(m, 'ask', return_value='test'), patch.object(m, 'ask_yesno', return_value=False):
            m.stage_entries(entries, local_only=True)

class GitTests(BareRepoCase):

    def test_selected_preserves_other_index(self):
        self.write('a', 'chosen\n')
        self.write('b', 'staged\n')
        self.git('add', 'b')
        self.write('b', 'unstaged\n')
        before = self.git('ls-files', '-s', 'b')
        self.commit([e for e in m.changed_entries() if e[0] == 'a'])
        self.assertEqual(self.git('show', 'HEAD:a'), b'chosen\n')
        self.assertEqual(self.git('show', 'HEAD:b'), b'base\n')
        self.assertEqual(before, self.git('ls-files', '-s', 'b'))
        self.assertEqual((self.w / 'b').read_text(), 'unstaged\n')

    def test_literal_and_unusual_names(self):
        names = ['[x]', 'x', 'colon: a', 'line\nbreak', '\x1b[31mred', 'unicodé', '-option', ':(glob)*']
        for n in names:
            self.write(n, 'one')
        self.git('add', '.')
        self.git('commit', '-qm', 'names')
        for n in names:
            self.write(n, 'two')
        self.git('add', '--', 'x')
        self.commit([e for e in m.changed_entries() if e[0] == '[x]'])
        self.assertEqual(self.git('show', 'HEAD:[x]'), b'two')
        self.assertEqual(self.git('show', 'HEAD:x'), b'one')
        self.commit(m.changed_entries())
        self.assertEqual(self.git('status', '--porcelain'), b'')

    def test_staged_and_unstaged_delete(self):
        (self.w / 'a').unlink()
        self.git('add', '-u', 'a')
        (self.w / 'b').unlink()
        self.commit(m.changed_entries())
        self.assertEqual(self.git('ls-tree', '--name-only', 'HEAD'), b'')

    def test_added_then_deleted(self):
        self.write('new', 'x')
        self.git('add', 'new')
        (self.w / 'new').unlink()
        self.commit(m.changed_entries())
        self.assertEqual(self.git('status', '--porcelain'), b'')

    def test_rename_modified(self):
        self.git('mv', 'a', 'renamed')
        self.write('renamed', 'new')
        self.commit(m.changed_entries())
        self.assertEqual(self.git('show', 'HEAD:renamed'), b'new')
        self.assertEqual(self.git('status', '--porcelain'), b'')

    def test_empty_manifest_discard(self):
        self.write('.manifest', '')
        self.write('a', 'keep')
        before = self.git('status', '--porcelain')
        with patch.object(m, 'ask_yesno', side_effect=AssertionError('must not prompt')):
            m.discard_local_changes()
        self.assertEqual(before, self.git('status', '--porcelain'))

    def test_manifest_preserves_unlisted(self):
        self.write('.manifest', 'a\n')
        self.write('a', 'chosen')
        self.write('b', 'other')
        self.git('add', 'b')
        with patch.object(m, 'ask', return_value='scoped'):
            m.sync_all(local_only=True)
        self.assertEqual(self.git('show', 'HEAD:b'), b'base\n')
        self.assertEqual(self.git('show', ':b'), b'other')
        self.assertIn(b'b', self.git('ls-files'))

    def test_raw_filename(self):
        path = os.fsencode(self.w) + b'/bad-\xff'
        with open(path, 'wb') as file:
            file.write(b'x')
        self.commit(m.changed_entries())
        self.assertIn(b'bad-\xff', self.git('ls-files', '-z'))

    def test_missing_manifest_tracked_only(self):
        self.write('a', 'new')
        self.write('new', 'untouched')
        with patch.object(m, 'ask', return_value='tracked'):
            m.sync_all(local_only=True)
        self.assertEqual(self.git('show', 'HEAD:a'), b'new')
        self.assertEqual(self.git('ls-files', 'new'), b'')

    def test_empty_initial_commit(self):
        self.git('symbolic-ref', 'HEAD', 'refs/heads/empty')
        self.git('read-tree', '--empty')
        self.commit([('a', None, '??')])
        self.assertEqual(self.git('show', 'HEAD:a'), b'base\n')

    def test_isolated_env(self):
        os.environ['GIT_INDEX_FILE'] = str(self.root / 'other-index')
        os.environ['GIT_GLOB_PATHSPECS'] = '1'
        self.write('[foo]', 'yes')
        self.commit([('[foo]', None, '??')])
        self.assertEqual(self.git('show', 'HEAD:[foo]'), b'yes')

class TimeMachineTests(BareRepoCase):

    def run_tm(self, script):
        env = self.env | {'HOME': str(self.w), 'DUSKY_SOURCED': '1', 'DUSKY_PERSIST_DIR': str(self.root / 'persist'), 'DUSKY_RUN_ROOT': str(self.root / 'run'), 'DUSKY_SESSION_DIR': str(self.root / 'session'), 'DUSKY_SETTINGS_DIR': str(self.root / 'settings'), 'DUSKY_TM_ENGINE': str(ROOT / 'time_machine/dusky_time_machine_tui.sh')}
        prefix = 'source "$DUSKY_TM_ENGINE"\n_dusky_bind_paths\n_dusky_bind_colors\n_dusky_state_init\n_dusky_load_present_target\n'
        p = subprocess.run(['bash', '--noprofile', '--norc', '-c', prefix + script], env=env, cwd=self.w, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def history(self):
        old = self.git('rev-parse', 'HEAD').decode().strip()
        self.write('a', 'present\n')
        self.git('add', 'a')
        self.git('commit', '-qm', 'present')
        return old

    def test_tm_roundtrip_index(self):
        old = self.history()
        self.write('a', 'staged\n')
        self.git('add', 'a')
        self.write('a', 'unstaged\n')
        self.write('secret', 'private')
        index = self.git('ls-files', '-s')
        status = self.git('status', '--porcelain=v1', '-z')
        self.run_tm(f'_dusky_git_checkout {old} || exit 10\n_dusky_git_return || exit 11\n')
        self.assertEqual(index, self.git('ls-files', '-s'))
        self.assertEqual(status, self.git('status', '--porcelain=v1', '-z'))
        self.assertEqual((self.w / 'a').read_text(), 'unstaged\n')
        self.assertEqual(self.git('stash', 'list'), b'')

    def test_tm_failed_trip_restores_stash(self):
        self.write('collision', 'historical')
        self.git('add', 'collision')
        self.git('commit', '-qm', 'old')
        old = self.git('rev-parse', 'HEAD').decode().strip()
        self.git('rm', 'collision')
        self.git('commit', '-qm', 'present')
        self.write('collision', 'private')
        self.write('a', 'edits')
        self.git('add', 'a')
        idx = self.git('ls-files', '-s')
        self.run_tm(f'if _dusky_git_checkout {old}; then exit 20; fi\n[[ "$(_dusky_read stash)" == none ]] || exit 21\n')
        self.assertEqual((self.w / 'collision').read_text(), 'private')
        self.assertEqual((self.w / 'a').read_text(), 'edits')
        self.assertEqual(idx, self.git('ls-files', '-s'))
        self.assertEqual(self.git('stash', 'list'), b'')

    def test_tm_ignored_collision(self):
        self.write('collision', 'historical')
        self.git('add', 'collision')
        self.git('commit', '-qm', 'old')
        old = self.git('rev-parse', 'HEAD').decode().strip()
        self.git('rm', 'collision')
        self.write('.gitignore', 'collision\n')
        self.git('add', '.gitignore')
        self.git('commit', '-qm', 'present')
        self.write('collision', 'private')
        self.run_tm(f'if _dusky_git_checkout {old}; then exit 22; fi\n')
        self.assertEqual((self.w / 'collision').read_text(), 'private')

    def test_tm_edits_in_past_block_return(self):
        old = self.history()
        self.run_tm(f'_dusky_git_checkout {old} || exit 10\nprintf changed > a\nif _dusky_git_return; then exit 23; fi\n')
        self.assertEqual((self.w / 'a').read_text(), 'changed')

    def test_tm_relaunch_restores_stash(self):
        old = self.history()
        self.write('a', 'staged')
        self.git('add', 'a')
        self.write('a', 'unstaged')
        idx = self.git('ls-files', '-s')
        self.run_tm(f'_dusky_git_checkout {old} || exit 10\n')
        self.run_tm('_dusky_write phase detached\n_dusky_find_session_stash >/dev/null || exit 24\n_dusky_write stash stashed\n_dusky_git_return || exit 25\n')
        self.assertEqual((self.w / 'a').read_text(), 'unstaged')
        self.assertEqual(idx, self.git('ls-files', '-s'))
        self.assertEqual(self.git('stash', 'list'), b'')

    def test_manifest_scans_match_full_filter(self):
        names = ['dir/a.conf', 'dir/deep/b.conf', 'dir/b.txt', 'other/c.conf']
        for name in names:
            self.write(name, 'new')
        for patterns in [['dir/*.conf'], ['dir'], ['*.conf'], ['dir/**/b.conf']]:
            self.write('.manifest', '\n'.join(patterns))
            expected = [e for e in m.changed_entries() if m.matches_pathspec(e[0], patterns) or m.matches_pathspec(e[1], patterns)]
            self.assertEqual(set(m.scoped_entries()), set(expected))

    def test_tm_file_index_preserves_control_characters(self):
        names = ['tab\tfile', 'end\n', '[literal]', 'unicodé']
        for name in names:
            self.write(name, 'contents')
        self.git('add', '.')
        self.git('commit', '-qm', 'filenames')
        self.run_tm('_dusky_write drill_sha "$(_gr rev-parse HEAD)"\n_dusky_git_list_files >/dev/null\n')
        index = (self.root / 'session/state/files_index').read_bytes().split(b'\0')
        self.assertEqual(set(index) - {b''}, {os.fsencode(name) for name in names})

    def test_tm_owner_selftest_and_terminal(self):
        try:
            import pexpect
        except ImportError:
            self.skipTest('pexpect is required for the owner terminal test')
        self.history()
        runtime = self.root / 'runtime'
        runtime.mkdir()
        env = self.env | {'XDG_RUNTIME_DIR': str(runtime), 'DUSKY_TM_SANDBOX': '1', 'TERM': 'xterm-256color'}
        script = str(ROOT / 'time_machine/dusky_time_machine_tui.sh')
        result = subprocess.run(['bash', script, '--self-test'], env=env, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('ALL PASSED', result.stdout)
        child = pexpect.spawn('bash', [script], env=env, encoding='utf-8', timeout=15, dimensions=(40,140))
        try:
            child.expect_exact('\x1b[?1049h')
            child.send('\x1b[1;1R')
            child.expect('Time Machine')
            child.send('\x1b')
            child.expect(pexpect.EOF)
            child.close()
            self.assertEqual(child.exitstatus, 0)
        finally:
            child.close(force=True)


class PushTests(BareRepoCase):

    def remote(self):
        self.remote_dir = self.root / 'remote'
        subprocess.run(['git', 'init', '--bare', '--initial-branch=main', str(self.remote_dir)], env={k: v for k, v in self.env.items() if k not in ('GIT_DIR', 'GIT_WORK_TREE')}, check=True, stdout=subprocess.DEVNULL)
        self.git('remote', 'add', 'backup', str(self.remote_dir))
        self.git('push', '-u', 'backup', 'main:refs/heads/different')
        self.git('config', 'branch.main.merge', 'refs/heads/different')

    def advance(self, *, local=False):
        self.write('b' if local else 'a', 'local\n' if local else 'remote\n')
        self.git('add', 'b' if local else 'a')
        self.git('commit', '-qm', 'advance')

    def test_push_different_upstream(self):
        self.remote()
        self.advance(local=True)
        self.assertTrue(m.safe_push())
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), subprocess.check_output(['git', '--git-dir=' + str(self.remote_dir), 'rev-parse', 'different'], env=self.env).strip())

    def test_fast_forward(self):
        self.remote()
        old = self.git('rev-parse', 'HEAD').decode().strip()
        self.advance()
        new = self.git('rev-parse', 'HEAD')
        self.git('push', 'backup', 'main:different')
        self.git('reset', '--hard', old)
        with patch.object(m, 'ask_yesno', return_value=True):
            self.assertTrue(m.safe_push())
        self.assertEqual(self.git('rev-parse', 'HEAD'), new)
        self.assertEqual((self.w / 'a').read_text(), 'remote\n')

    def test_diverged_rebase(self):
        self.remote()
        old = self.git('rev-parse', 'HEAD').decode().strip()
        self.advance()
        self.git('push', 'backup', 'main:different')
        self.git('reset', '--hard', old)
        self.advance(local=True)
        with patch.object(m, 'ask', return_value='1'):
            self.assertTrue(m.safe_push())
        self.assertEqual((self.w / 'a').read_text(), 'remote\n')
        self.assertEqual((self.w / 'b').read_text(), 'local\n')

    def test_dirty_divergence_preserved(self):
        self.remote()
        old = self.git('rev-parse', 'HEAD').decode().strip()
        self.advance()
        self.git('push', 'backup', 'main:different')
        self.git('reset', '--hard', old)
        self.advance(local=True)
        self.write('a', 'private')
        before = self.git('rev-parse', 'HEAD')
        self.assertFalse(m.safe_push())
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        self.assertEqual((self.w / 'a').read_text(), 'private')

class AdditionalTests(BareRepoCase):

    def test_discard_replacement_restores_head_after_approved_delete(self):
        self.write('.manifest', 'a\n')
        self.git('rm', '--cached', 'a')
        self.write('a', 'replacement')
        with patch.object(m, 'ask_yesno', return_value=True):
            m.discard_local_changes()
        self.assertEqual((self.w / 'a').read_text(), 'base\n')
        self.assertEqual(self.git('diff', 'HEAD', '--', 'a'), b'')

    def test_discard_preserves_unapproved_untracked_replacement(self):
        self.write('.manifest', 'a\n')
        self.git('rm', '--cached', 'a')
        self.write('a', 'replacement')
        before = self.git('status', '--porcelain=v1', '-z')
        with patch.object(m, 'ask_yesno', side_effect=[True, False]):
            m.discard_local_changes()
        self.assertEqual((self.w / 'a').read_text(), 'replacement')
        self.assertEqual(self.git('status', '--porcelain=v1', '-z'), before)

    def test_untrack_keeps_disk_file(self):
        self.git('rm', '--cached', 'a')
        self.commit([entry for entry in m.changed_entries() if entry[0] == 'a' and entry[2] == 'D '])
        self.assertEqual(self.git('ls-files', 'a'), b'')
        self.assertEqual((self.w / 'a').read_text(), 'base\n')

    def test_failing_commit_hook_preserves_index(self):
        hook = self.g / 'hooks/pre-commit'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(448)
        self.write('a', 'new')
        self.write('b', 'other')
        self.git('add', 'b')
        before = self.git('rev-parse', 'HEAD')
        bindex = self.git('ls-files', '-s', 'b')
        self.commit([entry for entry in m.changed_entries() if entry[0] == 'a'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.git('ls-files', '-s', 'b'), bindex)
        self.assertEqual(self.git('show', ':a'), b'new')

    def test_edited_commit_hook_updates_selected_index_only(self):
        hook = self.g / 'hooks/pre-commit'
        hook.write_text('#!/bin/sh\nprintf formatted > "$GIT_WORK_TREE/a"\ngit add -- a\n')
        hook.chmod(448)
        self.write('a', 'new')
        self.write('b', 'other')
        self.git('add', 'b')
        bindex = self.git('ls-files', '-s', 'b')
        self.commit([entry for entry in m.changed_entries() if entry[0] == 'a'])
        self.assertEqual(self.git('show', 'HEAD:a'), b'formatted')
        self.assertEqual(self.git('diff', '--cached', '--', 'a'), b'')
        self.assertEqual(self.git('ls-files', '-s', 'b'), bindex)

    def test_shared_lock_blocks_dispatch(self):
        import fcntl
        lock_dir = self.g / 'dusky-time-machine'
        lock_dir.mkdir()
        with (lock_dir / 'worktree.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            action = m.Action('test', 'Test', 0, False, lambda: self.fail('locked action executed'))
            with patch.dict(m.ACTION_MAP, {'test': action}):
                m.dispatch('test')

    def test_fzf_failure_is_reported(self):
        result = subprocess.CompletedProcess(['fzf'], 2, stdout=b'')
        with patch.object(m.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError):
                m.fzf_select(['a'])

class TerminalTests(unittest.TestCase):

    def setUp(self):
        try:
            import pexpect
        except ImportError:
            self.skipTest('pexpect is required for terminal tests')
        self.pexpect = pexpect
        self.env = os.environ | {'TERM': 'xterm-256color', 'FZF_DEFAULT_OPTS': '--height=10% --preview=echo BAD --bind=enter:abort', 'FZF_DEFAULT_OPTS_FILE': '/does/not/exist'}
        self.load = f"import runpy; m=runpy.run_path({str(ROOT / 'git_dusky.py')!r}); "

    def test_python_arrow_editing(self):
        p = self.pexpect.spawn(sys.executable, ['-B', '-c', self.load + "print('RESULT',repr(m['ask']('PROMPT> ')))"], env=self.env, encoding='utf-8', timeout=10)
        try:
            p.expect_exact('PROMPT> ')
            p.send('abc\x1b[DX\r')
            p.expect_exact("RESULT 'abXc'")
            p.expect(self.pexpect.EOF)
        finally:
            p.close(force=True)

    def test_fzf_fullscreen_ignores_global_defaults(self):
        p = self.pexpect.spawn(sys.executable, ['-B', '-c', self.load + "print('RESULT',repr(m['fzf_select'](['alpha','beta'],multi=True)))"], env=self.env, encoding='utf-8', timeout=10, dimensions=(40, 120))
        try:
            p.expect_exact('\x1b[?1049h')
            p.send('\x1b[1;1R')
            p.expect('alpha')
            p.send('\r')
            p.expect_exact("RESULT ['alpha']")
            p.expect(self.pexpect.EOF)
        finally:
            p.close(force=True)
class ShellIntegrationTests(unittest.TestCase):
    def setUp(self):
        try:
            import pexpect
        except ImportError:
            self.skipTest('pexpect is required for shell integration tests')
        self.pexpect = pexpect
        self.config = Path.home() / '.config/zshrc/git'
        if not self.config.is_file():
            self.skipTest('installed Zsh git module is unavailable')
        self.temp = tempfile.TemporaryDirectory(prefix='dusky-shell-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / 'fixture').write_text('untouched')
        self.env = os.environ | {'HOME': str(self.home), 'TERM': 'xterm-256color'}
        self.env.pop('TMUX_PANE', None)

    def test_shell_commit_prompt_arrow_editing(self):
        # Exercise the real shell helper, with Git stubbed to prevent writes.
        script = self.home / 'check.zsh'
        script.write_text('source "$1"\nfunction git_dusky() {\n case "$1" in\n diff) return 1 ;;\n commit) print -r -- "MESSAGE=$3" ;;\n branch) print main ;;\n esac\n return 0\n}\ngit_dusky_push "$HOME/fixture"\n')
        child = self.pexpect.spawn('zsh', ['-f', str(script), str(self.config)], env=self.env, encoding='utf-8', timeout=10)
        try:
            child.expect_exact("Commit message for 'fixture': ")
            child.send('abc\x1b[DX\r')
            child.expect_exact('MESSAGE=abXc (fixture)')
            child.expect(self.pexpect.EOF)
            child.close()
            self.assertEqual(child.exitstatus, 0)
        finally:
            child.close(force=True)

    def test_shell_ctrl_t_fullscreen(self):
        env = self.env | {'FZF_CTRL_T_COMMAND': 'printf "fixture\\n"', 'FZF_CTRL_T_OPTS': '--height=10%', 'FZF_DEFAULT_OPTS': '--height=20%'}
        child = self.pexpect.spawn('zsh', ['-f'], env=env, encoding='utf-8', timeout=12, dimensions=(40,120))
        try:
            child.sendline('PROMPT="READY> "; cd -- "$HOME"')
            child.expect_exact('READY> ')
            import shlex
            quoted = shlex.quote(str(self.config))
            child.sendline(f'source {quoted}; source {quoted}; source <(fzf --zsh)')
            child.expect_exact('READY> ')
            child.send('\x14')
            child.expect_exact('\x1b[?1049h')
            child.send('\x1b[1;1R')
            child.expect('fixture')
            child.send('\r')
            child.expect_exact('READY> fixture')
            child.send('\x03')
            child.sendline('print -r -- "OPTS=${FZF_CTRL_T_OPTS}"')
            child.expect_exact('OPTS=--height=10% --no-height\r\n')
        finally:
            child.close(force=True)

if __name__ == '__main__':
    unittest.main(verbosity=2)
