import base64,ctypes,errno,hashlib,json,os,re,shutil,sys,tempfile,stat,time
import zipfile
import zlib
from contextlib import ExitStack, closing, contextmanager, suppress
from pathlib import Path
# Windows also reserves device names with extensions, spaces, and superscript digits.
WINDOWS_INVALID_LEAF = (
    r'(?i)^$|[\x00-\x1f<>:"/\\|?*]|[ .]$|'
    r'^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³]) *(?:\.|$)'
)

# One call carries one chunk. herdr-core accepts at most 8 MB piped in or out, base64 included.
CHUNK = 4 * 1024 * 1024
STALE_STAGE_SECONDS = 24 * 3600
# ZipFile keeps an in-memory central directory. Bound both the member count and long path names.
ARCHIVE_SLICE_BYTES = 32 * 1024**2
ARCHIVE_SLICE_SECONDS = 1.5
ARCHIVE_MAX_ENTRIES = 100_000
ARCHIVE_MAX_NAME_BYTES = 16 * 1024**2

def host_program(source):
    # hc passes the command through the Windows process command line. Keep source and paths
    # off that command line as plain text and stay well below its 32K-character limit.
    packed=base64.b64encode(zlib.compress(source.encode('utf8'))).decode('ascii')
    return f"import base64,zlib\nexec(zlib.decompress(base64.b64decode('{packed}')))"

def archive_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT)

@contextmanager
def archive_directory(path, name, parent_fd, expected):
    if os.name=='nt':
        # Pin each directory against rename/deletion while its children are inspected.
        # OPEN_REPARSE_POINT opens the junction itself so the check never follows it.
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        create=kernel.CreateFileW
        create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                         wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        create.restype=wintypes.HANDLE
        handle=create(str(path),0x80,3,None,3,0x02000000|0x00200000,None)
        if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        try:
            actual=path.lstat()
            if archive_link(actual) or not os.path.samestat(expected,actual):
                raise ValueError('A folder changed while creating the ZIP. Retry.')
            yield None
        finally:
            kernel.CloseHandle(wintypes.HANDLE(handle))
    else:
        fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
        try:
            if not os.path.samestat(expected,os.fstat(fd)):
                raise ValueError('A folder changed while creating the ZIP. Retry.')
            yield fd
        finally:os.close(fd)

@contextmanager
def archive_entry(source, member):
    """Keep the parent chain of the selected member open, including across a file read."""
    path=source
    name=path
    parent=None
    info=path.lstat()
    with ExitStack() as dirs:
        for leaf in member.split('/')[1:]:
            if archive_link(info) or not stat.S_ISDIR(info.st_mode):
                raise ValueError('A folder changed while creating the ZIP. Retry.')
            parent=dirs.enter_context(archive_directory(path,name,parent,info))
            path=path/leaf
            name=path if parent is None else leaf
            info=path.lstat() if parent is None else os.stat(name,dir_fd=parent,follow_symlinks=False)
        yield path,name,parent,info

def queue_member(db, state, member):
    if re.search(WINDOWS_INVALID_LEAF,member.rsplit('/',1)[-1]):
        raise ValueError('A name in this folder cannot be safely extracted on Windows: '+member)
    state['entries']+=1
    state['names']+=len(member.encode('utf8'))+1
    if state['entries']>ARCHIVE_MAX_ENTRIES or state['names']>ARCHIVE_MAX_NAME_BYTES:
        raise ValueError('This folder has too many entries or long paths for one ZIP. Download smaller subfolders.')
    db.execute('INSERT INTO members(name) VALUES (?)',(member,))

def zip_entry(name, directory, stamp):
    try:date=time.localtime(stamp)[:6]
    except (OSError,OverflowError,ValueError):date=(1980,1,1,0,0,0)
    if not 1980<=date[0]<=2107:date=(1980,1,1,0,0,0)
    item=zipfile.ZipInfo(name+'/' if directory else name,date)
    item.compress_type=zipfile.ZIP_STORED if directory else zipfile.ZIP_DEFLATED
    item.external_attr=(0o40755<<16)|0x10 if directory else 0o100644<<16
    return item

