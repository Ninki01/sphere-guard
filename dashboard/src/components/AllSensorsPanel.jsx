import { useState, useEffect, useRef, useCallback } from 'react';
import { RefreshCw, Settings2 } from 'lucide-react';

/* Shared accent palette (matches the dashboard pages). */
const P = {
  red: '#7F2020',
  sage: '#869B7E',
  tan: '#C9CAAC',
  cream: '#F6F3EB',
  text: '#2a1010',
  border: '#C9CAAC',
};

/* Group definition: human label, sensor name (for online status), accent colour,
   and the CSV column keys it reads from the robot /sensors response. */
const GROUPS = [
  {
    label: 'BNO055 IMU',
    sensor: 'BNO055',
    color: P.red,
    keys: [
      ['pitch', 'Pitch', '°'],
      ['roll', 'Roll', '°'],
      ['heading', 'Heading', '°'],
      ['quat_w', 'Quat W', ''],
      ['quat_x', 'Quat X', ''],
      ['quat_y', 'Quat Y', ''],
      ['quat_z', 'Quat Z', ''],
      ['lin_acc_x', 'Lin Acc X', 'm/s²'],
      ['lin_acc_y', 'Lin Acc Y', 'm/s²'],
      ['lin_acc_z', 'Lin Acc Z', 'm/s²'],
      ['gyro_x', 'Gyro X', 'rad/s'],
      ['gyro_y', 'Gyro Y', 'rad/s'],
      ['gyro_z', 'Gyro Z', 'rad/s'],
      ['cal_sys', 'Cal Sys', '/3'],
      ['cal_gyro', 'Cal Gyro', '/3'],
      ['cal_accel', 'Cal Accel', '/3'],
      ['cal_mag', 'Cal Mag', '/3'],
    ],
  },
  {
    label: 'BME280',
    sensor: 'BME280',
    color: P.sage,
    keys: [
      ['bme_temp', 'Temperature', '°C'],
      ['bme_hum', 'Humidity', '%'],
      ['bme_press', 'Pressure', 'hPa'],
    ],
  },
  {
    label: 'SHT45',
    sensor: 'SHT45',
    color: P.tan,
    keys: [
      ['sht_temp', 'Temperature', '°C'],
      ['sht_hum', 'Humidity', '%'],
    ],
  },
  {
    label: 'SCD41',
    sensor: 'SCD41',
    color: P.sage,
    keys: [
      ['co2', 'CO₂', 'ppm'],
      ['scd_temp', 'Temperature', '°C'],
      ['scd_hum', 'Humidity', '%'],
    ],
  },
  {
    label: 'SDP810',
    sensor: 'SDP810',
    color: P.tan,
    keys: [
      ['diff_press', 'Diff Pressure', 'Pa'],
    ],
  },
  {
    label: 'VOC PS1',
    sensor: 'VOC_PS1',
    color: P.red,
    keys: [
      ['voc_ppb', 'VOC', 'ppb'],
    ],
  },
  {
    label: 'INA226',
    sensor: 'INA226',
    color: P.sage,
    keys: [
      ['bus_v', 'Bus Voltage', 'V'],
      ['current_a', 'Current', 'A'],
      ['power_w', 'Power', 'W'],
    ],
  },
  {
    label: 'Pi Internal',
    sensor: 'Pi',
    color: P.red,
    keys: [
      ['pi_temp', 'SoC Temp', '°C'],
      ['wifi_dbm', 'WiFi Signal', 'dBm'],
      ['internet', 'Internet', ''],
      ['net_type', 'Net Type', ''],
      ['net_name', 'Net Name', ''],
      ['ip_address', 'IP Address', ''],
      ['latency_ms', 'Latency', 'ms'],
      ['link_speed_mbps', 'Link Speed', 'Mbps'],
      ['wifi_quality', 'WiFi Quality', '%'],
    ],
  },
];

const fmt = (v) => (v === '' || v === null || v === undefined) ? '—' : String(v);

