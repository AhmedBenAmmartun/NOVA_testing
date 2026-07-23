import { access, readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const dashboard = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const required = [
  'web/index.html',
  'web/support.js',
  'web/tauri-shell.js',
  'web/nova-integration.js',
  'web/layout-engine.js',
  'web/desktop-mode-state.js',
  'web/dashboard-enhancements.js',
  'web/dashboard-enhancements.css',
  'web/vendor/react.production.min.js',
  'web/vendor/react-dom.production.min.js',
  'web/vendor/babel.min.js',
  'security.py',
  'app_registry.py',
  'integration_feeds.py',
];

await Promise.all(required.map((path) => access(resolve(dashboard, path))));
const html = await readFile(resolve(dashboard, 'web/index.html'), 'utf8');
if (/https?:\/\/(?:unpkg|cdn\.jsdelivr|cdnjs\.cloudflare)\./i.test(html)) {
  throw new Error('Dashboard startup still depends on a public runtime CDN.');
}
for (let page = 0; page < 5; page += 1) {
  if (!html.includes(`data-page-shell="${page}"`) || !html.includes(`data-page-canvas="${page}"`)) {
    throw new Error(`Missing isolated page canvas: ${page}`);
  }
}
const shell = await readFile(resolve(dashboard, 'web/tauri-shell.js'), 'utf8');
for (const marker of ['data-nova-chrome', 'nova-desktop-mode', 'set_click_through', 'nova://toggle-edit']) {
  if (!shell.includes(marker)) throw new Error(`Desktop shell is missing required behavior: ${marker}`);
}
const actions = await readFile(resolve(dashboard, 'actions.py'), 'utf8');
if (!actions.includes('app_action') || !actions.includes('can_open_recent_target')) {
  throw new Error('Trusted application IDs or sensitive-file backend guard are missing.');
}
for (const marker of ['calendarPayload', 'syncIntegrations', 'mailUnreadTotal']) {
  if (!html.includes(marker)) throw new Error(`Live email/calendar dashboard wiring is missing: ${marker}`);
}
if (!actions.includes('sync_integrations')) {
  throw new Error('Read-only email/calendar manual sync action is missing.');
}
console.log('Static dashboard build verified: offline assets, five clipped canvases, secure apps, Desktop Mode, and live email/calendar wiring are present.');
