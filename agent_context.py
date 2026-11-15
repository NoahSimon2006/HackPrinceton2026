"""Small model-facing evidence views; full validated facts stay in local artifacts."""


def fact_index(items, *, include_source=True):
    """Keep citation identities and exact display values without repeating provenance prose."""
    return [{key: item[key] for key in ('id', 'label', 'display', 'basis') if key in item}
            | ({'source': {key: value for key, value in item.get('source', {}).items()
                          if key in ('provider', 'observed_at') and value is not None}} if include_source else {})
            for item in items]


def compact_evaluation(payload):
    return {**payload, 'facts': fact_index(payload.get('facts', [])),
            'full_evidence_artifact': '/project/evaluations/traffic.json',
            'evidence_usage': 'Exact citation IDs and values above. Read the full artifact only for a specific source method, assumption or unresolved detail.'}


# Reviewed primary-source excerpts. These are design research, never site observations
# or permission to apply published aggregate safety effects to a selected intersection.
ROAD_GUIDANCE = (
    {
        'id': 'road-guidance-intersection', 'label': 'Connected intersection and corner design guidance',
        'url': 'https://highways.dot.gov/safety/speed-management/traffic-calming-eprimer/module-3-part-2',
        'kinds': ['intersection_redesign'],
        'summary': 'Corner extensions continue the sidewalk into available street space. A complete intersection concept coordinates the roadway, pedestrian waiting areas, crossings and the paths into adjoining streets.',
        'checks': 'Connect crossings to pedestrian space and review access, turning vehicles, bicycle routes and available roadway width together. A detached stripe or decorative island is not a complete redesign.',
    },
    {
        'id': 'road-guidance-roundabout', 'label': 'Roundabout layout and site selection guidance',
        'url': 'https://highways.dot.gov/safety/intersection-safety/intersection-types/roundabouts',
        'kinds': ['intersection_redesign'],
        'summary': 'Roundabouts organize vehicle paths around a central island with coordinated entries, exits and pedestrian crossings. Suitability depends on the available footprint and the connected approaches.',
        'checks': 'Do not force a circular layout into a constrained junction or treat a drawn circle as verified vehicle circulation. Check space, accessible crossings, large-vehicle paths and the intersection control choice before recommending construction.',
    },
    {
        'id': 'road-guidance-crossing', 'label': 'Crosswalk visibility guidance',
        'url': 'https://highways.dot.gov/safety/proven-safety-countermeasures/crosswalk-visibility-enhancements',
        'kinds': ['crossing', 'lane_marking'],
        'summary': 'High-visibility crossing patterns, lighting, signing and pavement markings can be combined to improve crossing conspicuity. A marked crossing alone may be insufficient on a multilane road.',
        'checks': 'Check crossing demand, sight lines, lane count, traffic conditions, lighting and applicable traffic-control requirements before selecting a treatment.',
    },
    {
        'id': 'road-guidance-refuge', 'label': 'Pedestrian refuge guidance',
        'url': 'https://highways.dot.gov/safety/proven-safety-countermeasures/medians-and-pedestrian-refuge-islands-urban-and-suburban-areas',
        'kinds': ['pedestrian_island'],
        'summary': 'A pedestrian refuge provides a place to cross one direction of traffic at a time. Multilane approaches and locations serving pedestrian destinations are contexts to investigate.',
        'checks': 'Check available width, accessible crossing connections, turning paths and the actual pedestrian route; a mapped island is not proof of safe operation.',
    },
    {
        'id': 'road-guidance-reallocation', 'label': 'Road space reallocation guidance',
        'url': 'https://highways.dot.gov/safety/speed-management/traffic-calming-eprimer/module-3-part-3',
        'kinds': ['bike_lane', 'pedestrian_space', 'pedestrian_island'],
        'summary': 'Roadway reconfiguration can allocate space to bicycle and pedestrian facilities. Review traffic accommodation, adjacent access, transit and emergency-vehicle turning requirements together.',
        'checks': 'Do not assume that a lane conversion reduces delay or emissions. Median and bicycle treatments need access, operating-width and turning review.',
    },
    {
        'id': 'road-guidance-curb', 'label': 'Crossing treatment selection guidance',
        'url': 'https://highways.dot.gov/sites/fhwa.dot.gov/files/2022-07/STEP_Guide_for_Improving_Ped_Safety_at_Unsig_Loc_3-2018_07_17-508compliant.pdf',
        'kinds': ['curb_extension', 'crossing', 'pedestrian_space'],
        'summary': 'Select crossing treatments using the roadway geometry, surrounding land use and pedestrian travel patterns. Curb extensions and refuge islands can be considered with road reconfiguration.',
        'checks': 'Keep access and turning needs visible, check the intended crossing endpoints, and evaluate complementary treatments instead of assuming markings alone resolve the problem.',
    },
)


def road_guidance_facts():
    from site_measurements import fact
    return [fact(item['id'], item['label'], item['summary'], '',
                 {'provider': 'FHWA', 'url': item['url'], 'observed_at': None,
                  'retrieved_at': '2026-11-15T00:00:00Z', 'collection': 'Reviewed road-design guidance'},
                 basis='reported', method='Paraphrased primary guidance reviewed November 15, 2026; not a site-specific study.',
                 note=item['checks'] + ' No site-specific crash, delay or emissions benefit is calculated.')
            for item in ROAD_GUIDANCE]
