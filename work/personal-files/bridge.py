"""Personal Files helper. Paths are argv/JSON, never interpolated shell code."""
import json
import os
import sys

def quick_revision(argv):
    """Answer a viewer's change poll for a file on this computer.

    Every open document asks every few seconds, so this runs before the heavier imports below.
    Anything unusual returns None and takes the ordinary path, which reports the error."""
    try:
        q=json.loads(argv[argv.index('--request')+1])
        job=q.get('job')
        if q.get('action')!='revision' or q.get('on'):return None
        if not isinstance(job,str) or len(job)!=32 or job.strip('0123456789abcdef'):return None
        s=os.stat(q['source'])
        return json.dumps({'ok':True,'revision':[str(s.st_size),str(s.st_mtime_ns),str(s.st_ino)]})
    except (ValueError,IndexError,KeyError,TypeError,AttributeError,OSError):
        return None

if __name__=='__main__':
    quick=quick_revision(sys.argv)
    if quick is not None:
        print(quick)
        sys.exit(0)

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import hashlib
from itertools import count
from html import escape
from html.parser import HTMLParser
import math
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time
import uuid
import zlib
import ctypes

import file_host
from file_host import CHUNK, WINDOWS_INVALID_LEAF
PAGE_CACHE_BYTES = 256 * 1024**2
PDF_CACHE_BYTES = 512 * 1024**2
LEGACY_CHUNK = 180 * 1024
# Bytes per call and calls in flight, tried in order. The later steps are the transports of earlier releases.
CHUNK_STEPS = ((CHUNK, 4), (1024 * 1024, 1), (LEGACY_CHUNK, 1))
HASH_LIMIT = 64 * 1024**2
# The app ends a helper after ten minutes. A transfer hands back well before that and continues in the next
# run. Whole-file verification can itself take minutes, so it only starts early in a run.
SLICE_SECONDS = 180
FINISH_WITHIN_SECONDS = 60
SLOW_CALL_SECONDS = 300
MAX_BATCH_CHARS = 120000

class HtmlPreview(HTMLParser):
    """Emit only native rich-text elements. Never pass source attributes to the viewer."""
    tags = set('p div blockquote pre code strong b em i u s del sub sup ul ol li h1 h2 h3 h4 h5 h6 table thead tbody tfoot tr th td'.split())
    hidden = set('head title script style template iframe object svg math noscript'.split())

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.open_tags = []
        self.skip = []
        self.elements = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'body' and self.skip == ['head']:
            self.skip.clear()
        if tag in self.hidden:
            self.skip.append(tag)
        if self.skip:
            return
        self.elements += 1
        if self.elements > 3000 or len(self.open_tags) >= 64:
            raise self.LimitReached
        if tag in self.tags:
            self.parts.append(f'<{tag}>')
            self.open_tags.append(tag)
        elif tag in ('br', 'hr'):
            self.parts.append(f'<{tag}>')
        elif tag == 'img':
            self.handle_data(dict(attrs).get('alt') or '')

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
        elif tag in self.open_tags:
            while self.open_tags:
                opened = self.open_tags.pop()
                self.parts.append(f'</{opened}>')
                if opened == tag:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(escape(data, quote=False))

    class LimitReached(Exception):
        pass

    @classmethod
    def render(cls, source):
        parser = cls()
        limited = len(source) > 100000
        try:
            parser.feed(source[:100000])
            parser.close()
        except cls.LimitReached:
            limited = True
        parser.parts.extend(f'</{tag}>' for tag in reversed(parser.open_tags))
        if limited:
            parser.parts.append('<p>Preview limit reached. Select Source to keep reading.</p>')
        return ''.join(parser.parts)


class Failure(Exception):
    def __init__(self, code, message, resume=None):
        super().__init__(message)
        self.code = code
        self.resume = resume

class Control:
    """Lets one transfer span several helper runs, and stop when its dialog asks."""
    def __init__(self, cancel_file=None, seconds=None):
        self.cancel_file=cancel_file
        self.started=time.monotonic()
        self.deadline=self.started+seconds if seconds else None
    def check(self):
        if self.cancel_file is not None and os.path.exists(self.cancel_file):
            raise Failure('cancelled','Transfer cancelled.')
    def due(self):
        return self.deadline is not None and time.monotonic()>=self.deadline
    def fresh(self):
        return self.deadline is None or time.monotonic()-self.started<FINISH_WITHIN_SECONDS

# The same packaged file handles local requests and executes on the chosen Herdr machine.
REMOTE = file_host.host_program(Path(file_host.__file__).read_text(encoding='utf8'))

