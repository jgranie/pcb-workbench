"""Stable proposal identities without merging overlapping or identical boxes."""
import hashlib
import json


def identify_candidates(candidates, prepared_sha256):
    """Keep the historical first ID and suffix further occurrences of that ID."""
    occurrences = {}
    result = []
    for candidate in candidates:
        payload = json.dumps([prepared_sha256, candidate['coords']], separators=(',', ':'))
        base = 'PAD-W' + hashlib.sha256(payload.encode()).hexdigest()[:16]
        occurrence = occurrences.get(base, 0) + 1
        occurrences[base] = occurrence
        identity = base if occurrence == 1 else f'{base}-{occurrence:02d}'
        result.append({**candidate, 'id': identity, 'origin': 'wevisone_tiled_detection', 'status': 'candidate'})
    return result
