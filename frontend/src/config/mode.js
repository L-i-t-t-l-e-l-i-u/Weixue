/**
 * Single source of truth for 演示模式 / 真实模式.
 *
 * Previously the demo/real split was decided at build time by
 * VITE_DEMO_MODE and read in three different places (client.js,
 * StudentWindow.jsx, plus a hardcoded DEMO badge in App.jsx), which drifted.
 * This module is the ONLY place that reads the env flag and the only place
 * that persists the user's choice. Everything else asks here.
 *
 * Modes:
 * - 'auto':  startup probe — reachable /api/health ⇒ real, otherwise demo.
 * - 'demo':  embedded demo-data.json, no backend needed (GitHub Pages).
 * - 'real':  the FastAPI backend.
 *
 * The user's explicit choice is stored in localStorage (`weixue-mode`);
 * VITE_DEMO_MODE only sets the *initial* preference for static hosting.
 */

const STORAGE_KEY = 'weixue-mode';
const CHANGE_EVENT = 'weixue-mode-change';

const _initialPreference = () =>
  import.meta.env.VITE_DEMO_MODE === 'true' ? 'demo' : 'auto';

export function getMode() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'demo' || saved === 'real') return saved;
  } catch { /* storage unavailable */ }
  return _initialPreference();
}

/** Persist the user's choice ('demo' | 'real'); 'auto' clears the override. */
export function setMode(mode) {
  try {
    if (mode === 'demo' || mode === 'real') {
      localStorage.setItem(STORAGE_KEY, mode);
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch { /* storage unavailable */ }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: mode }));
}

export function subscribeModeChange(cb) {
  const onEvent = (e) => cb(e.detail);
  // Same-tab custom event + cross-tab storage event (separate student windows).
  const onStorage = (e) => {
    if (e.key === STORAGE_KEY) cb(getMode());
  };
  window.addEventListener(CHANGE_EVENT, onEvent);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onEvent);
    window.removeEventListener('storage', onStorage);
  };
}

let _resolved = null;       // 'demo' | 'real' once auto has been probed
let _probePromise = null;

/**
 * Resolve the current mode for async layers (API dispatcher, status bus).
 * 'auto' probes /api/health once with a short timeout, then caches the result
 * for the lifetime of the tab.
 */
export function resolveMode() {
  const mode = getMode();
  if (mode !== 'auto') {
    _resolved = mode;
    return Promise.resolve(mode);
  }
  if (_resolved) return Promise.resolve(_resolved);
  if (!_probePromise) {
    _probePromise = (async () => {
      try {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 2500);
        const res = await fetch('/api/health', { signal: ctrl.signal });
        clearTimeout(timer);
        _resolved = res.ok ? 'real' : 'demo';
      } catch {
        _resolved = 'demo';
      }
      return _resolved;
    })();
  }
  return _probePromise;
}
