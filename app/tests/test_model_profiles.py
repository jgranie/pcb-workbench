"""Asset readiness checks only; no torch imports or model execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

PATH=Path(__file__).resolve().parents[2]/'wevisone-vl/model_profiles.py'
spec=importlib.util.spec_from_file_location('model_profiles_test',PATH)
profiles=importlib.util.module_from_spec(spec);spec.loader.exec_module(profiles)


class ProfileTests(unittest.TestCase):
    def test_only_pinned_verified_4b_assets_are_available(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'WeVisOne-VL-4B';folder.mkdir()
            self.assertFalse(profiles.profile('4B',root)['available'])
            header=json.dumps({'weight':{'dtype':'BF16','shape':[1],'data_offsets':[0,2]}}).encode()
            (folder/'model.safetensors').write_bytes(struct.pack('<Q',len(header))+header+b'00')
            (folder/'mask_decoder.pt').write_bytes(b'fake')
            receipt={'model_id':profiles.SPECS['4B']['model_id'],'revision':profiles.SPECS['4B']['revision'],
                     'verified':True,'native_bf16':True,'weight_header_sha256':hashlib.sha256(header).hexdigest(),
                     'files':{name:{'bytes':(folder/name).stat().st_size} for name in ('model.safetensors','mask_decoder.pt')}}
            (folder/'download.json').write_text(json.dumps(receipt))
            self.assertTrue(profiles.profile('4B',root)['available'])
            receipt['revision']='different';(folder/'download.json').write_text(json.dumps(receipt))
            self.assertFalse(profiles.profile('4B',root)['available'])
            receipt['revision']=profiles.SPECS['4B']['revision'];(folder/'download.json').write_text(json.dumps(receipt))
            (folder/'model.safetensors').write_bytes(b'changed')
            self.assertFalse(profiles.profile('4B',root)['available'])
            with self.assertRaises(ValueError):profiles.profile('8B',root)
