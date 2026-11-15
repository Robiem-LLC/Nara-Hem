// Lint rules for every JavaScript file in the repository.
// Run: npx eslint .
import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    ignores: ['**/node_modules/', '**/build/', '**/dist/', '.venv/', 'apps/webapp/backend/static/'],
  },
  js.configs.recommended,
  {
    rules: {
      // Unused arguments are often required by a callback's signature.
      'no-unused-vars': ['error', { args: 'after-used', caughtErrors: 'none' }],
      // A variable assigned after a closure that reads it (e.g. a timer handle) stays let.
      'prefer-const': ['error', { ignoreReadBeforeAssign: true }],
      'no-var': 'error',
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      // Readability: one declaration per statement, and braces whenever a body is on its own line.
      'one-var': ['error', 'never'],
      curly: ['error', 'multi-line', 'consistent'],
    },
  },

  // Web app: bundled browser modules.
  {
    files: ['apps/webapp/frontend/src/**/*.mjs'],
    languageOptions: { globals: { ...globals.browser } },
  },
  // Web app: plain browser script served as-is; uses the bundle's window.FamilyClient.
  {
    files: ['apps/webapp/frontend/public/**/*.js'],
    languageOptions: { sourceType: 'script', globals: { ...globals.browser } },
  },
  // Showcase site: plain browser script; Leaflet is loaded as the global L.
  {
    files: ['site/**/*.js'],
    languageOptions: { sourceType: 'script', globals: { ...globals.browser, L: 'readonly' } },
  },
  // Cloudflare Workers.
  {
    files: ['deploy/cloudflare/*.mjs'],
    languageOptions: { globals: { ...globals.serviceworker } },
  },
  // Node scripts, build files and tests.
  {
    files: ['**/build.mjs', '**/tests/**/*.mjs', 'eslint.config.mjs'],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    // CommonJS: Node scripts and the Alexa forwarder, which Amazon runs as lambda/index.js.
    files: ['**/*.cjs', 'deploy/alexa/forwarder/*.js'],
    languageOptions: { sourceType: 'commonjs', globals: { ...globals.node } },
  },
  // Playwright scripts: callbacks passed to page.evaluate() run inside the browser page.
  {
    files: ['apps/webapp/frontend/tests/browser/*.cjs', 'tools/showcase/*.cjs'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  // Browser-side test stubs are loaded into the page, not run by Node.
  {
    files: ['apps/webapp/frontend/tests/browser/*.js'],
    languageOptions: { sourceType: 'script', globals: { ...globals.browser } },
  },
];
