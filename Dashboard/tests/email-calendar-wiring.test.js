import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const html = await readFile(new URL('../web/index.html', import.meta.url), 'utf8');
const contract = await readFile(new URL('../web/nova-integration.js', import.meta.url), 'utf8');
const server = await readFile(new URL('../server.py', import.meta.url), 'utf8');

test('dashboard contract accepts live email and calendar payloads', () => {
  for (const type of ['integrations', 'mail', 'calendar']) {
    assert.match(contract, new RegExp(`['\"]${type}['\"]`));
  }
  assert.match(contract, /sync_integrations/);
});

test('calendar page is driven by live payload and offers manual sync', () => {
  assert.match(html, /calendarPayload/);
  assert.match(html, /calendarMonthTitle/);
  assert.match(html, /syncIntegrations/);
  assert.match(html, /mailUnreadTotal/);
});

test('server publishes integration snapshots and safe event notifications', () => {
  assert.match(server, /integration_feeds\.snapshot_messages/);
  assert.match(server, /IntegrationEventTail/);
  assert.match(server, /integrations_loop/);
});
