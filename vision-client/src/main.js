import { invoke } from '@tauri-apps/api/core';
import { LogicalSize, getCurrentWindow } from '@tauri-apps/api/window';
import { Room, RoomEvent, Track, VideoPresets } from 'livekit-client';

const appWindow = getCurrentWindow();
const FULL_SIZE = new LogicalSize(420, 560);
const COMPACT_SIZE = new LogicalSize(420, 150);

const state = {
  room: null,
  localIdentity: null,
  connected: false,
  connecting: false,
  cameraEnabled: false,
  micEnabled: false,
  speakerEnabled: false,
  chatSending: false,
  pinned: false,
  collapsed: false,
  shuttingDown: false,
};

const el = {
  shell: document.querySelector('#shell'),
  statusDot: document.querySelector('#statusDot'),
  statusText: document.querySelector('#statusText'),
  agentState: document.querySelector('#agentState'),
  cameraPreview: document.querySelector('#cameraPreview'),
  captionOverlay: document.querySelector('#captionOverlay'),
  captionSpeaker: document.querySelector('#captionSpeaker'),
  captionText: document.querySelector('#captionText'),
  chatPanel: document.querySelector('#chatPanel'),
  chatMessages: document.querySelector('#chatMessages'),
  chatEmpty: document.querySelector('#chatEmpty'),
  chatInput: document.querySelector('#chatInput'),
  sendChatButton: document.querySelector('#sendChatButton'),
  speakerButton: document.querySelector('#speakerButton'),
  speakerLabel: document.querySelector('#speakerLabel'),
  previewEmpty: document.querySelector('#previewEmpty'),
  sourceBadge: document.querySelector('#sourceBadge'),
  cameraSourceButton: document.querySelector('#cameraSourceButton'),
  micButton: document.querySelector('#micButton'),
  micLabel: document.querySelector('#micLabel'),
  cameraLabel: document.querySelector('#cameraLabel'),
  collapseButton: document.querySelector('#collapseButton'),
  pinButton: document.querySelector('#pinButton'),
  minimizeButton: document.querySelector('#minimizeButton'),
  closeButton: document.querySelector('#closeButton'),
  connectButton: document.querySelector('#connectButton'),
  stopButton: document.querySelector('#stopButton'),
  connectionDetail: document.querySelector('#connectionDetail'),
  remoteAudio: document.querySelector('#remoteAudio'),
};

function setStatus(kind, text, detail = '') {
  el.statusDot.className = 'status-dot';
  if (kind) el.statusDot.classList.add(kind);
  el.statusText.textContent = text;
  if (detail) el.connectionDetail.textContent = detail;
}

function render() {
  el.micButton.disabled = state.connecting;
  el.cameraSourceButton.disabled = state.connecting;
  el.chatInput.disabled = state.connecting;
  el.sendChatButton.disabled = state.connecting || state.chatSending || !el.chatInput.value.trim();
  el.stopButton.disabled = !state.connected && !state.connecting;
  el.connectButton.disabled = state.connected || state.connecting;
  el.connectButton.textContent = state.connecting
    ? 'Connecting…'
    : state.connected
      ? 'Session Connected'
      : 'Start NOVA Session';

  el.micButton.classList.toggle('active', state.micEnabled);
  el.cameraSourceButton.classList.toggle('active', state.cameraEnabled);
  el.speakerButton.classList.toggle('active', state.speakerEnabled);
  el.speakerLabel.textContent = state.speakerEnabled ? 'Sound on' : 'Silent';
  el.pinButton.classList.toggle('active', state.pinned);
  el.micLabel.textContent = state.micEnabled ? 'On' : 'Off';
  el.cameraLabel.textContent = state.cameraEnabled ? 'On' : 'Off';
  el.shell.classList.toggle('camera-active', state.cameraEnabled);

  el.cameraPreview.style.display = state.cameraEnabled ? 'block' : 'none';
  el.previewEmpty.style.display = state.cameraEnabled ? 'none' : 'grid';
  el.sourceBadge.textContent = state.cameraEnabled ? 'CAMERA SHARED' : 'CAMERA OFF';
  el.sourceBadge.classList.toggle('active', state.cameraEnabled);

  if (state.cameraEnabled) {
    setStatus('sharing', 'VISUAL ACTIVE', 'The preview is the same camera track published to NOVA.');
  } else if (state.connected && state.micEnabled) {
    setStatus('connected', 'MIC ONLY', 'NOVA can hear you. NOVA cannot see anything.');
  } else if (state.connected) {
    setStatus('connected', 'TEXT READY', 'Type below. Camera and microphone are both off.');
  } else if (!state.connecting) {
    setStatus('', 'DISCONNECTED', 'Camera and microphone start OFF.');
  }

  el.agentState.textContent = state.connected ? 'NOVA CONNECTED' : state.connecting ? 'CONNECTING' : 'NOVA OFFLINE';
  el.shell.classList.toggle('compact', state.collapsed);
}

