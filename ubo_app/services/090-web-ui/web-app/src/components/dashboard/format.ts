const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"];

/** Humanize a byte count, e.g. 1536 → "1.5 KB". */
export function formatBytes(bytes: number): string {
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  // Sub-10 values keep a decimal so "1.5 GB" doesn't collapse to "2 GB".
  const digits = value < 10 && unit > 0 ? 1 : 0;
  return `${value.toFixed(digits)} ${BYTE_UNITS[unit]}`;
}

/** Humanize a transfer rate in bytes/second. */
export function formatRate(bytesPerSecond: number): string {
  return `${formatBytes(bytesPerSecond)}/s`;
}

/**
 * Render an uptime from the device's boot time.
 *
 * `boot_time` is epoch seconds and the browser's clock is its own, so a device
 * whose clock is behind can yield a negative span — clamp rather than render
 * "-1h".
 */
export function formatUptime(bootTime: number): string {
  if (!bootTime) return "—";
  const seconds = Math.max(0, Date.now() / 1000 - bootTime);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

/** Format a sensor reading at the precision its registry entry asks for. */
export function formatReading(
  value: number | undefined,
  precision: number | undefined,
): string {
  if (value === undefined || value === null) return "—";
  if (precision !== undefined && precision !== null) {
    return value.toFixed(precision);
  }
  // No suggested precision: keep one decimal for small magnitudes, none for
  // counts like CO2 ppm or illuminance lux.
  return Math.abs(value) < 100 ? value.toFixed(1) : Math.round(value).toString();
}