def write_member(db, state, output, member, work, deadline, byte_limit):
    """Append one member, or enough of a large member to return before the host call times out."""
    source=Path(state['source'])
    with archive_entry(source,member) as (path,name,parent,info):
        directory=stat.S_ISDIR(info.st_mode)
        if (archive_link(info) or (not directory and not stat.S_ISREG(info.st_mode))
                or (state['exclude'] and path==Path(state['exclude']))
                or (path.parent==work.parent and re.fullmatch(r'\.herdr-archive-[a-f0-9]{32}',path.name))):
            if state.get('file') or path==source:
                raise ValueError('The source changed while creating the ZIP. Retry.')
            return True
        if directory and state.get('file'):raise ValueError('A file changed while creating the ZIP. Retry.')
        folded=member.casefold()
        if db.execute('SELECT 1 FROM members WHERE folded=?',(folded,)).fetchone():
            raise ValueError('Names in this folder would collide when extracted on Windows: '+member)
        item=zip_entry(member,directory,info.st_mtime)
        start=output.tell()
        if directory:
            with archive_directory(path,name,parent,info) as fd:
                with os.scandir(path if fd is None else fd) as children:
                    for child in children:
                        if child.is_symlink():continue
                        queue_member(db,state,member+'/'+child.name)
            item.CRC=0
            output.write(item.FileHeader(False))
        else:
            flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_BINARY',0)
            with os.fdopen(os.open(name,flags,dir_fd=parent),'rb') as original:
                before=os.fstat(original.fileno())
                if not stat.S_ISREG(before.st_mode) or not os.path.samestat(info,before):
                    raise ValueError('A file changed while creating the ZIP. Retry.')
                identity=stage_identity(before)
                zip64=before.st_size*1.05>zipfile.ZIP64_LIMIT
                part=state.get('file')
                if part:
                    if part['revision']!=identity:raise ValueError('A file changed while creating the ZIP. Retry.')
                    start=part['start']
                else:
                    part=state['file']={'start':start,'read':0,'crc':0,'revision':identity}
                    item.CRC=0
                    output.write(item.FileHeader(zip64))
                original.seek(part['read'])
                compressor=zlib.compressobj(1,zlib.DEFLATED,-15)
                while part['read']<before.st_size and state['done']<byte_limit:
                    size=min(1024**2, before.st_size-part['read'],byte_limit-state['done'])
                    block=original.read(size)
                    if not block:raise ValueError('A file changed while creating the ZIP. Retry.')
                    output.write(compressor.compress(block))
                    part['crc']=zlib.crc32(block,part['crc'])
                    part['read']+=len(block)
                    state['done']+=len(block)
                    if time.monotonic()>=deadline:break
                if stage_identity(os.fstat(original.fileno()))!=identity:
                    raise ValueError('A file changed while creating the ZIP. Retry.')
                complete=part['read']==before.st_size
                # FULL_FLUSH ends a byte-aligned, nonfinal deflate block and resets its history.
                # The next short-lived Python process can continue with a fresh raw compressor.
                output.write(compressor.flush(zlib.Z_FINISH if complete else zlib.Z_FULL_FLUSH))
                if not complete:return False
                item.CRC=part['crc']
                item.file_size=part['read']
                end=output.tell()
                item.compress_size=end-start-len(item.FileHeader(zip64))
                output.seek(start)
                output.write(item.FileHeader(zip64))
                output.seek(end)
                del state['file']
        db.execute('UPDATE members SET header=?, size=?, packed=?, crc=?, directory=?, stamp=?, folded=? WHERE id=?',
                   (start,item.file_size,item.compress_size,item.CRC,directory,info.st_mtime,folded,state['next']))
    return True

def finish_archive(db, output):
    # The local headers and deflate streams are already complete. ZipFile writes the standard
    # central directory and ZIP64 end records at the current position of this open stream.
    with zipfile.ZipFile(output,'w') as bundle:
        for name,header,size,packed,crc,directory,stamp in db.execute(
                'SELECT name,header,size,packed,crc,directory,stamp FROM members WHERE header IS NOT NULL ORDER BY id'):
            item=zip_entry(name,directory,stamp)
            item.header_offset,item.file_size,item.compress_size,item.CRC=header,size,packed,crc
            if size*1.05>zipfile.ZIP64_LIMIT:item.extract_version=item.create_version=45
            bundle.filelist.append(item)

def archive_next(db, state, work):
    path=work/'folder.zip'
    if not state.get('ready'):
        deadline=time.monotonic()+ARCHIVE_SLICE_SECONDS
        byte_limit=state['done']+ARCHIVE_SLICE_BYTES
        with path.open('r+b') as output:
            # SQLite commits the input position, output offset and CRC together. Replay any
            # uncommitted suffix after an interrupted host call, including a partially written index.
            output.seek(state['end'])
            output.truncate()
            while True:
                row=db.execute('SELECT name FROM members WHERE id=?',(state['next'],)).fetchone()
                if row is None:
                    finish_archive(db,output)
                    state['ready']=True
                    break
                if write_member(db,state,output,row[0],work,deadline,byte_limit):state['next']+=1
                if state['done']>=byte_limit or time.monotonic()>=deadline:break
            state['end']=output.tell()
        db.execute('UPDATE job SET state=?',(json.dumps(state),))
    result={'done':state['done']}
    if state.get('ready'):result.update(ready=True,path=str(path))
    return result

