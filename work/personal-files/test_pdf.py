from pathlib import Path
import os
import struct
import subprocess
import tempfile
import unittest
import zlib
import bridge

class Pdf(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows image codecs')
    def test_png_transparency_and_rotated_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def chunk(kind,data):
                return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
            png=root/'alpha.png'
            png.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',8,4,8,6,0,0,0))
                            +chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\x11\x22\x80'*8)*4))+chunk(b'IEND',b''))
            cache=root/'cache'
            image=bridge.render_image(png,cache)
            self.assertEqual((image['width'],image['height']),(8,4))
            preview=Path(image['image'])
            output=preview.read_bytes()
            self.assertTrue(output[25] in (4,6) or b'tRNS' in output)
            stamp=preview.stat().st_mtime_ns
            self.assertEqual(bridge.render_image(png,cache),image)
            self.assertEqual(preview.stat().st_mtime_ns,stamp)
            jpeg=root/'portrait.jpg'
            script="Add-Type -AssemblyName System.Drawing; $im=[Drawing.Bitmap]::new(8,4); try {$im.Save([Console]::In.ReadLine(),[Drawing.Imaging.ImageFormat]::Jpeg)} finally {$im.Dispose()}"
            subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),
                            '-NoProfile','-Command',script],input=str(jpeg)+'\n',text=True,check=True)
            data=jpeg.read_bytes()
            exif=b'Exif\0\0II'+struct.pack('<HIHHHIH',42,8,1,274,3,1,6)+b'\0'*6
            jpeg.write_bytes(data[:2]+b'\xff\xe1'+struct.pack('>H',len(exif)+2)+exif+data[2:])
            rotated=bridge.render_image(jpeg,cache)
            self.assertEqual((rotated['width'],rotated['height']),(4,8))

    def test_two_page_render_and_zoom(self):
        with tempfile.TemporaryDirectory() as cache:
            fixture=Path(__file__).with_name('fixture.pdf')
            first=bridge.render_pdf(fixture,0,600,cache,include_sizes=True)
            second=bridge.render_pdf(fixture,1,900,cache)
            self.assertEqual((first['pages'],second['page']),(2,1))
            self.assertEqual(first['sizes'], [[400,500],[400,500]])
            self.assertNotIn('sizes',second)
            self.assertNotEqual(first['image'],second['image'])
            for result in [first,second]:
                png=Path(result['image']).read_bytes()
                self.assertEqual(png[:8],b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II',png[16:24]),(result['width'],result['height']))
            self.assertGreater(second['width'],first['width'])
            self.assertEqual(bridge.render_pdf(fixture,999,900,cache)['page'],1)
    def test_high_resolution_page_matches_png_and_selection(self):
        with tempfile.TemporaryDirectory() as cache:
            fixture=Path(__file__).with_name('fixture.pdf')
            page=bridge.render_pdf(fixture,0,2800,cache)
            self.assertEqual((page['width'],page['height']), (2800,3500))
            with Path(page['image']).open('rb') as image:
                self.assertEqual(struct.unpack('>II',image.read(24)[16:24]),(2800,3500))
            first=next(c for c in page['chars'] if c['t']=='H')
            self.assertTrue(0.05 < first['r'][0] < 0.12)
            self.assertTrue(0.45 < first['r'][1] < 0.55)

    def test_broken_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'broken.pdf';path.write_bytes(b'not a pdf')
            with self.assertRaises(Exception):bridge.render_pdf(path,0,600,folder)
    def test_text_positions_match_rendered_page(self):
        with tempfile.TemporaryDirectory() as folder:
            result=bridge.render_pdf(Path(__file__).with_name('fixture.pdf'),0,800,folder)
            self.assertIn('Herdr PDF viewer', ''.join(c['t'] for c in result['chars']))
            first=next(c for c in result['chars'] if c['t']=='H')
            self.assertTrue(0.05 < first['r'][0] < 0.12)
            self.assertTrue(0.45 < first['r'][1] < 0.55)
            for c in result['chars']:
                if c['r']:
                    self.assertTrue(all(0<=v<=1 for v in c['r']))

if __name__=='__main__':unittest.main()
