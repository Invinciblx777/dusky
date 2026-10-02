"""Missing-codec regression tests; use isolated metadata and local media."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import struct
import threading
import time
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).with_name('mpv_yt_dlp_playback_livestream.py')
spec = importlib.util.spec_from_file_location('player', SOURCE)
player = importlib.util.module_from_spec(spec)
spec.loader.exec_module(player)


class CodecMetadata(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.enterContext(patch.object(player.shutil, 'which', return_value='/usr/bin/ffprobe'))

    def test_known_metadata_needs_no_probe(self):
        info = {'formats': [{'url': 'https://example.com/video', 'vcodec': 'av01', 'acodec': 'none'}]}
        with patch.object(player.subprocess, 'run') as run:
            player.probe_missing_codecs(info)
            run.assert_not_called()

    def test_probe_cli_preserves_format_short_option(self):
        for flag in ('-p', '--probe'):
            args = player.build_parser().parse_args(['https://example.com/video', flag, '-f', '#2'])
            self.assertTrue(args.probe)
            self.assertEqual(args.format, '#2')
        self.assertFalse(player.build_parser().parse_args(['https://example.com/video']).probe)

    def test_fast_retains_successes_and_skips_python_network_reads(self):
        info = {'formats': [
            {'url': 'https://example.com/known', 'vcodec': 'vp9', 'acodec': 'opus'},
            {'url': 'https://example.com/quick.mp4', 'ext': 'mp4'},
            {'url': 'https://example.com/failed', 'protocol': 'm3u8_native'}]}

        def probe(cmd, **kwargs):
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 3)
            if cmd[-1].endswith('/failed'):
                raise subprocess.TimeoutExpired(cmd, kwargs['timeout'])
            return Mock(returncode=0, stdout='{"streams": [{"codec_type": "video", "codec_name": "h264"},'
                                            '{"codec_type": "audio", "codec_name": "aac"}]}')

        with patch.object(player.subprocess, 'run', side_effect=probe) as run, \
                patch.object(player.urllib.request, 'urlopen') as urlopen:
            player.probe_missing_codecs(info)
        urlopen.assert_not_called()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(info['formats'][0]['vcodec'], 'vp9')
        self.assertEqual(info['formats'][1]['vcodec'], 'h264')
        self.assertNotIn('vcodec', info['formats'][2])

    def test_fast_stalled_probes_share_one_budget_and_are_reaped(self):
        # Use real child processes: a socket/read timeout alone is insufficient
        # to bound the entire operation, including queued formats.
        real_run = subprocess.run
        processes = []
        real_popen = subprocess.Popen

        def track_process(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process

        def stall(cmd, **kwargs):
            return real_run([player.sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)

        info = {'formats': [{'url': f'https://example.com/{i}.mp4', 'ext': 'mp4'} for i in range(12)]}
        started = time.monotonic()
        with patch.object(player.subprocess, 'run', side_effect=stall), \
                patch.object(player.subprocess, 'Popen', side_effect=track_process), \
                patch.object(player.urllib.request, 'urlopen') as urlopen:
            player.probe_missing_codecs(info)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 2.8)
        self.assertLess(elapsed, 4.5)
        self.assertEqual(len(processes), 4)
        self.assertTrue(all(process.poll() is not None for process in processes))
        urlopen.assert_not_called()

    def test_main_uses_quick_default_and_explicit_long_probe(self):
        for flags, fast in [(['-F'], True), (['-F', '-p'], False),
                            (['-F', '--probe'], False), (['--probe', '-f', 'best', '--print-cmds'], False)]:
            with self.subTest(flags=flags), \
                    patch.object(player.sys, 'argv', ['player', 'https://example.com/video', *flags]), \
                    patch.object(player, 'load_config', return_value={}), \
                    patch.object(player, 'pick_tmpfs', return_value='/dev/shm'), \
                    patch.object(player, 'run_yt_dlp_json', return_value={'formats': []}), \
                    patch.object(player, 'probe_missing_codecs') as probe, \
                    patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(player.main(), 0)
            self.assertEqual(probe.call_args.kwargs['fast'], fast)

    def test_help_plain_and_terminal_rendering(self):
        parser = player.build_parser()
        plain = io.StringIO()
        parser.print_help(file=plain)
        self.assertNotIn('\x1b[', plain.getvalue())
        for text in ('Formats and codec detection:', '-p, --probe', 'Examples:',
                     'default: 3 seconds', 'Codec budgets apply after yt-dlp'):
            self.assertIn(text, plain.getvalue())
        terminal = io.StringIO()
        with patch.object(terminal, 'isatty', return_value=True), \
                patch.object(player, '_RICH', False):
            parser.print_help(file=terminal)
        self.assertEqual(terminal.getvalue(), plain.getvalue())
        if player._RICH:
            terminal = io.StringIO()
            with patch.object(terminal, 'isatty', return_value=True), \
                    patch.dict(os.environ, {'TERM': 'xterm-256color'}):
                parser.print_help(file=terminal)
            # Rich styling must preserve flags and explanations, including brackets.
            visible = player.Text.from_ansi(terminal.getvalue()).plain
            self.assertEqual(visible, plain.getvalue())

    def test_hls_options_do_not_leak_into_other_protocols(self):
        result = Mock(returncode=0, stdout='{"streams": []}')
        for protocol in ('m3u8', 'm3u8_native', 'https', 'http_dash_segments'):
            with self.subTest(protocol=protocol), \
                    patch.object(player.subprocess, 'run', return_value=result) as run:
                player.probe_missing_codecs({'formats': [
                    {'url': 'https://example.com/video', 'protocol': protocol}]})
                cmd = run.call_args.args[0]
                self.assertEqual('-extension_picky' in cmd, protocol.startswith('m3u8'))
                if protocol.startswith('m3u8'):
                    self.assertEqual(cmd[cmd.index('-extension_picky') + 1], '0')

    def test_real_hls_segments_with_tar_url_and_ts_query(self):
        # Match Rumble's URL layout, while serving actual MPEG-TS bytes locally.
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            media = Path(directory) / 'segment.ts'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                            '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '0.5',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
                            '-f', 'mpegts', str(media)], check=True, timeout=15)
            segment = media.read_bytes()
            playlist = (b'#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n'
                        b'#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:0.5,\n'
                        b'archive.tar?r_file=media-0.ts&r_type=video%2Fmp2t\n#EXT-X-ENDLIST\n')

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.headers.get('Referer') != 'https://example.com/':
                        self.send_error(403)
                        return
                    is_playlist = 'r_file=chunklist.m3u8' in self.path
                    body = playlist if is_playlist else segment
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/vnd.apple.mpegurl' if is_playlist else 'video/mp2t')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args):
                    pass

            with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    url = f'http://127.0.0.1:{server.server_port}/archive.tar?r_file=chunklist.m3u8'
                    # Confirm the original failure, then exercise the production fix.
                    original = subprocess.run(['ffprobe', '-v', 'error', '-headers',
                                               'Referer: https://example.com/\r\n', '-i', url],
                                              capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(original.returncode, 0)
                    self.assertIn('allowed_segment_extensions', original.stderr)
                    fmt = {'url': url, 'protocol': 'm3u8_native', 'ext': 'mp4',
                           'http_headers': {'Referer': 'https://example.com/'}}
                    player.probe_missing_codecs({'formats': [fmt]})
                    self.assertEqual((fmt['vcodec'], fmt['acodec']), ('h264', 'aac'))
                finally:
                    server.shutdown()
                    worker.join(timeout=5)

    def test_missing_codecs_fill_table_and_codec_selection(self):
        info = {'formats': [{'url': 'https://example.com/video', 'format_id': 'mp4-1080p',
                             'vcodec': None, 'acodec': None}]}
        result = Mock(returncode=0, stdout=json.dumps({'streams': [
            {'codec_type': 'video', 'codec_name': 'h264'},
            {'codec_type': 'audio', 'codec_name': 'aac'}]}))
        with patch.object(player.subprocess, 'run', return_value=result):
            player.probe_missing_codecs(info)
        formats = player.fmt_list(info)
        self.assertEqual((formats[0]['fam'], formats[0]['vcodec'], formats[0]['acodec']),
                         ('avc', 'h264', 'aac'))
        self.assertEqual(player.resolve_format(formats, 'avc'), 'mp4-1080p')

    def test_headers_cookies_environment_and_timeout(self):
        info = {'http_headers': {'User-Agent': 'test', 'Referer': 'https://example.com/'},
                'formats': [{'url': 'https://example.com/video', 'http_headers': {'User-Agent': 'override'},
                             'cookies': 'name=value; domain=example.com; path=/'}]}
        result = Mock(returncode=0, stdout='{"streams": []}')
        env = dict(os.environ)
        with patch.object(player.subprocess, 'run', return_value=result) as run:
            player.probe_missing_codecs(info, env=env)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index('-headers') + 1],
                         'User-Agent: override\r\nReferer: https://example.com/\r\n')
        self.assertEqual(cmd[cmd.index('-cookies') + 1], info['formats'][0]['cookies'])
        self.assertIs(run.call_args.kwargs['env'], env)
        self.assertGreater(run.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(run.call_args.kwargs['timeout'], 20)

    def test_explicit_absent_audio_remains_authoritative(self):
        fmt = {'url': 'https://example.com/video', 'acodec': 'none'}
        result = Mock(returncode=0, stdout=json.dumps({'streams': [
            {'codec_type': 'video', 'codec_name': 'h264'},
            {'codec_type': 'audio', 'codec_name': 'aac'}]}))
        with patch.object(player.subprocess, 'run', return_value=result):
            player.probe_missing_codecs({'formats': [fmt]})
        self.assertEqual(fmt['acodec'], 'none')
        self.assertEqual(fmt['vcodec'], 'h264')

    def test_probe_failures_do_not_prevent_playback(self):
        for response in (subprocess.TimeoutExpired('ffprobe', 20),
                         Mock(returncode=1, stdout=''),
                         Mock(returncode=0, stdout='invalid JSON'),
                         Mock(returncode=0, stdout='{"streams": []}')):
            with self.subTest(response=response):
                fmt = {'url': 'https://example.com/video'}
                with patch.object(player.subprocess, 'run') as run:
                    if isinstance(response, Exception):
                        run.side_effect = response
                    else:
                        run.return_value = response
                    player.probe_missing_codecs({'formats': [fmt]})
                self.assertNotIn('vcodec', fmt)
                self.assertNotIn('acodec', fmt)

    def test_missing_ffprobe_is_optional(self):
        fmt = {'url': 'https://example.com/video'}
        with patch.object(player.shutil, 'which', return_value=None), \
                patch.object(player.subprocess, 'run') as run:
            player.probe_missing_codecs({'formats': [fmt]})
            run.assert_not_called()
        self.assertNotIn('vcodec', fmt)

    def test_shared_deadline_skips_queued_work(self):
        with patch.object(player.time, 'monotonic', side_effect=[0, 21]), \
                patch.object(player.subprocess, 'run') as run:
            player.probe_missing_codecs({'formats': [{'url': 'https://example.com/video'}]})
            run.assert_not_called()

    def test_real_mp4_header_detection(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            media = Path(directory) / 'test.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                            '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '0.5',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
                            '-movflags', '+faststart', str(media)], check=True, timeout=15)
            fmt = {'url': str(media)}
            player.probe_missing_codecs({'formats': [fmt]})
            self.assertEqual((fmt['vcodec'], fmt['acodec']), ('h264', 'aac'))
            data = media.read_bytes()
            received = []

            def serve(request, timeout):
                start, end = map(int, request.get_header('Range')[6:].split('-'))
                response = io.BytesIO(data[start:end + 1])
                response.status = 206
                response.headers = {'Content-Range': f'bytes {start}-{min(end, len(data)-1)}/{len(data)}'}
                received.append((start, end))
                return response

            fmt = {'url': 'https://example.com/video.mp4', 'ext': 'mp4'}
            with patch.object(player.urllib.request, 'urlopen', side_effect=serve):
                player.probe_missing_codecs({'formats': [fmt]}, fast=False)
            self.assertEqual((fmt['vcodec'], fmt['acodec']), ('h264', 'aac'))
            self.assertTrue(received)

    def test_range_rejection_falls_back_to_ffprobe(self):
        response = io.BytesIO(b'')
        response.status = 200
        result = Mock(returncode=0, stdout='{"streams": [{"codec_type": "video", "codec_name": "vp9"}]}')
        fmt = {'url': 'https://example.com/video.mp4', 'ext': 'mp4'}
        with patch.object(player.urllib.request, 'urlopen', return_value=response), \
                patch.object(player.subprocess, 'run', return_value=result) as run:
            player.probe_missing_codecs({'formats': [fmt]}, fast=False)
        self.assertEqual(fmt['vcodec'], 'vp9')
        self.assertEqual(fmt['acodec'], 'none')
        self.assertEqual(run.call_args.args[0][-1], fmt['url'])

    def test_interrupted_header_response_falls_back(self):
        result = Mock(returncode=0, stdout='{"streams": [{"codec_type": "video", "codec_name": "h264"}]}')
        fmt = {'url': 'https://example.com/video.mp4', 'ext': 'mp4'}
        with patch.object(player.urllib.request, 'urlopen',
                          side_effect=player.http.client.IncompleteRead(b'')), \
                patch.object(player.subprocess, 'run', return_value=result):
            player.probe_missing_codecs({'formats': [fmt]}, fast=False)
        self.assertEqual(fmt['vcodec'], 'h264')

    def test_sparse_header_skips_huge_index_and_supports_extended_sizes(self):
        def box(kind, payload):
            return struct.pack('>I4s', len(payload) + 8, kind) + payload

        huge_index_size = 10_000_000
        description = box(b'stsd', b'codec descriptor')
        index = struct.pack('>I4s', huge_index_size, b'stco')
        # Simulate a giant video sample index before the audio track.
        stbl = struct.pack('>I4s', 8 + len(description) + huge_index_size, b'stbl') + description + index
        audio = box(b'trak', box(b'mdia', box(b'minf', box(b'stbl', description))))
        # Put stbl at the proper minf/mdia nesting level.
        stbl_size = 8 + len(description) + huge_index_size
        video_prefix = (struct.pack('>I4s', stbl_size + 24, b'trak') +
                        struct.pack('>I4s', stbl_size + 16, b'mdia') +
                        struct.pack('>I4s', stbl_size + 8, b'minf') + stbl)
        payload = video_prefix + bytes(huge_index_size - 8) + audio
        data = struct.pack('>I4sQ', 1, b'moov', len(payload) + 16) + payload
        received = []

        def serve(request, timeout):
            start, end = map(int, request.get_header('Range')[6:].split('-'))
            response = io.BytesIO(data[start:end + 1])
            response.status = 206
            response.headers = {'Content-Range': f'bytes {start}-{min(end, len(data)-1)}/{len(data)}'}
            received.append((start, end))
            return response

        with patch.object(player.urllib.request, 'urlopen', side_effect=serve):
            compact = player.mp4_codec_header('https://example.com/v.mp4', {}, time.monotonic() + 5)
        self.assertEqual(compact.count(b'codec descriptor'), 2)
        self.assertLess(len(compact), 256)
        self.assertLessEqual(len(received), 2)

    def test_invalid_range_and_truncated_boxes_are_rejected(self):
        for content_range, data in [('bytes 99-120/121', b'bad'),
                                    ('bytes 0-2/3', b'bad'),
                                    ('bytes 0-7/8', struct.pack('>I4s', 0, b'moov'))]:
            response = io.BytesIO(data)
            response.status = 206
            response.headers = {'Content-Range': content_range}
            with self.subTest(content_range=content_range), \
                    patch.object(player.urllib.request, 'urlopen', return_value=response):
                with self.assertRaises(ValueError):
                    player.mp4_codec_header('https://example.com/v.mp4', {}, time.monotonic() + 5)


if __name__ == '__main__':
    unittest.main()