def clean_archive(work):
    for name in ('queue-journal','queue','folder.zip','lease'):
        with suppress(OSError):(work/name).unlink(missing_ok=True)
    with suppress(OSError):work.rmdir()

def archive_owned(work):
    info=work.lstat()
    return (stat.S_ISDIR(info.st_mode) and not archive_link(info)
            and (not hasattr(os,'geteuid') or (info.st_uid==os.geteuid() and not info.st_mode&0o077)))

def archive_request(q):
    import sqlite3
    token=q['token']
    if not isinstance(token,str) or not re.fullmatch('[a-f0-9]{32}',token):raise ValueError('Invalid ZIP job.')
    temp=Path(tempfile.gettempdir()).resolve()
    work=temp/('.herdr-archive-'+token)
    if q['action']=='archive-start' and not os.path.lexists(work):
        source=Path(q['path'])
        if not source.is_absolute():raise ValueError('Select an absolute folder path.')
        source=source.parent.resolve()/source.name
        info=source.lstat()
        if archive_link(info) or not stat.S_ISDIR(info.st_mode):raise ValueError('Select a regular folder.')
        for old in temp.glob('.herdr-archive-*'):
            with suppress(OSError):
                if archive_owned(old):
                    lease=old/'lease'
                    last_used=lease.stat().st_mtime if lease.exists() else old.stat().st_mtime
                    if time.time()-last_used>STALE_STAGE_SECONDS:clean_archive(old)
        work.mkdir(mode=0o700)
        try:
            (work/'lease').touch()
            (work/'folder.zip').touch()
            state=dict(source=str(source),exclude=q.get('exclude',''),next=1,done=0,end=0,entries=0,names=0)
            with closing(sqlite3.connect(work/'queue')) as db, db:
                db.execute('CREATE TABLE job (state TEXT)')
                db.execute('CREATE TABLE members (id INTEGER PRIMARY KEY, name TEXT, header INTEGER, '
                           'size INTEGER, packed INTEGER, crc INTEGER, directory INTEGER, stamp REAL, folded TEXT UNIQUE)')
                queue_member(db,state,source.name or 'folder')
                db.execute('INSERT INTO job VALUES (?)',(json.dumps(state),))
        except BaseException:
            clean_archive(work)
            raise
        return {}
    if not archive_owned(work):raise ValueError('ZIP temporary folder is no longer available.')
    os.utime(work/'lease',None)
    with closing(sqlite3.connect(work/'queue',timeout=30)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if q['action']=='archive-next':
            state=json.loads(db.execute('SELECT state FROM job').fetchone()[0])
            return archive_next(db,state,work)
    if q['action']=='archive-drop':clean_archive(work)
    return {}

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
def checked_name(name):
    if not isinstance(name,str) or not name or Path(name).name!=name or name in ('.','..') or '\0' in name:
        raise ValueError('Enter a single name')
    if os.name=='nt' and re.search(WINDOWS_INVALID_LEAF,name):
        raise ValueError('Enter a valid Windows name')
    return name

def create_item(directory, name, action):
    if not directory.is_absolute() or not directory.is_dir():
        raise ValueError('Choose an existing destination folder')
    target=directory/checked_name(name)
    if os.path.lexists(target):
        raise FileExistsError(str(target))
    if action=='new-folder':
        target.mkdir()
    else:
        with target.open('xb'):
            pass
    return dict(path=str(target))

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
        name=checked_name(q['name'])
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
    if q['action'] in ('archive-start','archive-next','archive-drop'):return archive_request(q)
    a=q['action'];p=Path(q['path'])
    if a in ('new-file','new-folder'):
        return create_item(p,q['name'],a)
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
        message='The destination already contains an item with this name.' if request['action'] in ('copy','move','rename','new-file','new-folder') else 'A file with this name already exists. Replace it?'
        return dict(ok=False,code='exists',error=message)
    except Exception as e:
        return dict(ok=False,code='transfer',error=str(e)[:300])

if __name__=='__main__':
    print(json.dumps(reply(json.load(sys.stdin))))
