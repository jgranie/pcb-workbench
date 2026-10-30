import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pcb_workshop.image_import import upload
from pcb_workshop.__main__ import ROOT
from pcb_workshop.wevisone_jobs import ModelJobs
from pcb_workshop.solder_model import start, finish
from pcb_workshop.model_settings import validate
from test_wevisone import setup_fake

FAKE='''import json,sys,time
from pathlib import Path
j=Path(sys.argv[1]);r=json.loads((j/'request.json').read_text());q=r['settings']['query']
if q=='wait':time.sleep(30)
n=24 if r['section'] is None else 1
(j/'manifest.json').write_text(json.dumps({'status':'complete','completed':[{'generation':{'response_complete':True}}]*(n-1 if q=='incomplete' else n)}))
result={'source_sha256':r['source_sha256'],'source_crop':r['source_crop'],'candidates':[{'id':'PAD-Wfake','coords':[10,10,30,30]}]}
(j/'detection.json').write_text(json.dumps(result))
'''


class SolderModelTests(unittest.TestCase):
    def setup(self,temp):
        root=Path(temp);selected=upload(root,'synthetic.png',(ROOT/'examples/synthetic.png').read_bytes());runtime,controller=setup_fake(root)
        controller.write_text(FAKE)
        jobs=ModelJobs(root,runtime=sys.executable,shared_runtime=runtime,controller=controller)
        return jobs,selected['id']

    def terminal(self,jobs,identity):
        until=time.monotonic()+6
        while time.monotonic()<until:
            state=jobs.state(identity)
            if state['status'] not in ('running','cancelling'):return state
            time.sleep(.03)
        self.fail('Job did not finish')

    def test_ready_and_no_workspace_write_and_shared_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs,source=self.setup(temp);path=jobs.result_root(source)/'workspace.json';before=path.read_bytes()
            state=start(jobs,{'source_result':source,'input':'original','section':0})
            done=self.terminal(jobs,state['id']);self.assertEqual(done['status'],'ready',done)
            self.assertEqual(done['total_tiles'],1);self.assertEqual(path.read_bytes(),before)
            request=json.loads((jobs.directory(state['id'])/'request.json').read_text())
            self.assertEqual(request['settings']['max_new_tokens'],2048)
            waiting=start(jobs,{'source_result':source,'input':'original','settings':{'query':'wait'}})
            try:
                with self.assertRaisesRegex(ValueError,'cours'):start(jobs,{'source_result':source,'input':'original'})
                with self.assertRaisesRegex(ValueError,'cours'):jobs.start(source_result=source)
                jobs.cancel(waiting['id']);self.assertEqual(self.terminal(jobs,waiting['id'])['status'],'cancelled')
            finally:jobs.close()
            self.assertEqual(path.read_bytes(),before)

    def test_incomplete_rejected_and_profiles_and_budgets_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs,source=self.setup(temp)
            for value in ({'settings':{'model_size':'4B'}},{'settings':{'max_new_tokens':2049}},{'section':24},{'input':'cropped'}):
                with self.assertRaises(ValueError):start(jobs,{'source_result':source,'input':'original',**value})
            state=start(jobs,{'source_result':source,'input':'original','settings':{'query':'incomplete'}})
            self.assertEqual(self.terminal(jobs,state['id'])['status'],'failed');jobs.close()
        with self.assertRaises(ValueError):validate('board',{'max_new_tokens':513})
        self.assertEqual(validate('solders')['model_size'],'2B')

    def test_finish_distinguishes_duplicate_identity_from_invalid_coordinates(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs,source=self.setup(temp)
            state=start(jobs,{'source_result':source,'input':'original','section':0})
            done=self.terminal(jobs,state['id']);self.assertEqual(done['status'],'ready',done)
            job=jobs.directory(state['id']);original=json.loads((job/'detection.json').read_text())
            for bad,message in [([{'id':'same','coords':[10,10,30,30]}]*2,'identifiant en double'),
                                ([{'id':'point','coords':[-1,10,30,30]}],'coordonnées invalides'),
                                ([{'id':'point','coords':[True,10,30,30]}],'coordonnées invalides')]:
                (job/'detection.json').write_text(json.dumps({**original,'candidates':bad}))
                checked={**done,'status':'running'};finish(jobs,job,checked,0)
                self.assertEqual(checked['status'],'failed');self.assertIn(message,checked['message'])
            from pcb_workshop.solder_ids import identify_candidates
            kept=identify_candidates([{'coords':[10,10,30,30]}]*2,'source')
            (job/'detection.json').write_text(json.dumps({**original,'candidates':kept}))
            checked={**done,'status':'running'};finish(jobs,job,checked,0)
            self.assertEqual(checked['status'],'ready',checked);self.assertEqual(checked['candidates'],2)
            jobs.close()

    def test_real_controller_and_runner_forward_exact_model_and_stop_incomplete(self):
        for incomplete in (False,True):
            with self.subTest(incomplete=incomplete),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);shared=root/'work/wevisone-vl';shared.mkdir(parents=True);job=root/'job';job.mkdir()
                from PIL import Image
                Image.new('RGBA',(480,360),(0,150,100,255)).save(job/'source.png')
                import hashlib
                request={'shared_runtime':str(shared),'kind':'solders','prepared_sha256':hashlib.sha256((job/'source.png').read_bytes()).hexdigest(),
                         'source_sha256':'source','source_crop':None,'mask_sha256':None,'input':'original','section':None,
                         'settings':validate('solders',{'model_size':'4B','query':'incomplete' if incomplete else 'solders'})}
                (job/'request.json').write_text(json.dumps(request))
                for name in ('detection_job_runner.py','tiled_detection.py'):shutil.copyfile(ROOT.parent/'wevisone-vl'/name,shared/name)
                (root/'outputs/wevisone-vl/jobs').mkdir(parents=True)
                engine="""import json,time
from pathlib import Path
from types import SimpleNamespace
PYTHON=PYTHON_VALUE
OUTPUT=None
get_model_profile=lambda s:{'model_id':'TEST-'+s,'revision':'test-revision','size':s}
preflight=lambda:{'swap_used_mb':0}
memory_percent=lambda:80
swap_mb=lambda:0
class GuardedEngine:
 def predict(self,image,**kwargs):
  folder=OUTPUT/'runs'/str(time.time_ns());folder.mkdir(parents=True)
  (folder/'request.json').write_text(json.dumps(kwargs))
  (folder/'result.json').write_text(json.dumps({'predictions':{'solders':[{'type':'box','coords':[10,10,30,30]},{'type':'box','coords':[10,10,30,30]},{'type':'box','coords':[11,10,31,30]}]}}))
  (folder/'generation.json').write_text(json.dumps({'response_complete':kwargs['query']!='incomplete'}))
  (folder/'metrics.json').write_text(json.dumps({'inference_seconds':.01}))
  return SimpleNamespace(run_directory=str(folder))
""".replace('PYTHON_VALUE',repr(sys.executable))
                (shared/'guarded_engine.py').write_text(engine)
                proc=subprocess.run([sys.executable,str(ROOT/'pcb_workshop/wevisone_controller.py'),str(job)],capture_output=True,text=True,timeout=20)
                manifest=json.loads((job/'manifest.json').read_text())
                if incomplete:
                    self.assertNotEqual(proc.returncode,0);self.assertEqual(len(manifest['attempts']),1);self.assertEqual(manifest['completed'],[])
                    self.assertFalse((job/'detection.json').exists())
                else:
                    self.assertEqual(proc.returncode,0,proc.stderr);result=json.loads((job/'detection.json').read_text())
                    self.assertEqual(result['model_id'],'TEST-4B');self.assertEqual(result['llm_calls'],24);self.assertFalse(result['traces_run'])
                    self.assertEqual(len({p['id'] for p in result['candidates']}),len(result['candidates']))
                    self.assertGreater(len(result['candidates']),len({tuple(p['coords']) for p in result['candidates']}))
                    calls=[json.loads(p.read_text()) for p in (job/'engine/runs').glob('*/request.json')]
                    self.assertEqual(len(calls),24)
                    self.assertTrue(all(c['model_size']=='4B' and c['max_new_tokens']==2048 and c['decode_matting'] is False for c in calls))

if __name__=='__main__':unittest.main()
