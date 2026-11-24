"""Install and diagnose the Windows Herdr Mod Kit."""
import argparse
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
VERSION = '1.5.0'
FEATURES = ('usage', 'transfer', 'pdf', 'tabs')
MODS = {'usage':'herdr-kit-usage', 'transfer':'herdr-kit-files', 'pdf':'herdr-kit-pdf', 'tabs':'herdr-kit-pane'}
TABS_MOD = 'herdr-kit-tabs'
LINKS_MOD = 'herdr-kit-links'
VERSION_MOD = 'herdr-kit-version'
NATIVE_DEPS = {
    'usage': (MODS['usage'],),
    'transfer': (MODS['transfer'],),
    'pdf': (MODS['transfer'], MODS['pdf'], TABS_MOD, LINKS_MOD),
    'tabs': (MODS['transfer'], MODS['tabs']),
}
DOCUMENT_MODULES = ('actions.js', 'document-drag.js', 'document-flow.js')
HELPERS = Path('data')/'herdr-mod-kit'/'helpers'
LAYOUT = 'herdr-mod-kit'
LAYOUT_KEYS = f'layout:{LAYOUT}'
sys.path.insert(0, str(ROOT/'common'))
from kit_log import record


class KitError(RuntimeError):
    pass


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def replace_atomic(temp, target, before_replace=None):
    # Windows readers can allow reads but briefly deny the delete access a rename needs.
    deadline = time.monotonic() + 3.0
    while True:
        try:
            if before_replace is not None:
                before_replace()
            os.replace(temp, target)
            return
        except PermissionError as error:
            remaining = deadline - time.monotonic()
            if getattr(error, 'winerror', None) not in (5, 32, 33) or remaining <= 0:
                raise
            time.sleep(min(0.1, remaining))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf8') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2)
            stream.write('\n')
        replace_atomic(temp,path)
    finally:
        Path(temp).unlink(missing_ok=True)


def hash_file(path):
    if not path.is_file():
        return None
    digest=sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def check_target(home, target):
    for item in (target, *target.parents):
        if item==home:
            break
        try:
            info=item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise KitError(f'linked_install_path: {item.relative_to(home)}')