function clearRemoteAudio() {
  for (const child of [...el.remoteAudio.children]) child.remove();
}

function attachRemoteAudio(track) {
  if (track.kind !== Track.Kind.Audio) return;
  const audio = track.attach();
  audio.autoplay = true;
  audio.muted = !state.speakerEnabled;
  audio.dataset.livekitRemote = 'true';
  el.remoteAudio.appendChild(audio);
}

function attachExactCameraPreview() {
  if (!state.room) return false;
  const publication = state.room.localParticipant.getTrackPublication(Track.Source.Camera);
  const track = publication?.track;
  if (!track) return false;

  track.detach(el.cameraPreview);
  track.attach(el.cameraPreview);
  return true;
}


const chatSegments = new Map();

function scrollChatToBottom() {
  requestAnimationFrame(() => {
    el.chatMessages.scrollTop = el.chatMessages.scrollHeight;
  });
}

function clearChat() {
  chatSegments.clear();
  for (const node of [...el.chatMessages.querySelectorAll('.chat-message')]) node.remove();
  el.chatEmpty.hidden = false;
  el.chatInput.value = '';
  state.chatSending = false;
}

function ensureChatMessage(key, role) {
  let row = chatSegments.get(key);
  if (row) return row;

  el.chatEmpty.hidden = true;
  row = document.createElement('div');
  row.className = `chat-message ${role}`;
  row.dataset.chatKey = key;

  const speaker = document.createElement('span');
  speaker.className = 'chat-message-speaker';
  speaker.textContent = role === 'user' ? 'YOU' : 'NOVA';

  const body = document.createElement('div');
  body.className = 'chat-message-body';

  row.append(speaker, body);
  el.chatMessages.appendChild(row);
  chatSegments.set(key, row);
  scrollChatToBottom();
  return row;
}

function upsertChatMessage(key, role, text) {
  const cleanText = String(text ?? '').trim();
  if (!cleanText) return;
  const row = ensureChatMessage(key, role);
  const body = row.querySelector('.chat-message-body');
  body.textContent = cleanText;
  scrollChatToBottom();
}

function upsertTranscriptionMessage(participantIdentity, attributes, text) {
  const isUser = Boolean(state.localIdentity) && participantIdentity === state.localIdentity;
  const role = isUser ? 'user' : 'nova';
  const segmentId = attributes['lk.segment_id'] || attributes['lk.transcribed_track_id'] || `${role}-${Date.now()}`;
  upsertChatMessage(`transcription:${participantIdentity}:${segmentId}`, role, text);
}


async function waitForNOVAAgent(room, timeoutMs = 10000) {
  if (!room) return false;
  if (room.remoteParticipants?.size > 0) return true;

  return await new Promise((resolve) => {
    let finished = false;

    const finish = (value) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      room.off(RoomEvent.ParticipantConnected, onParticipantConnected);
      resolve(value);
    };

    const onParticipantConnected = () => finish(true);
    const timer = setTimeout(() => finish(false), timeoutMs);

    room.on(RoomEvent.ParticipantConnected, onParticipantConnected);

    if (room.remoteParticipants?.size > 0) finish(true);
  });
}

