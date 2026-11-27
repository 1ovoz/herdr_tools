"""Serve only the selected document and its assets, and capture Edge's screen layout."""
import base64
from contextlib import contextmanager, ExitStack, suppress
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote, unquote, urlsplit
import webbrowser

import file_host


# Explicit MIME types keep preview behavior independent of a PC's file associations.
ASSETS = {
    '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.avif': 'image/avif', '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon', '.bmp': 'image/bmp', '.woff': 'font/woff', '.woff2': 'font/woff2',
    '.otf': 'font/otf', '.ttf': 'font/ttf'
}
INTERACTIVE_ASSETS = {
    **ASSETS, '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json',
    '.html': 'text/html', '.htm': 'text/html', '.wasm': 'application/wasm',
    '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.mp4': 'video/mp4', '.webm': 'video/webm',
}
PREVIEW_POLICY = ("sandbox allow-same-origin; default-src 'none'; script-src 'none'; "
                  "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
                  "base-uri 'self'; form-action 'none'; frame-ancestors 'none'")
MAX_REQUESTS = 128
MAX_BYTES = 32 * 1024**2
CAPTURE_SECONDS = 45
MAX_HEIGHT = 12000
MAX_PIXELS = 12_000_000


def document_name(source):
    name = source.replace('\\', '/').rsplit('/', 1)[-1]
    if Path(name).suffix.lower() not in ('.html', '.htm'):
        raise ValueError('Select an HTML file.')
    return name


class ResourceServer(ThreadingHTTPServer):
    """One random loopback URL for one document on one Herdr host."""
    daemon_threads = True

    def __init__(self, client, source, interactive):
        self.client = client
        self.source = source
        self.name = document_name(source)
        document = client.request('html-resource', path=source, member=self.name)
        self.document = base64.b64decode(document['data'], validate=True)
        self.revision = document['revision']
        self.interactive = interactive
        self.prefix = '/' + secrets.token_urlsafe(24) + '/'
        self.lock = threading.Lock()
        self.remaining_bytes = MAX_BYTES
        self.served_document = threading.Event()
        self.remaining_requests = MAX_REQUESTS
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(('127.0.0.1', 0), ResourceHandler)
        self.authority = '127.0.0.1:' + str(self.server_port)
        self.url = 'http://' + self.authority + self.prefix + quote(self.name)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.close_request(request)
            return
        super().process_request(request, address)

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def resource(self, member):
        assets = INTERACTIVE_ASSETS if self.interactive else ASSETS
        mime = 'text/html' if member == self.name else assets.get(Path(member).suffix.lower())
        if not mime:
            raise ValueError('Unavailable resource.')
        with self.lock:
            if self.remaining_requests <= 0 or self.remaining_bytes <= 0:
                raise ValueError('Resource limit reached.')
            self.remaining_requests -= 1
        if member == self.name:
            body = self.document
        else:
            value = self.client.request('html-resource', path=self.source, member=member)
            body = base64.b64decode(value['data'], validate=True)
        with self.lock:
            if len(body) > self.remaining_bytes:
                raise ValueError('Resource limit reached.')
            self.remaining_bytes -= len(body)
        return mime, body


class ResourceHandler(BaseHTTPRequestHandler):
    timeout = 3

    def log_message(self, *args):
        pass

    def do_GET(self):
        site = self.server
        path = urlsplit(self.path).path
        if self.headers.get('Host') != site.authority or not path.startswith(site.prefix):
            self.send_error(404)
            return
        try:
            member = unquote(path[len(site.prefix):], errors='strict')
            mime, body = site.resource(member)
        except Exception:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if not site.interactive:
            self.send_header('Content-Security-Policy', PREVIEW_POLICY)
        self.end_headers()
        with suppress(OSError):
            self.wfile.write(body)
            if member == site.name:
                site.served_document.set()


@contextmanager
def document_server(client, source, interactive):
    with ResourceServer(client, source, interactive) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


def find_edge():
    for folder in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        if os.environ.get(folder):
            exe = Path(os.environ[folder]) / 'Microsoft/Edge/Application/msedge.exe'
            if exe.is_file():
                return exe
    raise RuntimeError('Microsoft Edge is required for the HTML preview. Open the document in your browser or select Source.')


class EdgePipe:
    """Chromium DevTools Protocol over two inherited handles. No debugging port."""
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.pending = bytearray()
        self.current_id = 0
        self.session = None
        self.loaded = set()

    def receive(self):
        start = 0
        while True:
            end = self.pending.find(0, start)
            if end >= 0:
                frame = self.pending[:end]
                del self.pending[:end+1]
                message = json.loads(frame)
                if message.get('method') == 'Page.lifecycleEvent':
                    event = message['params']
                    self.loaded.add((event['loaderId'], event['name']))
                return message
            start = len(self.pending)
            block = self.reader.read(65536)
            if not block:
                raise RuntimeError('Edge stopped before the HTML preview finished.')
            self.pending.extend(block)
            if len(self.pending) > 80 * 1024**2:
                raise RuntimeError('The rendered HTML image exceeds the preview limit.')

    def call(self, method, **params):
        self.current_id += 1
        message = dict(id=self.current_id, method=method, params=params)
        if self.session:
            message['sessionId'] = self.session
        self.writer.write(json.dumps(message).encode() + b'\0')
        self.writer.flush()
        while True:
            response = self.receive()
            if response.get('id') == self.current_id:
                if 'error' in response:
                    raise RuntimeError('Edge could not render this document (' + method + ').')
                return response['result']


