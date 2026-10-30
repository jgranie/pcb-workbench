"""Offline WeVisOne inference, with optional server-owned model residency."""
import contextlib
import json
import os
import sys
import time
import threading
from pathlib import Path

os.environ['HF_DEACTIVATE_ASYNC_LOAD'] = '1'

import numpy as np
import torch
from PIL import Image
from wevisone_vl import WeVisOneVL
from wevisone_vl.visualization import save_result
from generation_audit import analyze_generation
from model_profiles import require_profile


class ModelWorker:
    def __init__(self):
        self.engine = None
        self.profile = None
        self.generated = {}
        self.requests = 0

    def prepare(self, profile, pixels):
        reused = self.engine is not None
        if reused and profile != self.profile:
            raise RuntimeError('Resident model identity changed; restart the session explicitly')
        if not reused:
            model = Path(profile['path'])
            if profile['size'] == '2B':
                preparation = json.loads((model / 'preparation.json').read_text())
                if not preparation.get('all_equal_to_source_cast') or preparation.get('verified_tensors') != 626:
                    raise RuntimeError('The prepared BF16 weights have not passed tensor verification')
            if not torch.backends.mps.is_available():
                raise RuntimeError('MPS unavailable; CPU fallback is not authorized')
            self.engine = WeVisOneVL(str(model), device='mps', dtype='bfloat16', backend='transformers',
                                      max_pixels=pixels, decoder_batch_size=1)
            self.profile = profile
            original_generate = self.engine.model.generate
            def audited_generate(*args, **kwargs):
                sequences = original_generate(*args, **kwargs)
                ids = sequences[0, kwargs['input_ids'].shape[1]:].detach().cpu().tolist()
                eos = self.engine.tokenizer.eos_token_id
                eos_ids = eos if isinstance(eos, list) else [eos]
                self.generated.update(count=len(ids), eos_reached=bool(ids and ids[-1] in eos_ids))
                grid = kwargs.get('image_grid_thw')
                if grid is not None:
                    g = grid[0].detach().cpu().tolist()
                    patch = int(self.engine.processor.image_processor.patch_size)
                    self.generated['vision_size'] = [int(g[2])*patch, int(g[1])*patch]
                return sequences
            self.engine.model.generate = audited_generate
        elif self.engine.max_pixels != pixels:
            # Reconfigure preprocessing only; preserve weights and the matting decoder.
            from transformers import AutoProcessor
            processor = AutoProcessor.from_pretrained(profile['path'], min_pixels=self.engine.min_pixels,
                                                       max_pixels=pixels, trust_remote_code=True)
            processor.tokenizer = self.engine.tokenizer
            self.engine.processor = processor
            self.engine.max_pixels = pixels
        return reused

    def predict(self, request_path, size=None, status_path=None):
        request_path = Path(request_path)
        request = json.loads(request_path.read_text())
        profile = require_profile(request.get('model_size', '2B'))
        if size is not None and profile['size'] != size:
            raise RuntimeError('Requested model differs from the resident session')
        out = request_path.parent
        with (out / 'worker.log').open('a') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            started = time.perf_counter()
            pixels = int(request.get('vision_max_pixels', 524288))
            if not 16384 <= pixels <= 6291456:
                raise ValueError('Vision pixel limit outside supported experiment range')
            print(json.dumps({'stage': 'loading' if self.engine is None else 'reusing',
                              'model': profile['path'], 'device': 'mps', 'dtype': 'bfloat16'}), flush=True)
            reused = self.prepare(profile, pixels)
            load_seconds = time.perf_counter() - started
            print(json.dumps({'stage': 'loaded', 'model_reused': reused, 'seconds': load_seconds,
                              'device': str(next(self.engine.model.parameters()).device),
                              'dtype': str(next(self.engine.model.parameters()).dtype)}), flush=True)
            if status_path:
                pending = status_path.with_suffix('.pending')
                pending.write_text(json.dumps({'loaded': True, 'model_size': profile['size'],
                                               'completed_requests': self.requests}))
                os.replace(pending, status_path)
            self.generated.clear()
            memory_stop = threading.Event()
            peaks = {'mps_allocated_peak_bytes': 0, 'mps_driver_peak_bytes': 0}
            def sample_memory():
                while not memory_stop.is_set():
                    peaks['mps_allocated_peak_bytes'] = max(peaks['mps_allocated_peak_bytes'], torch.mps.current_allocated_memory())
                    peaks['mps_driver_peak_bytes'] = max(peaks['mps_driver_peak_bytes'], torch.mps.driver_allocated_memory())
                    memory_stop.wait(.5)
            memory_thread = threading.Thread(target=sample_memory, daemon=True)
            memory_thread.start()
            try:
                with Image.open(request['image']) as opened:
                    image = opened.convert('RGB')
                kwargs = dict(request.get('generation_kwargs', {}))
                kwargs['max_new_tokens'] = min(4096, max(1, int(kwargs.get('max_new_tokens', 512))))
                result = self.engine.predict(image, task=request.get('task', 'segmentation'),
                                             query=request.get('query', 'copper traces'), prompt=request.get('prompt') or None,
                                             decode_matting=request.get('decode_matting', True), **kwargs)
                torch.mps.synchronize()
            finally:
                memory_stop.set()
                memory_thread.join(timeout=2)
            audit = analyze_generation(result.response, self.generated['count'], kwargs['max_new_tokens'], self.generated['eos_reached'])
            audit['vision_size'] = self.generated.get('vision_size')
            (out / 'generation.json').write_text(json.dumps(audit, indent=2) + '\n')
            paths = save_result(out, image, result)
            np.savez_compressed(out / 'masks.npz', **{f'mask_{i}': v for i, v in enumerate(result.masks)})
            metrics = {'stage': 'complete', 'model_id': profile['model_id'], 'model_revision': profile['revision'],
                       'model_size': profile['size'], 'prepared_model_path': profile['path'], 'load_dtype': 'bfloat16',
                       'async_load': False, 'device': 'mps', 'dtype': 'bfloat16', 'max_pixels': pixels, **peaks,
                       'image_size': list(image.size), 'max_new_tokens': kwargs['max_new_tokens'], 'generation': audit,
                       'mask_count': len(result.masks), 'total_seconds': time.perf_counter()-started,
                       'inference_seconds': result.latency_s, 'model_load_seconds': load_seconds,
                       'model_reused': reused, 'worker_pid': os.getpid(),
                       'mps_allocated_bytes': torch.mps.current_allocated_memory(),
                       'mps_driver_bytes': torch.mps.driver_allocated_memory(), 'paths': {k: str(v) for k, v in paths.items()}}
            (out / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
            print(json.dumps(metrics), flush=True)
            self.requests += 1
            if status_path:
                pending.write_text(json.dumps({'loaded': True, 'model_size': profile['size'],
                                               'completed_requests': self.requests}))
                os.replace(pending, status_path)
            # Keep weights only; request images, outputs, KV caches and audited tokens are local.
            self.generated.clear()


def main():
    worker = ModelWorker()
    if sys.argv[1] == '--serve':
        from resident_session import serve
        serve(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), worker.predict)
    else:
        worker.predict(Path(sys.argv[1]))


if __name__ == '__main__':
    main()