function AllSensorsPanel({ title, defaultUrl = '', storageKey, accent = P.sage }) {
  const [url, setUrl] = useState(() => localStorage.getItem(storageKey) || defaultUrl || '');
  const [inputUrl, setInputUrl] = useState(url);
  const [readings, setReadings] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(true);
  const timerRef = useRef(null);

  const connect = useCallback(() => {
    const clean = inputUrl.trim().replace(/\/+$/, '');
    setUrl(clean);
    if (clean) {
      localStorage.setItem(storageKey, clean);
    } else {
      localStorage.removeItem(storageKey);
    }
  }, [inputUrl, storageKey]);

  useEffect(() => {
    if (!url) return undefined;

    let stopped = false;
    let inFlight = false;

    const tick = async () => {
      if (inFlight || stopped) return;
      inFlight = true;
      try {
        const res = await fetch(url + '/sensors', { signal: AbortSignal.timeout(3000) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!stopped) {
          setReadings(data);
          setError(null);
          setLastUpdate(new Date());
        }
      } catch (e) {
        if (!stopped) setError(e.name === 'TimeoutError' ? 'timeout' : e.message);
      } finally {
        inFlight = false;
      }
    };

    tick();
    timerRef.current = setInterval(tick, 1500);
    return () => {
      stopped = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [url]);

  const onlineMap = {};
  (readings?._hardware?.sensors || []).forEach((s) => {
    onlineMap[s.name] = s.online;
  });

  const stripKeys = ['t_ms', 'robot_id', 'robot_name', '_hardware'];
  const extraKeys = readings
    ? Object.keys(readings).filter((k) => !stripKeys.includes(k) &&
        !GROUPS.some((g) => g.keys.some(([key]) => key === k)))
    : [];

  return (
    <div className="dark-panel" style={{ padding: '15px', marginBottom: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '14px', flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <RefreshCw size={18} color={accent} /> {title || 'All Sensor Readings'}
        </h3>

        <span style={{
          marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: '6px',
          fontSize: '12px', color: error ? P.red : readings ? P.sage : P.tan, fontWeight: 600,
        }}>
          <span className={`status-dot ${error ? 'red' : readings ? 'green' : ''}`}
            style={{ backgroundColor: error ? P.red : readings ? P.sage : P.tan }}></span>
          {error ? 'OFFLINE' : readings ? 'LIVE' : 'Connecting…'}
        </span>

        <span style={{ fontSize: '12px', color: P.tan }}>
          {lastUpdate ? `Updated ${lastUpdate.toLocaleTimeString('en-GB')}` : '—'}
        </span>

        <button onClick={() => setExpanded((v) => !v)} style={{
          background: 'rgba(255,255,255,0.12)', border: `1px solid ${P.border}`, color: P.cream,
          borderRadius: '5px', padding: '4px 10px', fontSize: '12px', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: '6px',
        }}>
          <Settings2 size={13} /> {expanded ? 'Collapse' : 'Expand'}
        </button>
      </div>

      {!expanded && (
        <div style={{ fontSize: '12px', color: P.tan }}>
          Live stream {url ? `from ${url}` : 'not connected'} · {error ? 'offline' : readings ? 'showing all sensor readings' : 'no data yet'}
        </div>
      )}

      {expanded && (
        <div style={{ display: 'flex', gap: '10px', marginBottom: '16px', flexWrap: 'wrap' }}>
          <input
            type="text"
            value={inputUrl}
            onChange={(e) => setInputUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && connect()}
            placeholder="http://192.168.1.50:8000"
            style={{
              flex: '1', minWidth: '260px', padding: '8px 10px', borderRadius: '6px',
              border: `1px solid ${P.border}`, backgroundColor: P.cream, color: P.text,
              fontSize: '13px', outline: 'none',
            }}
          />
          <button onClick={connect} style={{
            background: accent, color: 'white', border: 'none', borderRadius: '6px',
            padding: '8px 16px', fontWeight: 'bold', fontSize: '13px', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: '6px',
          }}>
            <RefreshCw size={14} /> Connect
          </button>
        </div>
      )}

      {expanded && !url && (
        <div style={{
          padding: '20px', textAlign: 'center', color: P.tan, fontSize: '13px',
          border: `1px dashed ${P.border}`, borderRadius: '6px',
        }}>
          Enter the robot server address above to stream every sensor reading live.
          (Set <code style={{ color: P.cream }}>VITE_ROBOT_SG01_URL</code> /{' '}
          <code style={{ color: P.cream }}>VITE_ROBOT_SG02_URL</code> in{' '}
          <code style={{ color: P.cream }}>dashboard/.env</code> to bake it in.)
        </div>
      )}

      {expanded && url && error && (
        <div style={{
          padding: '20px', textAlign: 'center', color: P.red, fontSize: '13px',
          border: `1px solid ${P.red}`, borderRadius: '6px', backgroundColor: 'rgba(127,32,32,0.08)',
        }}>
          No response from {url} ({error}). Check the robot is running and reachable on this network.
        </div>
      )}

      {expanded && url && !error && readings && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: '12px' }}>
          {GROUPS.map((g) => {
            const present = g.keys.some(([key]) => String(readings[key] ?? '').length > 0);
            const sensorOnline = onlineMap[g.sensor] ?? null;
            return (
              <div key={g.label} style={{
                backgroundColor: 'rgba(255,255,255,0.12)', borderRadius: '6px',
                border: `1px solid ${sensorOnline === false ? P.red : present ? g.color : P.border}`,
                borderLeft: `4px solid ${sensorOnline === false ? P.red : g.color}`,
                padding: '10px 12px', opacity: present || sensorOnline !== false ? 1 : 0.6,
              }}>
                <div style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  marginBottom: '8px', fontSize: '13px', color: P.sage, fontWeight: 600,
                }}>
                  <span>{g.label}</span>
                  <span className="status-dot"
                    style={{ backgroundColor: sensorOnline === false ? P.red : present ? g.color : '#999' }}
                    title={sensorOnline === false ? 'offline' : present ? 'online' : 'no data'} />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '5px 10px' }}>
                  {g.keys.map(([key, name, unit]) => (
                    <div key={key} style={{ fontSize: '12px' }}>
                      <div style={{ color: P.tan, fontSize: '11px' }}>{name}</div>
                      <div style={{ color: P.cream, fontWeight: 600, fontSize: '13px' }}>
                        {fmt(readings[key])}{unit ? <span style={{ color: P.tan, fontWeight: 'normal', fontSize: '11px' }}> {unit}</span> : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}

          {extraKeys.length > 0 && (
            <div style={{ backgroundColor: 'rgba(255,255,255,0.12)', borderRadius: '6px', border: `1px solid ${P.border}`, padding: '10px 12px' }}>
              <div style={{ marginBottom: '8px', fontSize: '13px', color: P.sage, fontWeight: 600 }}>Other fields</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '5px 10px' }}>
                {extraKeys.map((key) => (
                  <div key={key} style={{ fontSize: '12px' }}>
                    <div style={{ color: P.tan, fontSize: '11px' }}>{key}</div>
                    <div style={{ color: P.cream, fontWeight: 600, fontSize: '13px' }}>{fmt(readings[key])}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {expanded && url && !error && !readings && (
        <div style={{ padding: '20px', textAlign: 'center', color: P.tan, fontSize: '13px' }}>
          Fetching from {url}…
        </div>
      )}
    </div>
  );
}

export default AllSensorsPanel;