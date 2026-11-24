"""Personal Files helper. Paths are argv/JSON, never interpolated shell code."""
import argparse
import base64
from contextlib import suppress
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
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

class Failure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

# The same packaged file handles local requests and executes on the chosen Herdr machine.
REMOTE = Path(file_host.__file__).read_text(encoding='utf8')

class RemoteClient:
    def __init__(self, on, hc): self.on, self.hc = on, hc
    def request(self, action, **args):
        request={'action':action,**args}
        if self.on:
            command=[self.hc,'exec','--timeout','60','--on',self.on,'-i','python3','-c',REMOTE]
            result=subprocess.run(command,input=json.dumps(request).encode(),capture_output=True,timeout=75,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
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

def upload(client, source, target_dir, overwrite=False, progress=None):
    try:
        return upload_chunks(client,source,target_dir,overwrite,progress,CHUNK)
    except Failure as error:
        if error.code!='large_chunk':raise
    return upload_chunks(client,source,target_dir,overwrite,progress,LEGACY_CHUNK)

def upload_chunks(client, source, target_dir, overwrite, progress, chunk_size):
    source=Path(source)
    if not source.is_file(): raise Failure('folder','Drop individual files, not folders.')
    name=safe_leaf(source.name)
    target=target_dir.rstrip('/\\')+'/'+name
    before=file_revision(source)
    started=client.request('begin',path=target,overwrite=overwrite)
    part=started['part'];identity=started['identity']
    try:
        h=hashlib.sha256();offset=0
        with source.open('rb') as stream:
            while data:=stream.read(chunk_size):
                try:
                    written=client.request('write',path=part,offset=offset,data=base64.b64encode(data).decode(),identity=identity)
                except Failure as error:
                    if error.code=='connection' and len(data)>LEGACY_CHUNK:
                        raise Failure('large_chunk','Retry with a smaller transfer size') from error
                    raise
                identity=written['identity']
                offset+=len(data);h.update(data)
                if progress:progress(offset,before[0])
        if before!=file_revision(source): raise Failure('changed','The local source changed. Retry the upload.')
        return client.request('finish',path=target,part=part,overwrite=overwrite,size=offset,sha256=h.hexdigest(),identity=identity)
    except BaseException:
        try:client.request('abort',path=part)
        except Exception:pass
        raise

def download(client, source, target_dir, overwrite=False, progress=None, filename=None,info=None):
    leaf=Path(source).name if not getattr(client,'on',None) else source.rsplit('/',1)[-1]
    name=safe_leaf(filename or leaf)
    directory=Path(target_dir);directory.mkdir(parents=True,exist_ok=True)
    target=directory/name
    if os.path.lexists(target) and not overwrite: raise Failure('exists','A file with this name already exists. Replace it?')
    info=info or client.request('stat',path=source)
    fd,part=tempfile.mkstemp(prefix='.herdr-download-',suffix='.part',dir=directory)
    try:
        h=hashlib.sha256();offset=0
        chunk_size=CHUNK
        with os.fdopen(fd,'wb') as stream:
            while offset<info['size']:
                length=min(chunk_size,info['size']-offset)
                try:result=client.request('read',path=source,offset=offset,length=length,revision=info['revision'])
                except Failure as error:
                    if error.code!='connection' or length<=LEGACY_CHUNK:raise
                    chunk_size=LEGACY_CHUNK
                    continue
                block=base64.b64decode(result['data'],validate=True)
                if not block or len(block)>length:raise Failure('transfer','Incomplete download; retry.')
                stream.write(block);h.update(block);offset+=len(block)
                if progress:progress(offset,info['size'])
        if h.hexdigest()!=info['sha256']:raise Failure('hash','Download verification failed; retry.')
        marked=mark_download(part) if os.name=='nt' and getattr(client,'on',None) else True
        if overwrite:os.replace(part,target)
        else:
            try:
                if os.name=='nt':os.rename(part,target)
                else:os.link(part,target)
            except FileExistsError:raise Failure('exists','A file with this name already exists. Replace it?')
        return {'path':str(target),'size':offset,'sha256':h.hexdigest(),'zone_marked':marked}
    finally:
        if os.path.exists(part):os.unlink(part)

def downloads_folder():
    if os.name=='nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
            return os.path.expandvars(winreg.QueryValueEx(key,'{374DE290-123F-4565-9164-39C4925E467B}')[0])
    return str(Path.home()/'Downloads')

def choose_download_path(name):
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
    $dialog.OverwritePrompt = $false
    if ($dialog.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) {
        [Console]::Write($dialog.FileName)
    }
} finally { $dialog.Dispose() }
'''
    completed=subprocess.run(
        [str(Path(os.environ['SystemRoot'])/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'),
         '-NoProfile','-NonInteractive','-STA','-Command',script],
        input=json.dumps(dict(name=suggested,directory=downloads_folder())),
        encoding='utf-8',capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if completed.returncode:
        raise Failure('dialog','Could not open the Windows download location picker.')
    return Path(completed.stdout) if completed.stdout else None

def download_as(client, source, progress):
    leaf=source.rsplit('/',1)[-1] if client.on else Path(source).name
    target=choose_download_path(leaf)
    if target is None:
        return {'cancelled':True}
    try:
        return download(client,source,target.parent,progress=progress,filename=target.name)
    except Failure as error:
        if error.code=='exists':
            raise Failure('exists','This name is already in use. Choose a different download name.') from error
        raise

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
            if re.fullmatch(pattern,entry.name) and not entry.is_symlink():
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

def render_pdf(path, page_index, width, cache, include_sizes=False, include_chars=True):
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
        page_index=max(0,min(count-1,int(page_index)))
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
            prune_cache(result.parent,r'[a-f0-9]{64}-\d+-(?:\d+|\d+x\d+)\.png',PAGE_CACHE_BYTES,result)
            chars=[]
            try:
                textpage=page.get_textpage() if include_chars else None
            except pdfium.PdfiumError:
                textpage=None
            try:
                for index in range(min(textpage.count_chars(),50000) if textpage is not None else 0):
                    code=pdfium.raw.FPDFText_GetUnicode(textpage.raw,index)
                    text=chr(code) if 0<code<=0x10ffff else ''
                    if 0xD800<=code<=0xDFFF:text=''
                    rect=None
                    if text.strip():
                        try:
                            left,bottom,right,top=textpage.get_charbox(index)
                        except pdfium.PdfiumError:
                            chars.append({'t':text,'r':None})
                            continue
                        points=[]
                        for x,y in ((left,bottom),(right,top),(left,top),(right,bottom)):
                            dx=ctypes.c_int();dy=ctypes.c_int()
                            if pdfium.raw.FPDF_PageToDevice(page.raw,0,0,pixel_width,pixel_height,0,x,y,ctypes.byref(dx),ctypes.byref(dy)):
                                points.append((dx.value/pixel_width,dy.value/pixel_height))
                        if len(points)==4:
                            rect=[max(0,min(1,v)) for v in (min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))]
                    chars.append({'t':text,'r':rect})
            finally:
                if textpage is not None:textpage.close()
            value={'image':str(result),'page':page_index,'pages':count,'width':pixel_width,'height':pixel_height,'pdf':str(path),'chars':chars}
            if include_sizes:
                value['sizes']=[list(pdf.get_page_size(i)) for i in range(count)]
            return value
        finally:page.close()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--hc',required=True);parser.add_argument('--home',required=True);parser.add_argument('--request',required=True)
    args=parser.parse_args();q=json.loads(args.request)
    root=Path(args.home)/'data'/'personal-files'
    root.mkdir(parents=True,exist_ok=True)
    job=q.get('job','')
    if not re.fullmatch('[a-f0-9]{32}',job):raise Failure('job','Invalid file job')
    progress_path=root/'jobs'/(job+'.json')
    progress_temp=progress_path.with_suffix('.tmp')
    def progress(done,total):
        # A Windows reader can briefly prevent replacing the progress snapshot.
        with suppress(OSError):
            progress_path.parent.mkdir(exist_ok=True)
            progress_temp.write_text(json.dumps({'done':done,'total':total}),encoding='utf8')
            os.replace(progress_temp,progress_path)
    client=RemoteClient(q.get('on'),args.hc)
    action=q['action']
    try:
        if action=='revision':
            result=client.request('revision',path=q['source']) if q.get('on') else {'revision':list(file_revision(Path(q['source'])))}
            result['revision']=[str(number) for number in result['revision']]
        elif action=='text':
            result=client.request('text',path=q['source'])
            rev=result['revision'] if q.get('on') else result['revision'][:3]
            result['revision']=[str(number) for number in rev]
        elif action=='upload':result=upload(client,q['source'],q['directory'],q.get('overwrite',False),progress)
        elif action in ('copy','move'):result=client.request(action,path=q['source'],directory=q['directory'])
        elif action=='rename':result=client.request(action,path=q['source'],name=q['name'])
        elif action=='delete':result=client.request(action,path=q['source'],confirmed=q.get('confirmed'))
        elif action=='download':
            if q.get('choose'):
                result=download_as(client,q['source'],progress)
            else:
                result=download(client,q['source'],q.get('directory') or downloads_folder(),q.get('overwrite',False),progress)
            if q.get('open') and not result.get('cancelled'):open_download(result)
        elif action in ('preview','image'):
            if q.get('on'):
                info=client.request('stat',path=q['source'])
                limit=128*1024**2 if action=='image' else PDF_CACHE_BYTES
                if info['size']>limit:
                    raise Failure('size',f'Remote preview limit is {limit//1024**2} MiB. Download the file to open it locally.')
                identity=hashlib.sha256((q['on']+q['source']+info['sha256']).encode()).hexdigest()
                local=root/'image-sources'/(identity+'.img') if action=='image' else root/'pdf'/(identity+'.pdf')
                verified=False
                if not local.exists():
                    try:
                        download(client,q['source'],str(local.parent),progress=progress,filename=local.name,info=info)
                        verified=True
                    except Failure as error:
                        if error.code!='exists':raise
                if not verified and file_digest(local)!=info['sha256']:
                    raise Failure('cache','Document cache verification failed. Retry with a fresh copy.')
                mark_used(local)
                prune_cache(local.parent,r'[a-f0-9]{64}\.(?:pdf|img)',PDF_CACHE_BYTES,local)
                revision=info['revision']
            else:
                local=Path(q['source'])
                revision=file_revision(local)
            if action=='image':
                result=render_image(local,root/'images')
            else:
                result=render_pdf(local,q.get('page',0),q.get('width',1100),root/'pages',include_sizes=q.get('sizes',False),include_chars=q.get('chars',True))
            if not q.get('on') and revision!=file_revision(local):raise Failure('changed','File changed while opening')
            result['revision']=[str(number) for number in revision]
            result['image']=str(Path(result['image']).relative_to(args.home)).replace('\\','/')
        elif action=='render':
            local=Path(q['source']).resolve()
            allowed=(root/'pdf').resolve()
            if not local.is_relative_to(allowed):raise Failure('pdf','Invalid PDF cache path')
            if not local.is_file():raise Failure('cache_miss','Remote preview cache expired.')
            mark_used(local)
            result=render_pdf(local,q.get('page',0),q.get('width',1100),root/'pages',include_sizes=q.get('sizes',False),include_chars=q.get('chars',True))
            result['image']=str(Path(result['image']).relative_to(args.home)).replace('\\','/')
        elif action=='folder':os.startfile(q.get('directory') or downloads_folder());result={}
        else:raise Failure('action','Unknown Files action')
    finally:
        for snapshot in (progress_temp,progress_path):
            with suppress(OSError):
                snapshot.unlink(missing_ok=True)
    print(json.dumps({'ok':True,**result},ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'ok':False,'code':getattr(e,'code','error'),'error':str(e)[:300]},ensure_ascii=False))
