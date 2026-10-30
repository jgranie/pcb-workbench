"""Conservative colour confirmation of a reviewed semantic epoxy proposal."""
import cv2
import numpy as np
from .model_settings import validate


def epoxy_keep(rgb, board, proposal, settings=None, *, allow_empty=False):
    settings = validate("epoxy", settings)
    if rgb.shape[:2] != board.shape or proposal.shape != board.shape:
        raise ValueError("Masques de matière et photo incompatibles.")
    board = board.astype(bool)
    if not board.any():
        raise ValueError("Contour de carte vide.")
    # Filter only the analysis channel; never repaint Original. An edge-preserving
    # bilateral filter reduces the green texture without averaging across edges.
    channel = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[:, :, 1]
    smooth = cv2.bilateralFilter(channel, settings["bilateral_diameter"], settings["bilateral_sigma_color"], settings["bilateral_sigma_space"])
    threshold, _ = cv2.threshold(smooth[board], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if settings["lab_a_threshold"] is not None:
        threshold = settings["lab_a_threshold"]
    green = smooth < threshold
    excluded = board & (proposal >= 128) & green
    keep = board & ~excluded
    if (not excluded.any() and not allow_empty) or not keep.any():
        raise ValueError("Proposition d'époxy sans retrait exploitable ; aucun masque appliqué.")
    return keep.astype(np.uint8) * 255, {
        "method": "semantic_epoxy_AND_bilateral_lab_green_v1",
        "lab_a_threshold": float(threshold), "bilateral": [settings["bilateral_diameter"], settings["bilateral_sigma_color"], settings["bilateral_sigma_space"]],
        "excluded_pixels": int(excluded.sum()), "board_pixels": int(board.sum()),
        "uncertainty": "Colour agreement is not material identity or electrical validation.",
    }


def replace_section(previous, proposed, board, core=None):
    """Overwrite the selected core, including restored pixels; preserve its neighbours."""
    if previous.shape != proposed.shape or board.shape != previous.shape:
        raise ValueError("Dimensions des masques incompatibles.")
    height, width = previous.shape
    bounds = [0, 0, width, height] if core is None else core
    if (not isinstance(bounds, list) or len(bounds) != 4 or any(type(v) is not int for v in bounds)
            or not (0 <= bounds[0] < bounds[2] <= width and 0 <= bounds[1] < bounds[3] <= height)):
        raise ValueError("Section de remplacement invalide.")
    x,y,u,v = bounds
    result = previous.astype(bool).copy()
    result[y:v,x:u] = proposed[y:v,x:u].astype(bool) & board[y:v,x:u].astype(bool)
    return result


def legacy_epoxy_keep(job):
    """Rebuild the independent proposal from preserved raw output, without inference."""
    import hashlib
    import json
    from pathlib import Path
    from PIL import Image
    job = Path(job)
    evidence = json.loads((job/'mask-provenance.json').read_text())
    request = json.loads((job/'request.json').read_text())
    for name,key in [('raw-epoxy.png','raw_epoxy_sha256'),('input.png','source_sha256')]:
        if hashlib.sha256((job/name).read_bytes()).hexdigest() != evidence.get(key):
            raise ValueError("Source brute du masque modifiée ; remplacement refusé.")
    board = np.array(Image.open(job/'board.png')) >= 128
    parent = evidence['parent_board']
    if hashlib.sha256((job/'board.png').read_bytes()).hexdigest() != parent['alpha_sha256']:
        raise ValueError("Contour de la proposition modifié.")
    keep,_ = epoxy_keep(np.array(Image.open(job/'input.png').convert('RGB')), board,
                        np.array(Image.open(job/'raw-epoxy.png')),settings=request.get('settings'), allow_empty=True)
    return keep >= 128, request.get('core'), request
