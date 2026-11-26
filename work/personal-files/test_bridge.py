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
            if action in ('write','write_at') and len(fields['data'])>bridge.LEGACY_CHUNK*4//3:
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

    def test_html_document_preview(self):
        source = self.local / '미리보기.HTM'
        content = ('<!doctype html><html><head><title>Hidden title</title></head><body>'
                   '<h1>소개 &amp; 소식</h1><p style="color:red">A <b>bold</b> paragraph</p>'
                   '<img src="unavailable.png" alt="그림"><script>hidden()</script>'
                   '<iframe src="elsewhere">hidden frame</iframe><a href="other">Read</a></body></html>')
        source.write_text(content, encoding='utf8')
        request = {'action':'text','source':str(source),'job':'1'*32}
        output = io.StringIO()
        with patch.object(sys, 'argv', ['bridge','--home',str(self.local),'--hc','unused','--request',json.dumps(request)]), redirect_stdout(output):
            bridge.main()
        result = json.loads(output.getvalue())
        self.assertEqual(result['text'], content)
        self.assertIn('<h1>소개 &amp; 소식</h1>', result['html'])
        self.assertIn('<b>bold</b>', result['html'])
        self.assertIn('그림', result['html'])
        self.assertIn('Read', result['html'])
        for omitted in ('hidden', 'Hidden title', 'color:red', 'unavailable.png', 'href=', 'iframe', 'script'):
            self.assertNotIn(omitted, result['html'])

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
        with patch.object(bridge,'CHUNK_STEPS',((bridge.CHUNK,1),)):
            with self.assertRaises(bridge.Failure):bridge.upload(self.client,str(source),str(self.remote))
        self.assertFalse((self.remote/source.name).exists())

    def small_chunks(self):
        return patch.object(bridge,'CHUNK_STEPS',((64*1024,4),(16*1024,1)))

    def test_side_by_side_chunks_keep_their_order(self):
        payload=os.urandom(64*1024*9+123)
        source=self.local/'ordered.bin';source.write_bytes(payload)
        seen=[]
        real=self.client.request
        def recorded(action,**args):
            seen.append(action)
            return real(action,**args)
        self.client.request=recorded
        with self.small_chunks():
            bridge.upload(self.client,str(source),str(self.remote))
            result=bridge.download(self.client,str(self.remote/source.name),str(self.downloads))
        self.assertEqual((self.remote/source.name).read_bytes(),payload)
        self.assertEqual(Path(result['path']).read_bytes(),payload)
        self.assertEqual(seen.count('write_at'),10)
        self.assertEqual(seen.count('read'),10)
        self.assertNotIn('write',seen)

    def test_stage_swapped_between_chunks_publishes_nothing(self):
        source=self.local/'swap.bin';source.write_bytes(os.urandom(64*1024*3))
        real=self.client.request
        calls=[]
        def swapped(action,**args):
            if action=='write_at':
                calls.append(args['offset'])
                if len(calls)==3:
                    stage=Path(args['path']);stage.unlink();stage.write_bytes(b'')
            return real(action,**args)
        self.client.request=swapped
        with patch.object(bridge,'CHUNK_STEPS',((64*1024,2),)):
            with self.assertRaises(bridge.Failure):bridge.upload(self.client,str(source),str(self.remote))
        self.assertFalse((self.remote/source.name).exists())
        self.assertFalse(list(self.remote.glob('*.part')))

    def test_linked_stage_is_not_written(self):
        source=self.local/'linked.bin';source.write_bytes(b'private upload')
        victim=self.remote/'victim.txt';victim.write_bytes(b'keep')
        real=self.client.request
        def linked(action,**args):
            if action=='write_at':
                stage=Path(args['path']);stage.unlink();os.link(victim,stage)
            return real(action,**args)
        self.client.request=linked
        with self.assertRaises(bridge.Failure):bridge.upload(self.client,str(source),str(self.remote))
        self.assertEqual(victim.read_bytes(),b'keep')
        self.assertFalse((self.remote/source.name).exists())

    @unittest.skipIf(os.name=='nt','POSIX file modes')
    def test_upload_publishes_with_the_expected_mode(self):
        mask=os.umask(0o022)
        try:
            source=self.local/'run.sh';source.write_bytes(b'#!/bin/sh\necho v2\n')
            fresh=self.local/'fresh.txt';fresh.write_bytes(b'data')
            target=self.remote/source.name;target.write_bytes(b'#!/bin/sh\necho v1\n');target.chmod(0o755)
            for send in (lambda path,**o:bridge.upload(self.client,str(path),str(self.remote),**o),
                         lambda path,**o:bridge.local_upload(str(path),str(self.remote),**o)):
                target.chmod(0o755);(self.remote/fresh.name).unlink(missing_ok=True)
                send(source,overwrite=True);send(fresh)
                self.assertEqual(target.stat().st_mode&0o777,0o755,'Replacing a file keeps its mode')
                self.assertEqual((self.remote/fresh.name).stat().st_mode&0o777,0o644,'A new file gets the account default')
        finally:os.umask(mask)

    class Stops(bridge.Control):
        """Ends a run after a number of chunks, as the time limit would."""
        def __init__(self,chunks):
            super().__init__();self.chunks=chunks
        def due(self):
            self.chunks-=1
            return self.chunks<0

    def test_upload_continues_across_runs(self):
        payload=os.urandom(64*1024*7+5)
        source=self.local/'long.bin';source.write_bytes(payload)
        marks=[]
        with self.small_chunks():
            first=bridge.upload(self.client,str(source),str(self.remote),control=self.Stops(3),progress=lambda done,total:marks.append(done))
            self.assertTrue(first['partial'])
            self.assertEqual(first['resume']['offset'],64*1024*3)
            self.assertFalse((self.remote/source.name).exists())
            second=bridge.upload(self.client,str(source),str(self.remote),control=self.Stops(2),resume=first['resume'])
            self.assertEqual(second['resume']['offset'],64*1024*5)
            done=bridge.upload(self.client,str(source),str(self.remote),resume=second['resume'])
        self.assertEqual((self.remote/source.name).read_bytes(),payload)
        self.assertEqual(done['size'],len(payload))
        self.assertEqual(marks,sorted(marks))
        self.assertFalse(list(self.remote.glob('*.part')))

    def test_verification_waits_for_a_run_with_time_left(self):
        payload=os.urandom(64*1024*3)
        source=self.local/'late.bin';source.write_bytes(payload)
        remote=self.remote/'late-down.bin';remote.write_bytes(payload)
        def late():
            control=bridge.Control(None,3600);control.started-=bridge.FINISH_WITHIN_SECONDS+1
            return control
        seen=[]
        real=self.client.request
        def recorded(action,**args):
            seen.append(action)
            return real(action,**args)
        self.client.request=recorded
        with self.small_chunks():
            first=bridge.upload(self.client,str(source),str(self.remote),control=late())
            self.assertEqual((first['partial'],first['resume']['offset']),(True,len(payload)))
            self.assertNotIn('finish',seen)
            del seen[:]
            bridge.upload(self.client,str(source),str(self.remote),control=bridge.Control(None,3600),resume=first['resume'])
            self.assertEqual(seen,['finish'],'The next run only verifies and publishes')
            first=bridge.download(self.client,str(remote),str(self.downloads),control=late())
            self.assertEqual((first['partial'],first['resume']['offset']),(True,len(payload)))
            done=bridge.download(self.client,str(remote),str(self.downloads),control=bridge.Control(None,3600),resume=first['resume'])
        self.assertEqual((self.remote/source.name).read_bytes(),payload)
        self.assertEqual(Path(done['path']).read_bytes(),payload)

    def test_upload_does_not_continue_a_changed_source(self):
        source=self.local/'edited.bin';source.write_bytes(os.urandom(64*1024*4))
        with self.small_chunks():
            first=bridge.upload(self.client,str(source),str(self.remote),control=self.Stops(2))
            source.write_bytes(os.urandom(64*1024*4+1))
            with self.assertRaises(bridge.Failure) as caught:
                bridge.upload(self.client,str(source),str(self.remote),resume=first['resume'])
        self.assertEqual(caught.exception.code,'changed')
        self.assertEqual(list(self.remote.iterdir()),[])

    def test_download_continues_across_runs_and_verifies(self):
        payload=os.urandom(64*1024*6+77)
        source=self.remote/'long.bin';source.write_bytes(payload)
        with self.small_chunks(), patch.object(bridge,'HASH_LIMIT',1024):
            first=bridge.download(self.client,str(source),str(self.downloads),control=self.Stops(4))
            self.assertTrue(first['partial'])
            self.assertNotIn('sha256',first['resume']['info'],'Large files are hashed once, at the end')
            self.assertFalse((self.downloads/source.name).exists())
            # A corrupted staging file must not be published.
            part=Path(first['resume']['part'])
            done=bridge.download(self.client,str(source),str(self.downloads),resume=first['resume'])
            self.assertEqual(Path(done['path']).read_bytes(),payload)
            again=bridge.download(self.client,str(source),str(self.downloads),overwrite=True,control=self.Stops(4))
            part=Path(again['resume']['part'])
            data=bytearray(part.read_bytes());data[10]^=0xff;part.write_bytes(bytes(data))
            with self.assertRaises(bridge.Failure) as caught:
                bridge.download(self.client,str(source),str(self.downloads),overwrite=True,resume=again['resume'])
            self.assertEqual(caught.exception.code,'hash')
        self.assertEqual((self.downloads/source.name).read_bytes(),payload)
        self.assertFalse(list(self.downloads.glob('*.part')))

    def test_interrupted_transfer_offers_to_continue(self):
        payload=os.urandom(64*1024*8)
        source=self.remote/'flaky.bin';source.write_bytes(payload)
        upload_source=self.local/'flaky-up.bin';upload_source.write_bytes(payload)
        real=self.client.request
        state={'fail':6}
        def flaky(action,**args):
            if action in ('read','write_at'):
                state['fail']-=1
                if state['fail']<=0:raise bridge.Failure('connection','link dropped')
            return real(action,**args)
        self.client.request=flaky
        with self.small_chunks():
            with self.assertRaises(bridge.Failure) as caught:
                bridge.download(self.client,str(source),str(self.downloads))
            resume=caught.exception.resume
            self.assertGreater(resume['offset'],0)
            state['fail']=10**6
            done=bridge.download(self.client,str(source),str(self.downloads),resume=resume)
            self.assertEqual(Path(done['path']).read_bytes(),payload)
            state['fail']=6
            with self.assertRaises(bridge.Failure) as caught:
                bridge.upload(self.client,str(upload_source),str(self.remote))
            resume=caught.exception.resume
            self.assertGreater(resume['offset'],0)
            state['fail']=10**6
            bridge.upload(self.client,str(upload_source),str(self.remote),resume=resume)
        self.assertEqual((self.remote/upload_source.name).read_bytes(),payload)
        self.assertFalse(list(self.remote.glob('*.part'))+list(self.downloads.glob('*.part')))

    def test_retry_while_the_link_is_still_down_keeps_what_arrived(self):
        payload=os.urandom(64*1024*6)
        source=self.remote/'down.bin';source.write_bytes(payload)
        upload_source=self.local/'down-up.bin';upload_source.write_bytes(payload)
        real=self.client.request
        link={'up':True}
        def gated(action,**args):
            if action in ('read','write_at','write') and not link['up']:raise bridge.Failure('connection','link down')
            return real(action,**args)
        self.client.request=gated
        with self.small_chunks():
            first=bridge.download(self.client,str(source),str(self.downloads),control=self.Stops(4))
            started=bridge.upload(self.client,str(upload_source),str(self.remote),control=self.Stops(3))
            link['up']=False
            with self.assertRaises(bridge.Failure) as caught:
                bridge.download(self.client,str(source),str(self.downloads),resume=first['resume'])
            again=caught.exception.resume
            self.assertEqual((again['offset'],again['step']),(first['resume']['offset'],0),'A later retry uses the proven chunk size')
            with self.assertRaises(bridge.Failure) as caught:
                bridge.upload(self.client,str(upload_source),str(self.remote),resume=started['resume'])
            later=caught.exception.resume
            self.assertEqual(later['offset'],started['resume']['offset'])
            self.assertTrue(Path(later['part']).exists())
            link['up']=True
            done=bridge.download(self.client,str(source),str(self.downloads),resume=again)
            bridge.upload(self.client,str(upload_source),str(self.remote),resume=later)
        self.assertEqual(Path(done['path']).read_bytes(),payload)
        self.assertEqual((self.remote/upload_source.name).read_bytes(),payload)

    def test_cancel_request_stops_and_cleans_up(self):
        source=self.local/'stop.bin';source.write_bytes(os.urandom(64*1024*6))
        remote=self.remote/'stop-down.bin';remote.write_bytes(os.urandom(64*1024*6))
        marker=self.root/'cancel'
        def stop_after_two(done,total):
            if done>=64*1024*2:marker.touch()
        for run in (lambda:bridge.upload(self.client,str(source),str(self.remote),control=bridge.Control(marker),progress=stop_after_two),
                    lambda:bridge.download(self.client,str(remote),str(self.downloads),control=bridge.Control(marker),progress=stop_after_two),
                    lambda:bridge.local_upload(str(source),str(self.remote),control=bridge.Control(marker),progress=stop_after_two)):
            marker.unlink(missing_ok=True)
            with self.small_chunks(), patch.object(bridge,'CHUNK',64*1024):
                with self.assertRaises(bridge.Failure) as caught:run()
            self.assertEqual(caught.exception.code,'cancelled')
            self.assertEqual(sorted(p.name for p in self.remote.iterdir()),['stop-down.bin'])
            self.assertEqual(list(self.downloads.iterdir()),[])

    def test_discard_removes_only_staging_files(self):
        source=self.local/'drop.bin';source.write_bytes(os.urandom(64*1024*4))
        with self.small_chunks():
            first=bridge.upload(self.client,str(source),str(self.remote),control=self.Stops(2))
        part=Path(first['resume']['part'])
        self.assertTrue(part.exists())
        keep=self.remote/'keep.txt';keep.write_bytes(b'keep')
        bridge.discard(self.client,{'kind':'copy','part':str(keep),'offset':0})
        self.assertTrue(keep.exists())
        bridge.discard(self.client,first['resume'])
        self.assertFalse(part.exists())

    def test_same_computer_copy_matches_the_transfer_rules(self):
        payload=os.urandom(bridge.CHUNK+99)
        source=self.local/"로컬 ' $().bin";source.write_bytes(payload)
        result=bridge.local_upload(str(source),str(self.remote))
        target=self.remote/source.name
        self.assertEqual((Path(result['path']),target.read_bytes()),(target,payload))
        self.assertEqual(result['sha256'],hashlib.sha256(payload).hexdigest())
        with self.assertRaises(bridge.Failure) as caught:bridge.local_upload(str(source),str(self.remote))
        self.assertEqual(caught.exception.code,'exists')
        with self.assertRaises(bridge.Failure) as caught:bridge.local_upload(str(self.local),str(self.remote))
        self.assertEqual(caught.exception.code,'folder')
        with self.assertRaises(bridge.Failure):bridge.local_upload(str(source),str(self.remote/'missing'))
        saved=bridge.local_download(str(target),str(self.downloads),filename='other.bin')
        self.assertEqual(Path(saved['path']).read_bytes(),payload)
        self.assertTrue(saved['zone_marked'])
        with self.assertRaises(bridge.Failure) as caught:bridge.local_download(str(target),str(self.downloads),filename='other.bin')
        self.assertEqual(caught.exception.code,'exists')
        with patch.object(bridge,'CHUNK',64*1024):
            first=bridge.local_download(str(target),str(self.downloads),filename='resumed.bin',control=self.Stops(5))
            self.assertTrue(first['partial'])
            done=bridge.local_download(str(target),str(self.downloads),filename='resumed.bin',resume=first['resume'])
        self.assertEqual(Path(done['path']).read_bytes(),payload)
        self.assertEqual(done['sha256'],hashlib.sha256(payload).hexdigest())
        self.assertFalse(list(self.remote.glob('*.part'))+list(self.downloads.glob('*.part')))

    def test_stale_staging_files_are_removed_and_fresh_ones_kept(self):
        old=self.remote/'.herdr-upload-old.part';old.write_bytes(b'left behind');os.utime(old,(1,1))
        fresh=self.remote/'.herdr-upload-new.part';fresh.write_bytes(b'in progress')
        mine=self.remote/'notes.part';mine.write_bytes(b'user file');os.utime(mine,(1,1))
        source=self.local/'next.bin';source.write_bytes(b'next')
        bridge.upload(self.client,str(source),str(self.remote))
        self.assertEqual(sorted(p.name for p in self.remote.iterdir()),['.herdr-upload-new.part','next.bin','notes.part'])
        cache=self.root/'cache';cache.mkdir()
        dead=cache/'page.png.0123.part';dead.write_bytes(b'x');os.utime(dead,(1,1))
        live=cache/'page.png.4567.part';live.write_bytes(b'x')
        bridge.prune_cache(cache,r'\d+\.png',10,cache/'none.png')
        self.assertEqual([p.name for p in cache.glob('*.part')],[live.name])

    def test_change_poll_answers_without_the_full_helper(self):
        source=self.local/'poll.pdf';source.write_bytes(b'12345')
        argv=lambda **q:['bridge.py','--hc','unused','--home',str(self.root),'--request',json.dumps(q)]
        quick=json.loads(bridge.quick_revision(argv(action='revision',source=str(source),job='c'*32)))
        self.assertEqual(quick,self.in_process(action='revision',source=str(source),job='c'*32))
        self.assertEqual(quick,self.file_action('revision',source))
        self.assertEqual(quick['revision'][0],'5')
        for request in (dict(action='revision',source=str(source),job='c'*32,on='lab'),
                        dict(action='revision',source=str(source),job='../x'),
                        dict(action='revision',source=str(self.local/'missing.pdf'),job='c'*32),
                        dict(action='text',source=str(source),job='c'*32)):
            self.assertIsNone(bridge.quick_revision(argv(**request)))
        self.assertIsNone(bridge.quick_revision(['bridge.py','--request']))

    def in_process(self, **request):
        out=io.StringIO()
        argv=[bridge.__file__,'--hc','unused','--home',str(self.root),'--request',json.dumps(request)]
        with patch.object(sys,'argv',argv), redirect_stdout(out):
            bridge.main()
        return json.loads(out.getvalue())

    def test_open_folder_accepts_only_folders(self):
        with patch.object(os,'startfile',create=True) as launch:
            program=self.local/'tool.exe';program.write_bytes(b'MZ')
            with self.assertRaises(bridge.Failure) as caught:
                self.in_process(action='folder',directory=str(program),job='d'*32)
            self.assertEqual(caught.exception.code,'folder')
            launch.assert_not_called()
            self.assertTrue(self.in_process(action='folder',directory=str(self.local),job='d'*32)['ok'])
            launch.assert_called_once_with(str(self.local))

    def test_long_transfer_keeps_its_progress_between_runs(self):
        payload=os.urandom(64*1024*5)
        source=self.local/'sliced.bin';source.write_bytes(payload)
        os.utime(source,ns=(1732100000000000100,1732100000000000100))
        job='e'*32
        progress=self.root/'data'/'personal-files'/'jobs'/f'{job}.json'
        request=dict(action='upload',source=str(source),directory=str(self.remote),job=job)
        class Short(bridge.Control):
            def __init__(self,cancel_file,seconds):
                super().__init__(cancel_file);self.chunks=2
            def due(self):
                self.chunks-=1
                return self.chunks<0
        with patch.object(bridge,'CHUNK',64*1024), patch.object(bridge,'Control',Short):
            first=self.in_process(**request)
            self.assertTrue(first['partial'])
            self.assertEqual(json.loads(progress.read_text()),{'done':64*1024*2,'total':len(payload)})
            # A JavaScript view stores the token between helper runs. Its numbers use doubles.
            returned=json.loads(json.dumps(first['resume']),parse_int=lambda value:int(float(value)))
            second=self.in_process(**request,resume=returned)
            self.assertTrue(second['partial'])
            progress.with_suffix('.cancel').touch()
            with self.assertRaises(bridge.Failure) as caught:
                self.in_process(**request,resume=second['resume'])
            self.assertEqual(caught.exception.code,'cancelled')
            self.assertEqual(list(progress.parent.iterdir()),[],'A finished run removes its progress and cancel request')
            self.assertEqual(list(self.remote.iterdir()),[])
            first=self.in_process(**request)
            self.assertTrue(self.in_process(action='discard',job=job,resume=first['resume'])['ok'])
            self.assertEqual(list(self.remote.iterdir()),[])
            first=self.in_process(**request)
            done=first
            while done.get('partial'):done=self.in_process(**request,resume=done['resume'])
        self.assertEqual(Path(done['path']).read_bytes(),payload)
        self.assertFalse(progress.exists())
    def test_unsafe_windows_leaf_rejected(self):
        for name in ['CON.pdf','..','a:b.pdf','x\\y.pdf','trailing.']:
            with self.assertRaises(bridge.Failure): bridge.safe_leaf(name)

if __name__ == '__main__': unittest.main()
