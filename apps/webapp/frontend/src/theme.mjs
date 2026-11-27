// Colours for scripts, read from the theme variables at the top of style.css so the
// stylesheet stays the one place to change them.

import { GOOGLE_DARK_STYLES } from './mapstyle.mjs';

/** Returns a theme colour by name, such as 'route'. The fallback is used outside a browser. */
export function themeColor(name, fallback = '#ffc35a') {
  const style = globalThis.getComputedStyle?.(globalThis.document?.documentElement);
  return style?.getPropertyValue('--' + name).trim() || fallback;
}

/** Returns true when this browser chose the light theme in Appearance. */
export function lightTheme() {
  return globalThis.document?.documentElement?.dataset.theme === 'light';
}

/** Returns the Google map style for the theme: the dark style, or Google's own light map. */
export function googleStyles() {
  return lightTheme() ? [] : GOOGLE_DARK_STYLES;
}
