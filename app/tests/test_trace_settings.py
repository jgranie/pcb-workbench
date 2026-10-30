import unittest
from pcb_workshop.trace_settings import validate
class TraceSettingsTests(unittest.TestCase):
    def test_bounds_match_the_ui_and_boolean_types_are_strict(self):
        self.assertEqual(validate()['max_visited'], 3000000)
        for value in [{'max_visited':6000001},{'max_visited':True},{'time_limit_ms':float('nan')},{'allow_photo_gaps':1},{'model':'llm'}]:
            with self.assertRaises(ValueError):validate(value)
