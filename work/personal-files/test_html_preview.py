import base64
from contextlib import redirect_stdout
import http.client
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import zlib

import bridge
import file_host


class HtmlPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        self.source = self.site / '문서.html'
        self.source.write_text('<h1>문서</h1>', encoding='utf8')
        self.client = bridge.RemoteClient(None, 'unused')

    def call(self, action, **fields):
        request = dict(action=action, source=str(self.source), job='1'*32, **fields)
        output = io.StringIO()
        with patch.object(sys, 'argv', ['bridge', '--home', str(self.root), '--hc', 'unused',
                                        '--request', json.dumps(request)]), redirect_stdout(output):
            bridge.main()
        return json.loads(output.getvalue())

    def resource(self, member):
        return file_host.reply(dict(action='html-resource', path=str(self.source), member=member))

    def test_scoped_host_read_preserves_relative_stylesheets_and_revision(self):
        (self.site / 'assets').mkdir()
        css = self.site / 'assets' / '배경.css'
        css.write_bytes(b'body{color:green}')
        result = self.resource('assets/배경.css')
        self.assertTrue(result['ok'], result)
        self.assertEqual(base64.b64decode(result['data']), css.read_bytes())
        self.assertEqual(result['revision'], file_host.revision(css))

    def test_root_document_rejects_excess_size(self):
        with self.source.open('wb') as out:
            out.truncate(4 * 1024**2 + 1)
        self.assertFalse(self.resource(self.source.name)['ok'])

    def test_scoped_host_rejects_traversal_device_names_and_symlinks(self):
        (self.root / 'outside.css').write_text('outside')
        for member in ('../outside.css', str(self.root / 'outside.css'), 'NUL.css', 'a\\b.css', 'a.css:stream'):
            with self.subTest(member=member):
                self.assertFalse(self.resource(member)['ok'])
        try:
            (self.site / 'escape.css').symlink_to(self.root / 'outside.css')
        except OSError:
            return
        self.assertFalse(self.resource('escape.css')['ok'])

    def test_html_source_reads_declared_korean_encoding(self):
        source = '<meta charset="euc-kr"><h1>한글</h1>'
        self.source.write_bytes(source.encode('cp949'))
        result = self.call('text')
        self.assertEqual(result['text'], source)

    def test_automatic_server_exposes_only_requested_preview_assets(self):
        import html_preview
        (self.site / 'style.css').write_bytes(b'p{color:green}')
        (self.site / 'notes.txt').write_bytes(b'private')
        with html_preview.document_server(self.client, str(self.source), interactive=False) as site:
            url = urlsplit(site.url)
            conn = http.client.HTTPConnection(url.hostname, url.port, timeout=4)
            def get(path, **headers):
                conn.request('GET', path, headers=headers)
                response = conn.getresponse()
                return response.status, response.headers, response.read()
            status, headers, content = get(url.path)
            self.assertEqual(status, 200)
            self.assertEqual(content, self.source.read_bytes())
            self.assertIn("script-src 'none'", headers['Content-Security-Policy'])
            sibling = url.path.rsplit('/', 1)[0] + '/'
            self.assertEqual(get(sibling+'style.css')[2], b'p{color:green}')
            for path in (sibling+'notes.txt', '/style.css', sibling+'%2e%2e/outside.css'):
                self.assertGreaterEqual(get(path)[0], 400)
            self.assertGreaterEqual(get(url.path, Host='elsewhere.invalid')[0], 400)
            conn.close()

    def test_explicit_local_open_uses_the_selected_html_file(self):
        with patch('webbrowser.open', return_value=True) as launch:
            self.assertTrue(self.call('html-open')['ok'])
        self.assertEqual(launch.call_args.args, (self.source.resolve().as_uri(),))
        self.source = self.site / 'example.exe'
        self.source.write_bytes(b'')
        with patch('webbrowser.open', return_value=True) as launch:
            with self.assertRaises(ValueError):
                self.call('html-open')
            launch.assert_not_called()

    def test_local_open_checks_the_resolved_document_type(self):
        target = self.site / 'notes.txt'
        target.write_text('notes')
        self.source.unlink()
        try:
            self.source.symlink_to(target)
        except OSError:
            self.skipTest('Creating symlinks requires Windows Developer Mode or permission')
        with patch('webbrowser.open', return_value=True) as launch:
            with self.assertRaises(ValueError):
                self.call('html-open')
            launch.assert_not_called()

    def test_remote_browser_requests_scripts_from_selected_host(self):
        import html_preview
        script = self.site / 'reader.js'
        script.write_bytes(b'window.pageIsInteractive=true')
        # Model a second machine with a different path namespace and a serialized
        # host request, so local open/read shortcuts cannot satisfy the URL.
        remote_source = '/remote/work/report.html'
        (self.site / 'report.html').write_text('<script src="reader.js"></script>')
        class Remote:
            on = 'named-server'
            def request(remote, action, **fields):
                self.assertEqual(fields['path'], remote_source)
                return self.client.request(action, **{**fields, 'path': str(self.site / 'report.html')})
        with html_preview.document_server(Remote(), remote_source, interactive=True) as site:
            url = urlsplit(site.url)
            conn = http.client.HTTPConnection(url.hostname, url.port, timeout=4)
            conn.request('GET', url.path)
            response = conn.getresponse()
            self.assertIsNone(response.headers.get('Content-Security-Policy'))
            self.assertIn(b'reader.js', response.read())
            conn.request('GET', url.path.rsplit('/', 1)[0]+'/reader.js')
            self.assertEqual(conn.getresponse().read(), script.read_bytes())
            conn.close()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows Edge capture')
    def test_edge_renders_relative_css_image_and_tall_content_with_scripts_off(self):
        (self.site / 'assets').mkdir()
        (self.site / 'assets' / 'pattern.svg').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4" fill="#a32d51"/></svg>')
        (self.site / 'assets' / 'style.css').write_text('html{background:url(pattern.svg)}body{height:1350px;margin:0}')
        self.source.write_text('<link rel="stylesheet" href="assets/style.css"><body>'
                               '<script>document.documentElement.style.background="black"</script>')
        result = self.call('html-preview', width=460, height=340)
        self.assertEqual(result['width'], 460)
        self.assertEqual(result['height'], 1350)
        self.assertFalse(result['truncated'])
        self.assertEqual(result['revision'], [str(v) for v in bridge.file_revision(self.source)])
        image = self.root.joinpath(result['image']).read_bytes()
        self.assertEqual(struct.unpack('>II', image[16:24]), (460, 1350))
        # The PNG predictors use zero-valued neighbours at the top-left pixel.
        chunks = []
        i = 8
        while i < len(image):
            n = int.from_bytes(image[i:i+4], 'big')
            if image[i+4:i+8] == b'IDAT':
                chunks.append(image[i+8:i+8+n])
            i += 12+n
        self.assertEqual(zlib.decompress(b''.join(chunks))[1:4], bytes.fromhex('a32d51'))
