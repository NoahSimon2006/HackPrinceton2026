"""Audit local tour associations without contacting Matterport or other providers."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def audit():
    from server import LA_BOUNDS, property_catalog
    from site_view import SiteViewUnavailable, site_view_descriptor

    catalog = property_catalog()[0]
    statuses, exclusions = Counter(), Counter()
    tours, models, owners = 0, set(), {}
    maximum = 0
    for prop in catalog:
        try:
            value = site_view_descriptor(os.environ.get('COSTAR_KIT_DIR', ''), [prop], prop['id'])
        except SiteViewUnavailable:
            statuses['source_or_association_error'] += 1
            continue
        assert value['property']['id'] == prop['id'], 'Wrong property returned'
        scans = value['scans']
        assert value.get('tourCount', len(scans)) == len(scans), 'Tour count mismatch'
        assert len({scan['modelId'] for scan in scans}) == len(scans), 'Duplicate models returned'
        assert bool(scans) == (value['status'] == 'linked'), 'Incorrect availability status'
        assert value['scan'] in scans if scans else value['scan'] is None
        for scan in scans:
            model = scan['modelId']
            assert re.fullmatch(r'[A-Za-z0-9]{11}', model), 'Invalid model returned'
            assert scan['url'] == f'https://my.matterport.com/show/?m={model}', 'Untrusted tour URL'
            assert owners.setdefault(model, prop['id']) == prop['id'] or scan.get('sharedWithOtherProperty'), 'Shared model returned without disclosure'
            models.add(model)
        statuses[value['status']] += 1
        tours += len(scans)
        maximum = max(maximum, len(scans))
        for reason in value.get('exclusions', []):
            if isinstance(reason, dict):
                exclusions[reason.get('reason', 'unspecified')] += reason.get('count', 1)
    return {
        'audited_at_utc': datetime.now(timezone.utc).isoformat(),
        'catalog_properties': len(catalog), 'bounds': LA_BOUNDS,
        'property_statuses': dict(statuses), 'tours': tours,
        'unique_models': len(models), 'maximum_tours_per_property': maximum,
        'excluded_candidate_reasons': dict(exclusions),
        'playback_checked': False,
        'scope': 'Local supplied catalog and property/model associations only; no provider requests.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit-dir', help='Local CoStar kit directory; defaults to COSTAR_KIT_DIR or .env.')
    parser.add_argument('--output', type=Path, help='Optional aggregate JSON output; no raw property records.')
    args = parser.parse_args()
    if args.kit_dir:
        os.environ['COSTAR_KIT_DIR'] = args.kit_dir
    rendered = json.dumps(audit(), indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end='')
