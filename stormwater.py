"""Shared storage-only event balance for agent-generated stormwater drafts."""

def event_storage(rain_depth_m, treatment_area_m2, storage_depth_m, external_runoff_m3):
    """Reserve capacity for direct rain before screening external runoff storage."""
    capacity = treatment_area_m2 * storage_depth_m
    direct = rain_depth_m * treatment_area_m2 if rain_depth_m is not None else None
    capture = min(external_runoff_m3, max(capacity - direct, 0.)) if None not in (direct, external_runoff_m3) else None
    return dict(runoff_m3=external_runoff_m3, captured_m3=capture,
                excess_m3=external_runoff_m3 - capture if capture is not None else None,
                capacity_m3=capacity, direct_rain_m3=direct,
                direct_excess_m3=max(direct - capacity, 0.) if direct is not None else None,
                footprint_m2=treatment_area_m2)
