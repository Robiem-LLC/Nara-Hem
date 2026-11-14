// Builds the browser app into the backend's static folder (or CLIENT_OUT).
// The output folder is generated: never edit files there by hand.
import { build } from 'esbuild';
import { cp, mkdir, writeFile } from 'node:fs/promises';

const out = process.env.CLIENT_OUT || '../backend/static';
await mkdir(out, { recursive: true });

await cp('public', out, { recursive: true });

await build({
  entryPoints: ['src/client.mjs'],
  bundle: true,
  minify: true,
  format: 'iife',
  platform: 'browser',
  outfile: `${out}/client.js`,
  legalComments: 'external',
  define: { 'process.env.NODE_ENV': '"production"' },
});

await cp('node_modules/leaflet/dist/leaflet.css', `${out}/leaflet.css`);
await cp('node_modules/leaflet/dist/images', `${out}/images`, { recursive: true });
await cp('node_modules/libsodium-wrappers-sumo/LICENSE', `${out}/sodium-LICENSE`);
await cp('node_modules/leaflet/LICENSE', `${out}/leaflet-LICENSE`);
await writeFile(
  `${out}/client-versions.json`,
  JSON.stringify({ sodium: '0.8.4', leaflet: '1.9.4' }),
);
