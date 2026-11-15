"""Canonical planner controls and bounded agent choices for stormwater concepts."""
from copy import deepcopy
import math

DEFAULTS = {'targetAreaM2': None, 'storageDepthM': None, 'layout': 'auto', 'placement': 'auto',
            'runoffCoefficient': None, 'drainageAssumption': 'unknown', 'protectAccess': False}
LIMITS = {'targetAreaM2': (2, 500), 'storageDepthM': (.05, .30), 'runoffCoefficient': (0, 1)}


def validate_settings(value, workflow='water', *, markings=None, for_analysis=False):
    if value is None:
        return deepcopy(DEFAULTS) if workflow == 'water' else None
    if workflow != 'water' or not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Use the stormwater controls only in the Stormwater workflow.')
    clean = {**DEFAULTS, **value}
    for key, (low, high) in LIMITS.items():
        number = clean[key]
        if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high):
            raise ValueError(f'{key} must be between {low:g} and {high:g}, or left for the agent.')
    if clean['layout'] not in ('auto', 'compact', 'linear') or clean['placement'] not in ('auto', 'near_selection', 'landscape_first', 'away_from_previous'):
        raise ValueError('Choose a supported stormwater shape and placement preference.')
    if clean['drainageAssumption'] not in ('unknown', 'marked_connected') or type(clean['protectAccess']) is not bool:
        raise ValueError('Choose whether marked areas are an explicit connected-drainage what-if.')
    if for_analysis and clean['drainageAssumption'] == 'marked_connected':
        if clean['runoffCoefficient'] is None or not any(item['kind'] == 'drainage' for item in markings or []):
            raise ValueError('To evaluate the drainage what-if, outline a runoff source and explicitly enter its runoff coefficient.')
    return clean


def effective_settings(canonical, proposed=None, previous=None, previous_user=None):
    """Explicit user values win; agent choices cannot establish drainage connectivity."""
    user = validate_settings(canonical)
    proposed = proposed or {}
    previous = previous or {}
    result = {}
    for key, fallback in [('targetAreaM2', 40), ('storageDepthM', .15), ('layout', 'compact'), ('placement', 'near_selection')]:
        result[key] = next(value for value in (user[key], proposed.get(key), previous.get(key), fallback) if value not in (None, 'auto'))
    result['runoffCoefficient'] = user['runoffCoefficient'] if user['drainageAssumption'] == 'marked_connected' else None
    result['drainageAssumption'] = user['drainageAssumption']
    if (previous_user or {}).get('protectAccess') is True and not user['protectAccess']:
        result['protectAccess'] = False  # An explicit unchecked control withdraws its prior requirement.
    else:
        requested = proposed.get('protectAccess')
        result['protectAccess'] = user['protectAccess'] or (requested if requested is not None else previous.get('protectAccess', False))
    return validate_settings(result)
