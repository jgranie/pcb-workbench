import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from pcb_workshop.__main__ import ROOT, load_config, segment
from pcb_workshop.image_import import upload
from pcb_workshop.solder_detection import propose, validate, defaults, sha
from pcb_workshop.server import validate_workspace


class SolderTests(unittest.TestCase):
    def prepare(self, root):
        value=upload(root,'synthetic.png',(ROOT/'examples/synthetic.png').read_bytes())
        return Path(root)/'imports'/value['id']/'workspace'

    def test_standalone_matches_existing_detector_and_never_writes_or_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=self.prepare(temp);before={p.name:sha(p) for p in root.iterdir() if p.is_file()}
            rgb=np.array(Image.open(root/'original.png').convert('RGB'))
            _,_,_,old,_=segment(rgb,load_config(None))
            with patch('subprocess.Popen',side_effect=AssertionError('No model or trace process')):
                result=propose(root,{'input':'original'})
            self.assertEqual(len(result['candidates']),6)
            self.assertEqual([{k:v for k,v in p.items() if k!='id'} for p in result['candidates']],
                             [{k:v for k,v in p.items() if k!='id'} for p in old])
            self.assertEqual(before,{p.name:sha(p) for p in root.iterdir() if p.is_file()})
            self.assertEqual(result['llm_calls'],0);self.assertFalse(result['traces_run'])
            self.assertEqual(result['candidates'],propose(root,{'input':'original'})['candidates'])
            strict=propose(root,{'settings':{'solder_contrast':255}})
            self.assertEqual(strict['candidates'],[])
            partial=propose(root,{'settings':{'max_candidates':2}})
            self.assertTrue(partial['stats']['candidates_truncated'])
            self.assertEqual(partial['stats']['candidates_before_limit'],6)

    def test_crop_restricts_pixels_and_is_checked_without_blackening_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root=self.prepare(temp);full=propose(root,{})
            shape=Image.open(root/'original.png').size;folder=root/'preprocessing'/('a'*32);folder.mkdir(parents=True)
            keep=np.ones(shape[::-1],np.uint8)*255;keep[:,300:]=0
            Image.fromarray(keep).save(folder/'keep.png');Image.new('L',shape,255).save(folder/'board.png')
            original=Image.open(root/'original.png').convert('RGBA');original.putalpha(Image.fromarray(keep));original.save(folder/'original-cropped.png')
            receipt={'source_sha256':sha(root/'original.png'),'sha256':{n:sha(folder/n) for n in ('board.png','keep.png','original-cropped.png')}}
            (folder/'crop.json').write_text(json.dumps(receipt))
            result=propose(root,{'input':'cropped','source_crop':'a'*32})
            self.assertEqual(len(result['candidates']),4)
            self.assertTrue(all(c['coords'][2]<=300 for c in result['candidates']))
            self.assertEqual([c['coords'] for c in result['candidates']],[c['coords'] for c in full['candidates'] if c['coords'][2]<=300])
            Image.new('L',shape,0).save(folder/'keep.png')
            with self.assertRaisesRegex(ValueError,'modifié'):propose(root,{'input':'cropped','source_crop':'a'*32})
            with self.assertRaisesRegex(ValueError,'contour'):propose(root,{'input':'cropped'})
            with self.assertRaises(ValueError):propose(root,{'input':'cropped','source_crop':'../escape'})

    def test_invalid_settings_and_geometry_are_refused(self):
        for settings in ({'solder_close_size':2},{'solder_min_area':500,'solder_max_area':100},{'solder_contrast':True},{'solder_min_circularity':float('nan')},{'method':'llm'},{'max_candidates':2000}):
            with self.assertRaises(ValueError):validate(settings)
        self.assertEqual(defaults()['solder_min_circularity'],.05)
        with tempfile.TemporaryDirectory() as temp:
            root=self.prepare(temp);w=json.loads((root/'workspace.json').read_text())
            w['solderDetection']=propose(root,{})
            validate_workspace(w,w)
            w['solderDetection']['candidates'][0]['coords']=[-1,0,3,3]
            with self.assertRaisesRegex(ValueError,'hors image'):validate_workspace(w,w)

if __name__=='__main__':unittest.main()
