from pathlib import Path
import argparse
import re
import shutil
import sys
from zipfile import ZIP_DEFLATED, ZipFile

workspace=Path(__file__).resolve().parents[2]
kit=workspace/'work'/'herdr-mod-kit'
sys.path.insert(0,str(kit))
from kit import VERSION
parser=argparse.ArgumentParser()
parser.add_argument('--out-dir',type=Path,default=workspace/'outputs')
outputs=parser.parse_args().out_dir
outputs.mkdir(parents=True,exist_ok=True)
root_files=['kit.py','Install-Windows.cmd','Diagnose-Windows.cmd','README.md','AGENT_INSTALL.md',
            'licenses/Herdr-Apache-2.0.txt','common/actions.js','common/document-drag.js',
            'common/document-flow.js','common/bridge.py','common/file_host.py','common/html_preview.py','common/kit_log.py','common/default-windows-keys.json']
manifests={
    'herdr-kit-version': ['mod.json','main.js'],
    'herdr-kit-usage': ['mod.json','main.js','collect.py','codex.svg'],
    'herdr-kit-files': ['mod.json','main.js', 'file-plus.svg', 'folder-plus.svg', 'refresh.svg'],
    'herdr-kit-pdf': ['mod.json','main.js','pdf-geometry.js'],
    'herdr-kit-tabs': ['mod.json','main.js'],
    'herdr-kit-pane': ['mod.json','main.js'],
    'herdr-kit-links': ['mod.json','link.js'],
}
selected=[kit/name for name in root_files]
for mod,files in manifests.items():
    selected.extend(kit/'mods'/mod/name for name in files)
vendor=kit/'mods'/'herdr-kit-pdf'/'vendor'
selected.extend(p for p in vendor.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
blocked=re.compile(rb'(?:[A-Z]:[\\/]+Users[\\/]+|/home/)[\w.-]+[\\/]|sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----', re.IGNORECASE)
for p in selected:
    if p.suffix.lower() in {'.js','.py','.cmd','.md','.json','.txt','.svg'}:
        assert not blocked.search(p.read_bytes()),p
    assert p.name not in {'runtime.json','auth.json','.credentials.json','shared.json','settings.json'},p
assert any(p.name=='pdfium.dll' for p in selected)
assert any('licenses' in p.parts and '.dist-info' in str(p) for p in selected)
archive=outputs/f'Herdr-Mod-Kit-Windows-x64-v{VERSION}.zip'
with ZipFile(archive,'w',compression=ZIP_DEFLATED,compresslevel=8) as zip_file:
    for p in sorted(selected):
        zip_file.write(p,'Herdr-Mod-Kit/'+p.relative_to(kit).as_posix())
with ZipFile(archive) as zip_file:
    assert zip_file.testzip() is None
    print(f'Archive validated with {len(zip_file.namelist())} entries and {archive.stat().st_size:,} bytes')
shutil.copyfile(kit/'AGENT_INSTALL.md',outputs/'Herdr-GPT-설치-안내.md')
