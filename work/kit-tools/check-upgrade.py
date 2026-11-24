"""Install two real Windows archives into a disposable Herdr profile."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous',type=Path)
    parser.add_argument('current',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='herdr-upgrade-') as tmp:
        root=Path(tmp)
        profile=root/'profile'
        (profile/'layouts').mkdir(parents=True)
        layout=profile/'layouts'/'main.json'
        shutil.copyfile(Path(__file__).parent/'fixtures/main.json',layout)
        keys=profile/'keys.json'
        keys.write_bytes(b'{"global":{"ctrl-w":"user.binding"}}')
        settings=profile/'settings.json'
        settings.write_bytes(b'{"fixture":"user settings"}')
        originals={p:p.read_bytes() for p in (keys,layout,settings)}
        state=profile/'data'/'herdr-mod-kit'/'install.json'
        for label,archive in [('previous',args.previous),('current',args.current)]:
            with ZipFile(archive) as zipped:
                assert zipped.testzip() is None
                zipped.extractall(root/label)
        def run(label,action,*options):
            tool=root/label/'Herdr-Mod-Kit'/'kit.py'
            subprocess.run([sys.executable,'-B','-X','utf8',str(tool),action,
                            '--app-home',str(profile),*options],check=True)
        run('previous','install','--usage-machine','previous-machine')
        old=json.loads(state.read_text(encoding='utf8'))
        run('current','install')
        new=json.loads(state.read_text(encoding='utf8'))
        assert old['version']!=new['version']
        assert new['features']==old['features'] and new['usage_machine']=='previous-machine'
        assert (state.parent/'backups'/new['backup']/'install.json').is_file()
        run('current','install')
        run('current','diagnose')
        assert all(p.read_bytes()==value for p,value in originals.items())
        print(f"Verified {old['version']} -> {new['version']} -> reinstall; keys, settings, layout and host preserved.")


if __name__=='__main__':
    main()
