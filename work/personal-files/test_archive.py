from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import bridge
import file_host


class HostProcess:
    """Exercise the isolated stdin/stdout protocol used by hc, without a registered machine."""
    on = 'test-host'

    def request(self, action, **fields):
        response = subprocess.run(
            [sys.executable, '-I', '-c', bridge.REMOTE],
            input=json.dumps(dict(action=action, **fields)), encoding='utf8',
            capture_output=True, check=True,
        )
        value = json.loads(response.stdout)
        if not value['ok']:
            raise bridge.Failure(value['code'], value['error'])
        return value


class FolderDownload(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.source = self.home / '자료'
        self.source.mkdir()
        self.target = self.home / '사본.zip'
        self.suggestions = []

    def run_job(self, choice, remote=False, **options):
        request = dict(action='download-zip', source=str(self.source), choose=True,
                       on='test-host' if remote else None, job='b'*32, **options)
        argv = [bridge.__file__, '--hc', 'unused', '--home', str(self.home),
                '--request', json.dumps(request)]
        out = io.StringIO()
        def picker(name, **options):
            self.suggestions.append(name)
            return choice
        client = HostProcess() if remote else bridge.RemoteClient(None, 'unused')
        with patch.object(sys, 'argv', argv), redirect_stdout(out), \
                patch.object(bridge, 'choose_download_path', picker), \
                patch.object(bridge, 'RemoteClient', return_value=client):
            bridge.main()
        return json.loads(out.getvalue())

    def test_local_and_isolated_host_pack_unicode_and_empty_directories(self):
        (self.source / '하위').mkdir()
        (self.source / '빈 폴더').mkdir()
        payload = os.urandom(bridge.CHUNK + 9)
        (self.source / '하위' / '문서.bin').write_bytes(payload)
        for remote in (False, True):
            with self.subTest(remote=remote):
                result = self.run_job(self.target, remote=remote)
                self.assertEqual(Path(result['path']), self.target)
                with zipfile.ZipFile(self.target) as bundle:
                    self.assertEqual(bundle.read('자료/하위/문서.bin'), payload)
                    self.assertTrue(bundle.getinfo('자료/빈 폴더/').is_dir())
                    self.assertIsNone(bundle.testzip())
                self.target.unlink()
        self.assertEqual(self.suggestions, ['자료.zip', '자료.zip'])

    def test_chosen_path_is_retained_for_explicit_replace_and_skipped_in_source(self):
        self.target = self.source / '기록.zip'
        self.target.write_bytes(b'original')
        with self.assertRaises(bridge.Failure) as caught:
            self.run_job(self.target)
        self.assertEqual(caught.exception.code, 'exists')
        self.assertEqual(self.target.read_bytes(), b'original')
        self.run_job(None, resume=caught.exception.resume, overwrite=True)
        with zipfile.ZipFile(self.target) as bundle:
            self.assertEqual(bundle.namelist(), ['자료/'])
        self.assertEqual(self.suggestions, ['자료.zip'])

    def test_cancel_picker_creates_nothing(self):
        self.assertEqual(self.run_job(None), dict(ok=True, cancelled=True))
        self.assertFalse(self.target.exists())

    def test_extensionless_save_choice_uses_zip_suffix(self):
        result = self.run_job(self.home / '기록')
        self.assertEqual(Path(result['path']), self.home / '기록.zip')
        self.assertTrue(zipfile.is_zipfile(result['path']))

    @unittest.skipIf(os.name=='nt', 'Needs a case-sensitive source folder')
    def test_case_colliding_siblings_return_an_error_before_publication(self):
        (self.source / 'Art').mkdir()
        (self.source / 'ART').write_bytes(b'keep')
        with self.assertRaisesRegex(bridge.Failure, 'Windows'):
            self.run_job(self.target)
        self.assertFalse(self.target.exists())

    def test_cancel_job_preserves_an_existing_destination(self):
        self.target.write_bytes(b'original')
        with self.assertRaises(bridge.Failure) as collision:
            self.run_job(self.target)
        marker = self.home / 'data/personal-files/jobs' / ('b'*32 + '.cancel')
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        with self.assertRaises(bridge.Failure) as cancelled:
            self.run_job(None, resume=collision.exception.resume, overwrite=True)
        self.assertEqual(cancelled.exception.code, 'cancelled')
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertFalse(marker.exists())

    def test_links_within_the_tree_are_skipped_and_linked_roots_rejected(self):
        outside = self.home / 'unrelated'
        outside.mkdir()
        (outside / 'outside.txt').write_text('private')
        try:
            (self.source / 'linked directory').symlink_to(outside, target_is_directory=True)
            (self.source / 'linked file').symlink_to(outside / 'outside.txt')
        except OSError:
            self.skipTest('Symlink creation unavailable')
        self.run_job(self.target)
        with zipfile.ZipFile(self.target) as bundle:
            self.assertEqual(bundle.namelist(), ['자료/'])
        self.target.unlink()
        self.source = self.source / 'linked directory'
        with self.assertRaises(bridge.Failure):
            self.run_job(self.target)
        self.assertFalse(self.target.exists())

    def test_replace_confirmation_and_folder_selection_survive_a_slice(self):
        class EndSlice(bridge.Control):
            def due(self):return True
        self.target.write_bytes(b'original')
        with self.assertRaises(bridge.Failure) as collision:
            self.run_job(self.target)
        self.assertIn(str(self.target), str(collision.exception))
        with patch.object(bridge, 'Control', EndSlice):
            first = self.run_job(None, resume=collision.exception.resume, overwrite=True)
        self.assertTrue(first['partial'])
        self.assertEqual(self.target.read_bytes(), b'original')
        self.run_job(None, resume=first['resume'])
        with zipfile.ZipFile(self.target) as bundle:
            self.assertEqual(bundle.namelist(), ['자료/'])
        self.assertEqual(self.suggestions, ['자료.zip'])

    def test_cancel_between_slices_removes_host_workspace(self):
        class EndSlice(bridge.Control):
            def due(self):return True
        temp = self.home / 'staging'
        temp.mkdir()
        with patch.object(tempfile, 'tempdir', str(temp)):
            with patch.object(bridge, 'Control', EndSlice):
                first = self.run_job(self.target)
            self.assertTrue(first['partial'])
            self.assertTrue(list(temp.iterdir()))
            marker = self.home / 'data/personal-files/jobs' / ('b'*32 + '.cancel')
            marker.touch()
            with self.assertRaises(bridge.Failure) as cancelled:
                self.run_job(None, resume=first['resume'])
            self.assertEqual(cancelled.exception.code, 'cancelled')
            for _ in range(100):
                if not list(temp.iterdir()):break
                time.sleep(0.025)
            self.assertFalse(list(temp.iterdir()))
        self.assertFalse(self.target.exists())

    def test_limits_bound_zip_metadata_and_report_failure_before_publication(self):
        (self.source / 'deeply named file').write_bytes(b'contents')
        for key, limit in [('ARCHIVE_MAX_ENTRIES', 1), ('ARCHIVE_MAX_NAME_BYTES', 10)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory(dir=self.home) as temp:
                with patch.object(tempfile, 'tempdir', temp), patch.object(file_host, key, limit):
                    with self.assertRaises(bridge.Failure):
                        self.run_job(self.target)
                self.assertFalse(self.target.exists())
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_compression_can_continue_inside_one_member_after_host_process_exits(self):
        payload = os.urandom(700_000)
        (self.source / 'large.bin').write_bytes(payload)
        fields = dict(token='a'*32)
        def request(action, **extra):
            return file_host.reply(dict(action=action, **fields, **extra))
        with patch.object(tempfile, 'tempdir', str(self.home)), \
                patch.object(file_host, 'ARCHIVE_SLICE_BYTES', 128_000, create=True), \
                patch.object(subprocess, 'Popen', side_effect=AssertionError('detached child')):
            start = request('archive-start', path=str(self.source))
            self.assertTrue(start['ok'], start)
            try:
                status = request('archive-next')
                self.assertTrue(status['ok'], status)
                self.assertFalse(status.get('ready'))
                self.assertGreater(status['done'], 0)
                self.assertLess(status['done'], len(payload))
                for _ in range(10):
                    status = request('archive-next')
                    self.assertTrue(status['ok'], status)
                    if status.get('ready'):break
                self.assertTrue(status['ready'])
                with zipfile.ZipFile(status['path']) as bundle:
                    self.assertEqual(bundle.read('자료/large.bin'), payload)
                    self.assertIsNone(bundle.testzip())
            finally:
                request('archive-drop')
