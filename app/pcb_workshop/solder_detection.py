"""The existing CPU bright-component detector, independent of trace extraction."""
import hashlib
import json
import math
from pathlib import Path
import time
import cv2
import numpy as np
from PIL import Image
from .crops import crop_root

cv2.setNumThreads(1)
cv2.ocl.setUseOpenCL(False)
CONFIG = Path(__file__).resolve().parents[1] / 'config.json'
KEYS = ('solder_foreground','solder_contrast','solder_min_area','solder_max_area',
        'solder_max_extent','solder_min_circularity','solder_max_aspect','solder_close_size','max_candidates')


def defaults():
    config=json.loads(CONFIG.read_text())
    return {key:config[key] for key in KEYS}


def validate(settings=None):
    result=defaults()
    if settings is not None:
        if not isinstance(settings,dict) or set(settings)-set(result):raise ValueError('Paramètres soudures inconnus.')
        result.update(settings)
    if result['solder_foreground'] not in ('lab','none'):raise ValueError('Restriction couleur : lab ou none.')
    ranges={'solder_contrast':(0,255),'solder_min_area':(1,10000),'solder_max_area':(1,10000),
        'solder_max_extent':(3,300),'solder_min_circularity':(0,1),'solder_max_aspect':(1,10),
        'solder_close_size':(1,7),'max_candidates':(1,1500)}
    for key,(low,high) in ranges.items():
        value=result[key]
        integer=key not in ('solder_min_circularity','solder_max_aspect')
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high or (integer and type(value) is not int):
            raise ValueError('Paramètre invalide : '+key)
    if result['solder_min_area']>result['solder_max_area']:raise ValueError('Aire minimum supérieure au maximum.')
    if result['solder_close_size'] not in (1,3,5,7):raise ValueError('Fermeture : 1, 3, 5 ou 7 pixels.')
    return result


