"""Bounded CPU trace parameters stored independently of solder/model settings."""
DEFAULTS = {'allow_photo_gaps': False, 'protect_pin_rows': True, 'max_visited': 3000000, 'time_limit_ms': 10000}


def validate(value=None):
    if value is not None and (not isinstance(value, dict) or set(value)-set(DEFAULTS)):
        raise ValueError('Paramètres pistes inconnus.')
    result = {**DEFAULTS, **(value or {})}
    for key in ('allow_photo_gaps', 'protect_pin_rows'):
        if type(result[key]) is not bool:
            raise ValueError('Paramètre pistes invalide : '+key)
    for key, low, high in [('max_visited', 10000, 6000000), ('time_limit_ms', 1000, 30000)]:
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError('Paramètre pistes invalide : '+key)
    return result