@contextmanager
def install_lock(home):
    path=home/'data'/'herdr-mod-kit'/'install.lock'
    check_target(home,path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            raise KitError('install_busy: wait for the current installation to finish') from error
        yield


def nodes(node):
    yield node
    for child in node.get('children',[]):
        yield from nodes(child)


def make_layout(base, features):
    selected = set(features)
    if 'transfer' in selected or 'pdf' in selected:
        files = [node for node in nodes(base) if node.get('id')=='files' and node.get('content',{}).get('mod')=='files']
        if len(files)!=1:
            raise KitError('files_structure_changed: default layout needs one Files block')
        content = files[0]['content']
        content['mod'] = MODS['transfer']
        content['props'] = {**content.get('props',{}), 'transfer':'transfer' in selected, 'pdf':'pdf' in selected}
    if 'pdf' in selected:
        tabs = [node for node in nodes(base) if node.get('id')=='tabs' and node.get('content',{}).get('mod')=='tabs']
        if len(tabs)!=1:
            raise KitError('pdf_tabs_structure_changed: default layout needs one Tabs block')
        tabs[0]['content']['mod'] = TABS_MOD
        base['link_handlers'] = list(dict.fromkeys([*base.get('link_handlers',[]), LINKS_MOD]))
    if 'tabs' in selected:
        headers=[]
        for node in nodes(base):
            header=node.get('content',{}).get('pane',{}).get('header',{}).get('content',{})
            if header.get('mod')=='pane':
                headers.append(header)
        if not headers:
            raise KitError('tabs_header_structure_changed: default layout needs a Pane header')
        for header in headers:
            header['mod']=MODS['tabs']
    if selected:
        hosts = [(node,index) for node in nodes(base) for index,child in enumerate(node.get('children',[]))
                 if child.get('id')=='status' and child.get('content',{}).get('mod')=='workspace-status']
        if len(hosts)!=1:
            if 'usage' in selected:
                raise KitError('usage_structure_changed: default layout needs one workspace status block')
            return base
        parent,index=hosts[0]
        status=parent['children'][index]
        height=status.pop('size',{'px':28})
        status['size']={'weight':1}
        children=[status]
        if 'usage' in selected:
            children.append({'id':'herdr-kit-usage','type':'block','size':{'px':510},'min':400,'content':{'mod':MODS['usage']}})
        children.append({'id':VERSION_MOD,'type':'block','size':{'px':70},
                         'content':{'mod':VERSION_MOD,'props':{'version':VERSION}}})
        parent['children'][index]={'id':'herdr-kit-status','type':'row','size':height,'resizable':False,'children':children}
    return base


def enabled_mods(features):
    mods=tuple(dict.fromkeys(mod for feature in features for mod in NATIVE_DEPS[feature]))
    return (*mods,VERSION_MOD) if mods else ()


def invoke(exe, args, app_home, timeout=25):
    env={**os.environ,'HERDR_APP_HOME':str(app_home),'PYTHONUTF8':'1'}
    return subprocess.run([str(exe),*map(str,args)],capture_output=True,text=True,encoding='utf8',errors='replace',
                          timeout=timeout,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def find_program(override, stem, installed_folder):
    if override:
        path=Path(override).expanduser()
        if not path.is_file():
            raise KitError(f'{stem}_path_invalid: supply the executable path')
        return path.resolve()
    apps=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData'/'Local')))/'Programs'
    path=apps/installed_folder/(stem+'.exe')
    if path.is_file():
        return path
    for folder in os.get_exec_path():
        directory=Path(folder.strip('"'))
        if directory.is_absolute() and directory.resolve()!=Path.cwd().resolve():
            candidate=directory/(stem+'.exe')
            if candidate.is_file():return candidate.resolve()
    return None


def version(exe, home):
    result=invoke(exe,['--version'],home)
    text=(result.stdout or result.stderr).strip().splitlines()
    if result.returncode or not text:
        raise KitError('version_unavailable: Herdr desktop executable could not report its version')
    return text[0]


def native_check(exe, home, path, verbose=False):
    try:
        result=invoke(exe,['check',path],home,timeout=35)
        if result.returncode and verbose:
            print((result.stderr or result.stdout).strip()[:2400])
        return (result.returncode==0,'ok' if result.returncode==0 else f'exit_{result.returncode}')
    except subprocess.TimeoutExpired:
        return False,'timeout'
    except OSError:
        return False,'launch_failed'


def renderer_check(path, python=sys.executable):
    probe='import sys; sys.path.insert(0,sys.argv[1]); import pypdfium2; assert pypdfium2.raw.FPDF_GetLastError() >= 0'
    try:
        result=subprocess.run([python,'-I','-B','-X','utf8','-c',probe,str(path/'vendor')],capture_output=True,timeout=15,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired):
        return False


def system_layout(home):
    return home/'layouts'/'main.json'


def upstream(home):
    return {'layout/main.json':hash_file(system_layout(home)),
            'mods/files/main.js':hash_file(home/'mods'/'files'/'main.js'),
            'mods/tabs/main.js':hash_file(home/'mods'/'tabs'/'main.js'),
            'mods/pane/main.js':hash_file(home/'mods'/'pane'/'main.js')}


def is_tab_close(binding):
    return binding=='tab.close' or isinstance(binding,dict) and binding.get('command')=='tab.close'


def shortcut_status(keys):
    for section in ('terminal',LAYOUT_KEYS,'global'):
        bindings=keys.get(section,{})
        if 'ctrl-w' in bindings:
            return 'ok' if is_tab_close(bindings['ctrl-w']) else f'conflict_{section.split(":")[0]}'
    return 'missing'


def read_keys(path):
    data=read_json(path if path.is_file() else ROOT/'common'/'default-windows-keys.json')
    if not isinstance(data,dict) or any(not isinstance(data.get(key,{}),dict) for key in ('terminal',LAYOUT_KEYS,'global')):
        raise KitError('tabs_keys_invalid: check the binding sections in keys.json')
    return data


def prepare_tab_key(path, enable, owned):
    keys=read_keys(path)
    local=keys.get(LAYOUT_KEYS,{})
    managed=owned and local.get('ctrl-w')=='tab.close'
    if not enable:
        if managed:
            del local['ctrl-w']
            if not local:
                del keys[LAYOUT_KEYS]
        return (keys if managed else None),False,'disabled'
    code=shortcut_status(keys)
    if code!='missing':
        return None,managed,code
    keys.setdefault(LAYOUT_KEYS,{})['ctrl-w']='tab.close'
    return keys,True,'ok'


def helper_files(features):
    if not features:
        return ()
    common = ('kit_log.py', 'runtime.json')
    return (*common, 'bridge.py', 'file_host.py') if 'pdf' in features or 'transfer' in features else common


def copy_atomic(source, target, before_replace=None, created_dirs=None):
    missing=[]
    for parent in target.parents:
        if parent.is_dir():
            break
        missing.append(parent)
    for parent in reversed(missing):
        try:
            parent.mkdir()
        except FileExistsError:
            if not parent.is_dir():
                raise
        else:
            if created_dirs is not None:
                created_dirs.append(parent)
    fd, temp=tempfile.mkstemp(dir=target.parent,suffix='.tmp')
    os.close(fd)
    try:
        shutil.copyfile(source,temp)
        replace_atomic(temp,target,before_replace)
    finally:
        Path(temp).unlink(missing_ok=True)


def install(options, home, app, core):
    with install_lock(home):
        install_locked(options, home, app, core)


def install_locked(options, home, app, core):
    state_dir=home/'data'/'herdr-mod-kit'
    state_file=state_dir/'install.json'
    check_target(home,state_file)
    state=read_json(state_file) if state_file.exists() else {}
    if state and state.get('owner')!=LAYOUT:
        raise KitError('install_state_conflict: existing state is not owned by this kit')
    selection=options.features if options.features is not None else state.get('features', FEATURES)
    features=tuple(key for key in FEATURES if key in selection)
    if ('transfer' in features or 'pdf' in features) and not core:
        raise KitError('hc_missing: install herdr-core or supply --hc')
    if not system_layout(home).is_file():
        raise KitError('main_layout_missing: open Herdr desktop once or supply --app-home')
    app_version=version(app,home)
    match=re.search(r'\b(\d+)\.(\d+)\.(\d+)',app_version)
    minimum=(0,1,17) if 'pdf' in features else (0,1,16)
    if match and tuple(map(int,match.groups()))<minimum:
        required='.'.join(map(str,minimum))
        raise KitError(f'herdr_too_old: Herdr desktop {required} or newer is required for this selection')
    layout_path=home/'layouts'/(LAYOUT+'.json')
    old_owned={key for key in state.get('files',{})}
    needed=enabled_mods(features)
    for mod in needed:
        target=home/'mods'/mod
        if target.exists() and not any(path.startswith(f'mods/{mod}/') for path in old_owned):
            raise KitError(f'mod_name_conflict: {mod} already exists')
    if layout_path.exists() and f'layouts/{layout_path.name}' not in old_owned:
        raise KitError(f'layout_name_conflict: {layout_path.name} already exists')
    machine=options.usage_machine if options.usage_machine is not None else state.get('usage_machine', 'lab' if state else None)
    if isinstance(machine,str) and machine.lower()=='local':
        machine=None
    layout=make_layout(read_json(system_layout(home)),features)
    key_path=home/'keys.json'
    key_previous=hash_file(key_path)
    def check_keys_unchanged():
        if hash_file(key_path)!=key_previous:
            raise KitError('tabs_keys_changed: retry after the other keys.json edit completes')

    keys,owns_tab_key,key_code=prepare_tab_key(key_path,'tabs' in features,state.get('owns_tab_key',False)) \
        if 'tabs' in features or state.get('owns_tab_key') else (None,False,'disabled')
    state_dir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup=state_dir/'backups'/stamp
    check_target(home,backup)
    runtime={'python':sys.executable,'hc':str(core) if core else None}
    with tempfile.TemporaryDirectory(prefix='stage-',dir=state_dir) as temp:
        stage=Path(temp)
        staged_targets={}
        for name in helper_files(features):
            relative=HELPERS/name
            if (home/relative).exists() and relative.as_posix() not in old_owned:
                raise KitError(f'common_helper_conflict: {name} already exists')
            target=stage/relative
            if name=='runtime.json':
                write_json(target,{**runtime,'machine':machine})
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/'common'/name,target)
            staged_targets[relative.as_posix()]=target
        for mod in needed:
            dest=stage/'mods'/mod
            shutil.copytree(ROOT/'mods'/mod,dest,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            if mod in (MODS['transfer'],MODS['pdf']):
                # Herdr restricts JavaScript imports to the current mod's folder.
                for name in DOCUMENT_MODULES:
                    shutil.copyfile(ROOT/'common'/name,dest/name)
            staged_targets.update({p.relative_to(stage).as_posix():p for p in dest.rglob('*') if p.is_file()})
            ok,code=native_check(app,home,dest,verbose=True)
            owners=[feature for feature in features if mod in NATIVE_DEPS[feature]] or ['installer']
            for owner in owners:
                record(home,owner,f'install_native_check.{mod}',code)
            if not ok:
                raise KitError(f'{owners[0]}_native_check_{code}: {mod}; no layout activated; run diagnose')
        if 'pdf' in features:
            ok=renderer_check(stage/'mods'/MODS['pdf'])
            record(home,'pdf','install_renderer','ok' if ok else 'failed')
            if not ok:
                raise KitError('pdf_renderer_failed: a Windows x64 Python is required for PDF')
        staged_layout=stage/'layouts'/layout_path.name
        write_json(staged_layout,layout)
        staged_targets[staged_layout.relative_to(stage).as_posix()]=staged_layout
        if keys is not None:
            write_json(stage/'keys.json',keys)
            staged_targets['keys.json']=stage/'keys.json'
        touched=[]
        created_dirs=[]
        try:
            for relative,source in staged_targets.items():
                target=home/relative
                check_target(home,target)
                check=check_keys_unchanged if relative=='keys.json' else None
                if check:
                    check()
                if target.exists():
                    actual=hash_file(target)
                    if actual==hash_file(source):
                        continue
                    if relative!='keys.json' and (relative not in old_owned or actual!=state['files'][relative]):
                        raise KitError(f'local_file_conflict: preserve or move the modified file before retrying: {relative}')
                    saved=backup/relative
                    saved.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(target,saved)
                copy_atomic(source,target,before_replace=check,created_dirs=created_dirs)
                touched.append(relative)
            changed=touched or state.get('version')!=VERSION or state.get('features')!=list(features) or state.get('usage_machine')!=machine
            if state_file.exists() and changed:
                backup.mkdir(parents=True,exist_ok=True)
                shutil.copy2(state_file,backup/'install.json')
            # Keep ownership of dormant files so a feature can be enabled again later.
            records={**state.get('files',{}),**{relative:hash_file(home/relative) for relative in staged_targets if relative!='keys.json'}}
            write_json(state_file,{'owner':LAYOUT,'version':VERSION,'app_version':app_version,'features':list(features),
                                   'usage_machine':machine,'files':records,'owns_tab_key':owns_tab_key,
                                   'upstream':upstream(home),'backup':stamp if backup.exists() else state.get('backup')})
        except BaseException:
            for relative in reversed(touched):
                if (backup/relative).is_file():
                    copy_atomic(backup/relative,home/relative)
                else:
                    (home/relative).unlink(missing_ok=True)
            for directory in reversed(created_dirs):
                with suppress(OSError):
                    directory.rmdir()
            raise
    record(home,'installer','install','ok')
    if 'tabs' in features:
        record(home,'tabs','install_shortcut',key_code)
        if key_code!='ok':
            print(f'[tabs] Ctrl+W uses an existing binding ({key_code}); kept it.')
    print('Installed:', ', '.join(features) or 'no features', '| Herdr:', app_version)
    print('Layout:', LAYOUT)
    print('Logs:', state_dir/'logs')
    if options.activate:
        switched=invoke(app,['do','layout.switch',json.dumps({'name':LAYOUT})],home)
        if switched.returncode:
            record(home,'installer','activate','failed')
            print('Installed. Select herdr-mod-kit in Herdr when the app is running.')
        else:
            record(home,'installer','activate','ok')
            print('Activated in the running Herdr app.')
    else:
        print('Select herdr-mod-kit in Herdr Settings > Look, or cycle layouts with Ctrl+Shift+L.')


def print_recent(log):
    if not log.is_file():
        return
    for line in log.read_text(encoding='utf8').splitlines()[-5:]:
        try:
            row=json.loads(line)
            print(f'  {row["utc"]} {row["stage"]} {row["code"]}')
        except (ValueError,KeyError):
            pass


def diagnose(options, home, app):
    state_file=home/'data'/'herdr-mod-kit'/'install.json'
    state=read_json(state_file) if state_file.is_file() else {}
    active=state.get('features',[])
    chosen=options.features if options.features is not None else FEATURES
    old_upstream=state.get('upstream',{})
    current_upstream=upstream(home)
    current_version=version(app,home) if app else None
    log_dir=home/'data'/'herdr-mod-kit'/'logs'
    print(f'Kit {VERSION} | Herdr {current_version or "not found"} | Installed with {state.get("app_version","not installed")}')
    print('Logs:', log_dir)
    if options.features is None:
        print('[installer]')
        print_recent(log_dir/'installer.jsonl')
    failed=False
    if active and state.get('version')==VERSION:
        ok,code=native_check(app,home,home/'mods'/VERSION_MOD,options.verbose) if app else (False,'app_missing')
        for name in ('mod.json','main.js'):
            key=f'mods/{VERSION_MOD}/{name}'
            expected=state.get('files',{}).get(key)
            if not expected or hash_file(home/key)!=expected:
                ok,code=False,'file_changed_or_missing'
        print(f'[installer] {VERSION_MOD}={code}')
        failed=not ok
    for feature in chosen:
        mod=MODS[feature]
        if feature not in active:
            print(f'[{feature}] disabled or not installed')
            print_recent(log_dir/f'{feature}.jsonl')
            continue
        checks=[('herdr_version_changed',bool(current_version and current_version!=state.get('app_version')))]
        comparisons=['layout/main.json']
        if feature in ('pdf','transfer'):
            comparisons.append('mods/files/main.js')
        if feature=='pdf' and 'mods/tabs/main.js' in old_upstream:
            comparisons.append('mods/tabs/main.js')
        if feature=='tabs':
            comparisons.extend(['mods/files/main.js','mods/pane/main.js'])
        for item in comparisons:
            checks.append((f'upstream_changed:{item}',current_upstream.get(item)!=old_upstream.get(item)))
        deps=NATIVE_DEPS[feature]
        if feature=='pdf' and state.get('version') in ('1.0.0','1.1.0'):
            deps=(MODS['transfer'],mod) if state['version']=='1.0.0' else (MODS['transfer'],mod,TABS_MOD)
        relevant={key:value for key,value in state.get('files',{}).items() if any(key.startswith(f'mods/{name}/') for name in deps)}
        is_current=state.get('version')!='1.0.0'
        if is_current:
            for name in deps:
                for legacy in ('runtime.json','kit_log.py','bridge.py'):
                    relevant.pop(f'mods/{name}/{legacy}',None)
            for name in helper_files((feature,)):
                key=(HELPERS/name).as_posix()
                relevant[key]=state.get('files',{}).get(key)
        issues=[key for key,value in relevant.items() if hash_file(home/key)!=value]
        layout_key=f'layouts/{LAYOUT}.json'
        if hash_file(home/layout_key)!=state.get('files',{}).get(layout_key):
            issues.append(layout_key)
        runtime_mod=MODS['usage'] if feature=='usage' else MODS['transfer']
        runtime_path=home/HELPERS/'runtime.json' if is_current else home/'mods'/runtime_mod/'runtime.json'
        try:
            runtime=read_json(runtime_path) if runtime_path.is_file() else {}
        except (ValueError,OSError):
            runtime={}
        python_ok=bool(runtime.get('python') and Path(runtime['python']).is_file())
        needs_core=feature in ('transfer','pdf')
        core_ok=bool(runtime.get('hc') and Path(runtime['hc']).is_file()) if needs_core else True
        native=[]
        for name in sorted(deps):
            ok,code=native_check(app,home,home/'mods'/name,options.verbose) if app else (False,'app_missing')
            native.append(f'{name}={code}')
            if not ok:failed=True
        renderer_ok=python_ok and renderer_check(home/'mods'/mod,runtime['python']) if feature=='pdf' else True
        if issues or not python_ok or not core_ok or not renderer_ok:failed=True
        print(f'[{feature}] native {", ".join(native)} | Python={"ok" if python_ok else "missing"}'
              + (f' | core={"ok" if core_ok else "missing"}' if needs_core else '')
              + (f' | renderer={"ok" if renderer_ok else "failed"}' if feature=='pdf' else ''))
        if feature=='tabs':
            key_path=home/'keys.json'
            key_code=shortcut_status(read_keys(key_path)) if key_path.is_file() else 'missing'
            print(f'  Ctrl+W={key_code}')
            record(home,'tabs','diagnose_shortcut',key_code)
        for check,changed in checks:
            if changed:print(f'  NOTICE {check}')
        for issue in issues:print(f'  CHECK installed file changed or missing: {issue}')
        record(home,feature,'diagnose','attention' if issues or not python_ok or not core_ok or not renderer_ok or any(not message.endswith('=ok') for message in native) else 'ok')
        print_recent(log_dir/f'{feature}.jsonl')
    return int(failed)


def parse_features(value):
    names=() if value.lower()=='none' else tuple(dict.fromkeys(item.strip().lower() for item in value.split(',')))
    if any(name not in FEATURES for name in names):
        raise argparse.ArgumentTypeError('Expected usage, transfer, pdf, tabs, or none')
    return names


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subcommands=parser.add_subparsers(dest='action',required=True)
    for name in ('install','diagnose'):
        sub=subcommands.add_parser(name)
        sub.add_argument('--app-home',default=os.environ.get('HERDR_APP_HOME') or str(Path.home()/'.config'/'herdr-app'))
        sub.add_argument('--herdr-app',help='Override the Herdr desktop executable path')
        sub.add_argument('--hc',help='Override the herdr-core executable path')
        sub.add_argument('--features',type=parse_features,help='Default: previously enabled features, or all on first install')
    subcommands.choices['install'].add_argument('--usage-machine',help='Herdr Machines name or local; keep existing selection on upgrade')
    subcommands.choices['install'].add_argument('--activate',action='store_true')
    subcommands.choices['diagnose'].add_argument('--verbose',action='store_true',help='Show full local native-check errors, including any paths')
    options=parser.parse_args()
    if sys.platform!='win32' or platform.machine().lower() not in ('amd64','x86_64'):
        parser.exit(2,'This release is tested for Windows x64. macOS validation is pending.\n')
    app_home=Path(options.app_home).expanduser().resolve()
    try:
        app=find_program(options.herdr_app,'herdr-app','herdr-app')
        core=find_program(options.hc,'hc','herdr-core')
        if options.action=='diagnose':
            return diagnose(options,app_home,app)
        if not app:
            raise KitError('herdr_app_missing: install Herdr desktop or supply --herdr-app')
        if options.usage_machine is not None and not options.usage_machine.strip():
            raise KitError('usage_machine_empty: use a Herdr machine name or local')
        install(options,app_home,app,core)
        return 0
    except (KitError,OSError,ValueError,subprocess.SubprocessError) as error:
        code=str(error).split(':',1)[0] if isinstance(error,KitError) else type(error).__name__
        if app_home.is_dir():record(app_home,'installer',options.action,code)
        print(f'Herdr Mod Kit: {error}',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
