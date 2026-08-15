// How to render a sensor reading, keyed by the Home Assistant `device_class`
// the sensor registry assigns it. The device streams the class, unit and label
// with every reading, so this table only supplies what is purely presentational:
// an icon, and a range to meter against.
//
// A range is deliberately absent for anything with no natural bounds — a VOC
// index, a gas resistance in ohms, a time-of-flight distance. Those render as
// plain stats: a meter implies a limit, and inventing one would be a lie.

interface DisplaySpec {
  /** Nerd Font glyph. */
  icon: string;
  /** Meter bounds. Omitted where no meaningful range exists. */
  range?: [number, number];
}

const BY_DEVICE_CLASS: Record<string, DisplaySpec> = {
  temperature: { icon: "󰔏", range: [-10, 50] },
  humidity: { icon: "󰖎", range: [0, 100] },
  pressure: { icon: "󰊪", range: [950, 1050] },
  illuminance: { icon: "󰃞", range: [0, 1000] },
  carbon_dioxide: { icon: "󱂈", range: [400, 2000] },
  volatile_organic_compounds_parts: { icon: "󰤫", range: [0, 1000] },
  aqi: { icon: "󰵈", range: [1, 5] },
  pm1: { icon: "󰩵", range: [0, 100] },
  pm25: { icon: "󰩵", range: [0, 100] },
  pm10: { icon: "󰩵", range: [0, 100] },
  distance: { icon: "󰺪" },
};

// Fallbacks for the entities the registry gives no device_class — matched on
// the entity key instead.
const BY_KEY: Record<string, DisplaySpec> = {
  gas_resistance: { icon: "󰤫" },
  voc_index: { icon: "󰤫" },
  validity: { icon: "󰋼" },
  altitude: { icon: "󰔰" },
};

const FALLBACK: DisplaySpec = { icon: "󰊚" };

export function displaySpec(
  key: string,
  deviceClass: string | undefined,
): DisplaySpec {
  if (deviceClass && BY_DEVICE_CLASS[deviceClass]) {
    return BY_DEVICE_CLASS[deviceClass];
  }
  return BY_KEY[key] ?? FALLBACK;
}

/** Position a reading within its range, 0-1, for the meter fill. */
export function rangeFraction(value: number, [min, max]: [number, number]): number {
  if (max <= min) return 0;
  return (value - min) / (max - min);
}
