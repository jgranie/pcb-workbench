"""One explicitly requested model call using the existing guarded local engine.

Runs inside the configured WeVisOne environment, never the CPU application's
environment. No weights are downloaded and no runtime/profile is substituted.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sys

if __package__:
    from .model_settings import validate
else:
    from model_settings import validate


def main():
    job = Path(sys.argv[1]).resolve()
    request = json.loads((job / "request.json").read_text())
    shared = Path(request["shared_runtime"])
    sys.path.insert(0, str(shared))
    import guarded_engine
    from PIL import Image

    def interrupted(signum, frame):
        raise KeyboardInterrupt("Arrêt demandé ; aucune relance automatique.")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if Path(sys.prefix).resolve() != Path(guarded_engine.PYTHON).parent.parent.resolve():
        raise RuntimeError("Environnement WeVisOne différent de celui configuré.")
    kind = request.get("kind", "board")
    if kind == "solders":
        try:
            from solder_model_controller import run
            run(job)
        except BaseException as error:
            (job / "controller-error.txt").write_text(str(error) or type(error).__name__)
            raise
        return
    if kind not in ("board", "epoxy"):
        raise RuntimeError("Type de prétraitement inconnu.")
    settings = validate(kind, request.get("settings"))
    profile = guarded_engine.get_model_profile(settings["model_size"])
    query = settings["query"]
    source = job / "input.png"
    if hashlib.sha256(source.read_bytes()).hexdigest() != request["source_sha256"]:
        raise RuntimeError("L'image figée a changé.")
    try:
        with contextlib.ExitStack() as stack:
            # Keep both existing cross-application locks while redirecting artifacts.
            paths = [] if os.environ.get("PCB_WEVISONE_SESSION") else [shared.parents[1] / "outputs/wevisone-vl/jobs/.batch.lock",
                         shared.parents[1] / "outputs/wevisone-vl/inference.lock"]
            for path in paths:
                handle = stack.enter_context(path.open("r"))
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            guarded_engine.OUTPUT = job / "engine"
            guarded_engine.OUTPUT.mkdir()
            model_image = Image.open(source).convert("RGB")
            if kind == "epoxy" and request.get("crop"):
                model_image = model_image.crop(tuple(request["crop"]))
            result = guarded_engine.GuardedEngine().predict(
                model_image, task="segmentation", query=query,
                decode_matting=True, model_size=settings["model_size"], **{key: settings[key] for key in ("vision_max_pixels","max_new_tokens","temperature","top_p","top_k","repetition_penalty")})
            run = Path(result.run_directory)
            generation = result.generation
            if not generation.get("response_complete"):
                raise RuntimeError("Réponse incomplète ; le masque reste inutilisable et aucune relance n'est faite.")
            if not result.masks:
                raise RuntimeError("Aucun masque décodé malgré la réponse complète ; aucun retrait appliqué.")
            if len(result.masks) != 1:
                raise RuntimeError(f"{len(result.masks)} masques décodés ; une revue distincte est requise avant toute combinaison.")
            import numpy as np
            array = np.asarray(result.masks[0])
            if array.ndim != 2 or not np.isfinite(array).all():
                raise RuntimeError("Le décodeur n'a pas produit un masque fini à deux dimensions.")
            # The shared exporter writes alpha at the exact input canvas dimensions.
            alpha = Image.open(run / "alpha.png").convert("L")
            if alpha.size != model_image.size or alpha.getextrema() in ((0, 0), (255, 255)):
                raise RuntimeError("Masque vide, entièrement opaque ou mal dimensionné.")
            if kind == "epoxy" and request.get("crop"):
                # Decode with halo for context; commit only the non-overlapping core.
                a,b,u,v = request["crop"];x,y,r,t = request["core"]
                core = alpha.crop((x-a,y-b,r-a,t-b))
                full = Image.new("L", Image.open(source).size, 0)
                full.paste(core,(x,y));alpha = full
            alpha = alpha.point(lambda pixel: 255 if pixel >= settings["mask_threshold"] else 0)
            if alpha.getextrema() == (0,0) and kind == "board":
                raise RuntimeError("Le seuil choisi ne conserve aucun pixel du masque.")
            alpha.save(job / "alpha.png")
            cutout = Image.open(source).convert("RGBA");cutout.putalpha(alpha);cutout.save(job / "cutout.png")
            evidence = {"source_sha256": request["source_sha256"], "model": profile["model_id"], "model_size": profile["size"],
                        "revision": profile["revision"], "backend": "transformers",
                        "device": "mps", "dtype": "bfloat16", "task": "segmentation", "query": query, "kind": kind, "decode_matting": True,
                        "settings": settings, "vision_max_pixels": settings["vision_max_pixels"], "max_new_tokens": settings["max_new_tokens"],
                        "alpha_sha256": hashlib.sha256((job / "alpha.png").read_bytes()).hexdigest(),
                        "threshold_for_routing": 128, "generation": generation,
                        "crop": request.get("crop"), "core": request.get("core"), "section": request.get("section"),
                        "execution": "real_model", "electrical_validation": False}
            (job / "mask-provenance.json").write_text(json.dumps(evidence, indent=2) + "\n")
    except BaseException as error:
        (job / "controller-error.txt").write_text(str(error) or type(error).__name__)
        raise


if __name__ == "__main__":
    main()
