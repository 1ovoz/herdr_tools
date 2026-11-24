import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import bridge

class LocalRemote:
    on=None
    def request(self, action, **args):
        result = subprocess.run([sys.executable, '-c', bridge.REMOTE], input=json.dumps({'action': action, **args}).encode(), capture_output=True, check=True)
        value = json.loads(result.stdout)
        if not value['ok']:
            raise bridge.Failure(value['code'], value['error'])
        return value

class Transfers(unittest.TestCase):
    def test_smaller_transport_recovers_without_publishing_partial_data(self):
        source=self.local/'large.bin'
        payload=os.urandom(bridge.CHUNK+312)
        source.write_bytes(payload)
        client=bridge.RemoteClient(None,'unused')
        request=client.request
        def limited(action,**fields):
            if action=='write' and len(fields['data'])>bridge.LEGACY_CHUNK*4//3:
                request(action,**fields)  # Lost acknowledgement after writing the temporary file.
                raise bridge.Failure('connection','fixture limit')
            if action=='read' and fields['length']>bridge.LEGACY_CHUNK:
                raise bridge.Failure('connection','fixture limit')
            return request(action,**fields)
        with patch.object(client,'request',limited):
            bridge.upload(client,source,str(self.remote))
            bridge.download(client,str(self.remote/source.name),self.downloads)
        self.assertEqual((self.downloads/source.name).read_bytes(),payload)
        self.assertFalse(list(self.remote.glob('*.part')))
    def test_download_and_open_saves_programs_for_manual_review(self):
        with patch.object(os,'startfile',create=True) as launch:
            program={'path':'report.exe'}
            bridge.open_download(program)
            bridge.open_download({'path':'report.pdf','zone_marked':False})
            launch.assert_not_called()
            self.assertIn('Saved',program['message'])
            bridge.open_download({'path':'report.pdf','zone_marked':True})
            launch.assert_called_once_with('report.pdf')
    def test_bounded_text_preview(self):
        source=self.local/'sample.txt'
        source.write_text('한'*500000,encoding='utf8')
        result=self.client.request('text',path=str(source))
        self.assertEqual(result['text'],'한'*400001)
        self.assertEqual(result['revision'][0],source.stat().st_size)

    def test_cache_evicts_stale_generated_files_only(self):
        paths=[self.local/name for name in ('111.png','222.png','333.png','note.png')]
        for path in paths:
            path.write_bytes(b'0123456789')
            os.utime(path,(1,1))
        bridge.mark_used(paths[1])
        bridge.prune_cache(self.local,r'\d+\.png',10,paths[2])
        self.assertEqual([p.exists() for p in paths],[False,True,True,True])
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.local = self.root / 'local'; self.local.mkdir()
        self.remote = self.root / 'remote'; self.remote.mkdir()
        self.downloads = self.root / 'downloads'; self.downloads.mkdir()
        self.client = LocalRemote()
    def tearDown(self): self.temp.cleanup()
    def test_binary_multichunk_unicode_roundtrip(self):
        payload = bytes(range(256)) * 2500
        source = self.local / "테스트 ' $() ;.bin"; source.write_bytes(payload)
        bridge.upload(self.client, str(source), str(self.remote))
        result = bridge.download(self.client, str(self.remote / source.name), str(self.downloads))
        self.assertEqual(Path(result['path']).read_bytes(), payload)
        self.assertFalse(list(self.remote.glob('*.part')))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows file sharing semantics')
    def test_open_progress_file_does_not_abort_upload(self):
        source = self.local / 'locked-progress.pdf'
        payload = bytes(range(256)) * 2500
        source.write_bytes(payload)
        job = '1' * 32
        progress_path = self.root / 'data' / 'personal-files' / 'jobs' / f'{job}.json'
        progress_path.parent.mkdir(parents=True)
        progress_path.write_text('{"done":0,"total":640000}', encoding='utf8')
        request = {'action': 'upload', 'source': str(source), 'directory': str(self.remote), 'job': job}
        with progress_path.open('rb'):
            result = subprocess.run(
                [sys.executable, '-X', 'utf8', bridge.__file__, '--hc', 'unused',
                 '--home', str(self.root), '--request', json.dumps(request)],
                capture_output=True, check=True, encoding='utf8',
            )
            self.assertTrue(json.loads(result.stdout)['ok'], result.stdout)
        self.assertEqual((self.remote / source.name).read_bytes(), payload)
        self.assertFalse(list(self.remote.glob('*.part')))
        self.assertFalse(progress_path.with_suffix('.tmp').exists())
    def test_zero_byte(self):
        source = self.local / 'empty.bin'; source.touch()
        bridge.upload(self.client, str(source), str(self.remote))
        result = bridge.download(self.client, str(self.remote/source.name), str(self.downloads))
        self.assertEqual(Path(result['path']).stat().st_size, 0)

    def test_move_preserves_contents_and_removes_source(self):
        source = self.local / '이동 시험.pdf'
        source.write_bytes(b'move bytes')
        result = self.client.request('move', path=str(source), directory=str(self.remote))
        self.assertFalse(source.exists())
        self.assertEqual(Path(result['path']).read_bytes(), b'move bytes')

    def test_move_collision_keeps_both_files(self):
        source = self.local / 'same.pdf'
        source.write_bytes(b'source')
        target = self.remote / source.name
        target.write_bytes(b'target')
        with self.assertRaises(bridge.Failure) as caught:
            self.client.request('move', path=str(source), directory=str(self.remote))
        self.assertEqual(caught.exception.code, 'exists')
        self.assertEqual(source.read_bytes(), b'source')
        self.assertEqual(target.read_bytes(), b'target')

    def file_action(self, action, source, **options):
        request = dict(action=action, source=str(source), job='a' * 32, **options)
        result = subprocess.run(
            [sys.executable, '-X', 'utf8', bridge.__file__, '--hc', 'unused',
             '--home', str(self.root), '--request', json.dumps(request)],
            capture_output=True, check=True, encoding='utf8',
        )
        return json.loads(result.stdout)

    def test_copy_publishes_independent_file_and_rejects_collision(self):
        source = self.local / "원본 '$.txt"
        source.write_bytes(b'original')
        os.utime(source, (1_600_000_000, 1_600_000_000))
        result = self.file_action('copy', source, directory=str(self.remote))
        self.assertTrue(result['ok'], result)
        target = self.remote / source.name
        self.assertEqual(Path(result['path']), target)
        self.assertEqual(target.read_bytes(), b'original')
        self.assertEqual(target.stat().st_mtime_ns, source.stat().st_mtime_ns)
        source.write_bytes(b'changed')
        result = self.file_action('copy', source, directory=str(self.remote), overwrite=True)
        self.assertEqual(result['code'], 'exists')
        self.assertEqual(target.read_bytes(), b'original')
        self.assertEqual(list(self.remote.iterdir()), [target])

    def test_concurrent_copies_publish_exactly_one_complete_file(self):
        first = self.local / 'same.bin'
        second = self.downloads / first.name
        sources = [first, second]
        first.write_bytes(b'A' * 2_000_000)
        second.write_bytes(b'B' * 2_000_000)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(
                lambda source: self.file_action('copy', source, directory=str(self.remote)),
                sources,
            ))
        self.assertCountEqual([value.get('code', 'ok') for value in results], ['ok', 'exists'])
        winner = next(source for source, value in zip(sources, results) if value['ok'])
        target = self.remote / first.name
        self.assertEqual(target.read_bytes(), winner.read_bytes())
        self.assertEqual(list(self.remote.iterdir()), [target])

    def test_rename_requires_single_name_and_keeps_existing_file(self):
        source = self.local / 'first.txt'
        source.write_bytes(b'original')
        target = self.local / '두번째 $file.txt'
        target.write_bytes(b'other')
        result = self.file_action('rename', source, name=target.name)
        self.assertEqual(result['code'], 'exists')
        self.assertEqual(target.read_bytes(), b'other')
        invalid_names = ['', '.', '..', '../escape', 'sub/file', str(self.remote / 'escape')]
        if os.name == 'nt':
            invalid_names.extend(['CON .txt', 'COM¹', 'name:stream', 'trailing.', 'a\\b'])
        for invalid in invalid_names:
            with self.subTest(invalid=invalid):
                self.assertFalse(self.file_action('rename', source, name=invalid)['ok'])
                self.assertEqual(source.read_bytes(), b'original')
        target.unlink()
        result = self.file_action('rename', source, name=target.name)
        self.assertTrue(result['ok'], result)
        self.assertFalse(source.exists())
        self.assertEqual(Path(result['path']).read_bytes(), b'original')

    def test_delete_requires_confirmation_and_an_individual_file(self):
        source = self.local / 'selected.bin'
        source.write_bytes(b'selected')
        for confirmed in (False, 'true'):
            result = self.file_action('delete', source, confirmed=confirmed)
            self.assertFalse(result['ok'])
            self.assertTrue(source.exists())
        self.assertTrue(self.file_action('delete', source, confirmed=True)['ok'])
        self.assertFalse(source.exists())
        self.assertFalse(self.file_action('delete', self.local, confirmed=True)['ok'])
        self.assertTrue(self.local.is_dir())

    def selected_download(self, source, choice, **options):
        request = dict(action='download', choose=True, source=str(source),
                       directory=str(self.downloads), job='b' * 32, **options)
        argv = [bridge.__file__, '--hc', 'unused', '--home', str(self.root),
                '--request', json.dumps(request)]
        out = io.StringIO()
        with patch.object(sys, 'argv', argv), redirect_stdout(out), \
                patch.object(bridge, 'choose_download_path', return_value=choice):
            bridge.main()
        return json.loads(out.getvalue())

    def test_save_as_uses_chosen_directory_and_filename(self):
        source = self.remote / 'original.txt'
        source.write_bytes(b'original')
        chosen = self.local / '다른 이름.dat'
        result = self.selected_download(source, chosen)
        self.assertEqual(Path(result['path']), chosen)
        self.assertEqual(chosen.read_bytes(), b'original')
        self.assertEqual(list(self.downloads.iterdir()), [])
        chosen.write_bytes(b'keep')
        with self.assertRaises(bridge.Failure) as caught:
            self.selected_download(source, chosen, overwrite=True)
        self.assertEqual(caught.exception.code, 'exists')
        self.assertEqual(chosen.read_bytes(), b'keep')

    def test_cancel_save_as_creates_no_file(self):
        source = self.remote / 'original.txt'
        source.write_bytes(b'original')
        result = self.selected_download(source, None)
        self.assertEqual(result, {'ok': True, 'cancelled': True})
        self.assertEqual(list(self.downloads.iterdir()), [])
    def test_upload_requires_overwrite(self):
        source = self.local / 'same.bin'; source.write_bytes(b'new')
        target = self.remote / source.name; target.write_bytes(b'original')
        with self.assertRaises(bridge.Failure) as caught: bridge.upload(self.client, str(source), str(self.remote))
        self.assertEqual(caught.exception.code, 'exists')
        self.assertEqual(target.read_bytes(), b'original')
        bridge.upload(self.client, str(source), str(self.remote), overwrite=True)
        self.assertEqual(target.read_bytes(), b'new')
    def test_download_requires_overwrite(self):
        source = self.remote / 'same.bin'; source.write_bytes(b'new')
        target = self.downloads / source.name; target.write_bytes(b'original')
        with self.assertRaises(bridge.Failure) as caught: bridge.download(self.client, str(source), str(self.downloads))
        self.assertEqual(caught.exception.code, 'exists')
        self.assertEqual(target.read_bytes(), b'original')
        bridge.download(self.client, str(source), str(self.downloads), overwrite=True)
        self.assertEqual(target.read_bytes(), b'new')
    def test_remote_source_mutation_does_not_publish(self):
        source = self.remote / 'change.bin'; source.write_bytes(b'original')
        real = self.client.request
        def changed(action, **args):
            if action == 'read': source.write_bytes(b'changed')
            return real(action, **args)
        self.client.request = changed
        with self.assertRaises(bridge.Failure): bridge.download(self.client, str(source), str(self.downloads))
        self.assertFalse((self.downloads/source.name).exists())
        self.assertFalse(list(self.downloads.glob('*.part')))
    def test_remote_publish_race_does_not_overwrite(self):
        source = self.local/'race.bin'; source.write_bytes(b'new')
        real = self.client.request
        def raced(action, **args):
            if action == 'finish': (self.remote/source.name).write_bytes(b'winner')
            return real(action, **args)
        self.client.request = raced
        with self.assertRaises(bridge.Failure): bridge.upload(self.client, str(source), str(self.remote))
        self.assertEqual((self.remote/source.name).read_bytes(), b'winner')
        self.assertFalse(list(self.remote.glob('*.part')))
    def test_folder_drop_rejected(self):
        with self.assertRaises(bridge.Failure): bridge.upload(self.client, str(self.local), str(self.remote))
    def test_remote_backslash_is_not_a_path_separator(self):
        self.client.on='lab'
        with self.assertRaises(bridge.Failure) as caught:
            bridge.download(self.client,'/remote/draft\\report.pdf',str(self.downloads))
        self.assertEqual(caught.exception.code,'name')
    def test_bound_stat_rejects_changed_pdf(self):
        source=self.remote/'fixture.pdf';source.write_bytes(b'version A')
        stat=self.client.request('stat',path=str(source))
        source.write_bytes(b'version B changed')
        with self.assertRaises(bridge.Failure):
            bridge.download(self.client,str(source),str(self.downloads),info=stat)
        self.assertFalse((self.downloads/source.name).exists())
    def test_replaced_upload_stage_is_rejected(self):
        source=self.local/'stage.bin';source.write_bytes(b'new data')
        real=self.client.request
        def changed(action,**args):
            if action=='write':
                stage=Path(args['path']);stage.unlink();stage.write_bytes(b'')
            return real(action,**args)
        self.client.request=changed
        with self.assertRaises(bridge.Failure):bridge.upload(self.client,str(source),str(self.remote))
        self.assertFalse((self.remote/source.name).exists())
    def test_unsafe_windows_leaf_rejected(self):
        for name in ['CON.pdf','..','a:b.pdf','x\\y.pdf','trailing.']:
            with self.assertRaises(bridge.Failure): bridge.safe_leaf(name)

if __name__ == '__main__': unittest.main()
