// Static trip-card map backgrounds drawn from OpenStreetMap tiles.
// Only the tiles around a trip are requested (never the route itself); the
// finished picture is saved in this browser so later visits are instant.

/** Tile size in pixels. */
const TILE = 256;

/** Maximum zoom for thumbnails. */
const MAX_ZOOM = 17;

/** IndexedDB database for cached map backgrounds. */
const DB_NAME = 'narahem-thumbnails';

/** Object store for cached backgrounds. */
const STORE = 'basemaps';

/** Maximum number of cached backgrounds. */
const KEEP = 400;

/** Maximum age of a cached background (30 days). */
const MAX_AGE = 30 * 86400000;

/** Returns a point's pixel position on the Web Mercator world map at the given zoom. */
export function mercator(lat, lon, zoom) {
  const size = TILE * 2 ** zoom;
  const sin = Math.sin((lat * Math.PI) / 180);
  return [
    ((lon + 180) / 360) * size,
    (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size,
  ];
}

/**
 * Returns the view (zoom and top-left pixel offset) at the highest zoom where every point fits in
 * width by height minus padding, or null.
 */
export function frame(points, width, height, pad = 18) {
  const valid = points.filter(
    (p) =>
      Array.isArray(p) &&
      Number.isFinite(p[0]) &&
      Math.abs(p[0]) <= 85 &&
      Number.isFinite(p[1]) &&
      Math.abs(p[1]) <= 180,
  );
  if (!valid.length || width <= 2 * pad || height <= 2 * pad) return null;
  for (let zoom = MAX_ZOOM; zoom >= 1; zoom--) {
    const px = valid.map((p) => mercator(p[0], p[1], zoom));
    const xs = px.map((p) => p[0]);
    const ys = px.map((p) => p[1]);
    const lo = [Math.min(...xs), Math.min(...ys)];
    const hi = [Math.max(...xs), Math.max(...ys)];
    if ((hi[0] - lo[0] <= width - 2 * pad && hi[1] - lo[1] <= height - 2 * pad) || zoom === 1) {
      return {
        zoom,
        width,
        height,
        left: Math.round((lo[0] + hi[0]) / 2 - width / 2),
        top: Math.round((lo[1] + hi[1]) / 2 - height / 2),
      };
    }
  }
  return null;
}

/** Converts points to pixel positions within a thumbnail. */
export function project(points, view) {
  return points.map((p) => {
    const [x, y] = mercator(p[0], p[1], view.zoom);
    return [x - view.left, y - view.top];
  });
}

/** Returns the tiles needed to draw a thumbnail. */
export function tilesFor(view) {
  const count = 2 ** view.zoom;
  const tiles = [];
  for (
    let ty = Math.floor(view.top / TILE);
    ty <= Math.floor((view.top + view.height) / TILE);
    ty++
  ) {
    if (ty < 0 || ty >= count) continue;
    for (
      let tx = Math.floor(view.left / TILE);
      tx <= Math.floor((view.left + view.width) / TILE);
      tx++
    ) {
      tiles.push({
        x: ((tx % count) + count) % count,
        y: ty,
        dx: tx * TILE - view.left,
        dy: ty * TILE - view.top,
      });
    }
  }
  return tiles;
}

import { googleStyles } from './theme.mjs';

/** Short OpenStreetMap attribution for thumbnails. */
export const OSM_ATTRIBUTION = '© OpenStreetMap contributors';
let opened = null;

// At most two thumbnails fetch tiles at once (OpenStreetMap tile policy).
let active = 0;
const waiting = [];

/** Returns an OpenStreetMap tile URL. */
const tileUrl = (zoom, tile) => `https://tile.openstreetmap.org/${zoom}/${tile.x}/${tile.y}.png`;

/** Converts "#rrggbb" to Google's "0xrrggbb". */
const hex = (color) => '0x' + color.slice(1);

/** Returns the cache database, opening it once. */
const db = () => (opened ||= database());

/** Converts a pixel position back to latitude and longitude. */
function unproject(x, y, zoom) {
  const size = TILE * 2 ** zoom;
  return [
    (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / size))) * 180) / Math.PI,
    (x / size) * 360 - 180,
  ];
}

/** Converts the theme's map style (dark, or none for light) to Static Maps style parameters. */
export function googleStaticStyle(styles = googleStyles()) {
  return styles.map((rule) =>
    [
      rule.featureType && 'feature:' + rule.featureType,
      rule.elementType && 'element:' + rule.elementType,
      ...rule.stylers.map((s) =>
        s.color ? 'color:' + hex(s.color) : 'visibility:' + s.visibility,
      ),
    ]
      .filter(Boolean)
      .join('|'),
  );
}

/**
 * Returns a Static Maps URL for the background only (max 640 px per side). The route is drawn on
 * top in the browser.
 */
export function googleStaticUrl(view, apiKey) {
  if (view.width > 640 || view.height > 640) throw new Error('Static map too large');
  const [lat, lon] = unproject(view.left + view.width / 2, view.top + view.height / 2, view.zoom);
  const params = new URLSearchParams({
    center: lat.toFixed(6) + ',' + lon.toFixed(6),
    zoom: String(view.zoom),
    size: view.width + 'x' + view.height,
    scale: '2',
    key: apiKey,
  });
  for (const style of googleStaticStyle()) params.append('style', style);
  return 'https://maps.googleapis.com/maps/api/staticmap?' + params;
}

