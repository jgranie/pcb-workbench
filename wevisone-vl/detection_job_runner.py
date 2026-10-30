"""Sequential, guarded detection for one frozen workshop job.

The production CLI always uses GuardedEngine. Dependency injection in run_job is
for unit tests; there is no synthetic CLI or production inference fallback.
"""
from pathlib import Path
import datetime
import fcntl
import hashlib
import json
import os
import shutil
import signal
import sys
import time
import uuid

from PIL import Image
from tiled_detection import globalize, stitch


def atomic_json(path, data):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.replace(temporary, path)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def freeze_source(directory, specification):
    """Composite the photographic source on black, independent of editor overlays."""
    source = specification['source']
    raw = (directory/'source.png').read_bytes()
    if hashlib.sha256(raw).hexdigest() != source['file_sha256']:
        raise ValueError('Frozen source checksum mismatch')
    with Image.open(directory/'source.png') as original:
        if original.size != (source['width'], source['height']):
            raise ValueError('Frozen source dimensions mismatch')
        rgba = original.convert('RGBA')
        image = Image.alpha_composite(Image.new('RGBA', rgba.size, (0, 0, 0, 255)), rgba).convert('RGB')
    image.save(directory/'input.png')
    source['rgb_sha256'] = hashlib.sha256(image.tobytes()).hexdigest()
    source['frozen_path'] = str(directory/'input.png')
    source['background'] = '#000000'
    return image


def run_job(directory, *, engine_factory=None, preflight_fn=None, memory_fn=None, swap_fn=None):
    directory = Path(directory).resolve()
    specification = json.loads((directory/'job.json').read_text())
    manifest = {**specification, 'status': 'running', 'started_at': now(),
                'completed': [], 'attempts': [], 'current_tile': None}
    proposals = []
    started = time.monotonic()
    old_handlers = {}

    def save():
        manifest['elapsed_seconds'] = round(time.monotonic()-started, 3)
        atomic_json(directory/'manifest.json', manifest)

    def assemble():
        candidates = stitch(proposals)
        atomic_json(directory/'raw-proposals.json', proposals)
        atomic_json(directory/'assembled.json', {
            'source_rgb_sha256': manifest['source'].get('rgb_sha256'),
            'width': manifest['source']['width'], 'height': manifest['source']['height'],
            'raw_count': len(proposals), 'candidate_count': len(candidates), 'candidates': candidates})

    def interrupt(signum, frame):
        # A second click must not interrupt GuardedEngine's worker cleanup.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt(f'Cancellation requested (signal {signum})')

    def cancellation_check():
        if (directory/'cancel.json').exists():
            raise KeyboardInterrupt('Cancellation requested by the workshop')

    for signum in (signal.SIGTERM, signal.SIGINT):
        old_handlers[signum] = signal.signal(signum, interrupt)
    save()
    try:
        # Keep a batch exclusive across server restarts and independent launchers.
        with (directory.parent/'.batch.lock').open('a+') as batch_lock:
            try:
                fcntl.flock(batch_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another workshop detection batch is running') from None
            cancellation_check()
            image = freeze_source(directory, manifest)
            assemble()
            save()
            if engine_factory is None:
                from guarded_engine import GuardedEngine, preflight, memory_percent, swap_mb
                engine_factory, preflight_fn, memory_fn, swap_fn = GuardedEngine, preflight, memory_percent, swap_mb
            if any(fn is None for fn in (preflight_fn, memory_fn, swap_fn)):
                raise ValueError('Runner guard dependencies must be complete')
            settings=specification.get('settings',{})
            if set(settings)-{'model_size','query','vision_max_pixels','max_new_tokens','temperature','top_p','top_k','repetition_penalty'}:raise ValueError('Unknown detection settings')
            if not 1<=settings.get('max_new_tokens',2048)<=2048 or not 16384<=settings.get('vision_max_pixels',524288)<=524288:raise ValueError('Detection budget exceeded')
            baseline = preflight_fn()
            manifest['preflight'] = baseline
            for tile in manifest['tiles']:
                cancellation_check()
                if time.monotonic()-started > 1200:
                    raise RuntimeError('Batch 1200 second time limit reached; no retry')
                if memory_fn() < 35:
                    raise RuntimeError('Batch continuation needs >=35% memory free; no retry')
                if swap_fn()-baseline['swap_used_mb'] > 2048:
                    raise RuntimeError('Batch cumulative swap guard; no retry')
                manifest['current_tile'] = tile['id']
                save()
                print('START ' + tile['id'], flush=True)
                result = engine_factory().predict(image.crop(tile['bounds']), task='detection',
                    query=specification['query'], prompt=specification['prompt'], decode_matting=False,
                    **{**dict(vision_max_pixels=524288,max_new_tokens=2048,temperature=0.,top_p=.95,top_k=50,repetition_penalty=1.05),**{k:v for k,v in settings.items() if k!='query'}})
                run = Path(result.run_directory)
                # Copy model evidence into this job; never edit the original run.
                evidence = directory/'tiles'/tile['id']
                evidence.mkdir(parents=True, exist_ok=False)
                hashes = {}
                for name in ('request.json', 'result.json', 'generation.json', 'metrics.json', 'supervision.json', 'preflight.json'):
                    path = run/name
                    if path.exists():
                        shutil.copyfile(path, evidence/name)
                        hashes[name] = hashlib.sha256((evidence/name).read_bytes()).hexdigest()
                data = json.loads((evidence/'result.json').read_text())
                audit = json.loads((evidence/'generation.json').read_text())
                metrics = json.loads((evidence/'metrics.json').read_text())
                record = {**tile, 'run': str(run), 'evidence': str(evidence), 'evidence_sha256': hashes,
                          'generation': audit, 'inference_seconds': metrics['inference_seconds'], 'reused': False}
                manifest['attempts'].append(record)
                save()
                if not audit.get('response_complete'):
                    raise RuntimeError('Incomplete model response in ' + tile['id'] + '; no retry')
                boxes = [p['coords'] for items in data['predictions'].values() for p in items if p['type'] == 'box']
                tile_proposals = []
                for index, box in enumerate(boxes):
                    proposal = globalize(box, tile, f'{tile["id"]}-{index+1:03d}')
                    if proposal:
                        tile_proposals.append(proposal)
                proposals.extend(tile_proposals)
                record['box_count'] = len(boxes)
                manifest['completed'].append(record)
                assemble()
                save()
                print('DONE ' + tile['id'] + ' boxes=' + str(len(boxes)), flush=True)
            manifest.update(status='complete', current_tile=None, finished_at=now(),
                            raw_proposals=len(proposals), assembled_candidates=len(stitch(proposals)))
            save()
            return 0
    except BaseException as error:
        cancelled = isinstance(error, KeyboardInterrupt)
        manifest.update(status='stopped' if cancelled else 'failed', stop_reason=str(error),
                        finished_at=now())
        assemble()
        save()
        print(manifest['status'].upper() + ' ' + str(error), flush=True)
        return 130 if cancelled else 1
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: detection_job_runner.py JOB_DIRECTORY')
    raise SystemExit(run_job(sys.argv[1]))