async function sendChatMessage() {
  if (state.chatSending) return;

  const text = el.chatInput.value.trim();
  if (!text) return;

  state.chatSending = true;
  render();

  try {
    if (!state.connected || !state.room) {
      setStatus('', 'CONNECTING FOR CHAT', 'Starting NOVA so your typed message can be delivered…');
      await connectSession();
    }

    if (!state.connected || !state.room) {
      throw new Error('NOVA session could not connect.');
    }

    setStatus('', 'WAITING FOR NOVA', 'Connected. Waiting for the NOVA worker to join…');
    const agentReady = await waitForNOVAAgent(state.room, 10000);

    if (!agentReady) {
      throw new Error('The NOVA worker did not join the LiveKit room in time.');
    }

    const localKey = `typed:${Date.now()}:${Math.random().toString(16).slice(2)}`;
    upsertChatMessage(localKey, 'user', text);
    el.chatInput.value = '';
    render();

    const dataPermission = state.room.localParticipant.permissions?.canPublishData;
    if (dataPermission === false) {
      throw new Error(
        'This NOVA Vision token does not allow LiveKit data publishing, so typed chat cannot be sent.',
      );
    }

    await state.room.localParticipant.sendText(text, { topic: 'lk.chat' });

    setStatus(
      'connected',
      'TEXT DELIVERED',
      'Your typed message was sent to the connected NOVA agent.',
    );
  } catch (error) {
    console.error(
      'NOVA typed-message delivery failed:',
      error instanceof Error ? error.message : 'UnknownError',
    );

    if (!el.chatInput.value.trim()) {
      el.chatInput.value = text;
    }

    const detail = error instanceof Error
      ? error.message
      : 'Unknown text delivery error.';

    upsertChatMessage(
      `error:${Date.now()}:${Math.random().toString(16).slice(2)}`,
      'nova',
      `Text delivery failed: ${detail}`,
    );

    setStatus('error', 'TEXT FAILED', detail);
  } finally {
    state.chatSending = false;
    render();
    el.chatInput.focus();
  }
}


let captionHideTimer = null;

function clearCaption() {
  if (captionHideTimer) {
    clearTimeout(captionHideTimer);
    captionHideTimer = null;
  }
  el.captionOverlay.classList.remove('visible', 'user', 'nova');
  el.captionSpeaker.textContent = 'NOVA';
  el.captionText.textContent = '';
}

function showCaption(participantIdentity, text, isFinal) {
  const cleanText = String(text ?? '').trim();
  if (!cleanText) return;

  const isUser = Boolean(state.localIdentity) && participantIdentity === state.localIdentity;
  el.captionOverlay.classList.toggle('user', isUser);
  el.captionOverlay.classList.toggle('nova', !isUser);
  el.captionSpeaker.textContent = isUser ? 'YOU' : 'NOVA';
  el.captionText.textContent = cleanText;
  el.captionOverlay.classList.add('visible');

  if (captionHideTimer) clearTimeout(captionHideTimer);
  captionHideTimer = setTimeout(
    clearCaption,
    isFinal ? 4200 : 1800,
  );
}

