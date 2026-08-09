/**
 * Lightweight status bus for the live classroom.
 *
 * Demo mode (default): BroadcastChannel synchronizes student windows ↔ teacher
 * cockpit inside the same browser, so states look real-time without a backend.
 * If BroadcastChannel is unavailable we fall back to localStorage storage
 * events, which also fire across tabs.
 *
 * Real mode: swap this module for a WebSocket/SSE-backed bus that keeps the
 * same publish/subscribe API (see 现场伴学设计与前端重构方案_v1.md §3.3).
 */

const PREFIX = 'weixue-live-';
let _channel = null;
let _listeners = new Set();
let _storageHandler = null;

function channelName(courseId) {
  return `${PREFIX}${courseId || 'default'}`;
}

function ensureChannel(courseId) {
  if (typeof BroadcastChannel !== 'undefined' && !_channel) {
    _channel = new BroadcastChannel(channelName(courseId));
    _channel.onmessage = (e) => {
      const evt = e.data || {};
      _listeners.forEach(fn => {
        try { fn(evt); } catch (err) { console.error('[statusBus] listener error', err); }
      });
    };
  }
  if (!_storageHandler && typeof window !== 'undefined') {
    _storageHandler = (e) => {
      if (e.key && e.key.startsWith(PREFIX) && e.newValue) {
        try {
          const evt = JSON.parse(e.newValue);
          _listeners.forEach(fn => {
            try { fn(evt); } catch (err) { console.error('[statusBus] storage listener error', err); }
          });
        } catch { /* ignore malformed payloads */ }
      }
    };
    window.addEventListener('storage', _storageHandler);
  }
  return _channel;
}

/** Subscribe to status events for a course. Returns an unsubscribe function. */
export function subscribeStatus(courseId, cb) {
  _listeners.add(cb);
  ensureChannel(courseId);
  return () => _listeners.delete(cb);
}

/** Publish a status event: { responseId, status, studentId, payload }. */
export function publishStatus(courseId, event) {
  const payload = { ...event, ts: Date.now() };
  const channel = ensureChannel(courseId);
  if (channel) {
    try { channel.postMessage(payload); } catch (err) { console.warn('[statusBus] postMessage failed', err); }
  } else if (typeof window !== 'undefined') {
    // localStorage fallback: a unique key value guarantees the storage event fires.
    try {
      window.localStorage.setItem(`${channelName(courseId)}-${Date.now()}-${Math.random()}`, JSON.stringify(payload));
    } catch (err) { console.warn('[statusBus] localStorage fallback failed', err); }
  }
  // Same-tab listeners always receive the event too.
  _listeners.forEach(fn => {
    try { fn(payload); } catch (err) { console.error('[statusBus] listener error', err); }
  });
}

export function closeStatusBus() {
  if (_channel) {
    try { _channel.close(); } catch { /* ignore */ }
    _channel = null;
  }
  if (_storageHandler && typeof window !== 'undefined') {
    window.removeEventListener('storage', _storageHandler);
    _storageHandler = null;
  }
  _listeners.clear();
}
