"""Exercise an installed isolated profile, using the live lab connection only for a fixture."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

work=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('profile', type=Path, help='Isolated profile with all kit features installed')
parser.add_argument('--machine', default='lab', help='Connected Linux machine name')
args=parser.parse_args()
home=args.profile.resolve()
helpers=home/'data'/'herdr-mod-kit'/'helpers'
runtime=json.loads((helpers/'runtime.json').read_text())
core=runtime['hc']
bridge=helpers/'bridge.py'
fixture=work/'personal-files'/'fixture.pdf'
dest=home/'kit-qa-downloads'
dest.mkdir(exist_ok=True)
def remote_exec(script, *values):
    return subprocess.check_output([core,'exec','--on',args.machine,'python3','-c',script,*values],text=True).strip()

folder=remote_exec('import tempfile; print(tempfile.mkdtemp(prefix="herdr-kit-qa-",dir="/tmp"))')
assert re.fullmatch(r'/tmp/herdr-kit-qa-[a-z0-9_]+',folder),folder


def request(action,**kwargs):
    payload={'action':action,'job':uuid.uuid4().hex,**kwargs}
    value=json.loads(subprocess.check_output([sys.executable,'-X','utf8',str(bridge),'--hc',core,'--home',str(home),'--request',json.dumps(payload)],encoding='utf8'))
    assert value['ok'],value
    return value


try:
    job=uuid.uuid4().hex
    progress=home/'data'/'herdr-mod-kit'/'files'/'jobs'/f'{job}.json'
    progress.parent.mkdir(parents=True,exist_ok=True)
    with progress.open('xb') as progress_reader:
        uploaded=request('upload',on=args.machine,source=str(fixture),directory=folder,job=job)
    progress.unlink(missing_ok=True)
    remote=folder+'/fixture.pdf'
    mode,default=remote_exec('import os,sys; mask=os.umask(0); print(os.stat(sys.argv[1]).st_mode&0o777, 0o666&~mask)',remote).split()
    assert mode==default,f'An uploaded file takes the account default mode: {mode} != {default}'
    first=request('preview',on=args.machine,source=remote,page=0,width=900,sizes=True)
    assert first['pages']==2 and (home/first['image']).is_file()
    assert len(first['sizes'])==2
    assert request('revision',on=args.machine,source=remote)['revision']==first['revision']
    assert 'Herdr PDF viewer' in ''.join(c['t'] for c in first['chars'])
    second=request('render',source=first['pdf'],page=1,width=1400)
    assert second['page']==1 and (home/second['image']).is_file()
    downloaded=request('download',on=args.machine,source=remote,directory=str(dest),overwrite=True)
    assert hashlib.sha256(Path(downloaded['path']).read_bytes()).hexdigest()==uploaded['sha256']
    updated=home/'kit-qa-updated'/'fixture.pdf'
    updated.parent.mkdir(exist_ok=True)
    updated.write_bytes((work/'kit-tools'/'fixtures'/'updated.pdf').read_bytes())
    request('upload',on=args.machine,source=str(updated),directory=folder,overwrite=True)
    assert request('revision',on=args.machine,source=remote)['revision']!=first['revision']
    revised=request('preview',on=args.machine,source=remote,page=1,width=900)
    assert revised['pdf']!=first['pdf'] and 'Updated while viewer is open' in ''.join(c['t'] for c in revised['chars'])
    subfolder=folder+'/sub'
    remote_exec('from pathlib import Path; import sys; Path(sys.argv[1]).mkdir()', subfolder)
    request('move',on=args.machine,source=remote,directory=subfolder)
    moved=request('download',on=args.machine,source=subfolder+'/fixture.pdf',directory=str(dest),overwrite=True)
    assert Path(moved['path']).read_bytes()==updated.read_bytes()
    assert remote_exec('from pathlib import Path; import sys; print(Path(sys.argv[1]).exists())',remote)=='False'
    logdir=home/'data'/'herdr-mod-kit'/'logs'
    for feature in ['transfer','pdf']:
        entries=[json.loads(line) for line in (logdir/f'{feature}.jsonl').read_text().splitlines()]
        assert all(e['feature']==feature and set(e)<= {'utc','feature','stage','code','job'} for e in entries)
    print('Packaged locked-progress upload, move, download, PDF render and refresh, and per-feature logs passed.')
finally:
    remote_exec('from pathlib import Path; import sys; p=Path(sys.argv[1]); (p/"fixture.pdf").unlink(missing_ok=True); d=p/"sub"; (d/"fixture.pdf").unlink(missing_ok=True); d.exists() and d.rmdir(); p.rmdir()',folder)
