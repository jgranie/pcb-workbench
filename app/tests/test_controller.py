"""Exercise the actual controller/engine boundary without loading a model."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from pcb_workshop.wevisone_controller import main


class ControllerTests(unittest.TestCase):
    def run_controller(self, kind="epoxy", mask_count=1, settings=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = root / "job";job.mkdir()
            shared = root / "work/wevisone-vl";shared.mkdir(parents=True)
            locks = root / "outputs/wevisone-vl";(locks / "jobs").mkdir(parents=True)
            (locks / "inference.lock").touch();(locks / "jobs/.batch.lock").touch()
            Image.new("RGB", (100, 80), (40, 120, 80)).save(job / "input.png")
            request = {"kind": kind, "shared_runtime": str(shared),
                       "source_sha256": hashlib.sha256((job / "input.png").read_bytes()).hexdigest()}
            if settings is not None:request["settings"] = settings
            if kind == "epoxy":
                request.update(crop=[10, 10, 90, 70], core=[20, 20, 80, 60], section=0)
            (job / "request.json").write_text(json.dumps(request))
            calls = []
            engine = SimpleNamespace(PYTHON=str(Path(sys.prefix) / "bin/python"))

            engine.get_model_profile = lambda size: {"model_id":"TEST-"+size,"revision":"simulation","size":size}
            class FakeEngine:
                def predict(self, image, **kwargs):
                    calls.append(kwargs)
                    # Match the installed library: False skips decoding entirely.
                    count = mask_count if kwargs.get("decode_matting") else 0
                    run = engine.OUTPUT / "run";run.mkdir()
                    mask = np.zeros((image.height, image.width), np.uint8)
                    mask[2:-2, 2:-2] = 255
                    Image.fromarray(mask).save(run / "alpha.png")
                    return SimpleNamespace(masks=[mask] * count,
                                           generation={"response_complete": True}, run_directory=str(run))
            engine.GuardedEngine = FakeEngine
            with patch.dict(sys.modules, {"guarded_engine": engine}), patch.object(sys, "argv", ["controller", str(job)]), patch("signal.signal"):
                if mask_count != 1:
                    with self.assertRaisesRegex(RuntimeError, "Aucun masque" if mask_count == 0 else "2 masques"):
                        main()
                    self.assertFalse((job / "mask-provenance.json").exists())
                    return
                main()
            self.assertEqual(len(calls), 1)
            self.assertIs(calls[0]["decode_matting"], True)
            evidence = json.loads((job / "mask-provenance.json").read_text())
            self.assertIs(evidence["decode_matting"], True)
            self.assertEqual(evidence["model"],"TEST-"+(settings or {}).get("model_size","2B"))
            self.assertEqual(evidence["query"], calls[0]["query"])
            if settings:
                for key,value in settings.items():
                    self.assertEqual(evidence["settings"][key], value)
                    if key not in ("mask_threshold",):self.assertEqual(calls[0][key], value)
            result = np.array(Image.open(job / "alpha.png"))
            self.assertEqual(result.shape, (80, 100))
            if kind == "epoxy":
                outside = np.ones(result.shape, bool);outside[20:60,20:80] = False
                self.assertFalse(result[outside].any())
                self.assertTrue(result[20:60,20:80].all())

    def test_epoxy_decodes_and_commits_only_core(self):
        self.run_controller()

    def test_board_still_decodes(self):
        self.run_controller("board")

    def test_zero_masks_is_not_reported_as_multiple(self):
        self.run_controller(mask_count=0)

    def test_multiple_masks_not_silently_combined(self):
        self.run_controller(mask_count=2)

    def test_custom_options_reach_the_actual_engine_call(self):
        self.run_controller("board",settings={"model_size":"4B","query":"circuit board", "vision_max_pixels":262144,
                            "max_new_tokens":256,"temperature":.2,"top_p":.9,"top_k":12,
                            "repetition_penalty":1.1,"mask_threshold":180})
