"""Guard MPS requests; the workshop may reuse its server-owned resident worker."""
import datetime
import fcntl
import json
import os
import re
import subprocess
import time
from pathlib import Path

import numpy as np
from wevisone_vl.engine import InferenceResult
from model_profiles import require_profile as get_model_profile
from resource_metrics import read_system_command as command, parse_swap_used_mb, parse_memory_free_percent

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUTPUT = ROOT/'outputs/wevisone-vl'
PYTHON = os.environ.get('PCB_WEVISONE_PYTHON', '/path/to/wevisone/.venv/bin/python')

def swap_mb():
    return parse_swap_used_mb(command('sysctl','vm.swapusage'))

def memory_percent():
    return parse_memory_free_percent(command('memory_pressure','-Q'))

def preflight():
    process_text=command('ps','-axo','pid,comm,args')
    conflicts=[]
    for line in process_text.splitlines():
        low=line.lower()
        if any(x in low for x in ('omlx serve','omlx.app/','ollama serve','llama-server','mlx_lm.server','mlx_vlm','splash serve','comfyui/main.py','comfyui main.py','lm studio.app/')):
            conflicts.append(line.strip())
    p=memory_percent()
    state={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'memory_free_percent':p,'swap_used_mb':swap_mb(),'conflicting_processes':conflicts}
    if conflicts: raise RuntimeError('Another local ML runtime is active; no process was stopped. '+str(conflicts))
    if p<30: raise RuntimeError(f'Preflight needs >=30% available memory; observed {p}%.')
    return state

class GuardedEngine:
    model_name_or_path='tencent/WeVisOne-VL-2B · MPS BF16'

    def predict(self,image,**kwargs):
        stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        out=OUTPUT/'runs'/stamp
        out.mkdir(parents=True)
        with (OUTPUT/'inference.lock').open('a+') as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('An inference is already running.')
            state=preflight()
            (out/'preflight.json').write_text(json.dumps(state,indent=2)+'\n')
            image.save(out/'input.png')
            fields={k:kwargs.pop(k) for k in ('task','query','prompt','decode_matting','vision_max_pixels','model_size') if k in kwargs}
            req={'image':str(out/'input.png'),**fields,'generation_kwargs':kwargs}
            (out/'request.json').write_text(json.dumps(req,indent=2)+'\n')
            env=os.environ.copy()
            env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',PYTORCH_ENABLE_MPS_FALLBACK='0',HF_HOME=os.environ.get('HF_HOME', str(Path.home()/'.cache/huggingface')))
            start=time.monotonic()
            samples=[]
            reason=None
            if os.environ.get('PCB_WEVISONE_SESSION'):
                from resident_session import supervised_request
                supervised_request(out/'request.json', state['swap_used_mb'],
                                   memory_fn=memory_percent, swap_fn=swap_mb, command=command)
                data=json.loads((out/'result.json').read_text())
                with np.load(out/'masks.npz') as archive:
                    masks=[archive[k].copy() for k in archive.files]
                result=InferenceResult(response=data['response'],prompt=data['prompt'],boxes=data['seg_boxes_normalized_xyxy'],masks=masks,latency_s=data['latency_s'])
                result.generation=json.loads((out/'generation.json').read_text())
                result.run_directory=str(out)
                return result
            with (out/'worker.log').open('w') as log:
                proc=subprocess.Popen([PYTHON,str(HERE/'worker.py'),str(out/'request.json')],env=env,stdout=log,stderr=subprocess.STDOUT)
                try:
                    while proc.poll() is None:
                        time.sleep(2)
                        if proc.poll() is not None: break
                        rss=int(command('ps','-o','rss=','-p',str(proc.pid)).strip())*1024
                        mem=memory_percent()
                        swap=swap_mb()
                        sample={'elapsed_s':round(time.monotonic()-start,2),'rss_bytes':rss,'memory_free_percent':mem,'swap_used_mb':swap}
                        samples.append(sample)
                        if sample['elapsed_s']>300: reason='300 second request limit'
                        elif rss>12*1024**3: reason='12 GiB child RSS limit'
                        elif mem<15: reason='system available memory below 15%'
                        elif swap-state['swap_used_mb']>2048: reason='swap grew more than 2 GiB'
                        if reason:
                            proc.terminate()
                            try: proc.wait(timeout=10)
                            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                            break
                finally:
                    if proc.poll() is None: proc.terminate(); proc.wait(timeout=10)
                    (out/'supervision.json').write_text(json.dumps({'child_pid':proc.pid,'returncode':proc.returncode,'stop_reason':reason,'samples':samples},indent=2)+'\n')
            if reason: raise RuntimeError(f'Stopped: {reason}; logs: {out}')
            if proc.returncode: raise RuntimeError(f'MPS request failed (exit {proc.returncode}); log: {out}/worker.log')
            data=json.loads((out/'result.json').read_text())
            with np.load(out/'masks.npz') as archive:
                masks=[archive[k].copy() for k in archive.files]
            print(f'WeVisOne result saved: {out}',flush=True)
            result=InferenceResult(response=data['response'],prompt=data['prompt'],boxes=data['seg_boxes_normalized_xyxy'],masks=masks,latency_s=data['latency_s'])
            result.generation=json.loads((out/'generation.json').read_text()) if (out/'generation.json').exists() else {}
            result.run_directory=str(out)
            return result
