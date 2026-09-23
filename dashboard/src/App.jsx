import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Home from './pages/Home';
import DashboardSG01 from './pages/DashboardSG01';
import DashboardSG02 from './pages/DashboardSG02';
import './App.css';

function App() {
  return (
    <Router>
      <Routes>
        {/* The landing page */}
        <Route path="/" element={<Home />} />
        
        {/* The individual robot pages */}
        <Route path="/sg01" element={<DashboardSG01 />} />
        <Route path="/sg02" element={<DashboardSG02 />} />
      </Routes>
    </Router>
  );
}

export default App;