import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Lock, Unlock } from 'lucide-react';
import robotLogo from '../assets/robot_illustration.jpg';

const COLORS = {
  red: '#7F2020',
  redHover: '#9a2828',
  sage: '#869B7E',
  tan: '#C9CAAC',
  cream: '#F6F3EB',
  textDark: '#2a1010',
};

const bgStyle = {
  minHeight: '100vh',
  background: `linear-gradient(145deg, ${COLORS.cream} 0%, ${COLORS.tan} 55%, ${COLORS.sage} 100%)`,
  display: 'flex',
  flexDirection: 'column',
};

const cardStyle = {
  backgroundColor: 'rgba(255, 255, 255, 0.72)',
  backdropFilter: 'blur(12px)',
  WebkitBackdropFilter: 'blur(12px)',
  borderRadius: '16px',
  border: `1px solid ${COLORS.tan}`,
  boxShadow: '0 8px 32px rgba(127, 32, 32, 0.10)',
};

function Home() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState('');

  const handleLogin = (e) => {
    e.preventDefault();
    if (username === 'admin' && password === 'reka123') {
      setIsAuthenticated(true);
      setErrorMsg('');
    } else {
      setErrorMsg('Invalid username or password.');
      setPassword('');
    }
  };

  if (!isAuthenticated) {
    return (
      <div style={bgStyle}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>

          {/* Branding above the card */}
          <div style={{ textAlign: 'center', marginBottom: '32px' }}>
            <img src={robotLogo} alt="Sphere Guard" style={{ width: '90px', height: '90px', borderRadius: '50%', objectFit: 'cover', border: `3px solid ${COLORS.tan}`, marginBottom: '14px', boxShadow: '0 4px 16px rgba(127,32,32,0.15)' }} />
            <h1 style={{ margin: 0, fontSize: '36px', fontWeight: '800', color: COLORS.red, letterSpacing: '-0.5px' }}>
              Sphere Guard
            </h1>
            <p style={{ margin: '6px 0 0', fontSize: '14px', color: COLORS.sage, fontWeight: 500 }}>
              Fleet Management System
            </p>
          </div>

          {/* Login card */}
          <div style={{ ...cardStyle, width: '100%', maxWidth: '400px', padding: '40px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: '28px' }}>
              <div style={{ width: '44px', height: '44px', borderRadius: '10px', backgroundColor: COLORS.red, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '14px' }}>
                <Lock size={22} color="white" />
              </div>
              <h2 style={{ margin: 0, fontSize: '20px', fontWeight: '700', color: COLORS.textDark }}>Sign in to continue</h2>
              <p style={{ margin: '6px 0 0', fontSize: '13px', color: COLORS.sage }}>Restricted access — authorised personnel only</p>
            </div>

            <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <input
                type="text"
                placeholder="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                style={{
                  padding: '12px 14px',
                  borderRadius: '8px',
                  border: `2px solid ${COLORS.tan}`,
                  backgroundColor: COLORS.cream,
                  color: COLORS.textDark,
                  fontSize: '14px',
                  outline: 'none',
                  width: '100%',
                  boxSizing: 'border-box',
                  transition: 'border-color 0.2s',
                }}
                onFocus={(e) => e.target.style.borderColor = COLORS.red}
                onBlur={(e) => e.target.style.borderColor = COLORS.tan}
              />

              <input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                style={{
                  padding: '12px 14px',
                  borderRadius: '8px',
                  border: `2px solid ${COLORS.tan}`,
                  backgroundColor: COLORS.cream,
                  color: COLORS.textDark,
                  fontSize: '14px',
                  outline: 'none',
                  width: '100%',
                  boxSizing: 'border-box',
                  transition: 'border-color 0.2s',
                }}
                onFocus={(e) => e.target.style.borderColor = COLORS.red}
                onBlur={(e) => e.target.style.borderColor = COLORS.tan}
              />

              {errorMsg && (
                <p style={{ color: COLORS.red, fontSize: '13px', margin: 0, textAlign: 'center', fontWeight: 500 }}>
                  {errorMsg}
                </p>
              )}

              <button
                type="submit"
                style={{
                  marginTop: '6px',
                  padding: '13px',
                  backgroundColor: COLORS.red,
                  color: 'white',
                  border: 'none',
                  borderRadius: '8px',
                  fontWeight: '700',
                  fontSize: '15px',
                  cursor: 'pointer',
                  letterSpacing: '0.3px',
                  transition: 'background-color 0.2s',
                }}
                onMouseOver={(e) => e.target.style.backgroundColor = COLORS.redHover}
                onMouseOut={(e) => e.target.style.backgroundColor = COLORS.red}
              >
                Sign In
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={bgStyle}>
      {/* Top bar */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '20px 40px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <img src={robotLogo} alt="Sphere Guard" style={{ width: '38px', height: '38px', borderRadius: '50%', objectFit: 'cover', border: `2px solid ${COLORS.tan}` }} />
          <div>
            <span style={{ fontSize: '18px', fontWeight: '800', color: COLORS.red, letterSpacing: '-0.3px' }}>Sphere Guard</span>
            <span style={{ fontSize: '13px', color: COLORS.sage, marginLeft: '10px' }}>Fleet Manager</span>
          </div>
        </div>
        <button
          onClick={() => setIsAuthenticated(false)}
          style={{
            background: 'rgba(255,255,255,0.5)',
            border: `1px solid ${COLORS.tan}`,
            color: COLORS.red,
            padding: '8px 16px',
            borderRadius: '8px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '7px',
            fontWeight: '600',
            fontSize: '13px',
            backdropFilter: 'blur(4px)',
            transition: 'background 0.2s',
          }}
          onMouseOver={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.75)'}
          onMouseOut={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.5)'}
        >
          <Unlock size={14} /> Lock System
        </button>
      </header>

      {/* Hero */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '20px 20px 80px' }}>
        <h1 style={{ margin: '0 0 12px', fontSize: '52px', fontWeight: '800', color: COLORS.red, textAlign: 'center', letterSpacing: '-1px' }}>
          Fleet Overview
        </h1>
        <p style={{ margin: '0 0 60px', fontSize: '17px', color: COLORS.sage, textAlign: 'center', maxWidth: '480px', lineHeight: 1.6 }}>
          Select a spherical ducting inspection robot to connect, monitor, and operate.
        </p>

        {/* Robot cards */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: '28px', flexWrap: 'wrap' }}>

          {/* SG-01 */}
          <Link to="/sg01" style={{ textDecoration: 'none' }}>
            <div
              style={{
                ...cardStyle,
                width: '280px',
                padding: '32px 28px',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.transform = 'translateY(-6px)';
                e.currentTarget.style.border = `1px solid ${COLORS.red}`;
                e.currentTarget.style.boxShadow = `0 16px 40px rgba(127, 32, 32, 0.18)`;
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.transform = 'translateY(0)';
                e.currentTarget.style.border = `1px solid ${COLORS.tan}`;
                e.currentTarget.style.boxShadow = '0 8px 32px rgba(127, 32, 32, 0.10)';
              }}
            >
              <div style={{ width: '44px', height: '44px', borderRadius: '10px', backgroundColor: COLORS.red, marginBottom: '18px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ color: 'white', fontWeight: '800', fontSize: '13px' }}>SG</span>
              </div>
              <h2 style={{ color: COLORS.red, margin: '0 0 8px', fontSize: '26px', fontWeight: '800' }}>SG-01</h2>
              <p style={{ margin: '0 0 6px', color: COLORS.textDark, fontSize: '14px', opacity: 0.7 }}>Controller: Raspberry Pi</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '14px' }}>
                <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: COLORS.sage }}></div>
                <span style={{ fontSize: '13px', color: COLORS.sage, fontWeight: '600' }}>Ready</span>
              </div>
            </div>
          </Link>

          {/* SG-02 */}
          <Link to="/sg02" style={{ textDecoration: 'none' }}>
            <div
              style={{
                ...cardStyle,
                width: '280px',
                padding: '32px 28px',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.transform = 'translateY(-6px)';
                e.currentTarget.style.border = `1px solid ${COLORS.sage}`;
                e.currentTarget.style.boxShadow = `0 16px 40px rgba(134, 155, 126, 0.25)`;
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.transform = 'translateY(0)';
                e.currentTarget.style.border = `1px solid ${COLORS.tan}`;
                e.currentTarget.style.boxShadow = '0 8px 32px rgba(127, 32, 32, 0.10)';
              }}
            >
              <div style={{ width: '44px', height: '44px', borderRadius: '10px', backgroundColor: COLORS.sage, marginBottom: '18px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ color: 'white', fontWeight: '800', fontSize: '13px' }}>SG</span>
              </div>
              <h2 style={{ color: COLORS.sage, margin: '0 0 8px', fontSize: '26px', fontWeight: '800' }}>SG-02</h2>
              <p style={{ margin: '0 0 6px', color: COLORS.textDark, fontSize: '14px', opacity: 0.7 }}>Controller: Raspberry Pi</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '14px' }}>
                <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: COLORS.sage }}></div>
                <span style={{ fontSize: '13px', color: COLORS.sage, fontWeight: '600' }}>Ready</span>
              </div>
            </div>
          </Link>

        </div>
      </div>
    </div>
  );
}

export default Home;