def estimate_board(rgb):
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    r,g,b=[rgb[:,:,i].astype(np.float32) for i in range(3)]
    green=((hsv[:,:,1]>55)&(g>1.15*r)&(g>.90*b)).astype(np.uint8)
    green=cv2.morphologyEx(green,cv2.MORPH_CLOSE,np.ones((9,9),np.uint8))
    contours,_=cv2.findContours(green,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not contours or cv2.contourArea(max(contours,key=cv2.contourArea))<green.size*.15:
        raise ValueError('Contour vert introuvable ; appliquer un contour PCB puis analyser Original-croppé.')
    board=np.zeros_like(green)
    cv2.drawContours(board,[max(contours,key=cv2.contourArea)],-1,1,-1)
    return board


def find_solders(rgb, config, board, material_mask=None, *, strict_board=False):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    if not board.any():raise ValueError('Aucun pixel à analyser.')
    local = cv2.GaussianBlur(gray, (21, 21), 0).astype(np.int16)
    bright = ((gray.astype(np.int16) - local >= config["solder_contrast"]) & (hsv[:, :, 1] < 150) & (board > 0)).astype(np.uint8)
    # Reject estimated epoxy without replacing source pixels or creating black edges.
    foreground_threshold = None
    if config["solder_foreground"] == "lab":
        material = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[:, :, 1]
        foreground_threshold, _ = cv2.threshold(material[board > 0], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bright &= (material > foreground_threshold).astype(np.uint8)
    if material_mask is not None:
        bright &= material_mask.astype(np.uint8)
    kernel = config["solder_close_size"]
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8))
    if strict_board:
        bright &= board
    if material_mask is not None:
        bright &= material_mask.astype(np.uint8)
    count, labels, stats, centers = cv2.connectedComponentsWithStats(bright, connectivity=8)
    proposals = []
    solder = np.zeros_like(gray)
    for label in range(1, count):
        x, y, w, h, area = map(int, stats[label])
        if (not config["solder_min_area"] <= area <= config["solder_max_area"] or max(w, h) > config["solder_max_extent"]
                or max(w, h) / min(w, h) > config["solder_max_aspect"]):
            continue
        component = (labels[y:y+h, x:x+w] == label).astype(np.uint8)
        contour = max(cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], key=cv2.contourArea)
        perimeter = cv2.arcLength(contour, True)
        circularity = 4 * np.pi * area / max(perimeter ** 2, 1)
        if circularity < config["solder_min_circularity"]:
            continue
        proposals.append({"coords": [x, y, x+w, y+h], "x": float(centers[label, 0]), "y": float(centers[label, 1]),
                          "area": area, "circularity": float(circularity), "component": label})
    proposals.sort(key=lambda a: (a["coords"][1], a["coords"][0]))
    found = len(proposals)
    truncated = found > config["max_candidates"]
    proposals = proposals[:config["max_candidates"]]
    selected_labels = np.zeros(count, dtype=np.uint8)
    for i, proposal in enumerate(proposals):
        selected_labels[proposal.pop("component")] = 1
        proposal.update(id=f"PAD-{i+1:04d}", status="candidate", origin="classical_bright_component")
    solder = selected_labels[labels]
    return solder, proposals, {"candidates_truncated": truncated, "solder_foreground": config["solder_foreground"],
        "solder_foreground_threshold": foreground_threshold, "candidates_before_limit": found, "candidates": len(proposals)}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def propose(root, value):
    """Read Original and optional reviewed crop; return candidates, write nothing."""
    root=Path(root);started=time.perf_counter();settings=validate(value.get('settings'))
    receipt=json.loads((root/'result.json').read_text());expected=receipt['useful_sha256']['original.png']
    if sha(root/'original.png')!=expected:raise ValueError('Original modifié ; détection refusée.')
    with Image.open(root/'original.png') as image:
        if image.width*image.height>6_000_000:raise ValueError('Détection limitée à 6 millions de pixels.')
        rgba=np.array(image.convert('RGBA'))
    rgb=rgba[:,:,:3].copy();visible=rgba[:,:,3]>=128;source=value.get('input','original');crop_id=None;mask_hash=None
    if source=='cropped':
        crop_id=value.get('source_crop')
        if crop_id:
            folder=crop_root(root,crop_id)
            board=np.array(Image.open(folder/'board.png'))>=128
            material=np.array(Image.open(folder/'keep.png'))>=128
            mask_hash=sha(folder/'keep.png')
        else:
            provenance=json.loads((root/'provenance.json').read_text())
            if provenance.get('standalone_from_original') is not False:raise ValueError('Appliquer un contour avant de choisir Original-croppé.')
            def verified_mask(name):
                if sha(root/name)!=receipt['useful_sha256'].get(name):raise ValueError('Masque modifié.')
                return np.array(Image.open(root/name))>=128
            board=verified_mask('board.png')
            name='external-material-mask.png' if (root/'external-material-mask.png').exists() else 'board.png'
            material=verified_mask(name);mask_hash=sha(root/name)
        if board.shape!=visible.shape or material.shape!=visible.shape:raise ValueError('Masque incompatible avec Original.')
        board=board & visible;material=material & board
    elif source=='original':
        board=estimate_board(rgb).astype(bool)&visible;material=None
    else:raise ValueError('Image analysée inconnue.')
    _,candidates,stats=find_solders(rgb,settings,board.astype(np.uint8),material,strict_board=source=='cropped' or not visible.all())
    for candidate in candidates:
        key=json.dumps([expected,candidate['coords']],separators=(',',':')).encode()
        candidate['id']='PAD-D'+hashlib.sha256(key).hexdigest()[:16]
    return {'schema_version':1,'method':'local_contrast_lab_components_v0.2','input':source,'source_crop':crop_id,
        'source_sha256':expected,'mask_sha256':mask_hash,'settings':settings,'candidates':candidates,'stats':stats,
        'elapsed_seconds':time.perf_counter()-started,'llm_calls':0,'traces_run':False,'electrical_validation':False}
