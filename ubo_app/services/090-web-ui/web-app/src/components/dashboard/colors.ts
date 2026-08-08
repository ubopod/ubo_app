// Status palette — fixed, never themed, and deliberately distinct from any
// series color so a status hue never impersonates a category. On a light
// surface `warning` and `serious` fall below 3:1 by design; every meter that
// uses them also carries a visible label, so color is never the only channel.
export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
} as const;

// The neutral accent for ratios that carry no severity meaning — a sensor
// reading within its normal range is not "good news", it is just a number.
export const NEUTRAL_ACCENT = "#2a78d6";

/**
 * Pick a meter fill for a load-style percentage, where more is worse.
 *
 * Applies to CPU, RAM and disk. Sensor readings deliberately do not use this:
 * a high humidity is not a fault.
 */
export function loadSeverity(percent: number): string {
  if (percent >= 90) return STATUS.critical;
  if (percent >= 80) return STATUS.serious;
  if (percent >= 60) return STATUS.warning;
  return STATUS.good;
}
