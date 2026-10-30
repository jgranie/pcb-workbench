"""Deterministic tile geometry and conservative cross-tile proposal stitching."""
import math


def make_tiles(width, height, columns=4, rows=6, halo=64):
    xs = [round(i * width / columns) for i in range(columns + 1)]
    ys = [round(i * height / rows) for i in range(rows + 1)]
    return [
        {'id': f'R{r+1}C{c+1}', 'row': r, 'column': c,
         'core': [xs[c], ys[r], xs[c+1], ys[r+1]],
         'bounds': [max(0, xs[c]-halo), max(0, ys[r]-halo),
                    min(width, xs[c+1]+halo), min(height, ys[r+1]+halo)]}
        for r in range(rows) for c in range(columns)
    ]


def globalize(box, tile, proposal_id):
    bx, by, right, bottom = tile['bounds']
    width, height = right-bx, bottom-by
    x0, y0, x1, y1 = [float(v) for v in box]
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        raise ValueError('Non-finite detection coordinates')
    x0, x1 = max(0, min(width, x0)), max(0, min(width, x1))
    y0, y1 = max(0, min(height, y0)), max(0, min(height, y1))
    if x1 <= x0 or y1 <= y0:
        return None
    edge_margin = min(x0, y0, width-x1, height-y1)
    coords = [x0+bx, y0+by, x1+bx, y1+by]
    cx, cy = (coords[0]+coords[2])/2, (coords[1]+coords[3])/2
    a, b, c, d = tile['core']
    return {'proposal_id': proposal_id, 'tile': tile['id'], 'coords': coords,
            'core_owned': a <= cx < c and b <= cy < d,
            'touches_crop_edge': edge_margin <= 2,
            'edge_margin_px': edge_margin}


def duplicate_match(a, b):
    """Match similar nearby boxes, never collapse a large group onto a small pad."""
    if a['tile'] == b['tile']:
        return False
    x0, y0, x1, y1 = a['coords']
    u0, v0, u1, v1 = b['coords']
    area_a, area_b = (x1-x0)*(y1-y0), (u1-u0)*(v1-v0)
    intersection = max(0, min(x1,u1)-max(x0,u0))*max(0, min(y1,v1)-max(y0,v0))
    if intersection == 0 or max(area_a,area_b)/min(area_a,area_b) > 2:
        return False
    iou = intersection/(area_a+area_b-intersection)
    distance = math.hypot((x0+x1-u0-u1)/2, (y0+y1-v0-v1)/2)
    min_diagonal = min(math.hypot(x1-x0,y1-y0), math.hypot(u1-u0,v1-v0))
    return iou >= .45 and distance <= .3*min_diagonal


def stitch(proposals):
    # Retain an actual observed box; averaging could move it between terminals.
    ranked = sorted(proposals, key=lambda p: (
        p['touches_crop_edge'], not p['core_owned'], -p['edge_margin_px'], p['proposal_id']))
    groups = []
    for proposal in ranked:
        for group in groups:
            if proposal['tile'] not in {p['tile'] for p in group['observations']} and duplicate_match(proposal, group['representative']):
                group['observations'].append(proposal)
                break
        else:
            groups.append({'representative': proposal, 'observations': [proposal]})
    groups.sort(key=lambda g: (sum(g['representative']['coords'][1::2])/2,
                               sum(g['representative']['coords'][::2])/2))
    return [
        {'id': f'PAD-{i+1:04d}', 'coords': g['representative']['coords'],
         'selected_proposal': g['representative']['proposal_id'],
         'status': 'candidate_unvalidated', 'observation_count': len(g['observations']),
         'observations': g['observations']}
        for i, g in enumerate(groups)
    ]
