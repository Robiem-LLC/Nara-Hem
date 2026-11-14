// Colours for scripts, read from the theme variables at the top of style.css so the
// stylesheet stays the one place to change them.

/** Returns a theme colour by name, such as 'route'. The fallback is used outside a browser. */
export function themeColor(name, fallback = '#ffc35a') {
  const style = globalThis.getComputedStyle?.(globalThis.document?.documentElement);
  return style?.getPropertyValue('--' + name).trim() || fallback;
}