class RemoteClient:
    def __init__(self, on, hc): self.on, self.hc = on, hc
    def request(self, action, **args):
        request={'action':action,**args}
        if self.on:
            # Whole-file hashes can take longer than a chunk.
            seconds=SLOW_CALL_SECONDS if action in ('stat','digest','finish') else 60
            # -I: the host's home folder is the working directory there, and must not supply modules.
            command=[self.hc,'exec','--timeout',str(seconds),'--on',self.on,'-i','python3','-I','-c',REMOTE]
            try:
                result=subprocess.run(command,input=json.dumps(request).encode(),capture_output=True,timeout=seconds+15,
                                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except subprocess.TimeoutExpired:
                raise Failure('connection','The file host did not answer in time. Check its Herdr connection.')
            if result.returncode:
                raise Failure('connection','Cannot reach the file host. Check its Herdr connection.')
            try:value=json.loads(result.stdout)
            except ValueError:raise Failure('connection','Invalid response from the file host.')
        else:
            value=file_host.reply(request)
        if not value.get('ok'): raise Failure(value.get('code','transfer'), value.get('error','Transfer failed'))
        return value

def safe_leaf(name):
    if not isinstance(name,str) or re.search(WINDOWS_INVALID_LEAF,name):
        raise Failure('name', 'This filename cannot be saved on Windows. Rename it on the server first.')
    return name

def file_revision(path):
    s=path.stat();return (s.st_size,s.st_mtime_ns,s.st_ino)

def mark_download(path):
    try:
        with open(str(path)+':Zone.Identifier','w',encoding='ascii') as zone:
            zone.write('[ZoneTransfer]\nZoneId=3\n')
        return True
    except OSError:
        return False  # Some destination filesystems do not support Windows security zones.

def open_download(result):
    path=Path(result['path'])
    if path.suffix.lower() in {'.pdf','.txt','.log','.png','.jpg','.jpeg','.gif','.bmp'} and result.get('zone_marked',True):
        os.startfile(str(path))
    else:
        result['message']='Saved. Open this file manually from its destination.'

def discard(client, state):
    """Remove the staging file of a transfer that will not continue."""
    if isinstance(state,dict) and state.get('kind')=='zip':
        discard(client,state.get('transfer'))
        if state.get('token'):
            with suppress(Exception):client.request('archive-drop',token=state['token'])
        return
    if not isinstance(state,dict) or not isinstance(state.get('part'),str):return
    if state.get('kind')=='upload' and getattr(client,'on',None):
        with suppress(Exception):client.request('abort',path=state['part'])
        return
    part=Path(state['part'])
    if part.name.startswith(('.herdr-upload-','.herdr-download-')) and part.name.endswith('.part') and not part.is_symlink():
        with suppress(OSError):part.unlink(missing_ok=True)

def upload(client, source, target_dir, overwrite=False, progress=None, control=None, resume=None):
    control=control or Control()
    source=Path(source)
    if not source.is_file(): raise Failure('folder','Drop individual files, not folders.')
    name=safe_leaf(source.name)
    target=target_dir.rstrip('/\\')+'/'+name
    before=file_revision(source)
    if resume and tuple(resume.get('revision',()))!=before:
        discard(client,resume)
        raise Failure('changed','The local source changed. Retry the upload.')
    step=resume['step'] if resume else 0
    while True:
        try:
            return upload_stage(client,source,target,overwrite,progress,control,before,step,resume)
        except Failure as error:
            if error.code!='large_chunk':raise
        step+=1;resume=None

def upload_stage(client, source, target, overwrite, progress, control, before, step, state):
    size,workers=CHUNK_STEPS[step]
    # Several chunks in flight are written at their offsets. One at a time keeps the earlier append protocol.
    positional=workers>1
    if state:
        part,identity,offset=state['part'],state['identity'],state['offset']
    else:
        started=client.request('begin',path=target,overwrite=overwrite)
        part,identity,offset=started['part'],started['identity'],0
    first=offset
    total=before[0]
    digest=None if offset else hashlib.sha256()
    position=offset
    flights=[]
    def settle(limit):
        nonlocal offset,identity
        while len(flights)>limit:
            future,end=flights.pop(0)
            written=future.result()
            if not positional:identity=written['identity']
            offset=end
            if progress:progress(offset,total)
    try:
        with source.open('rb') as stream, ThreadPoolExecutor(workers) as pool:
            stream.seek(offset)
            try:
                while not control.due():
                    control.check()
                    data=stream.read(size)
                    if not data:break
                    if digest:digest.update(data)
                    fields=dict(path=part,offset=position,data=base64.b64encode(data).decode(),identity=identity)
                    position+=len(data)
                    flights.append((pool.submit(client.request,'write_at' if positional else 'write',**fields),position))
                    settle(workers-1)
                settle(0)
            finally:
                for future,_ in flights:future.cancel()
        if (position<total and control.due()) or not control.fresh():
            return {'partial':True,'resume':{'kind':'upload','part':part,'identity':identity,'offset':offset,
                                             'step':step,'revision':list(before)}}
        if before!=file_revision(source): raise Failure('changed','The local source changed. Retry the upload.')
        sha=digest.hexdigest() if digest else file_digest(source)
        if before!=file_revision(source): raise Failure('changed','The local source changed. Retry the upload.')
        return client.request('finish',path=target,part=part,overwrite=overwrite,size=position,sha256=sha,
                              identity=identity[:2] if positional else identity)
    except Failure as error:
        if error.code=='connection' and positional and offset:
            # The link has carried chunks of this size, so this is an interruption: a retry continues from here.
            raise Failure('connection',str(error),{'kind':'upload','part':part,'identity':identity,'offset':offset,
                                                   'step':step,'revision':list(before)}) from error
        with suppress(Exception):client.request('abort',path=part)
        if error.code=='connection' and offset==first and step+1<len(CHUNK_STEPS):
            # Nothing of this size arrived: the transport may not carry it.
            raise Failure('large_chunk','Retry with a smaller transfer size') from error
        raise
    except BaseException:
        with suppress(Exception):client.request('abort',path=part)
        raise

def resumed_part(directory, state, prefix):
    part=Path(state['part']);offset=state['offset']
    usable=(part.parent.resolve()==Path(directory).resolve() and part.name.startswith(prefix) and part.name.endswith('.part')
            and not part.is_symlink() and part.is_file() and isinstance(offset,int) and 0<=offset<=part.stat().st_size)
    if not usable:raise Failure('transfer','This transfer can no longer continue. Start it again.')
    return part,offset

def publish_download(part, target, overwrite, private=False, keep_both=False):
    if os.name!='nt' and not private:os.chmod(part,file_host.publish_mode(target,overwrite))
    if keep_both:
        for number in count(1):
            candidate = target.with_name(f'{target.stem} ({number}){target.suffix}')
            if os.path.lexists(candidate):
                continue
            try:
                file_host.publish_new_file(part,candidate)
                return candidate
            except FileExistsError:
                continue  # Another download claimed this name after the check.
    if overwrite:os.replace(part,target)
    else:
        try:file_host.publish_new_file(Path(part),target)
        except FileExistsError:raise Failure('exists','A file with this name already exists. Replace it?')
    return target

def download(client, source, target_dir, overwrite=False, progress=None, filename=None, info=None, control=None, resume=None, private=False, keep_both=False):
    control=control or Control()
    remote=bool(getattr(client,'on',None))
    leaf=source.rsplit('/',1)[-1] if remote else Path(source).name
    name=safe_leaf(filename or leaf)
    directory=Path(target_dir);directory.mkdir(parents=True,exist_ok=True)
    target=directory/name
    if os.path.lexists(target) and not overwrite and not keep_both: raise Failure('exists','A file with this name already exists. Replace it?',resume)
    if resume:
        part,offset=resumed_part(directory,resume,'.herdr-download-')
        info,step=resume['info'],resume['step']
    else:
        info=info or client.request('stat',path=source,hash_limit=HASH_LIMIT)
        file_host.sweep_stale(directory)
        fd,name_part=tempfile.mkstemp(prefix='.herdr-download-',suffix='.part',dir=directory);os.close(fd)
        part,offset,step=Path(name_part),0,0
    total=info['size']
    digest=None if offset else hashlib.sha256()
    proven=step   # the last step that delivered data, so a retry does not stay on a smaller size it fell back to
    def state():
        return {'kind':'download','part':str(part),'offset':offset,'step':proven,'info':info,
                'directory':str(directory),'filename':name}
    def read(start,length):
        result=client.request('read',path=source,offset=start,length=length,revision=info['revision'])
        block=base64.b64decode(result['data'],validate=True)
        if len(block)!=length:raise Failure('transfer','Incomplete download; retry.')
        return block
    keep=False
    try:
        with part.open('r+b') as stream, ThreadPoolExecutor(max(workers for _,workers in CHUNK_STEPS)) as pool:
            stream.truncate(offset);stream.seek(offset)
            flights=[];position=offset;received=False
            try:
                while offset<total:
                    size,workers=CHUNK_STEPS[step]
                    try:
                        # Ranges are requested side by side and written in order.
                        while position<total and len(flights)<workers and not control.due():
                            control.check()
                            length=min(size,total-position)
                            flights.append((pool.submit(read,position,length),length));position+=length
                        if not flights:break
                        future,length=flights.pop(0)
                        block=future.result()
                    except Failure as error:
                        for future,_ in flights:future.cancel()
                        flights=[];position=offset
                        if error.code!='connection':raise
                        if received or step+1>=len(CHUNK_STEPS):
                            if not offset:raise
                            keep=True
                            raise Failure('connection',str(error),state()) from error
                        step+=1;received=False
                        continue
                    stream.write(block);offset+=length;received=True;proven=step
                    if digest:digest.update(block)
                    if progress:progress(offset,total)
            finally:
                for future,_ in flights:future.cancel()
        if offset<total or not control.fresh():
            keep=True
            return {'partial':True,'resume':state()}
        expected=info.get('sha256') or client.request('digest',path=source,revision=info['revision'])['sha256']
        actual=digest.hexdigest() if digest else file_digest(part)
        if actual!=expected:raise Failure('hash','Download verification failed; retry.')
        marked=mark_download(part) if os.name=='nt' and remote else True
        control.check()
        target=publish_download(part,target,overwrite,private,keep_both)
        return {'path':str(target),'size':offset,'sha256':actual,'zone_marked':marked}
    finally:
        if not keep:
            with suppress(OSError):part.unlink(missing_ok=True)

def local_copy(source, target, overwrite, prefix, progress, control, resume, keep_both=False):
    """Copy between folders of this computer in one pass, without the chunk protocol used for other machines."""
    control=control or Control()
    before=file_revision(source)
    if resume:
        if tuple(resume.get('revision',()))!=before:
            discard(None,resume)
            raise Failure('changed','The source changed. Retry.')
        part,offset=resumed_part(target.parent,resume,prefix)
    else:
        file_host.sweep_stale(target.parent)
        fd,name=tempfile.mkstemp(prefix=prefix,suffix='.part',dir=target.parent);os.close(fd)
        part,offset=Path(name),0
    digest=None if offset else hashlib.sha256()
    keep=False
    try:
        with source.open('rb') as original, part.open('r+b') as stream:
            original.seek(offset);stream.truncate(offset);stream.seek(offset)
            while not control.due():
                control.check()
                block=original.read(CHUNK)
                if not block:break
                stream.write(block);offset+=len(block)
                if digest:digest.update(block)
                if progress:progress(offset,before[0])
        if (offset<before[0] and control.due()) or (digest is None and not control.fresh()):
            keep=True
            return {'partial':True,'resume':{'kind':'copy','part':str(part),'offset':offset,'revision':list(before),
                                             'directory':str(target.parent),'filename':target.name}}
        if before!=file_revision(source) or offset!=before[0]:raise Failure('changed','The source changed. Retry.')
        sha=digest.hexdigest() if digest else file_digest(part)
        control.check()
        target=publish_download(part,target,overwrite,keep_both=keep_both)
        return {'path':str(target),'size':offset,'sha256':sha}
    finally:
        if not keep:
            with suppress(OSError):part.unlink(missing_ok=True)

def local_upload(source, target_dir, overwrite=False, progress=None, control=None, resume=None):
    source=Path(source)
    if not source.is_file(): raise Failure('folder','Drop individual files, not folders.')
    directory=Path(target_dir)
    if not directory.is_dir(): raise Failure('transfer','Upload folder no longer exists')
    target=directory/safe_leaf(source.name)
    if os.path.lexists(target) and not overwrite: raise Failure('exists','A file with this name already exists. Replace it?',resume)
    return local_copy(source,target,overwrite,'.herdr-upload-',progress,control,resume)

def local_download(source, target_dir, overwrite=False, progress=None, filename=None, control=None, resume=None, keep_both=False):
    source=Path(source)
    if not source.is_file(): raise Failure('transfer','Select an individual file')
    directory=Path(target_dir);directory.mkdir(parents=True,exist_ok=True)
    target=directory/safe_leaf(filename or source.name)
    if os.path.lexists(target) and not overwrite and not keep_both: raise Failure('exists','A file with this name already exists. Replace it?',resume)
    return {**local_copy(source,target,overwrite,'.herdr-download-',progress,control,resume,keep_both),'zone_marked':True}

def downloads_folder():
    if os.name=='nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
            return os.path.expandvars(winreg.QueryValueEx(key,'{374DE290-123F-4565-9164-39C4925E467B}')[0])
    return str(Path.home()/'Downloads')

def choose_download_path(name, zip_archive=False, control=None):
    if os.name!='nt':
        raise Failure('dialog','The download location picker requires the Windows desktop.')
    try:
        suggested=safe_leaf(name)
    except Failure:
        suggested='download'
    # The dialog runs on the desktop host. Pass user paths as UTF-8 JSON on stdin.
    script=r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$options = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
$dialog = [Windows.Forms.SaveFileDialog]::new()
try {
    $dialog.Title = 'Download as'
    $dialog.FileName = $options.name
    $dialog.InitialDirectory = $options.directory
    $dialog.Filter = 'All files (*.*)|*.*'
    $dialog.AddExtension = $false
    if ($options.zip) {
        $dialog.Filter = 'ZIP archive (*.zip)|*.zip'
        $dialog.DefaultExt = 'zip'
        $dialog.AddExtension = $true
    }
    $dialog.OverwritePrompt = $false
    if ($dialog.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) {
        [Console]::Write($dialog.FileName)
    }
} finally { $dialog.Dispose() }
'''
    control = control or Control()
    control.check()
    options = json.dumps(dict(name=suggested,directory=downloads_folder(),zip=zip_archive))
    # Each picker owns a dedicated PowerShell process. Only stop this job's picker.
    with subprocess.Popen(
        [str(Path(os.environ['SystemRoot'])/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'),
         '-NoProfile','-NonInteractive','-STA','-Command',script],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW,
    ) as picker:
        try:
            while True:
                control.check()
                try:
                    selected,_ = picker.communicate(options,timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    options = None
            control.check()
        finally:
            if picker.poll() is None:
                picker.kill()
                picker.communicate()
        if picker.returncode:
            raise Failure('dialog','Could not open the Windows download location picker.')
    return Path(selected) if selected else None

def fetch(client, source, directory, **options):
    if client.on:return download(client,source,directory,**options)
    return local_download(source,directory,**options)

def download_file(client, request, progress, control, resume):
    source=request['source']
    leaf=source.rsplit('/',1)[-1] if client.on else Path(source).name
    control.check()
    if resume:
        target=Path(resume['directory'])/safe_leaf(resume['filename'])
    elif request.get('choose'):
        target=choose_download_path(leaf,control=control)
        if target is None:return {'cancelled':True}
    else:
        target=Path(request.get('directory') or downloads_folder())/safe_leaf(leaf)
    if target.is_dir():raise Failure('folder','Choose a file as the download destination.')
    # A decision about one chosen path must never follow a new Save As selection.
    confirmed = bool(resume) or not request.get('choose')
    previous = resume or {}
    overwrite = confirmed and request.get('overwrite', previous.get('overwrite')) is True
    keep_both = confirmed and request.get('keep_both', previous.get('keep_both')) is True
    transfer = resume if resume and resume.get('part') else None
    try:
        result=fetch(client,source,target.parent,filename=target.name,overwrite=overwrite,
                     keep_both=keep_both,progress=progress,control=control,resume=transfer)
        if result.get('partial'):
            result['resume'].update(overwrite=overwrite,keep_both=keep_both)
        return result
    except Failure as error:
        if error.code!='exists':
            if error.resume:error.resume.update(overwrite=overwrite,keep_both=keep_both)
            raise
        destination = error.resume or {'kind':'destination','directory':str(target.parent),'filename':target.name}
        raise Failure('exists',f'Replace the existing file at {target}?',destination) from error

def download_zip(client, source, progress, control, resume=None, overwrite=False, keep_both=False):
    if resume:
        if resume.get('kind')!='zip':raise Failure('transfer','Invalid ZIP job.')
        state=dict(resume)
        target=Path(state['directory'])/safe_leaf(state['filename'])
        if overwrite:state['overwrite']=True
        if keep_both:state['keep_both']=True
    else:
        leaf=re.split(r'[/\\]',source.rstrip('/\\'))[-1] if client.on else Path(source).name
        suggestion=(leaf or 'folder')+'.zip'
        target=choose_download_path('folder.zip' if re.search(WINDOWS_INVALID_LEAF,suggestion) else suggestion,zip_archive=True,control=control)
        if target is None:return {'cancelled':True}
        if not target.suffix:target=target.with_name(target.name+'.zip')
        safe_leaf(target.name)
        state={'kind':'zip','directory':str(target.parent),'filename':target.name}
    overwrite=state.get('overwrite') is True
    keep_both=state.get('keep_both') is True
    keep=False
    try:
        control.check()
        if target.is_dir():raise Failure('folder','Choose a file as the ZIP destination.')
        if os.path.lexists(target) and not overwrite and not keep_both:
            raise Failure('exists','The ZIP destination already exists.')
        if not state.get('started'):
            token=state.setdefault('token',uuid.uuid4().hex)
            exclude='' if client.on else str(target.parent.resolve()/target.name)
            client.request('archive-start',path=source,token=token,exclude=exclude)
            state['started']=True
            progress(0,0,'archive')
        while True:
            control.check()
            if control.due():
                keep=True
                return {'partial':True,'resume':state}
            status=client.request('archive-next',token=state['token'])
            if status.get('ready'):break
            progress(status['done'],0,'archive')
        control.check()
        options=dict(overwrite=overwrite,keep_both=keep_both,progress=lambda done,total:progress(done,total,'download'),
                     control=control,resume=state.get('transfer'),filename=target.name)
        result=fetch(client,status['path'],target.parent,**options)
        if result.get('partial'):
            keep=True
            state['transfer']=result['resume']
            return {'partial':True,'resume':state}
        return result
    except Failure as error:
        if error.code in ('exists','connection'):
            keep=True
            if error.resume:state['transfer']=error.resume
            # fetch may already have removed a part which failed its final no-replace publish.
            elif state.get('transfer') and not Path(state['transfer']['part']).exists():
                state.pop('transfer')
            message=f'Replace the existing file at {target}?' if error.code=='exists' else str(error)
            raise Failure(error.code,message,state) from error
        raise
    finally:
        if not keep:discard(client,state)

def write_png(bitmap, stream):
    def chunk(kind,data):
        stream.write(struct.pack('>I',len(data))+kind)
        stream.write(data)
        stream.write(struct.pack('>I',zlib.crc32(data,zlib.crc32(kind))&0xffffffff))
    data=memoryview(bitmap.buffer).cast('B')
    compressor=zlib.compressobj(1)
    stream.write(b'\x89PNG\r\n\x1a\n')
    chunk(b'IHDR',struct.pack('>IIBBBBB',bitmap.width,bitmap.height,8,6,0,0,0))
    for y in range(bitmap.height):
        start=y*bitmap.stride
        block=compressor.compress(b'\0'+data[start:start+bitmap.width*4])
        if block:chunk(b'IDAT',block)
    chunk(b'IDAT',compressor.flush())
    chunk(b'IEND',b'')

def file_digest(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()

def prune_cache(directory, pattern, budget, keep):
    # Keep recently used assets available to open tabs. Limit directory scans to once per minute.
    now=time.time()
    marker=directory/'.last-cleanup'
    try:
        if marker.exists() and now-marker.stat().st_mtime<60:return
        marker.touch()
        entries=[]
        for entry in directory.iterdir():
            if entry.name.endswith('.part') and not entry.is_symlink():
                # Left by a helper that was ended while writing.
                with suppress(OSError):
                    if now-entry.stat().st_mtime>3600:entry.unlink()
            elif re.fullmatch(pattern,entry.name) and not entry.is_symlink():
                with suppress(OSError):
                    info=entry.stat()
                    entries.append((max(info.st_atime,info.st_mtime),entry,info.st_size))
        total=sum(size for _,_,size in entries)
        for used,entry,size in sorted(entries):
            if now-used<600 or (total<=budget and now-used<7*86400):break
            if entry!=keep:
                with suppress(OSError):
                    entry.unlink()
                    total-=size
    except OSError:
        pass

def mark_used(path):
    info=path.stat()
    os.utime(path,ns=(time.time_ns(),info.st_mtime_ns))

def render_image(source, cache):
    source=Path(source)
    stamp=file_revision(source)
    if stamp[0]>128*1024**2:raise Failure('size','Image preview supports files up to 128 MiB.')
    with source.open('rb') as stream:signature=stream.read(8)
    is_png=signature==b'\x89PNG\r\n\x1a\n'
    if not is_png and not signature.startswith(b'\xff\xd8\xff'):raise Failure('image','Expected a PNG or JPEG image.')
    identity=hashlib.sha256((str(source)+str(stamp)).encode()).hexdigest()
    cache.mkdir(parents=True,exist_ok=True)
    target=cache/(identity+'.png')
    if not target.exists():
        # WIC runs on the Windows desktop. Never give it a URL or an executable document.
        script=r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
$q=[Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName PresentationCore
$inputFile=[IO.File]::OpenRead($q.source)
try {
    $decoder=if ($q.png) {
        [Windows.Media.Imaging.PngBitmapDecoder]::new($inputFile,'DelayCreation','None')
    } else {
        [Windows.Media.Imaging.JpegBitmapDecoder]::new($inputFile,'DelayCreation','None')
    }
    $frame=$decoder.Frames[0]
    $w=$frame.PixelWidth
    $h=$frame.PixelHeight
    if ($w -lt 1 -or $h -lt 1 -or [long]$w*$h -gt 100000000) {throw 'dimensions'}
    $orientation=1
    if (!$q.png) {try {$orientation=[int]$frame.Metadata.GetQuery('/app1/ifd/{ushort=274}')} catch {}}
    $inputFile.Position=0
    $bitmap=[Windows.Media.Imaging.BitmapImage]::new()
    $bitmap.BeginInit()
    $bitmap.CacheOption='OnLoad'
    $bitmap.CreateOptions='IgnoreColorProfile'
    $bitmap.StreamSource=$inputFile
    if ($w -ge $h) {$bitmap.DecodePixelWidth=[Math]::Min(2560,$w)}
    else {$bitmap.DecodePixelHeight=[Math]::Min(2560,$h)}
    $bitmap.EndInit()
    $result=$bitmap
    if ($orientation -in 2..8) {
        $matrices=@('','', '-1,0,0,1,0,0','-1,0,0,-1,0,0','1,0,0,-1,0,0','0,1,1,0,0,0','0,1,-1,0,0,0','0,-1,-1,0,0,0','0,-1,1,0,0,0')
        $transform=[Windows.Media.MatrixTransform]::new([Windows.Media.Matrix]::Parse($matrices[$orientation]))
        $result=[Windows.Media.Imaging.TransformedBitmap]::new($bitmap,$transform)
    }
    $encoder=[Windows.Media.Imaging.PngBitmapEncoder]::new()
    $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($result))
    $outputFile=[IO.File]::Open($q.target,[IO.FileMode]::CreateNew)
    try {$encoder.Save($outputFile)} finally {$outputFile.Dispose()}
} finally {$inputFile.Dispose()}
'''
        temp=target.with_name(target.name+'.'+uuid.uuid4().hex+'.part')
        try:
            shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
            proc=subprocess.run([str(shell),'-NoProfile','-NonInteractive','-STA','-Command',script],
                                input=json.dumps(dict(source=str(source),target=str(temp),png=is_png)).encode(),
                                capture_output=True,timeout=35,creationflags=subprocess.CREATE_NO_WINDOW)
            if proc.returncode:raise Failure('image','Cannot decode image. Check the file and the 100-megapixel preview limit.')
            os.replace(temp,target)
        finally:temp.unlink(missing_ok=True)
    mark_used(target)
    prune_cache(cache,r'[a-f0-9]{64}\.png',PAGE_CACHE_BYTES,target)
    with target.open('rb') as stream:
        width,height=struct.unpack('>II',stream.read(24)[16:24])
    return dict(image=str(target),width=width,height=height)

def page_chars(pdfium, page):
    """Characters in reading order, each with its box as fractions of the page image (left, top, right, bottom)."""
    try:textpage=page.get_textpage()
    except pdfium.PdfiumError:return []
    try:
        raw=pdfium.raw;span=100000
        def device(x,y):
            dx=ctypes.c_int();dy=ctypes.c_int()
            if not raw.FPDF_PageToDevice(page.raw,0,0,span,span,0,x,y,ctypes.byref(dx),ctypes.byref(dy)):return None
            return dx.value/span,dy.value/span
        # The page-to-image mapping is affine and carries the page's rotation and crop, so three points give it
        # for every character on the page.
        origin,along,up=device(0,0),device(1000,0),device(0,1000)
        mapped=None not in (origin,along,up)
        if mapped:
            ox,oy=origin
            ax,ay,bx,by=(along[0]-ox)/1000,(along[1]-oy)/1000,(up[0]-ox)/1000,(up[1]-oy)/1000
        left=ctypes.c_double();right=ctypes.c_double();bottom=ctypes.c_double();top=ctypes.c_double()
        box=(ctypes.byref(left),ctypes.byref(right),ctypes.byref(bottom),ctypes.byref(top))
        handle=textpage.raw;unicode=raw.FPDFText_GetUnicode;charbox=raw.FPDFText_GetCharBox
        chars=[]
        for index in range(min(textpage.count_chars(),50000)):
            code=unicode(handle,index)
            text=chr(code) if 0<code<=0x10ffff and not 0xD800<=code<=0xDFFF else ''
            rect=None
            if mapped and text.strip() and charbox(handle,index,*box):
                x0=ax*left.value+bx*bottom.value+ox;x1=ax*right.value+bx*top.value+ox
                y0=ay*left.value+by*bottom.value+oy;y1=ay*right.value+by*top.value+oy
                rect=[round(max(0,min(1,v)),5) for v in (min(x0,x1),min(y0,y1),max(x0,x1),max(y0,y1))]
            chars.append({'t':text,'r':rect})
        return chars
    finally:textpage.close()

def render_pdf_pages(path, page_indexes, width, cache, include_sizes=False, include_chars=True):
    """Render several pages of one document in one run. `include_chars` may name a choice per page."""
    vendor=str(Path(__file__).parent/'vendor')
    if vendor not in sys.path:sys.path.insert(0,vendor)
    try:import pypdfium2 as pdfium
    except ImportError:raise Failure('renderer','PDF renderer is missing. Reinstall the personal-files helper.')
    max_edge=4096
    width=max(300,min(max_edge,int(width)))
    path=Path(path);stamp=file_revision(path)
    identity=hashlib.sha256((str(path)+str(stamp)).encode()).hexdigest()
    with pdfium.PdfDocument(str(path)) as pdf:
        count=len(pdf)
        if not count:raise Failure('pdf','This PDF has no pages.')
        value={'pages':count,'pdf':str(path),'rendered':[]}
        budget=MAX_BATCH_CHARS
        if not page_indexes:raise Failure('pdf','No page was requested.')
        for position,requested in enumerate(page_indexes):
            page_index=max(0,min(count-1,int(requested)))
            wanted=include_chars[position] if isinstance(include_chars,list) else include_chars
            page=pdf[page_index]
            try:
                pw,ph=page.get_size()
                scale=min(width/max(pw,1),max_edge/max(ph,1))
                pixel_width=max(1,math.ceil(pw*scale));pixel_height=max(1,math.ceil(ph*scale))
                result=Path(cache)/f'{identity}-{page_index}-{pixel_width}x{pixel_height}.png'
                result.parent.mkdir(parents=True,exist_ok=True)
                if not result.exists():
                    bitmap=page.render(scale=scale,rev_byteorder=True,force_bitmap_format=pdfium.raw.FPDFBitmap_BGRA)
                    try:
                        temp=result.with_name(result.name+'.'+uuid.uuid4().hex+'.part')
                        try:
                            with temp.open('xb') as stream:write_png(bitmap,stream)
                            os.replace(temp,result)
                        finally:temp.unlink(missing_ok=True)
                    finally:bitmap.close()
                mark_used(result)
                chars=page_chars(pdfium,page) if wanted else []
            finally:page.close()
            value['rendered'].append({'image':str(result),'page':page_index,'width':pixel_width,'height':pixel_height,'chars':chars})
            budget-=len(chars)
            # One reply stays well under the host's output limit. The viewer asks again for pages left out.
            if budget<=0:break
        prune_cache(result.parent,r'[a-f0-9]{64}-\d+-(?:\d+|\d+x\d+)\.png',PAGE_CACHE_BYTES,result)
        if include_sizes:
            value['sizes']=[list(pdf.get_page_size(i)) for i in range(count)]
        return value

def render_pdf(path, page_index, width, cache, include_sizes=False, include_chars=True):
    value=render_pdf_pages(path,[page_index],width,cache,include_sizes,include_chars)
    return {**value.pop('rendered')[0],**value}

def sweep_jobs(folder):
    # Progress snapshots and cancel requests of helpers that were ended before removing their own.
    limit=time.time()-86400
    with suppress(OSError):
        folder.mkdir(parents=True,exist_ok=True)
        for entry in folder.iterdir():
            with suppress(OSError):
                if not entry.is_symlink() and entry.is_file() and entry.stat().st_mtime<limit:entry.unlink()

def render_request(q, local, cache, home):
    def shown(item):
        item['image']=str(Path(item['image']).relative_to(home)).replace('\\','/')
    options=dict(include_sizes=q.get('sizes',False),include_chars=q.get('chars',True))
    pages=q.get('pages')
    if isinstance(pages,list) and pages:
        result=render_pdf_pages(local,pages[:6],q.get('width',1100),cache,**options)
        for page in result['rendered']:shown(page)
    else:
        result=render_pdf(local,q.get('page',0),q.get('width',1100),cache,**options)
        shown(result)
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--hc',required=True);parser.add_argument('--home',required=True);parser.add_argument('--request',required=True)
    args=parser.parse_args();q=json.loads(args.request)
    root=Path(args.home)/'data'/'personal-files'
    root.mkdir(parents=True,exist_ok=True)
    job=q.get('job','')
    if not re.fullmatch('[a-f0-9]{32}',job):raise Failure('job','Invalid file job')
    jobs=root/'jobs'
    progress_path=jobs/(job+'.json')
    progress_temp=progress_path.with_suffix('.tmp')
    cancel_file=jobs/(job+'.cancel')
    def progress(done,total,phase=None):
        # A Windows reader can briefly prevent replacing the progress snapshot.
        with suppress(OSError):
            progress_path.parent.mkdir(exist_ok=True)
            snapshot={'done':done,'total':total}
            if phase:snapshot['phase']=phase
            progress_temp.write_text(json.dumps(snapshot),encoding='utf8')
            os.replace(progress_temp,progress_path)
    client=RemoteClient(q.get('on'),args.hc)
    action=q['action']
    control=Control(cancel_file,SLICE_SECONDS)
    resume=q.get('resume')
    if isinstance(resume,str):resume=json.loads(resume)
    unfinished=False
    try:
        if action=='revision':
            result=client.request('revision',path=q['source']) if q.get('on') else {'revision':list(file_revision(Path(q['source'])))}
            result['revision']=[str(number) for number in result['revision']]
        elif action=='text':
            result=client.request('text',path=q['source'])
            if Path(q['source']).suffix.lower() in ('.htm', '.html') and result['text'] is not None:
                result['html'] = HtmlPreview.render(result['text'])
            rev=result['revision'] if q.get('on') else result['revision'][:3]
            result['revision']=[str(number) for number in rev]
        elif action=='upload':
            sweep_jobs(jobs)
            options=dict(overwrite=q.get('overwrite',False),progress=progress,control=control,resume=resume)
            if q.get('on'):result=upload(client,q['source'],q['directory'],**options)
            else:result=local_upload(q['source'],q['directory'],**options)
        elif action in ('new-file','new-folder'):result=client.request(action,path=q['directory'],name=q['name'])
        elif action in ('copy','move'):result=client.request(action,path=q['source'],directory=q['directory'])
        elif action=='rename':result=client.request(action,path=q['source'],name=q['name'])
        elif action=='delete':result=client.request(action,path=q['source'],confirmed=q.get('confirmed'))
        elif action=='download-zip':
            sweep_jobs(jobs)
            result=download_zip(client,q['source'],progress,control,resume,q.get('overwrite') is True,q.get('keep_both') is True)
        elif action=='download':
            sweep_jobs(jobs)
            result=download_file(client,q,progress,control,resume)
            if q.get('open') and not result.get('cancelled') and not result.get('partial'):open_download(result)
        elif action=='discard':
            discard(client,resume);result={}
        elif action in ('preview','image'):
            if q.get('on'):
                # The cached copy is named after the file's revision, so opening it again hashes neither side.
                info=client.request('stat',path=q['source'],hash_limit=0)
                limit=128*1024**2 if action=='image' else PDF_CACHE_BYTES
                if info['size']>limit:
                    raise Failure('size',f'Remote preview limit is {limit//1024**2} MiB. Download the file to open it locally.')
                identity=hashlib.sha256(json.dumps([q['on'],q['source'],info['revision']]).encode()).hexdigest()
                local=root/'image-sources'/(identity+'.img') if action=='image' else root/'pdf'/(identity+'.pdf')
                if not local.exists():
                    try:
                        # Verified against the host's hash before it takes its cache name.
                        download(client,q['source'],str(local.parent),progress=progress,filename=local.name,info=info,private=True)
                    except Failure as error:
                        if error.code!='exists':raise
                mark_used(local)
                prune_cache(local.parent,r'[a-f0-9]{64}\.(?:pdf|img)',PDF_CACHE_BYTES,local)
                revision=info['revision']
            else:
                local=Path(q['source'])
                revision=file_revision(local)
            if action=='image':
                result=render_image(local,root/'images')
                result['image']=str(Path(result['image']).relative_to(args.home)).replace('\\','/')
            else:
                result=render_request(q,local,root/'pages',args.home)
            if not q.get('on') and revision!=file_revision(local):raise Failure('changed','File changed while opening')
            result['revision']=[str(number) for number in revision]
        elif action=='render':
            local=Path(q['source']).resolve()
            allowed=(root/'pdf').resolve()
            if not local.is_relative_to(allowed):raise Failure('pdf','Invalid PDF cache path')
            if not local.is_file():raise Failure('cache_miss','Remote preview cache expired.')
            mark_used(local)
            result=render_request(q,local,root/'pages',args.home)
        elif action=='folder':
            folder=q.get('directory') or downloads_folder()
            if not os.path.isdir(folder):raise Failure('folder','This folder is not available.')
            os.startfile(folder);result={}
        else:raise Failure('action','Unknown Files action')
        unfinished=bool(result.get('partial'))
        # The UI echoes this state. Keep native file IDs and nanosecond timestamps out of JS numbers.
        if result.get('resume') is not None:
            result['resume']=json.dumps(result['resume'],separators=(',',':'))
    except Failure as error:
        if error.code == 'cancelled' and resume:
            discard(client,resume)
        raise
    finally:
        # A transfer that continues in the next run keeps its progress on screen.
        if not unfinished:
            for leftover in (progress_temp,progress_path,cancel_file):
                with suppress(OSError):
                    leftover.unlink(missing_ok=True)
    print(json.dumps({'ok':True,**result},ensure_ascii=False,separators=(',',':')))

if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'ok':False,'code':getattr(e,'code','error'),'error':str(e)[:300],
                          **({'resume':json.dumps(e.resume,separators=(',',':'))} if getattr(e,'resume',None) else {})},ensure_ascii=False))
