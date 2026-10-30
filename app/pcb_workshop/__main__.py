"""Local CLI. All processing is CPU-only and offline after installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from . import __version__
from .solder_detection import find_solders

ROOT = Path(__file__).resolve().parents[1]
cv2.setNumThreads(1)
cv2.ocl.setUseOpenCL(False)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def load_config(path):
    default = json.loads((ROOT / "config.json").read_text())
    config = json.loads(Path(path).read_text()) if path else default
    if config.keys() != default.keys():
        raise ValueError("Configuration : clés inconnues ou manquantes ; partir de config.json.")
    if config["schema_version"] != 1 or config["method"] not in ("otsu", "adaptive", "lab-a"):
        raise ValueError("Version ou méthode de segmentation non reconnue.")
    if config["solder_foreground"] not in ("none", "lab"):
        raise ValueError("solder_foreground doit être none ou lab.")
    for key in ("mirror_x", "allow_photo_gaps", "protect_pin_rows"):
        if type(config[key]) is not bool:
            raise ValueError(f"{key} doit être un booléen.")
    for key in ("rotate_quarters", "adaptive_window", "adaptive_offset", "remove_components_below",
                "solder_contrast", "solder_min_area", "solder_max_area", "solder_max_extent", "max_candidates", "solder_close_size"):
        if type(config[key]) is not int:
            raise ValueError(f"{key} doit être entier.")
    if not 0 <= config["rotate_quarters"] <= 3:
        raise ValueError("rotate_quarters doit être compris entre 0 et 3.")
    if not 3 <= config["adaptive_window"] <= 501 or config["adaptive_window"] % 2 != 1:
        raise ValueError("adaptive_window : entier impair de 3 à 501.")
    if not 1 <= config["max_candidates"] <= 1500 or not 0 <= config["remove_components_below"] <= 10000:
        raise ValueError("Limite de candidats ou taille de composante invalide.")
    if not 1 <= config["solder_min_area"] <= config["solder_max_area"] <= 10000:
        raise ValueError("Intervalle d'aire des soudures invalide.")
    if not 0 <= config["solder_contrast"] <= 255 or not 0 <= config["adaptive_offset"] <= 255:
        raise ValueError("Contrastes hors de l'intervalle 0–255.")
    if not 3 <= config["solder_max_extent"] <= 300 or not 0 <= config["solder_min_circularity"] <= 1:
        raise ValueError("Filtre de forme invalide.")
    if not 1 <= config["solder_max_aspect"] <= 10 or config["solder_close_size"] not in (1, 3, 5, 7):
        raise ValueError("Rapport de forme ou noyau de fermeture invalide.")
    crop = config["crop"]
    if crop is not None and (not isinstance(crop, list) or len(crop) != 4 or any(type(x) is not int for x in crop)):
        raise ValueError("crop : null ou [gauche, haut, droite, bas] en pixels.")
    return config


def extract_xcf(source, out, layer, gimp, *, native_path=None, inventory=False):
    executable = gimp or shutil.which("gimp-console") or shutil.which("gimp")
    mac = Path("/Applications/GIMP.app/Contents/MacOS/gimp-console")
    executable = executable or (str(mac) if mac.exists() else None)
    if not executable:
        raise ValueError("Entrée XCF : installer GIMP 3 ou fournir --gimp ; sinon exporter le calque en PNG.")
    # A dedicated configuration and --new-instance prevent contact with an open GUI.
    with tempfile.TemporaryDirectory(prefix="pcb-xcf-") as temporary:
        temp = Path(temporary)
        request = temp / "request.json"
        copy = temp / source.name
        shutil.copyfile(source, copy)
        save_json(request, {"source": str(copy), "output": str(out / "extracted.png"), "layer": layer, "native_path": native_path, "inventory": inventory})
        env = {**os.environ, "PCB_XCF_REQUEST": str(request), "GIMP3_DIRECTORY": str(temp / "gimp-config"),
               "GEGL_USE_OPENCL": "no", "GEGL_THREADS": "1"}
        script = ROOT / "pcb_workshop/xcf_export.py"
        command = [executable, "--new-instance", "--no-interface", "--no-data", "--no-fonts", "--no-splash",
                   "--batch-interpreter=python-fu-eval", "--batch", f"exec(compile(open({str(script)!r}).read(), {str(script)!r}, 'exec'))", "--quit"]
        try:
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired as error:
            raise ValueError("Extraction GIMP interrompue après 90 s ; consulter le XCF sans relance automatique.") from error
        # Batch failures may return zero. Require the export AND its receipt.
        (out / "gimp.log").write_text(result.stdout + result.stderr)
        if result.returncode or not (out / "extracted.json").exists():
            raise ValueError("Extraction XCF échouée ; voir gimp.log. Calque exact et GIMP 3 requis.")
    return out / "extracted.png", json.loads((out / "extracted.json").read_text())


def remove_small(mask, minimum):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=4)
    keep = np.zeros(count, dtype=np.uint8)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= minimum
    return keep[labels]


def segment(rgb, config, board_mask=None, material_mask=None):
    """Green-board heuristic; no labels, boxes or old masks are accepted."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    r, g, b = [rgb[:, :, i].astype(np.float32) for i in range(3)]
    green = ((hsv[:, :, 1] > 55) & (g > 1.15 * r) & (g > .90 * b)).astype(np.uint8)
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    if board_mask is None:
        contours, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours or cv2.contourArea(max(contours, key=cv2.contourArea)) < gray.size * .15:
            raise ValueError("Contour de carte verte introuvable. Recadrer ou utiliser une photo plus contrastée ; méthode hors domaine.")
        board = np.zeros_like(gray)
        cv2.drawContours(board, [max(contours, key=cv2.contourArea)], -1, 1, -1)
    else:
        if board_mask.shape != gray.shape or not board_mask.any():
            raise ValueError("Masque de carte vide ou de dimensions incompatibles.")
        board = board_mask.astype(np.uint8)
    solder, proposals, stats = find_solders(rgb, config, board, material_mask, strict_board=board_mask is not None)
    threshold = None
    if config["method"] == "otsu":
        threshold, _ = cv2.threshold(gray[board > 0], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        copper = gray <= threshold
    elif config["method"] == "adaptive":
        copper = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,
                                       config["adaptive_window"], config["adaptive_offset"]) > 0
    else:
        a = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[:, :, 1]
        threshold, _ = cv2.threshold(a[board > 0], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        copper = a > threshold
    if material_mask is not None:
        copper &= material_mask
    mask = remove_small(((copper | (solder > 0)) & (board > 0)).astype(np.uint8), config["remove_components_below"])
    return mask, board, solder, proposals, {"threshold": threshold, **stats,
                                          "board_pixels": int(board.sum()), "mask_pixels": int(mask.sum()),
                                          "mask_fraction": float(mask.mean()), "candidates": len(proposals)}


def source_code_hashes():
    paths = sorted([*ROOT.glob("pcb_workshop/*.py"), *ROOT.glob("web/**/*.mjs"), *ROOT.glob("web/*.html"),
                    ROOT / "requirements.lock", ROOT / "workshop", ROOT / ".python-version", ROOT / ".node-version"])
    return {str(p.relative_to(ROOT)): digest(p) for p in paths if p.is_file()}


def run_pipeline(args):
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Entrée introuvable : {source.name}")
    config = load_config(args.config)
    out = Path(args.output).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    try:
        before = digest(source)
        provenance = {"input_filename": source.name, "input_sha256": before, "llm_calls_during_this_cpu_run": 0,
                      "manual_reference_inputs": [], "algorithm_version": __version__, "config": config,
                      "code_sha256": source_code_hashes(),
                      "runtime": {"python": sys.version.split()[0], "opencv": cv2.__version__,
                                  "numpy": np.__version__, "pillow": Image.__version__,
                                  "node": subprocess.check_output(["node", "--version"], text=True).strip()},
                      "coordinate_policy": "EXIF transpose, explicit crop, clockwise quarters, explicit mirror; no auto perspective"}
        photo_path = source
        if source.suffix.lower() == ".xcf":
            photo_path, extraction = extract_xcf(source, out, args.layer, args.gimp)
            provenance["xcf"] = extraction
        with Image.open(photo_path) as im:
            provenance["encoded_size"] = list(im.size)
            provenance["exif_orientation"] = im.getexif().get(274, 1)
            image = ImageOps.exif_transpose(im).convert("RGBA")
        provenance["exif_transposed_size"] = list(image.size)
        if config["crop"]:
            x, y, u, v = config["crop"]
            if not (0 <= x < u <= image.width and 0 <= y < v <= image.height):
                raise ValueError("Recadrage hors de l'image.")
            image = image.crop((x, y, u, v))
        if config["rotate_quarters"]:
            image = image.rotate(-90 * config["rotate_quarters"], expand=True)
        if config["mirror_x"]:
            image = ImageOps.mirror(image)
        if image.width < 32 or image.height < 32 or image.width * image.height > 6000000:
            raise ValueError("Image hors des bornes CPU : minimum 32×32, maximum 6 millions de pixels ; recadrer explicitement.")
        rgba = np.array(image)
        if np.any(rgba[:, :, 3] != 255):
            raise ValueError("L'entrée Original comporte des pixels transparents ; fournir une photo opaque pour éviter un masque préparé implicite.")
        Image.fromarray(rgba).save(out / "original.png")
        board_mask = None
        mask_path = getattr(args, "board_mask", None)
        provenance["pipeline_mode"] = "cpu_from_original" if not mask_path else "assisted_background_mask"
        provenance["standalone_from_original"] = not bool(mask_path)
        if mask_path:
            mask_path = Path(mask_path).resolve()
            with Image.open(mask_path) as prepared:
                if prepared.mode != "L" or prepared.size != image.size:
                    raise ValueError("Le masque doit être un PNG gris au même repère et aux dimensions de l'Original.")
                board_mask = np.array(prepared) >= 128
            shutil.copyfile(mask_path, out / "external-board-mask.png")
            evidence_path = getattr(args, "board_mask_provenance", None)
            evidence = json.loads(Path(evidence_path).read_text()) if evidence_path else {"origin": "provided_mask_unknown_producer"}
            if evidence_path and (evidence.get("source_sha256") != before or evidence.get("alpha_sha256") != digest(mask_path)):
                raise ValueError("La provenance du masque ne correspond pas à cette source.")
            provenance["background_mask"] = {"sha256": digest(mask_path), "threshold": 128, "evidence": evidence}
        material_mask = None
        material_path = getattr(args, "material_mask", None)
        if material_path:
            if board_mask is None:
                raise ValueError("Un masque de matière nécessite un contour de carte distinct.")
            material_path = Path(material_path).resolve()
            with Image.open(material_path) as prepared:
                if prepared.mode != "L" or prepared.size != image.size:
                    raise ValueError("Masque de matière incompatible avec Original.")
                material_mask = np.array(prepared) >= 128
            if not material_mask.any() or np.any(material_mask & ~board_mask):
                raise ValueError("Le masque de matière doit rester dans la carte et conserver des pixels.")
            evidence = json.loads(Path(args.material_mask_provenance).read_text())
            if evidence.get("source_sha256") != before or evidence.get("alpha_sha256") != digest(material_path):
                raise ValueError("La provenance du masque de matière ne correspond pas à cette source.")
            shutil.copyfile(material_path, out / "external-material-mask.png")
            provenance["material_mask"] = {"sha256": digest(material_path), "evidence": evidence}
            provenance["pipeline_mode"] = "assisted_epoxy_mask"
        mask, board, solder, candidates, stats = segment(rgba[:, :, :3], config, board_mask=board_mask, material_mask=material_mask)
        for name, values in (("mask", mask), ("board", board), ("solder", solder)):
            Image.fromarray(values * 255).save(out / f"{name}.png")
        (out / "alpha.bin").write_bytes((mask * 255).tobytes())
        (out / "photo.bin").write_bytes(rgba.tobytes())
        save_json(out / "config.json", config)
        save_json(out / "image.json", {"width": image.width, "height": image.height,
                                     "rgba_sha256": hashlib.sha256(rgba.tobytes()).hexdigest()})
        save_json(out / "candidates.json", {"candidates": candidates, "electrical_validation": False})
        save_json(out / "segmentation-diagnostics.json", stats)
        routed = subprocess.run(["node", str(ROOT / "web/route.mjs"), str(out)], capture_output=True, text=True, timeout=120)
        (out / "routing.log").write_text(routed.stdout + routed.stderr)
        if routed.returncode:
            raise ValueError("Routage interrompu ; voir routing.log. Résultats partiels conservés.")
        scan = json.loads((out / "scan.json").read_text())
        workspace = {"schema_version": 1, "source_rgba_sha256": hashlib.sha256(rgba.tobytes()).hexdigest(),
                     "canvas": {"width": image.width, "height": image.height}, "objects": [], "nextId": 1,
                     "detectionReviews": {}, "traceScan": scan, "calibration": {"status": "unverified", "sx": None, "sy": None}}
        save_json(out / "workspace.json", workspace)
        provenance["source_unchanged"] = before == digest(source)
        if not provenance["source_unchanged"]:
            raise ValueError("L'entrée a changé pendant le traitement.")
        save_json(out / "provenance.json", provenance)
        save_json(out / "timings.json", {"total_seconds": time.perf_counter() - start})
        render_preview(out, image, candidates, scan)
        status = "complete_proposals" if scan["complete"] and not stats["candidates_truncated"] else "partial_proposals"
        # The initial workspace remains an immutable reproducibility receipt after review starts.
        shutil.copyfile(out / "workspace.json", out / "workspace.initial.json")
        useful = ["original.png", "mask.png", "board.png", "solder.png", "image.json", "config.json", "candidates.json", "alpha.bin", "photo.bin",
                  "scan.json", "workspace.initial.json", "provenance.json", "segmentation-diagnostics.json", "routing-diagnostics.json", "preview.jpg"]
        if board_mask is not None:
            useful.append("external-board-mask.png")
        if material_mask is not None:
            useful.append("external-material-mask.png")
        save_json(out / "result.json", {"status": status, "electrical_validation": False,
                                       "useful_sha256": {name: digest(out / name) for name in useful}})
        print(json.dumps({"output": str(out), "status": status, **stats, **json.loads((out / "routing-diagnostics.json").read_text())}, ensure_ascii=False))
    except Exception as error:
        save_json(out / "failure.json", {"error": str(error), "status": "failed", "retained_for_diagnosis": True})
        raise


def render_preview(out, photo, candidates, scan):
    overlay = Image.new("RGBA", photo.size)
    draw = ImageDraw.Draw(overlay)
    for route in scan["routes"]:
        color = (242, 160, 10, 230) if route["gaps"] else (180, 80, 240, 220) if route["broad"] else (255, 205, 10, 230)
        draw.line([tuple(p) for p in route["points"]], fill=color, width=3)
    for candidate in candidates:
        draw.rectangle(candidate["coords"], outline=(30, 245, 240, 255), width=2)
    result = Image.alpha_composite(photo, overlay).convert("RGB")
    result.thumbnail((1000, 1400))
    result.save(out / "preview.jpg", quality=88)


def compare_runs(args):
    a, b = Path(args.first), Path(args.second)
    left, right = [json.loads((p / "result.json").read_text()) for p in (a, b)]
    keys = sorted(set(left["useful_sha256"]) | set(right["useful_sha256"]))
    differences = [key for key in keys if left["useful_sha256"].get(key) != right["useful_sha256"].get(key)]
    # Re-hash files: a matching stale receipt alone is not a comparison.
    corrupt = [f"{label}/{key}" for label, directory, receipt in (("first", a, left), ("second", b, right))
               for key, sha in receipt["useful_sha256"].items() if digest(directory / key) != sha]
    result = {"equal_useful_outputs": not differences and not corrupt, "differences": differences, "corrupt": corrupt,
              "excluded": ["timings.json", "routing-timings.json", "gimp.log", "routing.log", "extracted.png container metadata"],
              "same_status": left["status"] == right["status"], "electrical_validation": False}
    if args.output:
        save_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["equal_useful_outputs"] or not result["same_status"]:
        raise ValueError("Les sorties utiles diffèrent ; examiner le rapport.")


def main():
    parser = argparse.ArgumentParser(description="Atelier PCB reproductible, propositions CPU sans LLM.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Créer un résultat et un workspace vierges ; n'écrase jamais un dossier.")
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--config")
    run.add_argument("--layer", default="Original")
    run.add_argument("--gimp")
    run.add_argument("--material-mask", help="Masque de matière à conserver, distinct du contour PCB.")
    run.add_argument("--material-mask-provenance", help="Provenance obligatoire du masque matière.")
    run.add_argument("--board-mask", help="Masque gris facultatif au repère canonique ; parcours assisté distinct du CPU depuis zéro.")
    run.add_argument("--board-mask-provenance", help="Preuve de source et d'origine du masque facultatif.")
    run.set_defaults(handler=run_pipeline)
    compare = commands.add_parser("compare", help="Comparer deux exécutions, hors dates et durées.")
    compare.add_argument("first"); compare.add_argument("second"); compare.add_argument("--output")
    compare.set_defaults(handler=compare_runs)
    serve = commands.add_parser("serve", help="Ouvrir la revue isolée locale.")
    serve.add_argument("directory"); serve.add_argument("--port", type=int, default=8876)
    from .server import serve_workspace
    serve.set_defaults(handler=serve_workspace)
    args = parser.parse_args()
    try:
        args.handler(args)
    except (ValueError, OSError, subprocess.SubprocessError, Image.DecompressionBombError) as error:
        parser.exit(2, f"Erreur : {error}\n")


if __name__ == "__main__":
    main()
