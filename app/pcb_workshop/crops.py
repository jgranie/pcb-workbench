"""Immutable crop snapshots behind a single editable workspace layer.

Applying a mask only composes image alpha. It never detects pads or routes.
"""
import hashlib
import json
from pathlib import Path
import uuid
import numpy as np
from PIL import Image
from .material_mask import replace_section, legacy_epoxy_keep


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def crop_root(root, identity):
    if not isinstance(identity, str) or len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError("Référence de crop invalide.")
    folder = Path(root) / 'preprocessing' / identity
    if not (folder / 'crop.json').is_file():
        raise ValueError("Crop absent de ce travail ; ouvrir le JSON dans son dossier d'origine.")
    data = json.loads((folder / 'crop.json').read_text())
    if data['source_sha256'] != sha(Path(root) / 'original.png'):
        raise ValueError("Crop d'une autre image.")
    for name, expected in data['sha256'].items():
        if name not in ('board.png', 'keep.png', 'original-cropped.png') or sha(folder / name) != expected:
            raise ValueError("Crop modifié ; chargement refusé.")
    return folder


def apply_crop(root, job, state, previous=None):
    root, job = Path(root), Path(job)
    evidence = json.loads((job / 'mask-provenance.json').read_text())
    if sha(root / 'original.png') != evidence['source_sha256'] or sha(job / 'alpha.png') != evidence['alpha_sha256']:
        raise ValueError("Source ou masque modifié.")
    if state.get('status') not in ('ready', 'derived') or not evidence['generation'].get('response_complete'):
        raise ValueError("Le masque n'est pas disponible.")
    image = Image.open(root / 'original.png').convert('RGBA')
    with Image.open(job / 'alpha.png') as mask:
        if mask.mode != 'L' or mask.size != image.size:
            raise ValueError("Masque incompatible avec Original.")
        proposed = np.array(mask) >= 128
    kind = state.get('kind', 'board')
    prior = crop_root(root, previous) if previous else None
    if prior:
        board = np.array(Image.open(prior / 'board.png')) >= 128
        keep = np.array(Image.open(prior / 'keep.png')) >= 128
    else:
        assisted = json.loads((root / 'provenance.json').read_text()).get('standalone_from_original') is False
        board = np.array(Image.open(root / 'board.png')) >= 128 if assisted else np.ones((image.height,image.width),bool)
        # Existing assisted results migrate by copying their material mask.
        material = root / 'external-material-mask.png'
        keep = np.array(Image.open(material)) >= 128 if material.exists() else board.copy()
    if kind == 'board':
        board &= proposed
        keep &= proposed & board
    elif kind == 'epoxy':
        if evidence.get('composition') == 'replace_section_v1':
            core = evidence.get('core')
        else:
            proposed, core, _ = legacy_epoxy_keep(job)
        keep = replace_section(keep, proposed, board, core)
    else:
        raise ValueError("Type de masque inconnu.")
    if not keep.any():
        raise ValueError("Ce retrait ne conserve aucun pixel.")
    identity = uuid.uuid4().hex
    folder = root / 'preprocessing' / identity;folder.mkdir(parents=True)
    Image.fromarray(board.astype(np.uint8)*255).save(folder / 'board.png')
    alpha = Image.fromarray(keep.astype(np.uint8)*255);alpha.save(folder / 'keep.png')
    image.putalpha(Image.fromarray(np.minimum(np.array(image)[:,:,3],np.array(alpha))));image.save(folder / 'original-cropped.png')
    data = {'id': identity, 'parent': previous, 'source_sha256': sha(root / 'original.png'),
            'job': state['id'], 'kind': kind, 'simulation': bool(state.get('simulation')),
            'mask_evidence': evidence, 'composition': 'replace_section_v1' if kind=='epoxy' else 'intersection', 'detections_run': False,
            'sha256': {name: sha(folder/name) for name in ('board.png','keep.png','original-cropped.png')}}
    (folder/'crop.json').write_text(json.dumps(data, indent=2)+'\n')
    return {'id': identity, 'job': state['id'], 'source_sha256': data['source_sha256'], 'simulation': data['simulation']}
