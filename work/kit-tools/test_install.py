import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

work = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(work / 'herdr-mod-kit'))
import kit


class Reinstall(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.package = root / 'package'
        self.profile = root / 'profile'
        self.common = self.package / 'common'
        self.common.mkdir(parents=True)
        for name in ('kit_log.py', 'bridge.py','file_host.py', *kit.DOCUMENT_MODULES):
            (self.common / name).write_text(name)
        for name in kit.enabled_mods(('transfer', 'tabs')):
            mod = self.package / 'mods' / name
            mod.mkdir(parents=True)
            (mod / 'main.js').write_text('old module')
        (self.profile / 'layouts').mkdir(parents=True)
        shutil.copyfile(Path(__file__).parent / 'fixtures' / 'main.json', kit.system_layout(self.profile))
        self.stack.enter_context(patch.object(kit, 'ROOT', self.package))
        self.stack.enter_context(patch.object(kit, 'version', return_value='0.1.17'))
        self.stack.enter_context(patch.object(kit, 'native_check', return_value=(True, 'ok')))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.install()
        self.target = self.profile / kit.HELPERS / 'bridge.py'
        self.state_file = self.target.parent.parent / 'install.json'

    def install(self, features=('transfer',)):
        options = SimpleNamespace(features=features, usage_machine=None, activate=False)
        kit.install(options, self.profile, 'test-app', 'test-core')

    def test_identical_open_file_keeps_original_timestamp(self):
        os.utime(self.target, (1_600_000_000, 1_600_000_000))
        stamp = self.target.stat().st_mtime_ns
        with self.target.open('rb'):
            self.install()
        self.assertEqual(self.target.stat().st_mtime_ns, stamp)
        self.assertEqual(kit.read_json(self.state_file)['files'][self.target.relative_to(self.profile).as_posix()],
                         kit.hash_file(self.target))

    def test_upgrade_preserves_feature_selection_and_machine(self):
        state=kit.read_json(self.state_file)
        state.update(version='1.3.0',usage_machine='my-machine')
        kit.write_json(self.state_file,state)
        (self.common/'bridge.py').write_text('new helper')
        self.install(None)
        result=kit.read_json(self.state_file)
        self.assertEqual((result['features'],result['usage_machine']),(['transfer'],'my-machine'))
        self.assertEqual(result['version'],kit.VERSION)
        before=list((self.state_file.parent/'backups').iterdir())
        self.install(None)
        self.assertEqual(list((self.state_file.parent/'backups').iterdir()),before)

    def test_old_backups_are_pruned_and_the_current_one_kept(self):
        backups=self.state_file.parent/'backups'
        for round in range(8):
            (self.common/'bridge.py').write_text(f'helper {round}')
            self.install(None)
        kept=sorted(item.name for item in backups.iterdir())
        self.assertEqual(len(kept),5)
        self.assertIn(kit.read_json(self.state_file)['backup'],kept)
        self.assertEqual((backups/kept[-1]/kit.HELPERS/'bridge.py').read_text(),'helper 6')
        note=backups/'my-notes';note.mkdir()
        (self.common/'bridge.py').write_text('helper 9')
        self.install(None)
        self.assertTrue(note.is_dir(),'Only the installer\'s own dated folders are removed')
        self.assertEqual(len(list(backups.iterdir())),6)

    def test_owned_modification_is_preserved(self):
        before=self.state_file.read_bytes()
        self.target.write_text('local edit')
        with self.assertRaisesRegex(kit.KitError,'local_file_conflict'):
            self.install(None)
        self.assertEqual(self.target.read_text(),'local edit')
        self.assertEqual(self.state_file.read_bytes(),before)

    def test_install_lock_blocks_second_installer_and_releases(self):
        with kit.install_lock(self.profile):
            with self.assertRaisesRegex(kit.KitError,'install_busy'):
                self.install(None)
        self.install(None)

    def when_windows_denies_replace(self, target, on_denial):
        actual = os.replace
        def replace(source, destination):
            try:
                return actual(source, destination)
            except PermissionError:
                if Path(destination) == target:
                    on_denial()
                raise
        return patch.object(kit.os, 'replace', replace)

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_changed_file_updates_after_reader_releases(self):
        (self.common / 'bridge.py').write_bytes(b'updated helper')
        with self.target.open('rb') as reader, self.when_windows_denies_replace(self.target, reader.close):
            self.install()
        self.assertEqual(self.target.read_bytes(), b'updated helper')
        backup = self.state_file.parent / 'backups' / kit.read_json(self.state_file)['backup']
        self.assertEqual((backup / kit.HELPERS / 'bridge.py').read_bytes(), b'bridge.py')

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_permanent_lock_rolls_back_prior_change(self):
        (self.common / 'kit_log.py').write_bytes(b'changed before failure')
        (self.common / 'bridge.py').write_bytes(b'locked update')
        previous_state = self.state_file.read_bytes()
        with self.target.open('rb'), self.assertRaises(PermissionError):
            self.install()
        self.assertEqual(self.state_file.read_bytes(), previous_state)
        self.assertEqual((self.target.parent / 'kit_log.py').read_bytes(), b'kit_log.py')
        self.assertEqual(self.target.read_bytes(), b'bridge.py')
        self.assertEqual(list(self.target.parent.glob('*.tmp')), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_key_edit_during_retry_is_preserved(self):
        keys = self.profile / 'keys.json'
        keys.write_bytes(b'{}')
        previous_state = self.state_file.read_bytes()
        with keys.open('r+b') as editor:
            def save_edit():
                editor.write(b'{"global":{"ctrl-w":"other"}}')
                editor.close()
            with self.when_windows_denies_replace(keys, save_edit):
                with self.assertRaisesRegex(kit.KitError, 'tabs_keys_changed'):
                    self.install(('transfer', 'tabs'))
        self.assertEqual(kit.read_json(keys), {'global': {'ctrl-w': 'other'}})
        self.assertEqual(self.state_file.read_bytes(), previous_state)
        self.assertFalse((self.profile / 'mods' / kit.MODS['tabs'] / 'main.js').exists())
        self.install(('transfer', 'tabs'))
        self.assertEqual(kit.read_json(self.state_file)['features'], ['transfer', 'tabs'])
        self.assertEqual(kit.read_json(keys), {'global': {'ctrl-w': 'other'}})


if __name__ == '__main__':
    unittest.main()
