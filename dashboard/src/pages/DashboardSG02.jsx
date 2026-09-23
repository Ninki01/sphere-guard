import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Battery, Thermometer, ArrowLeft, Droplets, Cpu, Gauge, Camera, Wind, Activity, Play, Square } from 'lucide-react';
import robotLogo from '../assets/robot_illustration.jpg';
import { ref, onValue, set, update } from 'firebase/database';
import { doc, setDoc, updateDoc, serverTimestamp } from 'firebase/firestore';
import { rtdb, db } from '../lib/firebase';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts';
import AllSensorsPanel from '../components/AllSensorsPanel';

function ChartEmpty() {
  return (
    <div style={{
      height: '200px', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: '8px',
      color: '#C9CAAC', borderRadius: '6px',
      border: '1px dashed #C9CAAC', backgroundColor: 'rgba(201,202,172,0.08)',
    }}>
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#C9CAAC" strokeWidth="1.5">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
      <span style={{ fontSize: '13px' }}>Waiting for first data...</span>
    </div>
  );
}

const C = {
  red: '#7F2020',
  sage: '#869B7E',
  tan: '#C9CAAC',
  cream: '#F6F3EB',
  text: '#2a1010',
  border: '#C9CAAC',
  panel: 'rgba(255,255,255,0.72)',
  chartGrid: '#C9CAAC',
  chartAxis: '#869B7E',
  tooltip: { backgroundColor: '#F6F3EB', borderColor: '#C9CAAC', color: '#2a1010' },
};

