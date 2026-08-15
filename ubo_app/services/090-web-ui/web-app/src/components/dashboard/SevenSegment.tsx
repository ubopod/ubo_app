// A seven-segment digit display, drawn as SVG rather than set in a font: it
// scales to whatever the tile gives it, needs no webfont in a bundle that must
// stay self-contained, and can render the unlit segments — which is most of
// what makes a real LED display read as one.

// Segment geometry for a single digit cell, 60 × 100.
//
//    --a--
//   |     |
//   f     b
//   |     |
//    --g--
//   |     |
//   e     c
//   |     |
//    --d--
const DIGIT_WIDTH = 60;
const DIGIT_HEIGHT = 100;
const THICKNESS = 11;
const X0 = 7;
const X1 = 53;
const Y0 = 7;
const Y1 = 50;
const Y2 = 93;

const half = THICKNESS / 2;

/** A horizontal segment: a bar with mitred ends, so corners meet cleanly. */
function horizontal(x: number, y: number, length: number): string {
  return [
    [x, y],
    [x + half, y - half],
    [x + length - half, y - half],
    [x + length, y],
    [x + length - half, y + half],
    [x + half, y + half],
  ]
    .map(([px, py]) => `${px},${py}`)
    .join(' ');
}

function vertical(x: number, y: number, length: number): string {
  return [
    [x, y],
    [x + half, y + half],
    [x + half, y + length - half],
    [x, y + length],
    [x - half, y + length - half],
    [x - half, y + half],
  ]
    .map(([px, py]) => `${px},${py}`)
    .join(' ');
}

const SEGMENTS: Record<string, string> = {
  a: horizontal(X0, Y0, X1 - X0),
  b: vertical(X1, Y0, Y1 - Y0),
  c: vertical(X1, Y1, Y2 - Y1),
  d: horizontal(X0, Y2, X1 - X0),
  e: vertical(X0, Y1, Y2 - Y1),
  f: vertical(X0, Y0, Y1 - Y0),
  g: horizontal(X0, Y1, X1 - X0),
};

const LIT: Record<string, string> = {
  '0': 'abcdef',
  '1': 'bc',
  '2': 'abged',
  '3': 'abgcd',
  '4': 'fgbc',
  '5': 'afgcd',
  '6': 'afgecd',
  '7': 'abc',
  '8': 'abcdefg',
  '9': 'abcdfg',
};

interface DigitProps {
  /** A single character; anything not 0-9 renders every segment unlit. */
  char: string;
  x: number;
  color: string;
}

function Digit({ char, x, color }: DigitProps) {
  const lit = LIT[char] ?? '';
  return (
    <g transform={`translate(${x} 0)`}>
      {Object.entries(SEGMENTS).map(([name, points]) => (
        <polygon
          key={name}
          points={points}
          fill={color}
          // The unlit segments stay faintly visible — that ghost is what
          // makes the lit ones read as a display rather than as text.
          fillOpacity={lit.includes(name) ? 1 : 0.1}
        />
      ))}
    </g>
  );
}

const GAP = 14;
const COLON_WIDTH = 26;
const DIGIT_PITCH = DIGIT_WIDTH + GAP;
// Two digits, the colon, then two more.
const TOTAL_WIDTH = DIGIT_PITCH * 2 + COLON_WIDTH + DIGIT_PITCH + DIGIT_WIDTH;

interface SevenSegmentClockProps {
  /** Four characters; a space renders as a blank cell. */
  digits: string;
  color: string;
}

export function SevenSegmentClock({ digits, color }: SevenSegmentClockProps) {
  const colonX = DIGIT_PITCH * 2 + COLON_WIDTH / 2;
  const positions = [
    0,
    DIGIT_PITCH,
    DIGIT_PITCH * 2 + COLON_WIDTH,
    DIGIT_PITCH * 3 + COLON_WIDTH,
  ];

  return (
    <svg
      viewBox={`0 0 ${TOTAL_WIDTH} ${DIGIT_HEIGHT}`}
      width="100%"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={digits.trim().replace(/(\d\d)(\d\d)/, '$1:$2')}
    >
      {positions.map((x, index) => (
        <Digit key={x} char={digits[index] ?? ' '} x={x} color={color} />
      ))}
      {[Y0 + (Y1 - Y0) / 2, Y1 + (Y2 - Y1) / 2].map((cy) => (
        <circle key={cy} cx={colonX} cy={cy} r={half * 0.9} fill={color} />
      ))}
    </svg>
  );
}
