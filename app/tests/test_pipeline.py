import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
from pcb_workshop.__main__ import ROOT, load_config, run_pipeline, compare_runs, digest
from pcb_workshop.server import validate_workspace, serve_workspace

spec = importlib.util.spec_from_file_location("synthetic", ROOT / "examples/generate.py")
synthetic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(synthetic)


class PipelineTests(unittest.TestCase):
    def test_independent_runs_preserve_input_and_two_separate_nets(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            synthetic.generate(directory)
            source = directory / "synthetic.png"
            before = digest(source)
            for name in ("first", "second"):
                run_pipeline(argparse.Namespace(input=source, output=directory / name, config=None, layer="Original", gimp=None))
            compare_runs(argparse.Namespace(first=directory / "first", second=directory / "second", output=None))
            self.assertEqual(before, digest(source))
            scan = json.loads((directory / "first/scan.json").read_text())
            candidates = json.loads((directory / "first/candidates.json").read_text())["candidates"]
            self.assertEqual(len(candidates), 6)
            self.assertTrue(scan["complete"])
            self.assertEqual(len(scan["routes"]), 5)  # All four sides of the ring plus the separate line.
            for route in scan["routes"]:
                a = next(c for c in candidates if c["id"] == route["from"])
                b = next(c for c in candidates if c["id"] == route["to"])
                self.assertEqual(a["x"] > 300, b["x"] > 300, "False connection across the known insulating gap")
            with self.assertRaises(FileExistsError):
                run_pipeline(argparse.Namespace(input=source, output=directory / "first", config=None, layer="Original", gimp=None))
            # A tampered useful output must be detected even when receipts match.
            (directory / "second/mask.png").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                compare_runs(argparse.Namespace(first=directory / "first", second=directory / "second", output=None))
            with self.assertRaisesRegex(ValueError, "modifié"):
                serve_workspace(argparse.Namespace(directory=directory / "second", port=0))

    def test_transparent_prepared_input_is_refused_and_failure_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            Image.new("RGBA", (64, 64), (20, 170, 130, 0)).save(directory / "prepared.png")
            with self.assertRaisesRegex(ValueError, "transparents"):
                run_pipeline(argparse.Namespace(input=directory / "prepared.png", output=directory / "failed", config=None, layer="Original", gimp=None))
            self.assertTrue((directory / "failed/failure.json").exists())

    def test_bad_config_and_cross_source_workspace_refused(self):
        config = json.loads((ROOT / "config.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            config["adaptive_window"] = 100
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "impair"):
                load_config(path)
        with self.assertRaisesRegex(ValueError, "autre image"):
            validate_workspace({"schema_version": 1, "source_rgba_sha256": "other", "canvas": {"width": 80, "height": 80}},
                               {"source_rgba_sha256": "expected", "canvas": {"width": 80, "height": 80}})


if __name__ == "__main__":
    unittest.main()
