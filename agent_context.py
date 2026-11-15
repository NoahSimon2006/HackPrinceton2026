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
