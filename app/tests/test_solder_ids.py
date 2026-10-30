import copy
import hashlib
import json
import unittest
from pcb_workshop.solder_ids import identify_candidates


class SolderIdentityTests(unittest.TestCase):
    def test_identical_and_overlapping_boxes_are_all_retained_with_unique_stable_ids(self):
        candidates=[{'id':'temporary','coords':[10,10,30,30],'observations':[{'tile':'R1C1'}]},
                    {'coords':[10,10,30,30]}, {'coords':[10,10,30,30]},
                    {'coords':[11,10,31,30]}]
        before=copy.deepcopy(candidates)
        result=identify_candidates(candidates,'prepared')
        expected='PAD-W'+hashlib.sha256(json.dumps(['prepared',[10,10,30,30]],separators=(',',':')).encode()).hexdigest()[:16]
        self.assertEqual([p['id'] for p in result[:3]],[expected,expected+'-02',expected+'-03'])
        self.assertEqual(len({p['id'] for p in result}),4)
        self.assertEqual([p['coords'] for p in result],[p['coords'] for p in candidates])
        self.assertEqual(result[0]['observations'],candidates[0]['observations'])
        self.assertEqual(result,identify_candidates(candidates,'prepared'))
        self.assertEqual(candidates,before)

    def test_unrelated_proposal_order_does_not_change_existing_identities(self):
        first={'coords':[10,10,30,30]};other={'coords':[100,100,130,130]}
        a=identify_candidates([first,first,other],'prepared')
        b=identify_candidates([other,first,first],'prepared')
        self.assertEqual([p['id'] for p in a],[b[1]['id'],b[2]['id'],b[0]['id']])
        self.assertEqual(identify_candidates([],'prepared'),[])


if __name__=='__main__':unittest.main()