function DashboardSG02() {
  const [cameraUrl, setCameraUrl] = useState(null);
  const [cameraStatus, setCameraStatus] = useState('OFFLINE');

  const [isConnected, setIsConnected] = useState(false);
  const [steering, setSteering] = useState(90);
  const [driveMode, setDriveMode] = useState('stop');
  const [heading] = useState(0);

  const [isFirebaseConnected, setIsFirebaseConnected] = useState(false);
  const [robotStatusText, setRobotStatusText] = useState('OFFLINE');

  const [activeSession, setActiveSession] = useState(null);
  const [operatorName, setOperatorName] = useState('Admin');
  const [locationTag, setLocationTag] = useState('Main Duct A');

  const [sensorData, setSensorData] = useState({
    battery: 0, speed: 0, mcuTemp: 0, motorDriverTemp: 0,
    internalTemp: 0, rssi: 0, distance: 0, pitch: 0,
    envTemp: 0, humidity: 0, voc: 0, co2: 0,
  });

  const [unifiedHistory, setUnifiedHistory] = useState([]);
  const [lastKnownPoint, setLastKnownPoint] = useState(null);

  const sendDriveCommand = (mode) => {
    setDriveMode(mode);
    const clickTime = Date.now();
    const commandRef = ref(rtdb, 'robots/sg02/control/movement');
    set(commandRef, { direction: mode, timestamp: clickTime })
      .then(() => console.log(`📡 Dash -> RTDB Latency: ${Date.now() - clickTime} ms`))
      .catch(error => console.error('Drive command failed', error));
  };

  const handleSteeringRelease = () => {
    const clickTime = Date.now();
    const steeringRef = ref(rtdb, 'robots/sg02/control/steering_command');
    set(steeringRef, { angle: parseInt(steering), timestamp: clickTime })
      .then(() => console.log(`📡 Steering -> RTDB Latency: ${Date.now() - clickTime} ms`))
      .catch(error => console.error('Steering command failed', error));
  };

  const startInspectionSession = async () => {
    if (activeSession) return;
    const newSessionId = `session_${Date.now()}`;
    try {
      await setDoc(doc(db, 'inspection_sessions', newSessionId), {
        sessionId: newSessionId, operator: operatorName, location: locationTag,
        status: 'IN_PROGRESS', startTime: serverTimestamp(),
      });
      await update(ref(rtdb, 'robots/sg02/system'), { activeSessionId: newSessionId });
      console.log('Inspection started! Session ID:', newSessionId);
    } catch (error) {
      console.error('Error starting session:', error);
    }
  };

  const stopInspectionSession = async () => {
    if (!activeSession) return;
    try {
      await updateDoc(doc(db, 'inspection_sessions', activeSession), {
        status: 'COMPLETED', endTime: serverTimestamp(),
      });
      await update(ref(rtdb, 'robots/sg02/system'), { activeSessionId: null });
      console.log('Inspection stopped!');
    } catch (error) {
      console.error('Error stopping session:', error);
    }
  };

  useEffect(() => {
    const unsubFirebase = onValue(ref(rtdb, '.info/connected'), (snap) => {
      setIsFirebaseConnected(snap.val() === true);
    });

    const unsubscribe = onValue(ref(rtdb, 'robots/sg02'), (snapshot) => {
      const data = snapshot.val();
      if (data) {
        const status = data.system?.connection?.status || 'OFFLINE';
        setRobotStatusText(status);
        setIsConnected(status === 'ONLINE');
        setCameraStatus(data.system?.camera?.status || 'OFFLINE');
        setCameraUrl(data.system?.camera?.url || null);
        setActiveSession(data.system?.activeSessionId || null);

        setSensorData({
          battery: data.battery?.percentage || 0,
          speed: data.telemetry?.speed || 0,
          mcuTemp: data.system?.temperature?.mcu || 0,
          motorDriverTemp: data.system?.temperature?.motorDriver || 0,
          rssi: data.system?.connection?.rssi || 0,
          distance: data.obstacle?.distanceCm || 0,
          pitch: data.telemetry?.imu_mpu6050?.pitch || 0,
          internalTemp: data.sensors?.bme280_temperature_c || 0,
          envTemp: data.sensors?.scd41_temperature_c || 0,
          humidity: data.sensors?.scd41_humidity_percent || 0,
          co2: data.sensors?.scd41_co2_ppm || 0,
          voc: data.sensors?.gas_ppm || 0,
        });

        const timeString = new Date().toLocaleTimeString('en-GB');
        const newPoint = {
          time: timeString,
          extTemp: data.sensors?.scd41_temperature_c || 0,
          extHum: data.sensors?.scd41_humidity_percent || 0,
          co2: data.sensors?.scd41_co2_ppm || 0,
          intTemp: data.sensors?.bme280_temperature_c || 0,
          intHum: data.sensors?.bme280_humidity_percent || 0,
          pressure: data.sensors?.bme280_pressure_hpa || 0,
        };
        setLastKnownPoint(newPoint);
        setUnifiedHistory(prev => [...prev, newPoint].slice(-30));
      }
    });

    return () => { unsubFirebase(); unsubscribe(); };
  }, []);

  const robotStatusColor = robotStatusText === 'ONLINE' ? C.sage
    : robotStatusText === 'OFFLINE' ? C.red : '#b59a00';

  const isLive = isConnected && unifiedHistory.length >= 2;
  const chartData = unifiedHistory.length >= 2
    ? unifiedHistory
    : lastKnownPoint
      ? [{ ...lastKnownPoint, time: '' }, lastKnownPoint]
      : [];
  const hasChartData = chartData.length > 0;

  const inputStyle = {
    width: '100%', padding: '10px', borderRadius: '6px',
    border: `1px solid ${C.border}`, backgroundColor: C.cream,
    color: C.text, boxSizing: 'border-box', fontSize: '14px', outline: 'none',
  };

  return (
    <div className="dashboard-container">
      {/* HEADER */}
      <header className="top-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <img src={robotLogo} alt="Sphere Guard" style={{ width: '52px', height: '52px', borderRadius: '50%', objectFit: 'cover', border: `2px solid ${C.tan}` }} />
          <div>
            <h1 className="title">SG-02 Controller</h1>
            <p className="subtitle">Raspberry Pi • Sphere Guard</p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '12px' }}>
            <div className="connection-status">
              <span className={`status-dot ${isFirebaseConnected ? 'green' : 'red'}`}></span>
              DB: {isFirebaseConnected ? 'Connected' : 'Disconnected'}
            </div>
            <div className="connection-status">
              <span className="status-dot" style={{ backgroundColor: robotStatusColor }}></span>
              Pi: {robotStatusText}
            </div>
          </div>

          <Link to="/" style={{ textDecoration: 'none' }}>
            <button className="switch-btn active" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ArrowLeft size={16} /> Back to Fleet
            </button>
          </Link>
        </div>
      </header>

      {/* MAIN GRID */}
      <div className="dashboard-grid">

        {/* LEFT COLUMN */}
        <aside className="left-column">

          {/* Movement Control */}
          <div className="dark-panel">
            <h3>Movement Control</h3>
            <div className="control-label">Forward</div>
            <div className="speed-group">
              <button className={`btn-speed ${driveMode === 'fwd_slow' ? 'active-fwd' : ''}`} onClick={() => sendDriveCommand('fwd_slow')}>Slow</button>
              <button className={`btn-speed ${driveMode === 'fwd_med'  ? 'active-fwd' : ''}`} onClick={() => sendDriveCommand('fwd_med')}>Med</button>
              <button className={`btn-speed ${driveMode === 'fwd_fast' ? 'active-fwd' : ''}`} onClick={() => sendDriveCommand('fwd_fast')}>Fast</button>
            </div>

            <button className={`btn-stop-large ${driveMode === 'stop' ? 'active-stop' : ''}`} onClick={() => sendDriveCommand('stop')}>STOP</button>

            <div className="control-label">Backward</div>
            <div className="speed-group">
              <button className={`btn-speed ${driveMode === 'rev_slow' ? 'active-rev' : ''}`} onClick={() => sendDriveCommand('rev_slow')}>Slow</button>
              <button className={`btn-speed ${driveMode === 'rev_med'  ? 'active-rev' : ''}`} onClick={() => sendDriveCommand('rev_med')}>Med</button>
              <button className={`btn-speed ${driveMode === 'rev_fast' ? 'active-rev' : ''}`} onClick={() => sendDriveCommand('rev_fast')}>Fast</button>
            </div>

            <div className="slider-container" style={{ marginTop: '30px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', color: C.sage }}>
                <span>Left (0°)</span>
                <label style={{ color: C.text, fontWeight: 600 }}>Steering: {steering}°</label>
                <span>Right (180°)</span>
              </div>
              <input type="range" min="0" max="180" step="5" value={steering}
                onChange={(e) => setSteering(e.target.value)}
                onPointerUp={handleSteeringRelease} />
            </div>
          </div>

          {/* System Status */}
          <div className="dark-panel">
            <h3>System Status</h3>

            <div className="status-row">
              <span>Firebase</span>
              <span style={{ color: isFirebaseConnected ? C.sage : C.red, fontWeight: 600 }}>
                {isFirebaseConnected ? 'Connected' : 'Disconnected'}
              </span>
            </div>

            <div className="status-row">
              <span>Raspberry Pi</span>
              <span style={{ color: robotStatusColor, fontWeight: 'bold' }}>{robotStatusText}</span>
            </div>

            <div className="status-row">
              <span>MCU Temp</span>
              <span style={{ color: sensorData.mcuTemp > 65 ? C.red : C.sage, fontWeight: 600 }}>
                {sensorData.mcuTemp} °C
              </span>
            </div>

            <div className="status-row" style={{ marginTop: '15px', borderTop: `1px solid ${C.border}`, paddingTop: '10px' }}>
              <span>Signal (RSSI)</span>
              <span style={{ color: C.text }}>{sensorData.rssi} dBm</span>
            </div>

            <div className="status-row">
              <span>Obstacle Dist</span>
              <span style={{ color: sensorData.distance < 20 ? C.red : C.text, fontWeight: sensorData.distance < 20 ? 'bold' : 'normal' }}>
                {sensorData.distance} cm
              </span>
            </div>

            <div className="status-row">
              <span>Pitch Angle</span>
              <span style={{ color: C.text }}>{sensorData.pitch}°</span>
            </div>

            <div className="status-row" style={{ marginTop: '15px', borderTop: `1px solid ${C.border}`, paddingTop: '10px' }}>
              <span>Drive Mode</span>
              <span style={{ textTransform: 'uppercase', color: C.red, fontWeight: 600 }}>
                {driveMode.replace('_', ' ')}
              </span>
            </div>

            <div className="status-row">
              <span>Heading</span>
              <span style={{ color: C.text }}>{heading}°</span>
            </div>
          </div>

          {/* Inspection Logging */}
          <div className="dark-panel" style={{ border: activeSession ? `2px solid ${C.sage}` : `1px solid ${C.border}` }}>
            <h3>Inspection Logging</h3>

            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', fontSize: '12px', color: C.sage, marginBottom: '5px', fontWeight: 600 }}>Operator</label>
              <input type="text" value={operatorName} onChange={(e) => setOperatorName(e.target.value)}
                disabled={activeSession !== null} style={inputStyle} />
            </div>

            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', fontSize: '12px', color: C.sage, marginBottom: '5px', fontWeight: 600 }}>Duct Location</label>
              <input type="text" value={locationTag} onChange={(e) => setLocationTag(e.target.value)}
                disabled={activeSession !== null} style={inputStyle} />
            </div>

            {!activeSession ? (
              <button onClick={startInspectionSession} style={{
                width: '100%', padding: '12px', backgroundColor: C.sage, color: 'white',
                border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer',
                display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px', fontSize: '14px',
              }}>
                <Play size={18} /> Start Recording
              </button>
            ) : (
              <>
                <button onClick={stopInspectionSession} style={{
                  width: '100%', padding: '12px', backgroundColor: C.red, color: 'white',
                  border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer',
                  display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px', fontSize: '14px',
                }}>
                  <Square size={18} /> Stop Recording
                </button>
                <div style={{ marginTop: '12px', fontSize: '12px', color: C.sage, textAlign: 'center', wordBreak: 'break-all' }}>
                  🔴 Live: {activeSession}
                </div>
              </>
            )}
          </div>
        </aside>

        {/* RIGHT COLUMN */}
        <main className="right-column">

          {/* Robot Status Cards */}
          <h3 style={{ margin: '0 0 15px 0', color: C.sage, fontSize: '16px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '1px' }}>Robot Status</h3>
          <div className="sensor-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', gap: '15px', marginBottom: '24px' }}>

            <div className="light-card">
              <div className="card-header" style={{ marginBottom: '15px' }}>
                <span>Battery</span>
                <Battery size={18} color={C.sage} />
              </div>
              <div className="card-value">{sensorData.battery} <span className="unit">%</span></div>
            </div>

            <div className="light-card">
              <div className="card-header" style={{ marginBottom: '15px' }}>
                <span>Speed</span>
                <Gauge size={18} color={C.red} />
              </div>
              <div className="card-value">{sensorData.speed} <span className="unit">cm/s</span></div>
            </div>

            <div className="light-card">
              <div className="card-header" style={{ marginBottom: '15px' }}>
                <span>Internal Temp</span>
                <Thermometer size={18} color={C.tan} />
              </div>
              <div className="card-value">{sensorData.internalTemp} <span className="unit">°C</span></div>
            </div>

            <div className="light-card">
              <div className="card-header" style={{ marginBottom: '15px' }}>
                <span>MCU Temp</span>
                <Cpu size={18} color={C.red} />
              </div>
              <div className="card-value">{sensorData.mcuTemp} <span className="unit">°C</span></div>
            </div>

          </div>

          {/* Ducting Environment */}
          <h3 style={{ marginTop: '10px', marginBottom: '15px', color: C.sage, fontSize: '16px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '1px' }}>Ducting Environment</h3>
          <div className="sensor-grid" style={{ marginBottom: '30px' }}>

            <div className="dark-panel" style={{ padding: '15px', borderLeft: `4px solid ${C.sage}`, margin: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: C.sage, fontSize: '14px', marginBottom: '10px' }}>
                <span>Duct Temp</span><Thermometer size={16} color={C.sage} />
              </div>
              <div style={{ fontSize: '28px', fontWeight: 'bold', color: C.text }}>
                {sensorData.envTemp} <span style={{ fontSize: '14px', color: C.sage }}>°C</span>
              </div>
            </div>

            <div className="dark-panel" style={{ padding: '15px', borderLeft: `4px solid ${C.red}`, margin: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: C.sage, fontSize: '14px', marginBottom: '10px' }}>
                <span>Humidity</span><Droplets size={16} color={C.red} />
              </div>
              <div style={{ fontSize: '28px', fontWeight: 'bold', color: C.text }}>
                {sensorData.humidity} <span style={{ fontSize: '14px', color: C.sage }}>%</span>
              </div>
            </div>

            <div className="dark-panel" style={{ padding: '15px', borderLeft: `4px solid ${C.tan}`, margin: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: C.sage, fontSize: '14px', marginBottom: '10px' }}>
                <span>Gas (VOC)</span><Wind size={16} color={C.tan} />
              </div>
              <div style={{ fontSize: '28px', fontWeight: 'bold', color: C.text }}>
                {sensorData.voc} <span style={{ fontSize: '14px', color: C.sage }}>ppm</span>
              </div>
            </div>

            <div className="dark-panel" style={{ padding: '15px', borderLeft: `4px solid ${C.red}`, margin: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: C.sage, fontSize: '14px', marginBottom: '10px' }}>
                <span>Gas (CO2)</span><Wind size={16} color={C.red} />
              </div>
              <div style={{ fontSize: '28px', fontWeight: 'bold', color: C.text }}>
                {sensorData.co2} <span style={{ fontSize: '14px', color: C.sage }}>ppm</span>
              </div>
            </div>

          </div>

          {/* Charts */}
          {/* Status badge */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '12px',
            padding: '10px 16px', borderRadius: '8px', marginBottom: '16px',
            backgroundColor: isLive ? 'rgba(134,155,126,0.12)' : hasChartData ? 'rgba(201,202,172,0.2)' : 'rgba(201,202,172,0.1)',
            border: `1px solid ${isLive ? C.sage : C.tan}`,
            fontSize: '13px',
          }}>
            <span style={{
              width: '9px', height: '9px', borderRadius: '50%', flexShrink: 0,
              backgroundColor: isLive ? C.sage : hasChartData ? C.tan : '#ccc',
              boxShadow: isLive ? `0 0 0 3px rgba(134,155,126,0.25)` : 'none',
            }} />
            {isLive ? (
              <>
                <span style={{ color: C.sage, fontWeight: 600 }}>Live</span>
                <span style={{ color: C.sage }}>· Streaming sensor data</span>
                <span style={{ color: C.tan, marginLeft: 'auto' }}>{unifiedHistory.length} / 30 pts</span>
              </>
            ) : hasChartData ? (
              <>
                <span style={{ color: C.text, fontWeight: 600 }}>Last recorded reading</span>
                <span style={{ color: C.sage }}>· {lastKnownPoint?.time}</span>
                <span style={{ color: C.tan, marginLeft: 'auto', fontStyle: 'italic' }}>Robot {robotStatusText.toLowerCase()} — data frozen</span>
              </>
            ) : (
              <span style={{ color: C.sage }}>Awaiting first connection...</span>
            )}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

            {/* CO2 */}
            <div className="dark-panel" style={{ padding: '15px', opacity: isLive ? 1 : 0.75, transition: 'opacity 0.4s' }}>
              <h3 style={{ margin: '0 0 15px 0', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Wind size={20} color={C.red} /> Duct Gas Analysis (SCD41)
              </h3>
              {hasChartData ? (
                <div style={{ width: '100%', height: '250px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={C.chartGrid} vertical={false} />
                      <XAxis dataKey="time" stroke={C.chartAxis} fontSize={12} />
                      <YAxis stroke={C.red} fontSize={12} domain={['dataMin - 50', 'dataMax + 50']}
                        label={{ value: 'PPM', angle: -90, position: 'insideLeft', fill: C.sage, fontSize: 10 }} />
                      <Tooltip contentStyle={C.tooltip} />
                      <Legend />
                      <Line type="monotone" dataKey="co2" name="Duct CO2 (ppm)" stroke={C.red} strokeWidth={2} dot={false} isAnimationActive={false} />
                      {!isLive && <ReferenceLine y={lastKnownPoint?.co2} stroke={C.red} strokeDasharray="6 3"
                        label={{ value: `${lastKnownPoint?.co2} ppm`, fill: C.red, fontSize: 11, position: 'insideTopRight' }} />}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : <ChartEmpty />}
            </div>

            {/* Temperature */}
            <div className="dark-panel" style={{ padding: '15px', opacity: isLive ? 1 : 0.75, transition: 'opacity 0.4s' }}>
              <h3 style={{ margin: '0 0 15px 0', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Thermometer size={20} color={C.sage} /> Temperature (°C)
              </h3>
              {hasChartData ? (
                <div style={{ width: '100%', height: '250px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={C.chartGrid} vertical={false} />
                      <XAxis dataKey="time" stroke={C.chartAxis} fontSize={12} />
                      <YAxis stroke={C.sage} fontSize={12} domain={[15, 55]} />
                      <Tooltip contentStyle={C.tooltip} />
                      <Legend />
                      <Line type="monotone" dataKey="extTemp" name="Duct Temp (Ext)" stroke={C.sage} strokeWidth={2} dot={false} isAnimationActive={false} />
                      <Line type="monotone" dataKey="intTemp" name="Robot Temp (Int)" stroke={C.red} strokeWidth={2} strokeDasharray="5 5" dot={false} isAnimationActive={false} />
                      {!isLive && <ReferenceLine y={lastKnownPoint?.extTemp} stroke={C.sage} strokeDasharray="6 3"
                        label={{ value: `${lastKnownPoint?.extTemp}°C`, fill: C.sage, fontSize: 11, position: 'insideTopRight' }} />}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : <ChartEmpty />}
            </div>

            {/* Pressure */}
            <div className="dark-panel" style={{ padding: '15px', opacity: isLive ? 1 : 0.75, transition: 'opacity 0.4s' }}>
              <h3 style={{ margin: '0 0 15px 0', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Activity size={20} color={C.tan} /> Barometric Pressure (Internal)
              </h3>
              {hasChartData ? (
                <div style={{ width: '100%', height: '200px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={C.chartGrid} vertical={false} />
                      <XAxis dataKey="time" stroke={C.chartAxis} fontSize={12} />
                      <YAxis stroke={C.red} fontSize={12} domain={['dataMin - 5', 'dataMax + 5']} />
                      <Tooltip contentStyle={C.tooltip} />
                      <Line type="monotone" dataKey="pressure" name="Pressure (hPa)" stroke={C.red} strokeWidth={2} dot={false} isAnimationActive={false} />
                      {!isLive && <ReferenceLine y={lastKnownPoint?.pressure} stroke={C.red} strokeDasharray="6 3"
                        label={{ value: `${lastKnownPoint?.pressure} hPa`, fill: C.red, fontSize: 11, position: 'insideTopRight' }} />}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : <ChartEmpty />}
            </div>

            {/* Humidity */}
            <div className="dark-panel" style={{ padding: '15px', marginBottom: '24px', opacity: isLive ? 1 : 0.75, transition: 'opacity 0.4s' }}>
              <h3 style={{ margin: '0 0 15px 0', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Droplets size={20} color={C.sage} /> Humidity Comparison (%)
              </h3>
              {hasChartData ? (
                <div style={{ width: '100%', height: '250px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={C.chartGrid} vertical={false} />
                      <XAxis dataKey="time" stroke={C.chartAxis} fontSize={12} />
                      <YAxis stroke={C.sage} fontSize={12} domain={[0, 100]} />
                      <Tooltip contentStyle={C.tooltip} />
                      <Legend />
                      <Line type="monotone" dataKey="extHum" name="Duct Humidity (Ext)" stroke={C.sage} strokeWidth={2} dot={false} isAnimationActive={false} />
                      <Line type="monotone" dataKey="intHum" name="Robot Humidity (Int)" stroke={C.red} strokeWidth={2} strokeDasharray="5 5" dot={false} isAnimationActive={false} />
                      {!isLive && <ReferenceLine y={lastKnownPoint?.extHum} stroke={C.sage} strokeDasharray="6 3"
                        label={{ value: `${lastKnownPoint?.extHum}%`, fill: C.sage, fontSize: 11, position: 'insideTopRight' }} />}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : <ChartEmpty />}
            </div>

          </div>

          {/* All Sensor Readings */}
          <AllSensorsPanel
            title="All Sensor Readings"
            defaultUrl={import.meta.env.VITE_ROBOT_SG02_URL || ''}
            storageKey="sg02_robot_url"
            accent={C.sage}
          />

          {/* Camera Feed */}
          <div className="dark-panel" style={{ marginBottom: '24px', padding: '15px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
              <h3 style={{ margin: 0 }}>Live Camera Feed</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: cameraStatus === 'ONLINE' ? C.sage : C.red }}>
                <span className={`status-dot ${cameraStatus === 'ONLINE' ? 'green' : 'red'}`}></span>
                {cameraStatus}
              </div>
            </div>
            <div style={{
              width: '100%', height: '350px', backgroundColor: 'rgba(255,255,255,0.4)',
              borderRadius: '8px', border: `1px solid ${C.border}`, overflow: 'hidden',
              display: 'flex', justifyContent: 'center', alignItems: 'center',
            }}>
              {cameraStatus === 'ONLINE' && cameraUrl ? (
                <img src={cameraUrl} alt="SG02 Live Feed" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              ) : (
                <div style={{ color: C.sage, textAlign: 'center' }}>
                  <Camera size={48} style={{ marginBottom: '10px', opacity: 0.4 }} />
                  <p style={{ margin: 0 }}>Waiting for video stream connection...</p>
                </div>
              )}
            </div>
          </div>

          {/* System Log */}
          <div className="dark-panel terminal">
            <h3>System Log</h3>
            <p><span className="time">[3:38:24 PM]</span> <span className="info">INFO:</span> Connected to Raspberry Pi</p>
            <p><span className="time">[3:38:25 PM]</span> <span className="system">SYSTEM:</span> Waiting for PCA9685 driver...</p>
          </div>

        </main>
      </div>
    </div>
  );
}

export default DashboardSG02;
