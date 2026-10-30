"""Run the existing guarded tiling protocol with a frozen prepared source."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
from model_settings import validate
from solder_ids import identify_candidates


def run(job):
    request=json.loads((job/'request.json').read_text());settings=validate('solders',request['settings']);shared=Path(request['shared_runtime'])
    sys.path.insert(0,str(shared))
    import guarded_engine
    from detection_job_runner import run_job
    from tiled_detection import make_tiles
    from PIL import Image
    if Path(sys.prefix).resolve()!=Path(guarded_engine.PYTHON).parent.parent.resolve():raise RuntimeError('Environnement WeVisOne différent de celui configuré.')
    profile=guarded_engine.get_model_profile(settings['model_size'])
    if hashlib.sha256((job/'source.png').read_bytes()).hexdigest()!=request['prepared_sha256']:raise RuntimeError('Image préparée modifiée.')
    with Image.open(job/'source.png') as image:width,height=image.size
    tiles=make_tiles(width,height)
    if request['section'] is not None:tiles=[tiles[request['section']]]
    specification={'source':{'file_sha256':request['prepared_sha256'],'width':width,'height':height},'tiles':tiles,
                   'query':settings['query'],'prompt':'Locate all the instances that match the following description: '+settings['query']+'.',
                   'settings':settings,'authorization':'Explicit solder detection from the PCB workshop','retries':0}
    (job/'job.json').write_text(json.dumps(specification,indent=2)+'\n')
    with contextlib.ExitStack() as stack:
        paths=[] if os.environ.get('PCB_WEVISONE_SESSION') else [shared.parents[1]/'outputs/wevisone-vl/jobs/.batch.lock',shared.parents[1]/'outputs/wevisone-vl/inference.lock']
        for path in paths:
            handle=stack.enter_context(path.open('a+'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        guarded_engine.OUTPUT=job/'engine';guarded_engine.OUTPUT.mkdir()
        code=run_job(job)
        if code:raise RuntimeError('Détection interrompue : '+json.loads((job/'manifest.json').read_text()).get('stop_reason','échec'))
    assembled=json.loads((job/'assembled.json').read_text());manifest=json.loads((job/'manifest.json').read_text())
    assembled['candidates']=identify_candidates(assembled['candidates'],request['prepared_sha256'])
    result={**assembled,'schema_version':1,'method':'wevisone_tiled_4x6_halo64','job_id':job.name,
            'input':request['input'],'source_sha256':request['source_sha256'],'source_crop':request['source_crop'],
            'mask_sha256':request['mask_sha256'],'prepared_sha256':request['prepared_sha256'],'settings':settings,
            'model_id':profile['model_id'],'model_revision':profile['revision'],'model_size':profile['size'],
            'section':request['section'],'tiles':tiles,'completed_tiles':len(manifest['completed']),
            'stats':{'candidates':assembled['candidate_count'],'candidates_before_limit':assembled['candidate_count'],'candidates_truncated':False},
            'elapsed_seconds':manifest['elapsed_seconds'],'llm_calls':len(manifest['attempts']),'traces_run':False,'electrical_validation':False}
    (job/'detection.json').write_text(json.dumps(result,indent=2)+'\n')
