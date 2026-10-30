"""Explicit tiled solder jobs, sharing the preparation manager and process slot."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import uuid
import math
from PIL import Image
from .crops import crop_root
from .model_settings import validate


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def start(jobs, value):
    with jobs.lock:
        if jobs.active:raise ValueError('Un calcul est déjà en cours.')
        settings=validate('solders',value.get('settings'))
        if not jobs.capabilities()['available']:raise ValueError('Environnement WeVisOne indisponible.')
        if not any(p['size']==settings['model_size'] and p['available'] for p in jobs.model_profiles()):raise ValueError('Modèle absent ou non vérifié ; aucun repli automatique.')
        selected=jobs.result_root(value.get('source_result'));source=selected/'original.png'
        expected=json.loads((selected/'result.json').read_text())['useful_sha256']['original.png']
        if sha(source)!=expected:raise ValueError('Original modifié.')
        section=value.get('section')
        if section is not None and (type(section) is not int or not 0<=section<24):raise ValueError('Section invalide.')
        input_layer=value.get('input','cropped');crop_id=value.get('source_crop');mask_path=None
        if input_layer=='cropped':
            if crop_id:mask_path=crop_root(selected,crop_id)/'keep.png'
            else:
                provenance=json.loads((selected/'provenance.json').read_text())
                if provenance.get('standalone_from_original') is not False:raise ValueError('Appliquer la préparation avant de choisir Original-croppé.')
                mask_path=selected/('external-material-mask.png' if (selected/'external-material-mask.png').exists() else 'board.png')
                if sha(mask_path)!=json.loads((selected/'result.json').read_text())['useful_sha256'].get(mask_path.name):raise ValueError('Masque modifié.')
        elif input_layer!='original':raise ValueError('Image analysée inconnue.')
        with Image.open(source) as opened:
            if opened.width*opened.height>6_000_000:raise ValueError('Détection limitée à 6 millions de pixels.')
            rgba=opened.convert('RGBA')
        identity=uuid.uuid4().hex;job=jobs.folder/identity;job.mkdir()
        shutil.copyfile(source,job/'original.png')
        if mask_path:
            with Image.open(mask_path) as mask:
                if mask.size!=rgba.size:raise ValueError('Masque incompatible.')
                from PIL import ImageChops
                rgba.putalpha(ImageChops.darker(rgba.getchannel('A'),mask.convert('L')))
            shutil.copyfile(mask_path,job/'source-mask.png')
        rgba.save(job/'source.png')
        request={'kind':'solders','source_result':value.get('source_result'),'source_crop':crop_id if input_layer=='cropped' else None,
                 'source_sha256':expected,'prepared_sha256':sha(job/'source.png'),'mask_sha256':sha(job/'source-mask.png') if mask_path else None,
                 'input':input_layer,'section':section,'settings':settings,'shared_runtime':str(jobs.shared)}
        (job/'request.json').write_text(json.dumps(request,indent=2)+'\n')
        state={'id':identity,'kind':'solders','status':'running','phase':'Préparation et contrôle mémoire','model_size':settings['model_size'],
               'source_result':request['source_result'],'source_sha256':expected,'source_crop':request['source_crop'],'input':input_layer,
               'section':section,'total_tiles':24 if section is None else 1,'completed_tiles':0,'simulation':jobs.simulation,
               'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
        jobs._save(job,state);jobs.active=identity
        try:
            with (job/'controller.log').open('w') as log:
                jobs.process=subprocess.Popen([str(jobs.runtime),str(jobs.controller),str(job)],stdout=log,stderr=subprocess.STDOUT,
                                              env=jobs.model_environment(settings['model_size']),start_new_session=True)
        except (OSError,ValueError) as error:
            state.update(status='failed',message=str(error));jobs._save(job,state);jobs.active=None;raise ValueError(str(error))
        threading.Thread(target=jobs._watch,args=(identity,jobs.process),daemon=True).start()
        return state


def finish(jobs,job,state,code):
    cancelled=state['status']=='cancelling'
    try:
        if cancelled:state.update(status='cancelled',phase='Arrêté',message='Calcul arrêté ; résultats partiels conservés, aucune relance.');return
        if code:raise ValueError((job/'controller-error.txt').read_text() if (job/'controller-error.txt').exists() else 'Échec du modèle ; consulter le journal.')
        detection=json.loads((job/'detection.json').read_text());manifest=json.loads((job/'manifest.json').read_text())
        if manifest['status']!='complete' or len(manifest['completed'])!=state['total_tiles']:raise ValueError('Détection incomplète ; aucun résultat appliqué.')
        if not all(t['generation'].get('response_complete') for t in manifest['completed']):raise ValueError('Réponse de section incomplète.')
        if detection['source_sha256']!=state['source_sha256'] or detection['source_crop']!=state['source_crop']:raise ValueError('Provenance incompatible.')
        if len(detection['candidates'])>3000:raise ValueError('Plus de 3000 propositions ; revoir une section séparément.')
        request=json.loads((job/'request.json').read_text());profile=next(p for p in jobs.model_profiles() if p['size']==state['model_size'])
        if not jobs.simulation and (detection['model_id']!=profile['model_id'] or detection['model_revision']!=profile['revision']):raise ValueError('Modèle ou révision incompatible.')
        selected=jobs.result_root(state['source_result'])
        if sha(selected/'original.png')!=state['source_sha256']:raise ValueError('Original modifié pendant le calcul.')
        if request['source_crop']:crop_root(selected,request['source_crop'])
        with Image.open(job/'source.png') as image:width,height=image.size
        ids=set()
        for index,p in enumerate(detection['candidates'],1):
            x,y,u,v=p['coords']
            if not all(type(n) in (float,int) and math.isfinite(n) for n in (x,y,u,v)) or not 0<=x<u<=width or not 0<=y<v<=height:
                raise ValueError(f'Proposition {index} : coordonnées invalides ou hors image.')
            if not isinstance(p['id'],str) or not p['id'] or len(p['id'])>80:
                raise ValueError(f'Proposition {index} : identifiant invalide.')
            if p['id'] in ids:raise ValueError(f'Proposition {index} : identifiant en double.')
            ids.add(p['id'])
        state.update(status='ready',phase='Soudures proposées',message='',completed_tiles=state['total_tiles'],candidates=len(detection['candidates']),result_sha256=sha(job/'detection.json'))
    except (OSError,ValueError,KeyError,TypeError) as error:state.update(status='failed',phase='Échec',message=str(error))
