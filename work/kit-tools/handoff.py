"""Bundle the editable sources and the matching, already-built Windows installer."""
from pathlib import Path, PurePosixPath
from hashlib import sha256
import shutil
import sys
from zipfile import ZIP_DEFLATED, ZipFile


root = Path(__file__).resolve().parents[2]
out = root / 'outputs'
sys.path.insert(0,str(root/'work'/'herdr-mod-kit'))
from kit import VERSION
installer = out / f'Herdr-Mod-Kit-Windows-x64-v{VERSION}.zip'
archive = out / f'Herdr-Mod-Kit-Dev-v{VERSION}.zip'
source_files = {
    '': ['HANDOFF.md', 'README.md', '.gitignore', '.gitattributes'],
    'docs': ['remote-work.md'],
    'docs/screenshots': ['files-menu.png', 'files-drag.png', 'pdf-split.png', 'local-usage.png',
                         'usage-sources.png', 'markdown-preview.png', 'image-preview.png'],
    'work': ['package-publish-notes.md'],
    'work/kit-tools': ['stage.py', 'release.py', 'handoff.py', 'verify.py',
                       'check-layout.py', 'check-tabs-and-links.cjs', 'check-file-actions.py', 'test_install.py', 'windows-kit.sh',
                       'check-upgrade.py','check-resources.py','check-speed.py',
                       'fixtures/main.json', 'fixtures/updated.pdf','fixtures/preview.md'],
    'work/herdr-mod-kit': ['kit.py', 'README.md', 'AGENT_INSTALL.md', 'Install-Windows.cmd',
                           'Diagnose-Windows.cmd', 'common/kit_log.py',
                           'common/default-windows-keys.json', 'licenses/Herdr-Apache-2.0.txt'],
    'work/kit-version': ['mod.json','main.js'],
    'work/lab-usage': ['mod.json', 'main.js', 'collect.py', 'codex.svg', 'test_collect.py','test_sources.mjs'],
    'work/personal-files': ['mod.json', 'main.js', 'actions.js', 'bridge.py','file_host.py', 'document-drag.js',
                            'document-flow.js', 'document-view.js', 'pdf-geometry.js', 'fixture.pdf',
                            'test_bridge.py', 'test_pdf.py', 'test_ui.mjs', 'test_flow.mjs', 'test_pdf_ui.mjs'],
    'work/personal-tabs': ['mod.json', 'main.js'],
    'work/personal-pane': ['mod.json', 'main.js'],
    'work/personal-terminal-links': ['mod.json', 'link.js'],
}

def main():
    sources = [root / directory / name for directory, names in source_files.items() for name in names]
    for directory in ('lab-usage', 'personal-files', 'personal-tabs', 'personal-pane'):
        sources.extend(root / 'work' / directory / name for name in ('jsconfig.json', 'gpui-kit.d.ts'))
    # Use the exact runtime and licenses selected for this installer as the build inputs.
    prefix = 'Herdr-Mod-Kit/mods/herdr-kit-pdf/vendor/'
    with ZipFile(installer) as installed:
        for entry in installed.namelist():
            if entry.startswith(prefix):
                name = PurePosixPath(entry.removeprefix(prefix))
                vendor_file = root / 'work' / 'personal-files' / 'vendor' / name
                if vendor_file.read_bytes() != installed.read(entry):
                    raise ValueError(f'Rebuild the installer after changing {name}')
                sources.append(vendor_file)
    sources.append(installer)
    with ZipFile(archive, 'w', compression=ZIP_DEFLATED, compresslevel=8) as bundle:
        for path in sorted(sources):
            bundle.write(path, 'Herdr-Mod-Kit-Dev/' + path.relative_to(root).as_posix())
    with ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError('Handoff ZIP integrity check failed')
        print(f'{archive.name}: {len(bundle.namelist())} entries')
    shutil.copyfile(root / 'HANDOFF.md', out / f'Herdr-개발-인계-v{VERSION}.md')
    with (out/'SHA256SUMS').open('w',encoding='ascii',newline='\n') as sums:
        for path in (installer,archive):
            sums.write(f'{sha256(path.read_bytes()).hexdigest()}  {path.name}\n')


if __name__ == '__main__':
    main()
