import json
from pathlib import Path
import tempfile
import sys
import test_wevisone as job_tests
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from pcb_workshop.image_import import upload,folder_for,select_layer
from pcb_workshop.__main__ import ROOT
from pcb_workshop.server import validate_workspace
from pcb_workshop.wevisone_jobs import ModelJobs


class ImportTests(unittest.TestCase):
    def test_png_opens_empty_without_any_subprocess(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);png=ROOT/'examples/synthetic.png';source=png.read_bytes()
            with patch('subprocess.Popen',side_effect=AssertionError('No detection or model')):
                result=upload(root,'photo.png',source)
            selected=folder_for(root,result['id'])/'workspace'
            original=np.array(Image.open(png).convert('RGBA'))
            self.assertTrue(np.array_equal(np.array(Image.open(selected/'original.png')),original))
            w=json.loads((selected/'workspace.json').read_text());validate_workspace(w,w)
            self.assertEqual(w['traceScan']['routes'],[])
            self.assertEqual(json.loads((selected/'candidates.json').read_text())['candidates'],[])
            self.assertFalse(json.loads((selected/'provenance.json').read_text())['detections_run'])
            self.assertEqual((folder_for(root,result['id'])/'source.png').read_bytes(),source)
            jobs=ModelJobs(root,runtime='/no-runtime',shared_runtime=root/'no-runtime')
            self.assertEqual(jobs.result_root(result['id']),selected.resolve())
            with self.assertRaises(ValueError):folder_for(root,'../../escape')
            with self.assertRaises(ValueError):upload(root,'file.exe',b'invalid')

    def test_new_image_can_use_model_jobs_without_root_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);result=upload(root,'new.png',(ROOT/'examples/synthetic.png').read_bytes())
            runtime,controller=job_tests.setup_fake(root)
            jobs=ModelJobs(root,runtime=sys.executable,shared_runtime=runtime,controller=controller)
            first=jobs.start('board',source_result=result['id'])
            ready=job_tests.JobTests.wait_terminal(self,jobs,first['id'])
            self.assertEqual(ready['status'],'ready',ready)
            crop=jobs.apply(first['id'],source_result=result['id'])
            self.assertTrue((jobs.result_root(result['id'])/'preprocessing'/crop['id']/'original-cropped.png').exists())
            jobs.close()

    def test_xcf_selection_is_by_native_path_not_ambiguous_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def fake(source,out,layer,gimp,**options):
                inventory={'layers':[{'name':'same','native_path':[0],'is_group':False,'size':[20,20]},{'name':'same','native_path':[1],'is_group':False,'size':[20,20]}]}
                if options.get('inventory'):return out/'extracted.png',inventory
                self.assertEqual(options['native_path'],[1])
                Image.new('RGBA',(20,20),(20,40,80,128)).save(out/'extracted.png')
                return out/'extracted.png',{'selected':[1]}
            with patch('pcb_workshop.image_import.extract_xcf',side_effect=fake):
                value=upload(root,'layers.xcf',b'fake-xcf')
                self.assertEqual(value['status'],'choose_layer')
                with self.assertRaises(ValueError):select_layer(root,value['id'],[100])
                result=select_layer(root,value['id'],[1])
            with Image.open(folder_for(root,value['id'])/'workspace/original.png') as image:self.assertEqual(image.getextrema()[3],(128,128))
