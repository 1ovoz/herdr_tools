"""Compare matched file transfers and PDF renders against a previous Windows installer."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from zipfile import ZipFile

work=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(work/'personal-files'))
import bridge


class CoreLoopback:
    # Exercise hc's stdin/stdout transport on this PC without an external SSH machine.
    on='loopback'
    def __init__(self,module):
        self.module=module
        self.calls=0
    def request(self,action,**fields):
        self.calls+=1
        core=Path(os.environ['LOCALAPPDATA'])/'Programs/herdr-core/hc.exe'
        result=subprocess.run([str(core),'exec','-i',sys.executable,'-I','-c',self.module.REMOTE],
                              input=json.dumps(dict(action=action,**fields)).encode(),
                              capture_output=True,check=True,timeout=75)
        reply=json.loads(result.stdout)
        if not reply['ok']:raise RuntimeError(reply['error'])
        return reply


def check_folder_zip():
    with tempfile.TemporaryDirectory(prefix='herdr-core-zip-') as tmp:
        root=Path(tmp)
        source=root/'자료'
        (source/'empty').mkdir(parents=True)
        (source/'nested').mkdir()
        data=os.urandom(5*1024**2)
        (source/'nested'/'한글.bin').write_bytes(data)
        target=root/'export.zip'
        client=CoreLoopback(bridge)
        with patch.object(bridge,'choose_download_path',return_value=target):
            bridge.download_zip(client,str(source),lambda *args:None,bridge.Control())
        with ZipFile(target) as bundle:
            assert bundle.testzip() is None
            assert bundle.read('자료/nested/한글.bin')==data
            assert bundle.getinfo('자료/empty/').is_dir()
        print('5 MiB folder ZIP verified through Herdr Core, calls:',client.calls)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous',type=Path,nargs='?')
    parser.add_argument('--folder-zip',action='store_true',help='exercise a folder download through Windows Herdr Core')
    args=parser.parse_args()
    if args.folder_zip:
        check_folder_zip()
    if not args.previous:
        if not args.folder_zip:parser.error('supply a previous Windows ZIP or --folder-zip')
        return
    with tempfile.TemporaryDirectory(prefix='herdr-speed-') as tmp:
        root=Path(tmp)
        with ZipFile(args.previous) as previous:previous.extractall(root)
        old_dir=root/'Herdr-Mod-Kit'/'common'
        sys.path.insert(0,str(old_dir))
        spec=importlib.util.spec_from_file_location('old_bridge',old_dir/'bridge.py')
        old=importlib.util.module_from_spec(spec)
        # Load the previous installer's own host protocol during the comparison.
        with patch.dict(sys.modules):
            sys.modules.pop('file_host',None)
            spec.loader.exec_module(old)
        source=root/'payload.bin'
        source.write_bytes(os.urandom(4*1024**2))
        fixture=work/'personal-files'/'fixture.pdf'
        # Both helpers use the same verified PDFium runtime and the same document.
        sys.path.insert(0,str(work/'personal-files'/'vendor'))
        for label,module in [(args.previous.stem,old),('current',bridge)]:
            folder=root/label
            folder.mkdir()
            dest=folder/'download'
            for transport in ('local','core loopback'):
                client=module.RemoteClient(None,'unused') if transport=='local' else CoreLoopback(module)
                times=[]
                # On this computer the current helper copies directly, as the app does.
                direct=transport=='local' and hasattr(module,'local_upload')
                for _ in range(3):
                    start=time.perf_counter()
                    if direct:module.local_upload(source,str(folder),overwrite=True)
                    else:module.upload(client,source,str(folder),overwrite=True)
                    middle=time.perf_counter()
                    if direct:result=module.local_download((folder/source.name).as_posix(),dest,overwrite=True)
                    else:result=module.download(client,(folder/source.name).as_posix(),dest,overwrite=True)
                    times.append((middle-start,time.perf_counter()-middle))
                    assert Path(result['path']).read_bytes()==source.read_bytes()
                print(label,transport,'4 MiB median seconds (upload, download)',
                      tuple(round(statistics.median(column),3) for column in zip(*times)),
                      'hc calls per pair',getattr(client,'calls',0)//3,flush=True)
            render=[]
            for i in range(9):
                start=time.perf_counter()
                result=module.render_pdf(fixture,0,1800,folder)
                elapsed=time.perf_counter()-start
                Path(result['image']).unlink()
                if i:render.append(elapsed)
            print(label,'1800x2250 uncached PDF median seconds',round(statistics.median(render),3),flush=True)


if __name__=='__main__':
    main()
