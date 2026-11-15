/** A static event-volume what-if, not a drainage or hydraulic model. */
export function eventVolumes(rainMm, scenario) {
  const rain = Math.min(scenario.maxRainMm, Math.max(0, Number(rainMm) || 0)) / 1000;
  const directRain = scenario.areaM2 * rain;
  const streetRunoff = scenario.sourceAreaM2 * scenario.coefficient * rain;
  const available = Math.max(0, scenario.storageM3 - directRain);
  const captured = Math.min(streetRunoff, available);
  return {rainMm: rain * 1000, directRain, streetRunoff, captured,
    overflow: Math.max(0, streetRunoff - captured),
    directOverflow: Math.max(0, directRain - scenario.storageM3),
    stored: Math.min(scenario.storageM3, directRain + streetRunoff)};
}
