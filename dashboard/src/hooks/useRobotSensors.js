import { useState, useEffect, useRef } from 'react';

export const sensorText = (v) =>
  (v === '' || v === null || v === undefined) ? '—' : String(v);

export const sensorNum = (v) => {
  if (v === '' || v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

export const internetLabel = (v) => {
  if (v === 1 || v === '1') return 'Online';
  if (v === 0 || v === '0') return 'Offline';
  return '—';
};

export function resolveRobotUrl(storageKey, envUrl = '') {
  try {
    return (localStorage.getItem(storageKey) || envUrl || '').replace(/\/+$/, '');
  } catch {
    return (envUrl || '').replace(/\/+$/, '');
  }
}

export function saveRobotUrl(storageKey, url) {
  const clean = String(url || '').trim().replace(/\/+$/, '');
  try {
    if (clean) localStorage.setItem(storageKey, clean);
    else localStorage.removeItem(storageKey);
  } catch {
    /* localStorage unavailable — keep in-memory only */
  }
  return clean;
}

export default function useRobotSensors(url, onData, intervalMs = 1500) {
  const [state, setState] = useState({ url: null, readings: null, error: null, lastUpdate: null });
  const inFlightRef = useRef(false);
  const onDataRef = useRef(onData);

  useEffect(() => {
    onDataRef.current = onData;
  });

  useEffect(() => {
    if (!url) return undefined;

    let stopped = false;
    const base = url.replace(/\/+$/, '');

    const tick = async () => {
      if (inFlightRef.current || stopped) return;
      inFlightRef.current = true;
      try {
        const res = await fetch(`${base}/sensors`, { signal: AbortSignal.timeout(3000) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (stopped) return;
        setState({ url, readings: data, error: null, lastUpdate: new Date() });
        onDataRef.current?.(data);
      } catch (e) {
        if (stopped) return;
        const msg = e.name === 'TimeoutError' ? 'timeout' : e.message;
        setState((prev) =>
          prev.url === url
            ? { ...prev, error: msg }
            : { url, readings: null, error: msg, lastUpdate: null }
        );
      } finally {
        inFlightRef.current = false;
      }
    };

    tick();
    const timer = setInterval(tick, intervalMs);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [url, intervalMs]);

  const active = Boolean(url) && state.url === url;
  return {
    readings: active ? state.readings : null,
    error: active ? state.error : null,
    lastUpdate: active ? state.lastUpdate : null,
  };
}