function wireCaptionStreams(room) {
  room.registerTextStreamHandler('lk.transcription', async (reader, participantInfo) => {
    const attributes = reader.info?.attributes ?? {};
    const isTranscription = Boolean(attributes['lk.transcribed_track_id']);
    const isFinal = !isTranscription || attributes['lk.transcription_final'] === 'true';
    const streamId = attributes['lk.segment_id']
      || attributes['lk.transcribed_track_id']
      || reader.info?.id
      || `text-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    let text = '';

    try {
      for await (const chunk of reader) {
        text += chunk;
        if (isTranscription) {
          showCaption(participantInfo.identity, text, isFinal);
        }
      }
    } catch (error) {
      console.error(
        'NOVA text stream failed:',
        error instanceof Error ? error.name : 'UnknownError',
      );
      return;
    }

    if (!text.trim()) return;

    if (isTranscription) {
      showCaption(participantInfo.identity, text, isFinal);
    }

    const isUser = Boolean(state.localIdentity) && participantInfo.identity === state.localIdentity;
    upsertChatMessage(
      `stream:${participantInfo.identity}:${streamId}`,
      isUser ? 'user' : 'nova',
      text,
    );
  });
}

function wireRoomEvents(room) {
  room.on(RoomEvent.TrackSubscribed, (track) => {
    attachRemoteAudio(track);
  });

  room.on(RoomEvent.TrackUnsubscribed, (track) => {
    track.detach();
  });

  room.on(RoomEvent.MediaDevicesError, () => {
    setStatus('error', 'DEVICE ERROR', 'Windows could not access the selected camera or microphone.');
  });

  room.on(RoomEvent.Disconnected, () => {
    if (!state.shuttingDown) resetDisconnectedState();
  });

  room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
    if (!room.canPlaybackAudio) {
      el.connectionDetail.textContent = 'Click inside NOVA Vision to allow NOVA audio playback.';
    }
  });
}

async function connectSession() {
  if (state.connected || state.connecting) return;

  state.connecting = true;
  render();
  setStatus('', 'CONNECTING', 'Creating a private short-lived LiveKit session…');

  let room = null;
  let failureDetail = null;

  try {
    const credentials = await invoke('get_livekit_connection');
    state.localIdentity = credentials.identity;
    room = new Room({
      adaptiveStream: true,
      dynacast: true,
      videoCaptureDefaults: {
        resolution: VideoPresets.h720.resolution,
      },
      publishDefaults: {
        stopMicTrackOnMute: true,
      },
    });
    wireRoomEvents(room);
    wireCaptionStreams(room);

    await room.connect(credentials.serverUrl, credentials.participantToken, {
      autoSubscribe: true,
    });

    state.room = room;
    state.connected = true;
    installVisionStatusHandler(room);
    await syncPersonalityToAgent();
    state.cameraEnabled = false;
    state.micEnabled = false;

  } catch (error) {
    console.error('NOVA Vision connection failed:', error instanceof Error ? error.name : 'UnknownError');
    failureDetail = 'Could not connect. Check the agent worker and LiveKit configuration.';
    if (room) room.disconnect();
    state.room = null;
    state.connected = false;
  } finally {
    state.connecting = false;
    render();
    if (failureDetail) setStatus('error', 'CONNECTION FAILED', failureDetail);
  }
}

async function stopAndUnpublish(source, previewElement = null) {
  if (!state.room) return;

  const publication = state.room.localParticipant.getTrackPublication(source);
  const track = publication?.track;
  if (!track) return;

  if (previewElement) track.detach(previewElement);
  await state.room.localParticipant.unpublishTrack(track, true);
}

async function setCamera(next) {
  if (!state.room || !state.connected) return;
  let failureDetail = null;

  try {
    if (next) {
      await state.room.localParticipant.setCameraEnabled(true);
      state.cameraEnabled = state.room.localParticipant.isCameraEnabled;

      const attached = attachExactCameraPreview();
      if (!state.cameraEnabled || !attached) {
        throw new Error('Camera publication did not expose a local track.');
      }
      await el.cameraPreview.play().catch(() => {});
    } else {
      await stopAndUnpublish(Track.Source.Camera, el.cameraPreview);
      el.cameraPreview.srcObject = null;
      state.cameraEnabled = false;
    }
  } catch (error) {
    await stopAndUnpublish(Track.Source.Camera, el.cameraPreview).catch(() => {});
    el.cameraPreview.srcObject = null;
    state.cameraEnabled = false;
    console.error('Camera toggle failed:', error instanceof Error ? error.name : 'UnknownError');
    failureDetail = 'Allow camera access in Windows/WebView2 and try again.';
  }

  render();
  if (failureDetail) setStatus('error', 'CAMERA BLOCKED', failureDetail);
}

async function setMicrophone(next) {
  if (!state.room || !state.connected) return;
  let failureDetail = null;

  try {
    if (next) {
      await state.room.localParticipant.setMicrophoneEnabled(true);
      state.micEnabled = state.room.localParticipant.isMicrophoneEnabled;
      if (!state.micEnabled) throw new Error('Microphone publication did not expose a local track.');
    } else {
      await stopAndUnpublish(Track.Source.Microphone);
      state.micEnabled = false;
    }
  } catch (error) {
    await stopAndUnpublish(Track.Source.Microphone).catch(() => {});
    state.micEnabled = false;
    console.error('Microphone toggle failed:', error instanceof Error ? error.name : 'UnknownError');
    failureDetail = 'Allow microphone access in Windows/WebView2 and try again.';
  }

  render();
  if (failureDetail) setStatus('error', 'MIC BLOCKED', failureDetail);
}

async function ensureConnectedForInput() {
  if (state.connected) return true;
  if (state.connecting) return false;

  await connectSession();
  return state.connected;
}

async function toggleCameraInput() {
  const next = !state.cameraEnabled;
  if (next && !state.connected) {
    const connected = await ensureConnectedForInput();
    if (!connected) return;
  }
  await setCamera(next);
}

async function toggleMicrophoneInput() {
  const next = !state.micEnabled;
  if (next && !state.connected) {
    const connected = await ensureConnectedForInput();
    if (!connected) return;
  }
  await setMicrophone(next);
}


function resetDisconnectedState() {
  state.room = null;
  state.localIdentity = null;
  clearCaption();
  clearChat();
  state.connected = false;
  state.connecting = false;
  state.cameraEnabled = false;
  state.micEnabled = false;
  el.cameraPreview.srcObject = null;
  clearRemoteAudio();
  render();
}

async function stopSession() {
  const room = state.room;
  if (!room) {
    resetDisconnectedState();
    return;
  }

  setStatus('', 'STOPPING', 'Releasing camera, microphone, and room connection…');
  try {
    await stopAndUnpublish(Track.Source.Camera, el.cameraPreview).catch(() => {});
    await stopAndUnpublish(Track.Source.Microphone).catch(() => {});
    el.cameraPreview.srcObject = null;
    room.disconnect();
  } finally {
    resetDisconnectedState();
  }
}

async function shutdownAndDestroy() {
  if (state.shuttingDown) return;
  state.shuttingDown = true;
  try {
    await stopSession();
  } finally {
    await appWindow.destroy();
  }
}

el.connectButton.addEventListener('click', connectSession);
el.stopButton.addEventListener('click', stopSession);
el.cameraSourceButton.addEventListener('click', toggleCameraInput);
el.micButton.addEventListener('click', toggleMicrophoneInput);
el.sendChatButton.addEventListener('click', sendChatMessage);
el.chatInput.addEventListener('input', render);
el.chatInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendChatMessage();
  }
});
el.speakerButton.addEventListener('click', async () => {
  state.speakerEnabled = !state.speakerEnabled;

  if (state.speakerEnabled && state.room && !state.room.canPlaybackAudio) {
    try {
      await state.room.startAudio();
    } catch {
      state.speakerEnabled = false;
      setStatus(
        'error',
        'SOUND BLOCKED',
        'Windows/WebView2 did not allow NOVA audio playback.',
      );
    }
  }

  for (const audio of el.remoteAudio.querySelectorAll('audio')) {
    audio.muted = !state.speakerEnabled;
  }

  render();
});

el.pinButton.addEventListener('click', async () => {
  state.pinned = !state.pinned;
  try {
    await appWindow.setAlwaysOnTop(state.pinned);
  } catch {
    state.pinned = !state.pinned;
  }
  render();
});

el.minimizeButton.addEventListener('click', () => appWindow.minimize());
el.closeButton.addEventListener('click', shutdownAndDestroy);

el.collapseButton.addEventListener('click', async () => {
  state.collapsed = !state.collapsed;
  render();
  await appWindow.setSize(state.collapsed ? COMPACT_SIZE : FULL_SIZE);
});


await appWindow.onCloseRequested(async (event) => {
  if (state.shuttingDown) return;
  event.preventDefault();
  await shutdownAndDestroy();
});

// === NOVA GLASS PERSONALITY V3 BEGIN ===

const PERSONALITY_PRESETS = {
  best_friend: { mode: 'best_friend', profanity: 'natural', humor: 72, sarcasm: 38, teasing: true, emoji: true, serious_tone_down: true },
  chill: { mode: 'chill', profanity: 'light', humor: 42, sarcasm: 18, teasing: true, emoji: true, serious_tone_down: true },
  focus: { mode: 'focus', profanity: 'light', humor: 12, sarcasm: 8, teasing: false, emoji: false, serious_tone_down: true },
  professional: { mode: 'professional', profanity: 'off', humor: 5, sarcasm: 0, teasing: false, emoji: false, serious_tone_down: true },
  unfiltered: { mode: 'unfiltered', profanity: 'unfiltered', humor: 75, sarcasm: 58, teasing: true, emoji: true, serious_tone_down: true },
};

let personality = loadPersonality();
let personalitySyncTimer = null;

const settingsEl = {
  button: document.querySelector('#settingsButton'),
  overlay: document.querySelector('#personalityOverlay'),
  back: document.querySelector('#settingsBackButton'),
  done: document.querySelector('#personalityDoneButton'),
  reset: document.querySelector('#personalityResetButton'),
  modes: [...document.querySelectorAll('[data-mode]')],
  profanity: [...document.querySelectorAll('[data-profanity]')],
  humor: document.querySelector('#humorSlider'),
  humorValue: document.querySelector('#humorValue'),
  sarcasm: document.querySelector('#sarcasmSlider'),
  sarcasmValue: document.querySelector('#sarcasmValue'),
  teasing: document.querySelector('#teasingToggle'),
  emoji: document.querySelector('#emojiToggle'),
  serious: document.querySelector('#seriousToggle'),
  saveState: document.querySelector('#personalitySaveState'),
};

function normalizePersonality(raw) {
  const fallback = { ...PERSONALITY_PRESETS.best_friend };
  if (!raw || typeof raw !== 'object') return fallback;

  const mode = Object.hasOwn(PERSONALITY_PRESETS, raw.mode) ? raw.mode : fallback.mode;
  const profanityAllowed = new Set(['off', 'light', 'natural', 'unfiltered']);
  const profanity = profanityAllowed.has(raw.profanity) ? raw.profanity : fallback.profanity;
  const clamp = (value, fallbackValue) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return fallbackValue;
    return Math.max(0, Math.min(100, Math.round(number)));
  };

  return {
    mode,
    profanity,
    humor: clamp(raw.humor, fallback.humor),
    sarcasm: clamp(raw.sarcasm, fallback.sarcasm),
    teasing: typeof raw.teasing === 'boolean' ? raw.teasing : fallback.teasing,
    emoji: typeof raw.emoji === 'boolean' ? raw.emoji : fallback.emoji,
    serious_tone_down: typeof raw.serious_tone_down === 'boolean'
      ? raw.serious_tone_down
      : fallback.serious_tone_down,
  };
}

function loadPersonality() {
  return { ...PERSONALITY_PRESETS.best_friend };
}

function savePersonality() {
  settingsEl.saveState.textContent = state.connected
    ? 'Applied for this NOVA session'
    : 'Ready for this NOVA session';
}

function renderPersonality() {
  settingsEl.modes.forEach((button) => {
    button.classList.toggle('active', button.dataset.mode === personality.mode);
  });

  settingsEl.profanity.forEach((button) => {
    button.classList.toggle('active', button.dataset.profanity === personality.profanity);
  });

  settingsEl.humor.value = String(personality.humor);
  settingsEl.humorValue.value = `${personality.humor}%`;
  settingsEl.sarcasm.value = String(personality.sarcasm);
  settingsEl.sarcasmValue.value = `${personality.sarcasm}%`;
  settingsEl.teasing.checked = personality.teasing;
  settingsEl.emoji.checked = personality.emoji;
  settingsEl.serious.checked = personality.serious_tone_down;
}

function openPersonalitySettings() {
  el.shell.classList.add('settings-open');
  settingsEl.overlay.setAttribute('aria-hidden', 'false');
  settingsEl.button.classList.add('active');
  renderPersonality();
}

function closePersonalitySettings() {
  el.shell.classList.remove('settings-open');
  settingsEl.overlay.setAttribute('aria-hidden', 'true');
  settingsEl.button.classList.remove('active');
  el.chatInput.focus();
}

async function syncPersonalityToAgent() {
  if (!state.connected || !state.room) return false;

  const agentReady = await waitForNOVAAgent(state.room, 5000);
  if (!agentReady) {
    settingsEl.saveState.textContent = 'Ready · NOVA will apply it when connected';
    return false;
  }

  try {
    const permission = state.room.localParticipant.permissions?.canPublishData;
    if (permission === false) {
      settingsEl.saveState.textContent = 'Not applied · text/data permission is blocked';
      return false;
    }

    await state.room.localParticipant.sendText(
      JSON.stringify(personality),
      { topic: 'nova.personality' },
    );

    settingsEl.saveState.textContent = 'Applied to NOVA';
    return true;
  } catch (error) {
    console.error(
      'NOVA personality sync failed:',
      error instanceof Error ? error.message : 'UnknownError',
    );
    settingsEl.saveState.textContent = 'Not applied to live session';
    return false;
  }
}

function schedulePersonalitySync() {
  savePersonality();
  renderPersonality();

  if (personalitySyncTimer) clearTimeout(personalitySyncTimer);
  personalitySyncTimer = setTimeout(() => {
    syncPersonalityToAgent();
  }, 180);
}

settingsEl.button.addEventListener('click', () => {
  if (el.shell.classList.contains('settings-open')) closePersonalitySettings();
  else openPersonalitySettings();
});
settingsEl.back.addEventListener('click', closePersonalitySettings);
settingsEl.done.addEventListener('click', closePersonalitySettings);

settingsEl.reset.addEventListener('click', () => {
  personality = { ...PERSONALITY_PRESETS.best_friend };
  schedulePersonalitySync();
});

settingsEl.modes.forEach((button) => {
  button.addEventListener('click', () => {
    personality = { ...PERSONALITY_PRESETS[button.dataset.mode] };
    schedulePersonalitySync();
  });
});

settingsEl.profanity.forEach((button) => {
  button.addEventListener('click', () => {
    personality.profanity = button.dataset.profanity;
    schedulePersonalitySync();
  });
});

settingsEl.humor.addEventListener('input', () => {
  personality.humor = Number(settingsEl.humor.value);
  schedulePersonalitySync();
});
settingsEl.sarcasm.addEventListener('input', () => {
  personality.sarcasm = Number(settingsEl.sarcasm.value);
  schedulePersonalitySync();
});
settingsEl.teasing.addEventListener('change', () => {
  personality.teasing = settingsEl.teasing.checked;
  schedulePersonalitySync();
});
settingsEl.emoji.addEventListener('change', () => {
  personality.emoji = settingsEl.emoji.checked;
  schedulePersonalitySync();
});
settingsEl.serious.addEventListener('change', () => {
  personality.serious_tone_down = settingsEl.serious.checked;
  schedulePersonalitySync();
});

window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && el.shell.classList.contains('settings-open')) {
    event.preventDefault();
    closePersonalitySettings();
  }
});

renderPersonality();

// === NOVA GLASS PERSONALITY V3 END ===

// === NOVA VISION TRANSPORT V3.2 BEGIN ===

const visionTransport = {
  backendState: 'WAITING_FOR_CAMERA',
  detail: 'Camera is not shared.',
};

const visionUi = {
  sessionButton: document.querySelector('#novaSessionButton'),
  sessionButtonLabel: document.querySelector('#novaSessionButtonLabel'),
  truth: document.querySelector('#visionTruth'),
  truthLabel: document.querySelector('#visionTruthLabel'),
  truthDetail: document.querySelector('#visionTruthDetail'),
};

function renderVisionTransport() {
  if (state.connected) {
    visionUi.sessionButton.classList.add('connected');
    visionUi.sessionButtonLabel.textContent = 'NOVA Online';
  } else {
    visionUi.sessionButton.classList.remove('connected');
    visionUi.sessionButtonLabel.textContent = 'Start NOVA';
  }

  let label = 'Vision off';
  let detail = 'Camera is not shared.';
  let level = 'off';

  if (state.cameraEnabled) {
    label = 'Camera shared';
    detail = 'Waiting for NOVA to receive video.';
    level = 'shared';
  }

  if (visionTransport.backendState === 'AGENT_RECEIVING_VIDEO') {
    label = 'Agent receiving video';
    detail = 'NOVA subscribed to your camera track.';
    level = 'receiving';
  } else if (visionTransport.backendState === 'VIDEO_SUBSCRIPTION_FAILED') {
    label = 'Vision connection failed';
    detail = visionTransport.detail || 'NOVA could not subscribe to video.';
    level = 'error';
  } else if (visionTransport.backendState === 'VIDEO_NOT_RECEIVING') {
    label = state.cameraEnabled ? 'Camera shared' : 'Vision off';
    detail = state.cameraEnabled
      ? 'Camera is published, but NOVA is not receiving it.'
      : 'Camera is not shared.';
    level = state.cameraEnabled ? 'shared' : 'off';
  }

  visionUi.truth.dataset.level = level;
  visionUi.truthLabel.textContent = label;
  visionUi.truthDetail.textContent = detail;

  el.sourceBadge.textContent = state.cameraEnabled
    ? (level === 'receiving' ? 'AGENT RECEIVING VIDEO' : 'CAMERA SHARED')
    : 'CAMERA OFF';
}

visionUi.sessionButton.addEventListener('click', async () => {
  if (!state.connected) {
    visionUi.sessionButton.disabled = true;
    visionUi.sessionButtonLabel.textContent = 'Connecting…';
    try {
      await connectSession();
    } finally {
      visionUi.sessionButton.disabled = false;
      renderVisionTransport();
    }
    return;
  }
  el.chatInput.focus();
});

function installVisionStatusHandler(room) {
  if (!room || room.__novaVisionStatusInstalled) return;
  room.__novaVisionStatusInstalled = true;

  room.registerTextStreamHandler(
    'nova.vision-status',
    async (reader) => {
      try {
        const payload = JSON.parse(await reader.readAll());
        if (payload && typeof payload.state === 'string') {
          visionTransport.backendState = payload.state;
          visionTransport.detail = typeof payload.detail === 'string'
            ? payload.detail
            : '';
          renderVisionTransport();
        }
      } catch (error) {
        console.warn(
          'NOVA vision status parse failed:',
          error instanceof Error ? error.message : 'UnknownError',
        );
      }
    },
  );
}

const _novaOriginalRenderV32 = render;
render = function renderWithVisionTransport() {
  _novaOriginalRenderV32();
  renderVisionTransport();
};

renderVisionTransport();

// === NOVA VISION TRANSPORT V3.2 END ===

render();
// === NOVA VISION SESSION V3.3 BEGIN ===
// Start NOVA uses connectSession(), vision status is installed on the real room,
// and Camera/Mic no longer start remote audio playback as a side effect.
// Audio playback starts only from the explicit Sound button.
// === NOVA VISION SESSION V3.3 END ===