@contextmanager
def edge_session():
    exe = find_edge()
    import msvcrt
    with ExitStack() as cleanup:
        # Edge may briefly hold its profile open after Browser.close.
        profile = tempfile.mkdtemp(prefix='herdr-html-')
        cleanup.callback(shutil.rmtree, profile, ignore_errors=True)
        read_command, write_command = os.pipe()
        read_result, write_result = os.pipe()
        writer = cleanup.enter_context(os.fdopen(write_command, 'wb'))
        reader = cleanup.enter_context(os.fdopen(read_result, 'rb', buffering=0))
        with os.fdopen(read_command, 'rb') as child_in, os.fdopen(write_result, 'wb') as child_out:
            handles = [msvcrt.get_osfhandle(f.fileno()) for f in (child_in, child_out)]
            for handle in handles:
                os.set_handle_inheritable(handle, True)
            start = subprocess.STARTUPINFO()
            start.lpAttributeList = {'handle_list': handles}
            process = subprocess.Popen([
                str(exe), '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                '--disable-background-networking', '--disable-extensions', '--disable-sync', '--disable-component-update',
                '--disable-features=msEdgeFirstRunExperience', '--disable-quic', '--proxy-server=http://127.0.0.1:9',
                '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1', '--hide-scrollbars', '--force-device-scale-factor=1',
                '--user-data-dir=' + profile, '--remote-debugging-pipe',
                '--remote-debugging-io-pipes=' + ','.join(map(str, handles)), 'about:blank',
            ], startupinfo=start, creationflags=subprocess.CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        timer = threading.Timer(CAPTURE_SECONDS, process.kill)
        timer.daemon = True
        timer.start()
        try:
            yield EdgePipe(reader, writer)
        finally:
            writer.close()  # Closing the command pipe asks this isolated Edge process to exit.
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            finally:
                timer.cancel()


def render(client, source, width, height, directory):
    width = max(64, min(4096, int(width)))
    height = max(64, min(4096, int(height)))
    with document_server(client, source, interactive=False) as site, edge_session() as edge:
        tabs = edge.call('Target.getTargets')['targetInfos']
        tab = next(target for target in tabs if target['type'] == 'page')
        edge.session = edge.call('Target.attachToTarget', targetId=tab['targetId'], flatten=True)['sessionId']
        edge.call('Emulation.setScriptExecutionDisabled', value=True)
        edge.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        edge.call('Page.enable')
        edge.call('Page.setLifecycleEventsEnabled', enabled=True)
        navigation = edge.call('Page.navigate', url=site.url)
        if navigation.get('errorText') or not navigation.get('loaderId'):
            raise RuntimeError('Edge could not open the HTML preview: ' + navigation.get('errorText', 'navigation failed'))
        while (navigation['loaderId'], 'networkIdle') not in edge.loaded:
            edge.receive()
        if not site.served_document.is_set():
            raise RuntimeError('Edge could not load the HTML document.')
        layout = edge.call('Page.getLayoutMetrics')['cssContentSize']
        natural_height = max(height, math.ceil(layout['height']))
        pixels_high = min(natural_height, MAX_HEIGHT, MAX_PIXELS // width)
        capture = edge.call('Page.captureScreenshot', format='png', captureBeyondViewport=True,
                            clip=dict(x=0, y=0, width=width, height=pixels_high, scale=1))
        data = base64.b64decode(capture['data'], validate=True)
        revision = site.revision
    if data[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', data[16:24]) != (width, pixels_high):
        raise RuntimeError('Edge returned an incomplete HTML image.')
    current = client.request('revision', path=source)['revision']
    if current != revision:
        raise ValueError('HTML changed while opening. Retry.')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(data).hexdigest() + '.png')
    if not path.exists():
        part = tempfile.NamedTemporaryFile(dir=directory, suffix='.part', delete=False)
        temporary = Path(part.name)
        try:
            with part:
                part.write(data)
            with suppress(FileExistsError):
                file_host.publish_new_file(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return dict(image=path, width=width, height=pixels_high, truncated=natural_height > pixels_high,
                revision=[str(v) for v in (revision if client.on else revision[:3])])


def open_document(client, source):
    document_name(source)
    if not client.on:
        path = Path(source).resolve(strict=True)
        document_name(str(path))
        if not path.is_file() or not webbrowser.open(path.as_uri()):
            raise RuntimeError('Cannot open this HTML file in your default browser.')
        return
    # The short-lived bridge exits after acknowledging the click. Its child owns the
    # remote document's URL so relative assets and page interactions keep working.
    with tempfile.TemporaryDirectory(prefix='herdr-html-start-') as tmp:
        ready = Path(tmp) / 'ready'
        child = subprocess.Popen([sys.executable, '-X', 'utf8', __file__, str(ready), source, client.on, client.hc],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 30
        while not ready.exists():
            if child.poll() is not None or time.monotonic() > deadline:
                child.kill()
                child.wait()
                raise RuntimeError('Cannot start the remote HTML document. Check the file host connection.')
            time.sleep(0.05)
        message = json.loads(ready.read_text(encoding='utf8'))
        if message:
            raise RuntimeError(message)


def serve_browser(ready, source, machine, hc):
    from bridge import RemoteClient
    def report(message):
        pending = ready.with_suffix('.tmp')
        pending.write_text(json.dumps(message), encoding='utf8')
        os.replace(pending, ready)
    try:
        with document_server(RemoteClient(machine, hc), source, interactive=True) as site:
            if not webbrowser.open(site.url):
                raise RuntimeError('Cannot open the default browser.')
            report('')
            time.sleep(15 * 60)
    except Exception as error:
        if ready.parent.is_dir():
            report(str(error)[:300])


if __name__ == '__main__':
    serve_browser(Path(sys.argv[1]), *sys.argv[2:])