/**
 * Draws a Google Static Maps background. Not cached beyond the browser's normal cache, per Google's
 * terms. Rejects if the key can't use Static Maps, so the caller can fall back to OpenStreetMap.
 */
export function drawGoogleBasemap(target, view, apiKey, isCurrent = () => true) {
  return slot(
    () =>
      new Promise((resolve, reject) => {
        if (!isCurrent()) return resolve('skipped');
        const image = new Image();
        image.className = 'trip-tiles';
        image.alt = '';
        image.onload = () => {
          if (isCurrent()) target.prepend(image);
          resolve('google');
        };
        image.onerror = () => reject(new Error('Google static map unavailable'));
        image.src = googleStaticUrl(view, apiKey);
      }),
  );
}

/** Opens the cache database, or returns null if IndexedDB is unavailable. */
function database() {
  return new Promise((resolve) => {
    if (!globalThis.indexedDB) return resolve(null);
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE).createIndex('at', 'at');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
  });
}

/** Returns a cached background if it is recent enough. */
async function cached(key) {
  const store = (await db())?.transaction(STORE).objectStore(STORE);
  if (!store) return null;
  return new Promise((resolve) => {
    const request = store.get(key);
    request.onsuccess = () =>
      resolve(
        request.result && Date.now() - request.result.at < MAX_AGE ? request.result.blob : null,
      );
    request.onerror = () => resolve(null);
  });
}

/** Caches a background and removes the oldest beyond the limit. */
async function remember(key, blob) {
  const handle = await db();
  if (!handle) return;
  const store = handle.transaction(STORE, 'readwrite').objectStore(STORE);
  store.put({ blob, at: Date.now() }, key);
  const count = store.count();
  count.onsuccess = () => {
    if (count.result <= KEEP) return;
    let excess = count.result - KEEP;
    store.index('at').openCursor().onsuccess = (event) => {
      const cursor = event.target.result;
      if (cursor && excess-- > 0) {
        cursor.delete();
        cursor.continue();
      }
    };
  };
}

/** Fetches a tile, rejecting error responses so they are never drawn or cached. */
async function loadTile(url) {
  const response = await fetch(url, {
    mode: 'cors',
    credentials: 'omit',
    referrerPolicy: 'origin',
  });
  if (!response.ok || !(response.headers.get('content-type') || '').startsWith('image/')) {
    throw new Error('Map tile unavailable');
  }
  return createImageBitmap(await response.blob());
}

/** Runs task with at most two running at a time. */
async function slot(task) {
  if (active >= 2) await new Promise((resolve) => waiting.push(resolve));
  active++;
  try {
    return await task();
  } finally {
    active--;
    waiting.shift()?.();
  }
}

/**
 * Draws an OpenStreetMap background into target from the cache, or renders and caches it. Falls
 * back to plain tile images if the canvas can't be used.
 */
export async function drawBasemap(target, view, isCurrent = () => true) {
  const ratio = Math.min(2, globalThis.devicePixelRatio || 1);
  const key = `dark/${view.zoom}/${view.left}/${view.top}/${view.width}x${view.height}@${ratio}`;
  const show = (blob) => {
    const image = new Image();
    image.className = 'trip-tiles';
    image.alt = '';
    image.src = URL.createObjectURL(blob);
    image.onload = () => URL.revokeObjectURL(image.src);
    target.prepend(image);
  };
  const saved = await cached(key);
  if (saved) {
    if (isCurrent()) show(saved);
    return 'cached';
  }
  return slot(async () => {
    if (!isCurrent()) return 'skipped';
    const tiles = tilesFor(view);
    try {
      const images = await Promise.all(tiles.map((tile) => loadTile(tileUrl(view.zoom, tile))));
      const canvas = document.createElement('canvas');
      canvas.width = view.width * ratio;
      canvas.height = view.height * ratio;
      const context = canvas.getContext('2d');
      context.scale(ratio, ratio);
      tiles.forEach((tile, index) =>
        context.drawImage(images[index], tile.dx, tile.dy, TILE, TILE),
      );
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/webp', 0.82));
      if (!blob) throw new Error('Canvas export unavailable');
      remember(key, blob);
      if (isCurrent()) show(blob);
      return 'drawn';
    } catch (_) {
      if (!isCurrent()) return 'skipped';
      const layer = document.createElement('div');
      layer.className = 'trip-tiles';
      const scale = (target.clientWidth || view.width) / view.width;
      layer.style.cssText =
        `width:${view.width}px;height:${view.height}px;` +
        `transform:scale(${scale});transform-origin:0 0;inset:auto`;
      for (const tile of tiles) {
        const image = new Image();
        image.alt = '';
        image.referrerPolicy = 'origin';
        image.style.cssText =
          `position:absolute;left:${tile.dx}px;top:${tile.dy}px;` +
          `width:${TILE}px;height:${TILE}px`;
        image.src = tileUrl(view.zoom, tile);
        layer.append(image);
      }
      target.prepend(layer);
      return 'tiles';
    }
  });
}

/** Deletes cached backgrounds, which reveal where trips happened. Called at sign-out. */
export function clearSavedBasemaps() {
  opened = null;
  try {
    globalThis.indexedDB?.deleteDatabase(DB_NAME);
  } catch (_) {
    /* storage may be unavailable */
  }
}
