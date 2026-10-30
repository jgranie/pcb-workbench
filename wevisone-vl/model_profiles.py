"""Pinned local assets. No model imports, downloads, fallback, or inference."""
import hashlib,json,struct,os
from pathlib import Path
BASE=Path(os.environ.get('PCB_WEVISONE_MODELS_DIR', '/path/to/wevisone/models'))
SPECS={
 '2B':{'model_id':'tencent/WeVisOne-VL-2B','revision':'3dad9ce8bcb6fbe0aea945bf8860bd2cfc3663bf','directory':'WeVisOne-VL-2B-bf16'},
 '4B':{'model_id':'tencent/WeVisOne-VL-4B','revision':'6b44a45873b4bbc7dca383922504430dc60eca23','directory':'WeVisOne-VL-4B'}}


def profile(size='2B', base=None):
 if size not in SPECS:raise ValueError('Taille de modèle non prise en charge.')
 spec=SPECS[size];path=Path(base or BASE)/spec['directory']
 result={**spec,'size':size,'path':str(path),'dtype':'bfloat16','available':False}
 try:
  if size=='2B':
   receipt=json.loads((path/'preparation.json').read_text())
   ready=receipt.get('all_equal_to_source_cast') is True and receipt.get('verified_tensors')==626 and receipt.get('source_revision')==spec['revision']
   index=json.loads((path/'model.safetensors.index.json').read_text())
   ready=ready and all((path/name).is_file() for name in set(index['weight_map'].values()))
  else:
   receipt=json.loads((path/'download.json').read_text())
   ready=receipt.get('verified') is True and receipt.get('native_bf16') is True and receipt.get('model_id')==spec['model_id'] and receipt.get('revision')==spec['revision']
   ready=ready and all((path/name).is_file() and (path/name).stat().st_size==data['bytes'] for name,data in receipt['files'].items())
   with (path/'model.safetensors').open('rb') as stream:
    length=struct.unpack('<Q',stream.read(8))[0]
    if length>16*1024**2:raise ValueError('En-tête invalide.')
    ready=ready and hashlib.sha256(stream.read(length)).hexdigest()==receipt['weight_header_sha256']
  result['available']=bool(ready and (path/'mask_decoder.pt').is_file())
 except (OSError,ValueError,KeyError,TypeError,struct.error):pass
 return result


def require_profile(size='2B'):
 result=profile(size)
 if not result['available']:raise RuntimeError(f"WeVisOne {size} absent ou non vérifié sur le NVMe ; aucun autre modèle substitué.")
 return result
