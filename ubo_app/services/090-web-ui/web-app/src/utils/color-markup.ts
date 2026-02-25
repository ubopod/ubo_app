/** Strip all [color=...][/color] tags, keeping inner text. */
export function stripColorMarkup(text: string): string {
  return text.replace(/\[color=[^\]]*\]/g, "").replace(/\[\/color\]/g, "");
}

/** Parse a single colored icon: extract symbol + color from [color=#XXX]icon[/color]. */
export function parseColoredIcon(raw: string): { icon: string; color?: string } {
  const match = raw.match(/\[color=(#[0-9a-fA-F]+)\](.*?)\[\/color\]/);
  if (match) {
    return { icon: match[2], color: match[1] };
  }
  return { icon: raw };
}

/** Segment produced by parseColorMarkup. */
export interface ColorSegment {
  text: string;
  color?: string;
  isIcon?: boolean;
}

/**
 * Parse [color=...] markup into an array of segments with optional color.
 * Each segment is a piece of text, optionally colored.
 */
export function parseColorMarkup(raw: string): ColorSegment[] {
  const segments: ColorSegment[] = [];
  const regex = /\[color=(#[0-9a-fA-F]+)\](.*?)\[\/color\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(raw)) !== null) {
    // Text before this match
    if (match.index > lastIndex) {
      segments.push({ text: raw.slice(lastIndex, match.index) });
    }
    const text = match[2];
    const cp = text.codePointAt(0);
    segments.push({
      text,
      color: match[1],
      isIcon: cp !== undefined && isNerdFontChar(cp),
    });
    lastIndex = regex.lastIndex;
  }

  // Remaining text after last match
  if (lastIndex < raw.length) {
    segments.push({ text: raw.slice(lastIndex) });
  }

  return segments;
}

/**
 * Check if a character is a Nerd Font / Private Use Area icon.
 * Covers PUA (U+E000-U+F8FF) and Supplementary PUA (U+F0000-U+10FFFF).
 */
function isNerdFontChar(codePoint: number): boolean {
  return (
    (codePoint >= 0xe000 && codePoint <= 0xf8ff) ||
    (codePoint >= 0xf0000 && codePoint <= 0x10ffff)
  );
}

/**
 * Split text into a leading icon prefix (Nerd Font chars) and the remaining text.
 * Strips color markup first, then separates leading icon characters.
 * Returns { icon, text } where icon may be empty.
 */
export function splitIconFromText(raw: string): {
  icon: string;
  text: string;
} {
  const stripped = stripColorMarkup(raw);
  let iconEnd = 0;

  for (const char of stripped) {
    const cp = char.codePointAt(0);
    if (cp !== undefined && isNerdFontChar(cp)) {
      iconEnd += char.length;
    } else {
      break;
    }
  }

  return {
    icon: stripped.slice(0, iconEnd),
    text: stripped.slice(iconEnd).trim(),
  };
}
