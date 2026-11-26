from pathlib import Path
import os
import struct
import subprocess
import tempfile
import unittest
import unittest.mock
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

    def test_several_pages_render_in_one_run(self):
        with tempfile.TemporaryDirectory() as cache:
            fixture=Path(__file__).with_name('fixture.pdf')
            both=bridge.render_pdf_pages(fixture,[0,1],900,cache,include_sizes=True,include_chars=[True,False])
            self.assertEqual((both['pages'],[page['page'] for page in both['rendered']]),(2,[0,1]))
            self.assertEqual(both['sizes'],[[400,500],[400,500]])
            first,second=both['rendered']
            self.assertTrue(first['chars'] and second['chars']==[])
            self.assertTrue(all(Path(page['image']).is_file() for page in both['rendered']))
            self.assertEqual(first,{k:v for k,v in bridge.render_pdf(fixture,0,900,cache).items() if k in first})
            with unittest.mock.patch.object(bridge,'MAX_BATCH_CHARS',1):
                limited=bridge.render_pdf_pages(fixture,[0,1],900,cache)
            self.assertEqual([page['page'] for page in limited['rendered']],[0],'A reply stops growing at the text budget')
            self.assertFalse(list(Path(cache).glob('*.part')))

    def test_helper_answers_a_request_for_several_pages(self):
        import json, sys
        with tempfile.TemporaryDirectory() as home:
            fixture=Path(__file__).with_name('fixture.pdf')
            request=dict(action='preview',source=str(fixture),pages=[1,0],width=700,chars=[True,False],sizes=True,job='f'*32)
            output=subprocess.run([sys.executable,'-X','utf8',bridge.__file__,'--hc','unused','--home',home,'--request',json.dumps(request)],
                                  capture_output=True,check=True,encoding='utf8').stdout
            reply=json.loads(output)
            self.assertTrue(reply['ok'],reply)
            self.assertEqual([page['page'] for page in reply['rendered']],[1,0])
            self.assertEqual((reply['pages'],len(reply['sizes']),len(reply['revision'])),(2,2,3))
            for page in reply['rendered']:
                self.assertNotIn('\\',page['image'])
                self.assertTrue((Path(home)/page['image']).is_file(),'Bitmaps are named from the app folder')
            self.assertTrue(reply['rendered'][0]['chars'] and reply['rendered'][1]['chars']==[])
            single=dict(action='preview',source=str(fixture),page=0,width=700,job='f'*32)
            output=subprocess.run([sys.executable,'-X','utf8',bridge.__file__,'--hc','unused','--home',home,'--request',json.dumps(single)],
                                  capture_output=True,check=True,encoding='utf8').stdout
            self.assertEqual(json.loads(output)['image'],reply['rendered'][1]['image'])

    def test_text_boxes_follow_page_rotation(self):
        import ctypes
        with tempfile.TemporaryDirectory() as cache:
            fixture=Path(__file__).with_name('fixture.pdf')
            bridge.render_pdf(fixture,0,600,cache)
            import pypdfium2 as pdfium
            with pdfium.PdfDocument(str(fixture)) as pdf:
                page=pdf[0]
                try:
                    for rotation in (0,90,180,270):
                        page.set_rotation(rotation)
                        width,height=(round(v*3) for v in page.get_size())
                        textpage=page.get_textpage()
                        try:
                            chars=bridge.page_chars(pdfium,page)
                            self.assertEqual(len(chars),textpage.count_chars())
                            checked=0
                            for index,char in enumerate(chars):
                                if not char['r']:continue
                                left,bottom,right,top=textpage.get_charbox(index)
                                points=[]
                                for x,y in ((left,bottom),(right,top),(left,top),(right,bottom)):
                                    dx=ctypes.c_int();dy=ctypes.c_int()
                                    pdfium.raw.FPDF_PageToDevice(page.raw,0,0,width,height,0,x,y,ctypes.byref(dx),ctypes.byref(dy))
                                    points.append((dx.value,dy.value))
                                expected=(min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))
                                actual=(char['r'][0]*width,char['r'][1]*height,char['r'][2]*width,char['r'][3]*height)
                                self.assertTrue(all(abs(a-e)<=1 for a,e in zip(actual,expected)),(rotation,index,actual,expected))
                                checked+=1
                            self.assertGreater(checked,10)
                        finally:textpage.close()
                finally:page.close()

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
