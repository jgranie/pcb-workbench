"""Local image/XCF import into an empty workspace; no detection or inference."""
import hashlib
import json
from pathlib import Path
import uuid
import numpy as np
from PIL import Image, ImageOps
from .__main__ import extract_xcf, load_config


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def folder_for(root, identity):
    if not isinstance(identity,str) or len(identity)!=32 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError("Import inconnu.")
    path=Path(root)/'imports'/identity
    if not (path/'import.json').is_file():raise ValueError("Import inconnu.")
    return path


def create_workspace(folder, photo, provenance):
    target=folder/'workspace'
    if target.exists():raise ValueError("Cette image est déjà ouverte ; aucun travail écrasé.")
    with Image.open(photo) as opened:
        if opened.width*opened.height>20_000_000:raise ValueError("Image limitée à 20 millions de pixels.")
        rgba=np.array(ImageOps.exif_transpose(opened).convert('RGBA'))
    target.mkdir()
    Image.fromarray(rgba).save(target/'original.png')
    height,width=rgba.shape[:2];zero=Image.new('L',(width,height),0)
    zero.save(target/'mask.png');zero.save(target/'solder.png')
    Image.fromarray(rgba[:,:,3]).save(target/'board.png')
    (target/'alpha.bin').write_bytes(bytes(width*height));(target/'photo.bin').write_bytes(rgba.tobytes())
    rgba_sha=hashlib.sha256(rgba.tobytes()).hexdigest()
    scan={'schema_version':1,'routes':[],'issues':[],'reviews':{},'complete':False,'electrical_validation':False}
    workspace={'schema_version':1,'canvas':{'width':width,'height':height},'source_rgba_sha256':rgba_sha,
               'objects':[],'nextId':1,'detectionReviews':{},'traceScan':scan,
               'calibration':{'status':'unverified','sx':None,'sy':None},
               'layerVisibility':{'original':True,'crop':False,'pads':False,'routes':False}}
    save(target/'workspace.json',workspace);save(target/'workspace.initial.json',workspace)
    save(target/'scan.json',scan);save(target/'candidates.json',{'candidates':[],'electrical_validation':False})
    save(target/'image.json',{'width':width,'height':height,'rgba_sha256':rgba_sha})
    save(target/'config.json',load_config(None))
    save(target/'routing-diagnostics.json',{'anchors':0,'strict':0,'issues':0,'electrical_validation':False})
    save(target/'provenance.json',{**provenance,'pipeline_mode':'image_import','standalone_from_original':True,
                                 'detections_run':False,'llm_calls_during_this_cpu_run':0})
    save(target/'result.json',{'status':'image_ready','electrical_validation':False,
                             'useful_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir() if p.is_file() and p.name!='workspace.json'}})
    return {'id':folder.name,'url':'/?result='+folder.name,'status':'ready'}


def upload(root, filename, data):
    suffix=Path(filename).suffix.lower()
    if suffix not in ('.png','.xcf'):raise ValueError("Choisir un PNG, un XCF ou un travail JSON.")
    folder=Path(root)/'imports'/uuid.uuid4().hex;folder.mkdir(parents=True)
    source=folder/('source'+suffix);source.write_bytes(data)
    info={'filename':Path(filename).name,'source_sha256':hashlib.sha256(data).hexdigest(),'format':suffix[1:]}
    save(folder/'import.json',info)
    if suffix=='.png':
        with Image.open(source) as image:
            if image.format!='PNG':raise ValueError("Le fichier n'est pas un PNG valide.")
        return create_workspace(folder,source,info)
    _,inventory=extract_xcf(source,folder,None,None,inventory=True)
    save(folder/'inventory.json',inventory)
    return {'id':folder.name,'status':'choose_layer','layers':inventory['layers']}


def select_layer(root, identity, native_path):
    folder=folder_for(root,identity);inventory=json.loads((folder/'inventory.json').read_text())
    matches=[l for l in inventory['layers'] if l['native_path']==native_path and not l.get('is_group')]
    if len(matches)!=1:raise ValueError("Choisir un calque de la liste.")
    info=json.loads((folder/'import.json').read_text());source=folder/'source.xcf'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=info['source_sha256']:raise ValueError("Le XCF importé a changé.")
    photo,extraction=extract_xcf(source,folder,matches[0]['name'],None,native_path=native_path)
    return create_workspace(folder,photo,{**info,'xcf_layer':matches[0],'extraction':extraction})
