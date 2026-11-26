import base64,ctypes,errno,hashlib,json,os,re,shutil,sys,tempfile,stat,time
from pathlib import Path
# Windows also reserves device names with extensions, spaces, and superscript digits.
WINDOWS_INVALID_LEAF = (
    r'(?i)^$|[\x00-\x1f<>:"/\\|?*]|[ .]$|'
    r'^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³]) *(?:\.|$)'
)

# One call carries one chunk. herdr-core accepts at most 8 MB piped in or out, base64 included.
CHUNK = 4 * 1024 * 1024
STALE_STAGE_SECONDS = 24 * 3600

def revision(p):
    s=p.stat()
    return [s.st_size,s.st_mtime_ns,s.st_ino,s.st_dev]
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def stage_identity(s):return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,getattr(s,'st_birthtime_ns',0)]
def open_stage(p,expected,flags):
    # `expected` is a whole identity, or only its device and inode when chunks arrive out of order.
    if p.is_symlink():raise ValueError('Temporary file was replaced')
    fd=os.open(p,flags|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
    s=os.fstat(fd)
    mine=not hasattr(os,'geteuid') or s.st_uid==os.geteuid()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or not mine or len(expected)<2 or stage_identity(s)[:len(expected)]!=list(expected):
        os.close(fd);raise ValueError('Temporary file was replaced')
    return fd
def default_mode():
    mask=os.umask(0);os.umask(mask)
    return 0o666&~mask
def publish_mode(target,overwrite):
    # Staging files are private. A published file takes the mode of the file it replaces, or the account's default.
    if os.name=='nt':return None
    if overwrite:
        try:
            old=os.lstat(target)
            if stat.S_ISREG(old.st_mode):return stat.S_IMODE(old.st_mode)
        except OSError:pass
    return default_mode()
def sweep_stale(folder):
    # A transfer that was killed leaves its staging file. Remove this tool's own a day after their last write.
    limit=time.time()-STALE_STAGE_SECONDS
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if not entry.name.endswith('.part') or not entry.name.startswith(('.herdr-upload-','.herdr-download-','.herdr-copy-')):continue
                try:
                    # Not the directory entry's cached stat: on Windows that one carries no link count.
                    s=os.lstat(entry.path)
                    if stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_mtime<limit:os.unlink(entry.path)
                except OSError:pass
    except OSError:pass
def stage_path(p):
    if not p.name.startswith('.herdr-upload-') or not p.name.endswith('.part'):
        raise ValueError('Invalid temporary upload')
    return p
def rename_no_replace(source, target):
    try:
        if os.name=='nt':
            os.rename(source,target)
        elif sys.platform.startswith('linux'):
            # renameat2 with RENAME_NOREPLACE makes the move atomic without clobbering.
            rename=getattr(ctypes.CDLL(None,use_errno=True),'renameat2',None)
            if rename is None:
                raise ValueError('This server does not support moving files without overwriting')
            rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
            if rename(-100,os.fsencode(source),-100,os.fsencode(target),1)!=0:
                code=ctypes.get_errno()
                raise OSError(code,os.strerror(code))
        else:
            raise ValueError('Moving files is supported on Windows and Linux hosts')
    except OSError as error:
        if error.errno==errno.EXDEV:
            raise ValueError('The destination is on a different filesystem') from error
        if error.errno in (errno.ENOSYS,errno.EOPNOTSUPP):
            raise ValueError('This filesystem does not support moving files without overwriting') from error
        raise
def publish_new_file(part, target):
    if os.name=='nt':
        os.rename(part,target)
    else:
        os.link(part,target)
        part.unlink()
def copy_file(source, target):
    if os.path.lexists(target):
        raise FileExistsError(str(target))
    before=revision(source)
    sweep_stale(target.parent)
    fd,part_name=tempfile.mkstemp(prefix='.herdr-copy-',suffix='.part',dir=target.parent)
    part=Path(part_name)
    try:
        with os.fdopen(fd,'wb') as output, source.open('rb') as original:
            shutil.copyfileobj(original,output,1024*1024)
        shutil.copystat(source,part)
        if revision(source)!=before or part.stat().st_size!=before[0]:
            raise ValueError('Source changed during copy; retry')
        publish_new_file(part,target)
    finally:
        try:
            part.unlink(missing_ok=True)
        except PermissionError:
            if os.name!='nt':raise
            # A failed publish can leave a stage with the source's read-only flag.
            part.chmod(stat.S_IWRITE)
            part.unlink()
def edit_file(q, source):
    if not source.is_absolute() or not stat.S_ISREG(source.lstat().st_mode):
        raise ValueError('Select an individual regular file')
    action=q['action']
    if action=='delete':
        if q.get('confirmed') is not True:
            raise ValueError('Confirm permanent deletion first')
        source.unlink()
        return dict(path=str(source))
    if action=='rename':
        name=q['name']
        if not isinstance(name,str) or not name or Path(name).name!=name or name in ('.','..') or '\0' in name:
            raise ValueError('Enter a single filename')
        if os.name=='nt' and re.search(WINDOWS_INVALID_LEAF,name):
            raise ValueError('Enter a valid Windows filename')
        if name==source.name:
            return dict(path=str(source))
        target=source.with_name(name)
    else:
        directory=Path(q['directory'])
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError('Choose an existing destination folder')
        if action=='move' and directory.resolve()==source.parent.resolve():
            return dict(path=str(source))
        target=directory/source.name
    if action=='copy':
        copy_file(source,target)
    else:
        rename_no_replace(source,target)
    return dict(path=str(target))
def go(q):
    a=q['action'];p=Path(q['path'])
    if a in ('copy','move','rename','delete'):
        return edit_file(q,p)
    if a=='text':
        before=revision(p)
        if not p.is_file():raise ValueError('Select an individual file')
        with p.open(encoding='utf-8-sig') as stream:
            text=stream.read(400001)
        if before!=revision(p):raise ValueError('The file changed while opening. Retry.')
        return dict(text=None if '\0' in text else text,revision=before)
    if a=='revision':
        if not p.is_file():raise ValueError('File is not available')
        return dict(revision=revision(p))
    if a=='stat':
        if not p.is_file():raise ValueError('Select an individual file')
        rev=revision(p);out=dict(size=rev[0],revision=rev)
        # Hashing a large file delays the first byte. Past the caller's limit, `digest` verifies at the end instead.
        if rev[0]<=q.get('hash_limit',rev[0]):
            out['sha256']=digest(p)
            if rev!=revision(p):raise ValueError('Source changed; retry')
        return out
    if a=='digest':
        if revision(p)!=q['revision']:raise ValueError('Source changed; retry')
        sha=digest(p)
        if revision(p)!=q['revision']:raise ValueError('Source changed; retry')
        return dict(sha256=sha)
    if a=='read':
        if revision(p)!=q['revision']:raise ValueError('Source changed; retry')
        with p.open('rb') as f:
            f.seek(q['offset']);data=f.read(max(0,min(q['length'],CHUNK)))
        if revision(p)!=q['revision']:raise ValueError('Source changed; retry')
        return dict(data=base64.b64encode(data).decode())
    if a=='begin':
        if not p.parent.is_dir():raise ValueError('Upload folder no longer exists')
        if os.path.lexists(p) and not q['overwrite']:raise FileExistsError(str(p))
        sweep_stale(p.parent)
        fd,part=tempfile.mkstemp(prefix='.herdr-upload-',suffix='.part',dir=str(p.parent));os.close(fd)
        return dict(part=part,identity=stage_identity(os.stat(part)))
    if a=='write_at':
        # Chunks sent side by side land at their own offsets; `finish` verifies the whole file.
        p=stage_path(p)
        b=base64.b64decode(q['data'],validate=True)
        if len(b)>CHUNK or q['offset']<0:raise ValueError('Upload chunk too large')
        fd=open_stage(p,q['identity'][:2],os.O_WRONLY)
        try:
            os.lseek(fd,q['offset'],os.SEEK_SET)
            view=memoryview(b)
            while view:view=view[os.write(fd,view):]
        finally:os.close(fd)
        return {}
    if a=='write':
        p=stage_path(p)
        b=base64.b64decode(q['data'],validate=True)
        if len(b)>CHUNK:raise ValueError('Upload chunk too large')
        fd=open_stage(p,q['identity'],os.O_WRONLY|os.O_APPEND)
        with os.fdopen(fd,'ab') as f:
            if os.fstat(f.fileno()).st_size!=q['offset']:raise ValueError('Upload position mismatch')
            f.write(b);f.flush()
        identity=stage_identity(p.stat())
        return dict(size=identity[2],identity=identity)
    if a=='finish':
        part=stage_path(Path(q['part']))
        if part.is_symlink() or part.parent!=p.parent:raise ValueError('Invalid upload temporary file')
        fd=open_stage(part,q['identity'],os.O_RDONLY)
        with os.fdopen(fd,'rb') as f:
            seen=stage_identity(os.fstat(f.fileno()))
            h=hashlib.sha256()
            for block in iter(lambda:f.read(1048576),b''):h.update(block)
            if seen[2]!=q['size'] or h.hexdigest()!=q['sha256']:raise ValueError('Upload verification failed')
            mode=publish_mode(p,q['overwrite'])
            if mode is not None:os.fchmod(f.fileno(),mode)
        if stage_identity(part.stat())!=seen:raise ValueError('Temporary file was replaced')
        if q['overwrite']:os.replace(part,p)
        else:publish_new_file(part,p)
        return dict(path=str(p),size=p.stat().st_size,sha256=q['sha256'])
    if a=='abort':
        stage_path(p).unlink(missing_ok=True);return {}
    raise ValueError('Unknown file operation')

def reply(request):
    try:
        return dict(ok=True,**go(request))
    except FileExistsError:
        message='The destination already contains an item with this name.' if request['action'] in ('copy','move','rename') else 'A file with this name already exists. Replace it?'
        return dict(ok=False,code='exists',error=message)
    except Exception as e:
        return dict(ok=False,code='transfer',error=str(e)[:300])

if __name__=='__main__':
    print(json.dumps(reply(json.load(sys.stdin))))
