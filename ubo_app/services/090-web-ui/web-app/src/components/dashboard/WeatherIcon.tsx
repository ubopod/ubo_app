// Weather icons for the MET Norway symbol codes that arrive in
// `LocalizationState.weather.symbolCode`. The ~30 codes collapse onto 8 shapes
// plus precipitation variants; the `_day` / `_night` / `_polartwilight` suffix
// only decides sun vs moon.
//
// Colors come from props (the caller passes theme tokens) so one asset set
// serves both light and dark mode.

const SUN = "#f5a623";
const MOON = "#c8cede";
const RAIN = "#4a9fe0";
const SNOW = "#bcd8ee";
const BOLT = "#f5c518";

type Shape =
  | "clear"
  | "fair"
  | "partlycloudy"
  | "cloudy"
  | "fog"
  | "rain"
  | "sleet"
  | "snow"
  | "thunder";

interface Parsed {
  shape: Shape;
  isNight: boolean;
  /** 0 = light, 1 = normal, 2 = heavy. Drives how many drops/flakes appear. */
  intensity: number;
}

export function parseSymbolCode(symbolCode: string): Parsed {
  let base = symbolCode;
  let isNight = false;
  for (const suffix of ["_day", "_night", "_polartwilight"]) {
    if (base.endsWith(suffix)) {
      isNight = suffix === "_night";
      base = base.slice(0, -suffix.length);
      break;
    }
  }

  let intensity = 1;
  if (base.startsWith("light")) intensity = 0;
  if (base.startsWith("heavy")) intensity = 2;

  // Thunder wins over the precipitation it comes with — it is the headline.
  const shape: Shape = base.includes("thunder")
    ? "thunder"
    : base.includes("sleet")
      ? "sleet"
      : base.includes("snow")
        ? "snow"
        : base.includes("rain") || base.includes("drizzle")
          ? "rain"
          : base === "clearsky"
            ? "clear"
            : base === "fair"
              ? "fair"
              : base === "partlycloudy"
                ? "partlycloudy"
                : base === "fog"
                  ? "fog"
                  : "cloudy";

  return { shape, isNight, intensity };
}

function Sun({ cx, cy, r }: { cx: number; cy: number; r: number }) {
  const rays = [0, 45, 90, 135, 180, 225, 270, 315];
  return (
    <g>
      <circle cx={cx} cy={cy} r={r} fill={SUN} />
      {rays.map((angle) => {
        const rad = (angle * Math.PI) / 180;
        return (
          <line
            key={angle}
            x1={cx + Math.cos(rad) * (r + 3)}
            y1={cy + Math.sin(rad) * (r + 3)}
            x2={cx + Math.cos(rad) * (r + 7)}
            y2={cy + Math.sin(rad) * (r + 7)}
            stroke={SUN}
            strokeWidth={2.5}
            strokeLinecap="round"
          />
        );
      })}
    </g>
  );
}

function Moon({ cx, cy, r }: { cx: number; cy: number; r: number }) {
  // Crescent by subtraction: a filled disc with an offset disc masked out.
  const maskId = `moon-${cx}-${cy}`;
  return (
    <g>
      <mask id={maskId}>
        <rect x="0" y="0" width="64" height="64" fill="white" />
        <circle cx={cx + r * 0.55} cy={cy - r * 0.45} r={r * 0.95} fill="black" />
      </mask>
      <circle cx={cx} cy={cy} r={r} fill={MOON} mask={`url(#${maskId})`} />
    </g>
  );
}

function Cloud({
  cx,
  cy,
  scale = 1,
  fill,
}: {
  cx: number;
  cy: number;
  scale?: number;
  fill: string;
}) {
  return (
    <g transform={`translate(${cx} ${cy}) scale(${scale})`}>
      <path
        d="M -16 8 A 9 9 0 0 1 -14 -9 A 12 12 0 0 1 8 -12 A 10 10 0 0 1 16 8 Z"
        fill={fill}
      />
    </g>
  );
}

function Drops({ count, color }: { count: number; color: string }) {
  const positions = [-10, 0, 10].slice(0, count);
  return (
    <g>
      {positions.map((x, index) => (
        <line
          key={x}
          x1={32 + x}
          y1={44 + (index % 2) * 3}
          x2={32 + x - 3}
          y2={54 + (index % 2) * 3}
          stroke={color}
          strokeWidth={3}
          strokeLinecap="round"
        />
      ))}
    </g>
  );
}

function Flakes({ count }: { count: number }) {
  const positions = [-10, 0, 10].slice(0, count);
  return (
    <g>
      {positions.map((x, index) => (
        <circle key={x} cx={32 + x} cy={48 + (index % 2) * 4} r={2.6} fill={SNOW} />
      ))}
    </g>
  );
}

interface WeatherIconProps {
  symbolCode: string;
  size?: number;
  /** Theme-derived color for the cloud body, so it reads in both modes. */
  cloudColor: string;
}

export function WeatherIcon({
  symbolCode,
  size = 64,
  cloudColor,
}: WeatherIconProps) {
  const { shape, isNight, intensity } = parseSymbolCode(symbolCode);
  const dropCount = intensity === 0 ? 2 : 3;
  const Luminary = isNight ? Moon : Sun;

  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role="img"
      aria-label={symbolCode}
    >
      {shape === "clear" && <Luminary cx={32} cy={32} r={13} />}

      {shape === "fair" && (
        <>
          <Luminary cx={26} cy={26} r={11} />
          <Cloud cx={38} cy={40} scale={0.75} fill={cloudColor} />
        </>
      )}

      {shape === "partlycloudy" && (
        <>
          <Luminary cx={24} cy={24} r={10} />
          <Cloud cx={36} cy={38} scale={1} fill={cloudColor} />
        </>
      )}

      {shape === "cloudy" && <Cloud cx={32} cy={34} scale={1.25} fill={cloudColor} />}

      {shape === "fog" && (
        <>
          <Cloud cx={32} cy={26} scale={1.1} fill={cloudColor} />
          {[42, 49, 56].map((y, index) => (
            <line
              key={y}
              x1={14 + index * 2}
              y1={y}
              x2={50 - index * 2}
              y2={y}
              stroke={cloudColor}
              strokeWidth={3}
              strokeLinecap="round"
              opacity={0.75}
            />
          ))}
        </>
      )}

      {shape === "rain" && (
        <>
          <Cloud cx={32} cy={28} scale={1.15} fill={cloudColor} />
          <Drops count={dropCount} color={RAIN} />
        </>
      )}

      {shape === "sleet" && (
        <>
          <Cloud cx={32} cy={28} scale={1.15} fill={cloudColor} />
          <Drops count={2} color={RAIN} />
          <circle cx={42} cy={50} r={2.6} fill={SNOW} />
        </>
      )}

      {shape === "snow" && (
        <>
          <Cloud cx={32} cy={28} scale={1.15} fill={cloudColor} />
          <Flakes count={dropCount} />
        </>
      )}

      {shape === "thunder" && (
        <>
          <Cloud cx={32} cy={26} scale={1.15} fill={cloudColor} />
          <path
            d="M 34 38 L 26 50 L 32 50 L 28 60 L 40 46 L 33 46 L 38 38 Z"
            fill={BOLT}
          />
        </>
      )}
    </svg>
  );
}
