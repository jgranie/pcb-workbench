import unittest
import numpy as np
from pcb_workshop.model_settings import defaults,validate
from pcb_workshop.material_mask import epoxy_keep


class SettingsTests(unittest.TestCase):
    def test_complete_solder_descriptions_fit_without_changing_preparation_limits(self):
        query='individual solder joints at component terminals, tightly boxed separately, excluding holes and printed markings, '+'dull or shiny solder '*20
        self.assertGreater(len(query),200)
        self.assertEqual(validate('solders',{'query':query})['query'],query.strip())
        self.assertEqual(len(validate('solders',{'query':'s'*1000})['query']),1000)
        for kind,value in [('solders','s'*1001),('solders','two\nlines'),('board','s'*201),('epoxy','s'*201)]:
            with self.assertRaises(ValueError):validate(kind,{'query':value})

    def test_options_cannot_change_model_or_bypass_existing_limits(self):
        for value in ({'model_size':'8B'},{'vision_max_pixels':1048576},{'max_new_tokens':513},{'device':'cpu'},
                      {'temperature':float('nan')},{'top_k':True},{'mask_threshold':0}):
            with self.assertRaises(ValueError):validate('board',value)
        with self.assertRaises(ValueError):validate('epoxy',{'bilateral_diameter':4})
        self.assertEqual(validate('board',{'query':'  board  '})['query'],'board')
        self.assertNotIn('lab_a_threshold',defaults('board'))
        self.assertIsNone(defaults('epoxy')['lab_a_threshold'])

    def test_lower_lab_cutoff_excludes_a_subset_without_repainting_pixels(self):
        rgb=np.full((40,80,3),(30,150,100),np.uint8)
        rgb[:,:40,0]=np.linspace(10,80,40).astype(np.uint8)[None,:]
        rgb[:,40:]=(110,110,110)
        original=rgb.copy();board=np.ones((40,80),bool);proposal=np.full((40,80),255,np.uint8)
        automatic,evidence=epoxy_keep(rgb,board,proposal)
        cutoff=evidence['lab_a_threshold']-2
        prudent,custom=epoxy_keep(rgb,board,proposal,{'lab_a_threshold':cutoff})
        self.assertFalse(np.any((prudent==0)&(automatic>0)))
        self.assertEqual(custom['lab_a_threshold'],cutoff)
        self.assertTrue(np.array_equal(rgb,original))
