// Applies the light theme before the page draws, if this browser chose it in Appearance, so the
// page doesn't flash dark first. Dark is the default.
try {
  if (localStorage.getItem('narahem.theme') === 'light') {
    document.documentElement.dataset.theme = 'light';
  }
} catch {
  // Storage can be blocked (private windows): stay dark.
}
