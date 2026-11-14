// The map never zooms out so far that the world repeats side by side.
import assert from 'node:assert/strict';
import test from 'node:test';

// Leaflet expects a browser; these stand-ins are enough to load the maps module.
globalThis.window = globalThis;
globalThis.devicePixelRatio = 1;
globalThis.screen = { width: 1280, height: 800 };
globalThis.navigator ??= { userAgent: 'node', platform: 'node' };
globalThis.document = {
  documentElement: { style: {} },
  createElement: () => ({ getContext: () => null, style: {} }),
};

const { worldMinZoom } = await import('../../src/maps.mjs');

test('one copy of the world fills the map at the minimum zoom', () => {
  for (const width of [390, 768, 1280, 2560]) {
    const zoom = worldMinZoom(width);
    assert.ok(256 * 2 ** zoom >= width, `world covers ${width}px at zoom ${zoom}`);
    assert.ok(
      zoom === 0 || 256 * 2 ** (zoom - 1) < width,
      `zoom ${zoom} is the smallest for ${width}px`,
    );
  }
  assert.equal(worldMinZoom(1280), 3);
  assert.equal(worldMinZoom(200), 0);
});
