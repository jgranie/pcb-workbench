"""Real IPC/process tests with simulated weights; no GPU inference."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image

SHARED = Path(__file__).resolve().parents[2] / 'wevisone-vl'
sys.path.insert(0, str(SHARED))
from resident_session import ResidentSession, supervised_request
sys.path.remove(str(SHARED))

FAKE_WORKER = '''
import json,os,sys,time
from pathlib import Path
from resident_session import serve
loads=requests=0
def predict(path,size,status):
 global loads,requests
 req=json.loads(path.read_text())
 if req.get('error'):raise RuntimeError('simulated request failure')
 if req.get('slow'):time.sleep(20)
 reused=loads>0
 if not reused:loads+=1
 requests+=1
 (path.parent/'reply.json').write_text(json.dumps({'pid':os.getpid(),'loads':loads,'requests':requests,'reused':reused,'size':size,'query':req['query'],'task':req['task'],'pixels':req['vision_max_pixels']}))
 status.write_text(json.dumps({'loaded':True,'model_size':size,'completed_requests':requests}))
serve(Path(sys.argv[2]),sys.argv[3],int(sys.argv[4]),predict)
'''

class ResidentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wv-test-')
        self.root = Path(self.temp.name)
        self.shared = self.root / 'work/wevisone-vl'
        self.shared.mkdir(parents=True)
        for name in ('resident_session.py', 'resource_metrics.py'):
            shutil.copyfile(SHARED / name, self.shared / name)
        (self.shared / 'worker.py').write_text(FAKE_WORKER)
        self.metrics = patch('resident_session.resources', return_value=(70, 0))
        self.metrics.start()
        self.session = ResidentSession(sys.executable, self.shared)

    def tearDown(self):
        self.session.close()
        self.metrics.stop()
        self.temp.cleanup()

    def request(self, size='2B', task='segmentation', query='board', pixels=524288, **extra):
        env = self.session.environment(size)
        folder = self.root / f'request-{time.monotonic_ns()}'
        folder.mkdir()
        path = folder / 'request.json'
        path.write_text(json.dumps({'query': query, 'task': task, 'vision_max_pixels': pixels, **extra}))
        with patch.dict(os.environ, env):
            supervised_request(path, 0, memory_fn=lambda: 70, swap_fn=lambda: 0, command=lambda *args: '100')
        return json.loads((folder / 'reply.json').read_text())

    def test_shared_weights_survive_tasks_sections_and_parameters(self):
        self.assertFalse(self.session.status()['running'])
        first = self.request()
        second = self.request(query='epoxy', pixels=262144)
        third = self.request(task='detection', query='solder terminals')
        for index, result in enumerate((first, second, third), 1):
            self.assertEqual(result['pid'], first['pid'])
            self.assertEqual(result['loads'], 1)
            self.assertEqual(result['requests'], index)
            self.assertEqual(result['reused'], index > 1)
        self.assertEqual(second['pixels'], 262144)
        self.assertEqual(third['query'], 'solder terminals')
        self.assertEqual(self.session.status()['completed_requests'], 3)
        for name in ('inference.lock', 'jobs/.batch.lock'):
            with (self.root / 'outputs/wevisone-vl' / name).open('a+') as handle:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.session.close()
        with (self.root / 'outputs/wevisone-vl/inference.lock').open('a+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertFalse(self.session.status()['running'])

    def test_model_change_and_explicit_release(self):
        first = self.request()
        old = self.session.process
        second = self.request(size='4B')
        self.assertIsNotNone(old.poll())
        self.assertNotEqual(first['pid'], second['pid'])
        self.assertFalse(second['reused'])
        self.assertEqual(second['size'], '4B')
        process = self.session.process
        self.session.close()
        self.assertIsNotNone(process.poll())
        self.assertFalse(self.request(size='4B')['reused'])

    def test_error_does_not_retry(self):
        with self.assertRaisesRegex(RuntimeError, 'simulated request failure'):
            self.request(error=True)
        self.session.process.wait(timeout=5)
        self.assertFalse(self.session.status()['running'])

    def test_idle_pressure_releases_weights(self):
        self.request()
        process = self.session.process
        with patch('resident_session.resources', return_value=(10, 0)), patch('resident_session.read_system_command', return_value='100'):
            process.wait(timeout=6)
        self.assertFalse(self.session.status()['running'])
        self.assertIn('15', self.session.reason)

    def test_request_pressure_stops_worker_without_retry(self):
        env = self.session.environment('2B')
        path = self.root / 'request.json'
        path.write_text(json.dumps({'query': 'board', 'task': 'segmentation', 'vision_max_pixels': 524288, 'slow': True}))
        with patch.dict(os.environ, env), self.assertRaisesRegex(RuntimeError, 'below 15'):
            supervised_request(path, 0, memory_fn=lambda: 10, swap_fn=lambda: 0, command=lambda *args: '100')
        self.session.process.wait(timeout=5)
        self.assertIn('below 15', json.loads((self.root / 'supervision.json').read_text())['stop_reason'])

class RealWorkerReuseTests(unittest.TestCase):
    def test_worker_retains_weights_and_reconfigures_only_processor(self):
        engines, processors = [], []
        class FakeEngine:
            def __init__(self, path, **options):
                engines.append(options)
                self.max_pixels, self.min_pixels = options['max_pixels'], 16384
                self.tokenizer = SimpleNamespace(eos_token_id=2)
                class Tokens:
                    def __getitem__(self, key):return self
                    def detach(self):return self
                    def cpu(self):return self
                    def tolist(self):return [100, 2]
                self.model = SimpleNamespace(generate=lambda **kwargs: Tokens(), parameters=lambda: iter([SimpleNamespace(device='mps', dtype='bfloat16')]))
                self.processor = SimpleNamespace()
            def predict(self, image, **kwargs):
                self.model.generate(input_ids=SimpleNamespace(shape=(1, 2)))
                return SimpleNamespace(response='<ref>s</ref><box><1><2><3><4></box>', masks=[], latency_s=.001)
        fake_torch = SimpleNamespace(backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
                                     mps=SimpleNamespace(synchronize=lambda: None, current_allocated_memory=lambda: 100,
                                                         driver_allocated_memory=lambda: 200))
        def save_result(out, image, result):
            (out/'result.json').write_text(json.dumps({'response': result.response, 'predictions': {}}))
            return {}
        fake_processor = SimpleNamespace(from_pretrained=lambda *args, **kwargs: processors.append(kwargs) or SimpleNamespace())
        with patch.dict(sys.modules, {'torch': fake_torch,
                                      'wevisone_vl': SimpleNamespace(WeVisOneVL=FakeEngine),
                                      'wevisone_vl.visualization': SimpleNamespace(save_result=save_result),
                                      'transformers': SimpleNamespace(AutoProcessor=fake_processor)}):
            sys.path.insert(0, str(SHARED))
            try:
                spec = importlib.util.spec_from_file_location('test_real_worker', SHARED / 'worker.py')
                module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                worker = module.ModelWorker()
                profile = {'size': '4B', 'path': '/fake/local', 'revision': 'fixed', 'model_id':'TEST-4B'}
                self.assertFalse(worker.prepare(profile, 524288))
                engine = worker.engine
                self.assertTrue(worker.prepare(profile, 524288))
                self.assertTrue(worker.prepare(profile, 262144))
                self.assertIs(engine, worker.engine)
                self.assertEqual(len(engines), 1)
                self.assertEqual(engines[0]['dtype'], 'bfloat16')
                self.assertEqual(engines[0]['device'], 'mps')
                self.assertEqual(processors, [{'min_pixels': 16384, 'max_pixels': 262144, 'trust_remote_code': True}])
                self.assertEqual(engine.max_pixels, 262144)
                with tempfile.TemporaryDirectory() as temporary, patch.object(module, 'require_profile', return_value=profile):
                    root = Path(temporary)
                    image = root/'image.png';Image.new('RGB', (20, 20)).save(image)
                    for index, query in enumerate(('epoxy', 'solder terminals')):
                        out = root/str(index);out.mkdir()
                        request = out/'request.json'
                        request.write_text(json.dumps({'model_size':'4B','image':str(image),'query':query,
                                                       'vision_max_pixels':262144,'generation_kwargs':{'max_new_tokens':128}}))
                        worker.predict(request)
                        metrics = json.loads((out/'metrics.json').read_text())
                        self.assertTrue(metrics['model_reused'])
                        self.assertTrue(metrics['generation']['response_complete'])
                        self.assertEqual(metrics['worker_pid'], os.getpid())
                        self.assertEqual(worker.generated, {})
                        with np.load(out/'masks.npz') as masks:self.assertEqual(masks.files, [])
                    self.assertEqual(len(engines), 1)
                with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                    worker.prepare({**profile, 'size': '2B'}, 262144)
            finally:
                sys.path.remove(str(SHARED))

if __name__ == '__main__':
    unittest.main()
