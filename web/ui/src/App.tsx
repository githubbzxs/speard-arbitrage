import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import ApiConfigPage from "./pages/ApiConfigPage";
import TradePage from "./pages/TradePage";

function navClassName({ isActive }: { isActive: boolean }): string {
  return isActive ? "tab-item active" : "tab-item";
}

export default function App() {
  return (
    <div className="app-shell">
      <header className="panel topbar">
        <div className="brand">
          <h1>前端控制台</h1>
        </div>
      </header>

      <nav className="panel nav-tabs">
        <NavLink to="/trade" className={navClassName}>
          行情/下单页面
        </NavLink>
        <NavLink to="/api-config" className={navClassName}>
          API 配置页面
        </NavLink>
      </nav>

      <Routes>
        <Route path="/" element={<Navigate to="/trade" replace />} />
        <Route path="/market" element={<Navigate to="/trade" replace />} />
        <Route path="/trade" element={<TradePage />} />
        <Route path="/api-config" element={<ApiConfigPage />} />
      </Routes>
    </div>
  );
}
