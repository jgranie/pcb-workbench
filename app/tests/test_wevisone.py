"""Exercise job lifecycle and real CPU derivation with a labelled fake model.

No GPU model is loaded by these tests. The real model invocation remains unrun.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

from PIL import Image, ImageDraw
from pcb_workshop.__main__ import ROOT, run_pipeline, segment, load_config
from pcb_workshop.wevisone_jobs import ModelJobs
import numpy as np

FAKE_CONTROLLER = '''
import json,time,hashlib,sys
from pathlib import Path
from PIL import Image,ImageDraw
job=Path(sys.argv[1]);request=json.loads((job/'request.json').read_text())
time.sleep(.4)
photo=Image.open(job/'input.png').convert('RGBA')
mask=Image.new('L',photo.size,0);ImageDraw.Draw(mask).rectangle((photo.width//2+20,10,photo.width-5,photo.height-5),fill=255)
if request.get('core'):
    scoped=Image.new('L',photo.size,0);scoped.paste(mask.crop(tuple(request['core'])),tuple(request['core'][:2]));mask=scoped
mask.save(job/'alpha.png');photo.putalpha(mask);photo.save(job/'cutout.png')
evidence={'source_sha256':request['source_sha256'],'alpha_sha256':hashlib.sha256((job/'alpha.png').read_bytes()).hexdigest(),'generation':{'response_complete':True},'execution':'simulation','model':'TEST ONLY - no inference'}
(job/'mask-provenance.json').write_text(json.dumps(evidence))
'''


def setup_fake(root):
    runtime = root / "fake-runtime";runtime.mkdir()
    (runtime / "guarded_engine.py").write_text("")
    (runtime / "worker.py").write_text("")
    controller = root / "fake-controller.py";controller.write_text(FAKE_CONTROLLER)
    return runtime, controller


class JobTests(unittest.TestCase):
    def prepare(self, temp):
        root = Path(temp)
        source = ROOT / "examples/synthetic.png"
        output = root / "result"
        run_pipeline(argparse.Namespace(input=source, output=output, config=None, layer="Original", gimp=None))
        runtime, controller = setup_fake(root)
        jobs = ModelJobs(output, shared_runtime=runtime, runtime=sys.executable, controller=controller)
        return output, jobs

    def wait_terminal(self, jobs, identity):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = jobs.state(identity)
            if state["status"] not in ("running", "cancelling", "deriving"):
                return state
            time.sleep(.02)
        self.fail("Fake job failed to terminate")

    def test_explicit_launch_single_job_review_and_separate_cpu_result(self):
        with tempfile.TemporaryDirectory() as temp:
            output,jobs = self.prepare(temp)
            before = (output / "workspace.json").read_bytes()
            self.assertEqual(jobs.capabilities()["jobs"], [])
            state = jobs.start()
            with self.assertRaisesRegex(ValueError, "déjà"):
                jobs.start()
            ready = self.wait_terminal(jobs,state["id"])
            self.assertEqual(ready["status"],"ready",ready)
            with self.assertRaisesRegex(ValueError,"revue"):
                jobs.derive(state["id"],False)
            jobs.derive(state["id"],True)
            derived = self.wait_terminal(jobs,state["id"])
            self.assertEqual(derived["status"],"derived",derived)
            destination = jobs.result_root(state["id"])
            self.assertEqual(before,(output / "workspace.json").read_bytes())
            provenance = json.loads((destination / "provenance.json").read_text())
            self.assertFalse(provenance["standalone_from_original"])
            self.assertEqual(provenance["pipeline_mode"],"assisted_background_mask")
            self.assertEqual(provenance["background_mask"]["evidence"]["execution"],"simulation")
            scan=json.loads((destination / "scan.json").read_text())
            for route in scan["routes"]:
                self.assertTrue(all(x>=260 for x,y in route["points"]),"A route escaped the explicitly accepted board mask")
            self.assertEqual(json.loads((destination/"image.json").read_text()),json.loads((output/"image.json").read_text()))
            jobs.close()

    def test_epoxy_second_pass_preserves_board_thresholds_and_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            output,jobs = self.prepare(temp)
            with self.assertRaisesRegex(ValueError,"d'abord"):
                jobs.start("epoxy")
            with self.assertRaisesRegex(ValueError,"inconnu"):
                jobs.start("unknown")
            first=jobs.start();self.wait_terminal(jobs,first["id"])
            jobs.derive(first["id"],True)
            self.assertEqual(self.wait_terminal(jobs,first["id"])["status"],"derived")
            parent=jobs.result_root(first["id"])
            saved=(parent/"workspace.json").read_bytes()
            state=jobs.start("epoxy",first["id"])
            ready=self.wait_terminal(jobs,state["id"])
            self.assertEqual(ready["status"],"ready",ready)
            self.assertTrue((jobs.directory(state["id"])/"raw-epoxy.png").exists())
            jobs.derive(state["id"],True)
            derived=self.wait_terminal(jobs,state["id"])
            self.assertEqual(derived["status"],"derived",derived)
            child=jobs.result_root(state["id"])
            self.assertEqual((parent/"board.png").read_bytes(),(child/"board.png").read_bytes())
            a=json.loads((parent/"segmentation-diagnostics.json").read_text())
            b=json.loads((child/"segmentation-diagnostics.json").read_text())
            self.assertEqual(a["solder_foreground_threshold"],b["solder_foreground_threshold"])
            self.assertEqual(a["threshold"],b["threshold"])
            self.assertEqual(saved,(parent/"workspace.json").read_bytes())
            self.assertEqual(json.loads((child/"provenance.json").read_text())["pipeline_mode"],"assisted_epoxy_mask")
            mask=np.array(Image.open(child/"mask.png"))>0
            keep=np.array(Image.open(child/"external-material-mask.png"))>0
            self.assertFalse(np.any(mask & ~keep))
            # A subsequent section keeps the previously accepted exclusion.
            next_state=jobs.start("epoxy",state["id"],section=7)
            next_ready=self.wait_terminal(jobs,next_state["id"])
            self.assertEqual(next_ready["status"],"ready",next_ready)
            scoped=np.array(Image.open(jobs.directory(next_state["id"])/"alpha.png"))>0
            request=json.loads((jobs.directory(next_state["id"])/"request.json").read_text())
            x,y,u,v=request["core"]
            outside=np.ones(keep.shape,dtype=bool);outside[y:v,x:u]=False
            self.assertTrue(np.array_equal(scoped[outside],keep[outside]))
            self.assertFalse(np.any(scoped & ~keep))
            jobs.close()

    def test_unavailable_4b_never_falls_back_to_2b(self):
        with tempfile.TemporaryDirectory() as temp:
            output,jobs=self.prepare(temp)
            with self.assertRaisesRegex(ValueError,"4B.*absent"):
                jobs.start(settings={"model_size":"4B"})
            self.assertEqual(jobs.capabilities()["jobs"],[])
            jobs.close()

    def test_cancel_has_no_retry_or_applied_mask(self):
        with tempfile.TemporaryDirectory() as temp:
            output,jobs = self.prepare(temp)
            state=jobs.start();jobs.cancel(state["id"])
            result=self.wait_terminal(jobs,state["id"])
            self.assertEqual(result["status"],"cancelled")
            self.assertFalse((output/"derived").exists())
            self.assertEqual(len(jobs.capabilities()["jobs"]),1)
            jobs.close()

    def test_tampered_source_and_mask_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            output,jobs = self.prepare(temp)
            state=jobs.start();self.wait_terminal(jobs,state["id"])
            (jobs.directory(state["id"])/"alpha.png").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError,"changé"):
                jobs.derive(state["id"],True)
            jobs.close()
            (output/"original.png").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError,"changé"):
                jobs.start()


if __name__=="__main__":unittest.main()
