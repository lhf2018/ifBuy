import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { Ledger } from './pages/Ledger'
import { Markets } from './pages/Markets'
import { Trade } from './pages/Trade'
import { Settings } from './pages/Settings'

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          IfBuy <span>Paper Desk</span>
        </div>
        <nav className="nav-links">
          <NavLink to="/" end>
            账本
          </NavLink>
          <NavLink to="/markets">行情</NavLink>
          <NavLink to="/settings">设置</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Ledger />} />
          <Route path="/ledger" element={<Navigate to="/" replace />} />
          <Route path="/markets" element={<Markets />} />
          <Route path="/watchlist" element={<Markets />} />
          <Route path="/trade/:symbol" element={<Trade />} />
          <Route path="/positions" element={<Navigate to="/?tab=positions" replace />} />
          <Route path="/orders" element={<Navigate to="/?tab=orders" replace />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/home" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
