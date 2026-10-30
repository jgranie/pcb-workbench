"""Apply/undo persistence contract: crop composition never starts detection."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
import test_wevisone as job_tests
from pcb_workshop.crops import crop_root


class CropTests(unittest.TestCase):
    prepare = job_tests.JobTests.prepare
    wait_terminal = job_tests.JobTests.wait_terminal

    def test_apply_is_image_only_incremental_and_reloadable(self):
        with tempfile.TemporaryDirectory() as temp:
            output,jobs = self.prepare(temp)
            before={p.name:p.read_bytes() for p in output.iterdir() if p.is_file()}
            first=jobs.start();ready=self.wait_terminal(jobs,first['id'])
            self.assertEqual(ready['status'],'ready',ready)
            with patch('subprocess.Popen', side_effect=AssertionError('Apply must not run any subprocess')):
                crop=jobs.apply(first['id'])
            folder=crop_root(output,crop['id'])
            self.assertFalse(json.loads((folder/'crop.json').read_text())['detections_run'])
            alpha=np.array(Image.open(folder/'keep.png'))
            image=np.array(Image.open(folder/'original-cropped.png'))
            original=np.array(Image.open(output/'original.png').convert('RGBA'))
            self.assertTrue(np.array_equal(image[:,:,:3],original[:,:,:3]))
            self.assertTrue(np.array_equal(image[:,:,3],alpha))
            second=jobs.start('epoxy',source_crop=crop['id'],section=7)
            self.assertEqual(self.wait_terminal(jobs,second['id'])['status'],'ready')
            with patch('subprocess.Popen', side_effect=AssertionError('No detector')):
                next_crop=jobs.apply(second['id'],previous=crop['id'])
            next_folder=crop_root(output,next_crop['id'])
            self.assertFalse(np.any((np.array(Image.open(next_folder/'keep.png'))>0)&(alpha==0)))
            self.assertEqual(json.loads((next_folder/'crop.json').read_text())['parent'],crop['id'])
            self.assertTrue(crop_root(output,crop['id']).is_dir()) # Undo still loads the old snapshot.
            for name,data in before.items():self.assertEqual((output/name).read_bytes(),data,name)
            self.assertFalse((output/'derived').exists())
            jobs.close()

    def test_tamper_and_cross_source_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            output,jobs=self.prepare(temp)
            first=jobs.start();self.wait_terminal(jobs,first['id'])
            crop=jobs.apply(first['id']);folder=crop_root(output,crop['id'])
            with self.assertRaisesRegex(ValueError,'invalide'):crop_root(output,'../x')
            (folder/'keep.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'modifié'):crop_root(output,crop['id'])
            with self.assertRaisesRegex(ValueError,'modifié'):jobs.start('epoxy',source_crop=crop['id'])
            jobs.close()
