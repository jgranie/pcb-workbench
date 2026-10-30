import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from pcb_workshop.crops import apply_crop, crop_root
from pcb_workshop.material_mask import replace_section, epoxy_keep
from pcb_workshop.wevisone_jobs import ModelJobs


class SectionReplaceTests(unittest.TestCase):
    def test_revisiting_section_restores_pixels_without_touching_other_sections(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);Image.new('RGBA',(40,40),(30,150,80,255)).save(root/'original.png')
            Image.new('L',(40,40),255).save(root/'board.png')
            (root/'provenance.json').write_text(json.dumps({'standalone_from_original':True}))
            def proposal(name,core,removed):
                job=root/name;job.mkdir();keep=np.full((40,40),255,np.uint8)
                x,y,u,v=removed;keep[y:v,x:u]=0;Image.fromarray(keep).save(job/'alpha.png')
                ev={'source_sha256':hashlib.sha256((root/'original.png').read_bytes()).hexdigest(),
                    'alpha_sha256':hashlib.sha256((job/'alpha.png').read_bytes()).hexdigest(),
                    'generation':{'response_complete':True},'composition':'replace_section_v1','core':core}
                (job/'mask-provenance.json').write_text(json.dumps(ev))
                return job,{'id':name,'status':'ready','kind':'epoxy'}
            def apply(job,state,previous=None):
                with patch('subprocess.Popen',side_effect=AssertionError('No model or detection')):
                    return apply_crop(root,job,state,previous)['id']
            first,state=proposal('A',[0,0,20,20],[4,4,12,8]);a=apply(first,state)
            second,state=proposal('B',[20,20,40,40],[25,22,35,26]);b=apply(second,state,a)
            before=np.array(Image.open(crop_root(root,b)/'keep.png'))
            third,state=proposal('A-prudent',[0,0,20,20],[4,4,8,6]);c=apply(third,state,b)
            after=np.array(Image.open(crop_root(root,c)/'keep.png'))
            self.assertEqual(before[7,10],0);self.assertEqual(after[7,10],255)
            outside=np.ones((40,40),bool);outside[:20,:20]=False
            self.assertTrue(np.array_equal(before[outside],after[outside]))
            self.assertEqual(after[24,30],0)
            self.assertEqual(np.array(Image.open(crop_root(root,b)/'keep.png'))[7,10],0)
            self.assertEqual(json.loads((crop_root(root,c)/'crop.json').read_text())['parent'],b)

    def test_no_exclusion_is_a_valid_way_to_clear_an_old_section(self):
        rgb=np.full((20,20,3),(30,150,80),np.uint8);board=np.ones((20,20),bool)
        fresh,_=epoxy_keep(rgb,board,np.zeros((20,20),np.uint8),allow_empty=True)
        previous=board.copy();previous[2:5,2:5]=False;previous[14:17,14:17]=False
        merged=replace_section(previous,fresh>=128,board,[0,0,10,10])
        self.assertTrue(merged[:10,:10].all());self.assertFalse(merged[15,15])
        with self.assertRaises(ValueError):replace_section(previous,fresh,board,[-1,0,10,10])

    def test_legacy_proposal_preview_and_apply_restore_the_same_pixels(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);Image.new('RGB',(40,40),(30,150,80)).save(root/'original.png')
            Image.new('L',(40,40),255).save(root/'board.png')
            (root/'provenance.json').write_text(json.dumps({'standalone_from_original':False}))
            previous=np.full((40,40),255,np.uint8);previous[4:8,4:12]=0;previous[22:26,25:35]=0
            Image.fromarray(previous).save(root/'external-material-mask.png')
            job=root/'old-job';job.mkdir()
            for a,b in [('original.png','input.png'),('board.png','board.png'),('external-material-mask.png','previous-material.png')]:
                (job/b).write_bytes((root/a).read_bytes())
            raw=np.zeros((40,40),np.uint8);raw[4:6,4:8]=255
            Image.fromarray(raw).save(job/'raw-epoxy.png')
            Image.fromarray(previous).save(job/'alpha.png') # Old monotone result lost restoration.
            digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            evidence={'source_sha256':digest(root/'original.png'),'alpha_sha256':digest(job/'alpha.png'),
                      'raw_epoxy_sha256':digest(job/'raw-epoxy.png'),'parent_board':{'alpha_sha256':digest(job/'board.png')},
                      'generation':{'response_complete':True}}
            (job/'mask-provenance.json').write_text(json.dumps(evidence))
            (job/'request.json').write_text(json.dumps({'core':[0,0,20,20],'settings':{'lab_a_threshold':255},
                 'previous_material_sha256':digest(job/'previous-material.png')}))
            state={'id':'old-job','status':'ready','kind':'epoxy'}
            service=SimpleNamespace(directory=lambda _:job,state=lambda _:state)
            preview=np.array(Image.open(io.BytesIO(ModelJobs.alpha_bytes(service,'old-job'))))
            result=apply_crop(root,job,state)
            applied=np.array(Image.open(crop_root(root,result['id'])/'keep.png'))
            self.assertEqual(applied[7,10],255);self.assertEqual(applied[24,30],0)
            self.assertTrue(np.array_equal(preview,applied))
            self.assertEqual(digest(job/'alpha.png'),evidence['alpha_sha256'])
