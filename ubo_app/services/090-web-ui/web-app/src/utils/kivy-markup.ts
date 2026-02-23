/** Strip all Kivy [color=...][/color] tags, keeping inner text. */
export function stripKivyMarkup(text: string): string {
  return text.replace(/\[color=[^\]]*\]/g, "").replace(/\[\/color\]/g, "");
}

/** Parse a single Kivy icon: extract symbol + color from [color=#XXX]icon[/color]. */
export function parseKivyIcon(raw: string): { icon: string; color?: string } {
  const match = raw.match(/\[color=(#[0-9a-fA-F]+)\](.*?)\[\/color\]/);
  if (match) {
    return { icon: match[2], color: match[1] };
  }
  return { icon: raw };
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
 * Strips Kivy markup first, then separates leading icon characters.
 * Returns { icon, text } where icon may be empty.
 */
export function splitIconFromText(raw: string): {
  icon: string;
  text: string;
} {
  const stripped = stripKivyMarkup(raw);
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
