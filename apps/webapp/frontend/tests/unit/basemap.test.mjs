// Drawing trip card backgrounds, with small stand-ins for the browser's Image, fetch, canvas and
// IndexedDB.
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  clearSavedBasemaps,
  drawBasemap,
  drawGoogleBasemap,
  frame,
} from '../../src/thumbnails.mjs';

const view = frame(
  [
    [40.86, -74.42],
    [40.88, -74.38],
  ],
  300,
  120,
);

/** An Image whose load succeeds unless its address contains "fail". */
class FakeImage {
  style = {};

  set src(value) {
    this.url = value;
    queueMicrotask(() => (value.includes('fail') ? this.onerror?.() : this.onload?.()));
  }

  get src() {
    return this.url;
  }
}

/** An element that records what is put in front of it. */
const target = () => ({
  clientWidth: 300,
  added: [],
  prepend(node) {
    this.added.push(node);
  },
});

/** A canvas whose export works unless [blob] is null. */
const canvasMaker = (blob) => () => ({
  getContext: () => ({ scale() {}, drawImage() {} }),
  toBlob: (done) => done(blob),
});

/** A tiny in-memory IndexedDB: one store with an "at" index. */
function fakeIndexedDB() {
  const rows = new Map();
  const later = (request, value) => {
    queueMicrotask(() => {
      request.result = value;
      request.onsuccess?.({ target: request });
    });
    return request;
  };
  const store = {
    get: (key) => later({}, rows.get(key)),
    put: (value, key) => rows.set(key, value),
    count: () => later({}, rows.size),
    createIndex() {},
    index: () => ({
      openCursor() {
        const ordered = [...rows.entries()].sort((a, b) => a[1].at - b[1].at);
        const request = {};
        const step = (index) =>
          queueMicrotask(() => {
            const entry = ordered[index];
            const cursor = entry && {
              delete: () => rows.delete(entry[0]),
              continue: () => step(index + 1),
            };
            request.onsuccess?.({ target: { result: cursor } });
          });
        step(0);
        return request;
      },
    }),
  };
  const handle = {
    transaction: () => ({ objectStore: () => store }),
    createObjectStore: () => store,
  };
  return {
    rows,
    open() {
      const request = {};
      queueMicrotask(() => {
        request.result = handle;
        request.onupgradeneeded?.();
        request.onsuccess?.();
      });
      return request;
    },
    deleteDatabase() {
      rows.clear();
    },
  };
}

function browser({ tilesOk = true, blob = { size: 1 }, indexedDB } = {}) {
  globalThis.Image = FakeImage;
  globalThis.URL.createObjectURL = () => 'blob:background';
  globalThis.URL.revokeObjectURL = () => {};
  globalThis.createImageBitmap = async () => ({});
  globalThis.fetch = async (url) => ({
    ok: tilesOk,
    headers: { get: () => (tilesOk ? 'image/png' : 'text/html') },
    blob: async () => url,
  });
  const element = (tag) =>
    tag === 'canvas'
      ? canvasMaker(blob)()
      : {
          style: {},
          children: [],
          append(c) {
            this.children.push(c);
          },
        };
  globalThis.document = { createElement: element };
  globalThis.indexedDB = indexedDB;
  clearSavedBasemaps();
}

test('Google backgrounds load, skip when stale and reject when the key fails', async () => {
  browser();
  const card = target();
  assert.equal(await drawGoogleBasemap(card, view, 'synthetic-key'), 'google');
  assert.equal(card.added.length, 1);
  assert.match(card.added[0].src, /maps\.googleapis\.com/);
  assert.equal(await drawGoogleBasemap(card, view, 'k', () => false), 'skipped');
  await assert.rejects(drawGoogleBasemap(card, view, 'fail-key'), /unavailable/);
});

test('OpenStreetMap backgrounds are drawn once, cached, then served from the cache', async () => {
  const storage = fakeIndexedDB();
  browser({ indexedDB: storage });
  const first = target();
  assert.equal(await drawBasemap(first, view), 'drawn');
  assert.equal(first.added[0].src, 'blob:background');
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(storage.rows.size, 1);
  const second = target();
  assert.equal(await drawBasemap(second, view), 'cached');
  assert.equal(second.added.length, 1);
  clearSavedBasemaps();
  assert.equal(storage.rows.size, 0);
});

test('the cache keeps only the newest backgrounds', async () => {
  const storage = fakeIndexedDB();
  browser({ indexedDB: storage });
  for (let i = 0; i < 401; i++) storage.rows.set('old/' + i, { blob: {}, at: i });
  await drawBasemap(target(), view);
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(storage.rows.size, 400);
  assert.ok(!storage.rows.has('old/0'));
});

test('without canvas export or tiles the plain tile images are shown', async () => {
  browser({ blob: null });
  const card = target();
  assert.equal(await drawBasemap(card, view), 'tiles');
  assert.ok(card.added[0].children.length >= 1);
  browser({ tilesOk: false });
  assert.equal(await drawBasemap(target(), view), 'tiles');
  assert.equal(await drawBasemap(target(), view, () => false), 'skipped');
});

test('at most two backgrounds are drawn at a time', async () => {
  browser();
  const results = await Promise.all([1, 2, 3, 4].map(() => drawBasemap(target(), view)));
  assert.deepEqual(results, ['drawn', 'drawn', 'drawn', 'drawn']);
});

test('clearing still works when storage is blocked', () => {
  browser({
    indexedDB: {
      deleteDatabase() {
        throw new Error('blocked');
      },
    },
  });
  clearSavedBasemaps();
});
