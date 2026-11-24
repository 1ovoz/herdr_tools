"""Measure repeated native PDF renders in one Windows process, including actual bitmap allocation."""
import ctypes
from ctypes import wintypes
import gc
from pathlib import Path
import sys
import tempfile
import time

files=Path(__file__).resolve().parents[1]/'personal-files'
sys.path.insert(0,str(files))
import bridge


class Counters(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('page_faults',wintypes.DWORD)]+[
        (name,ctypes.c_size_t) for name in ('peak_ws','ws','peak_paged','paged','peak_nonpaged',
                                             'nonpaged','pagefile','peak_pagefile','private')]


def snapshot():
    process=wintypes.HANDLE(-1)
    counters=Counters()
    counters.cb=ctypes.sizeof(counters)
    handles=wintypes.DWORD()
    gc.collect()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(process,ctypes.byref(counters),counters.cb):
        raise ctypes.WinError()
    if not ctypes.windll.kernel32.GetProcessHandleCount(process,ctypes.byref(handles)):
        raise ctypes.WinError()
    return counters.private,handles.value,counters.peak_ws


def main():
    started=time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='herdr-render-') as tmp:
        rows=[]
        for i in range(32):
            result=bridge.render_pdf(files/'fixture.pdf',i%2,2000,tmp)
            Path(result['image']).unlink()  # Render the bitmap again on every iteration.
            if (i+1)%8==0:rows.append(snapshot())
    print('32 renders at 2000x2500; samples every 8 (private MiB, handles, peak working set MiB):',
          [(round(private/2**20,2),handles,round(peak/2**20,2)) for private,handles,peak in rows])
    print('Elapsed seconds:',round(time.perf_counter()-started,2))
    if rows[-1][0]-rows[0][0]>8*2**20 or rows[-1][1]-rows[0][1]>4:
        raise RuntimeError('Unexpected private memory or handle growth after warm-up')


if __name__=='__main__':
    main()
