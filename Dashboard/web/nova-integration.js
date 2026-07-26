(function () {
  'use strict';

  var CONTRACT_VERSION = '1.1.0';
  var DATA_TYPES = Object.freeze([
    'snapshot', 'stats', 'spotify', 'weather', 'agent_status', 'phase', 'activity',
    'activity_seed', 'tasks', 'talk', 'transcript', 'obsidian',
    'approvals', 'usage', 'apps', 'briefing', 'notify',
    'integrations', 'mail', 'calendar'
  ]);
  var ACTION_TYPES = Object.freeze([
    'media', 'app_action', 'pin_app', 'refresh_apps', 'open_folder', 'open_recent', 'task',
    'forget', 'approval', 'delegate', 'sync_integrations'
  ]);
  var listeners = new Set();
  var state = {
    connected: false,
    mode: 'demo',
    contractVersion: CONTRACT_VERSION,
    lastEvent: null,
    error: null
  };

  function snapshot() {
    return {
      connected: state.connected,
      mode: state.mode,
      contractVersion: state.contractVersion,
      lastEvent: state.lastEvent,
      error: state.error
    };
  }

  function publish(kind, detail) {
    var event = { kind: kind, detail: detail, state: snapshot() };
    listeners.forEach(function (listener) {
      try { listener(event); } catch (_error) {}
    });
  }

  window.addEventListener('nova:integration-connection', function (event) {
    var detail = event.detail || {};
    state.connected = detail.connected === true;
    state.mode = state.connected ? 'live' : 'demo';
    if (!state.connected) state.error = null;
    publish('connection', detail);
  });

  window.addEventListener('nova:integration-data', function (event) {
    var message = event.detail;
    if (!message || typeof message !== 'object') return;
    if (message.contractVersion && message.contractVersion !== CONTRACT_VERSION) {
      state.error = 'contract_version_mismatch';
      publish('error', {
        code: state.error,
        expected: CONTRACT_VERSION,
        received: message.contractVersion
      });
      return;
    }
    state.lastEvent = message;
    state.error = null;
    publish('data', message);
  });

  window.NOVAIntegration = Object.freeze({
    contractVersion: CONTRACT_VERSION,
    dataTypes: DATA_TYPES,
    actionTypes: ACTION_TYPES,
    getState: snapshot,
    subscribe: function (listener) {
      if (typeof listener !== 'function') return function () {};
      listeners.add(listener);
      return function () { listeners.delete(listener); };
    },
    send: function (type, payload) {
      if (!ACTION_TYPES.includes(type)) {
        throw new TypeError('Unknown NOVA dashboard action: ' + type);
      }
      window.dispatchEvent(new CustomEvent('nova:integration-action', {
        detail: { type: type, payload: payload || {} }
      }));
      return state.connected;
    }
  });
})();
