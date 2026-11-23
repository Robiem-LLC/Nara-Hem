// The letters shown for someone without a profile photo: the first letter of each word of their
// name, so "John Doe" is "JD" and "Kim" is "K". Same rule as the iPhone and Android apps.

/** Returns up to two capital letters for the name, or "?" for an empty one. */
export function initials(name) {
  const words = String(name ?? '')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return (
    words
      .slice(0, 2)
      .map((word) => Array.from(word)[0])
      .join('')
      .toUpperCase() || '?'
  );
}
