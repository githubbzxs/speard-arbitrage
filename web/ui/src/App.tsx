import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import ApiConfigPage from "./pages/ApiConfigPage";
import MarketPage from "./pages/MarketPage";
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
        <NavLink to="/market" className={navClassName}>
          行情页面
        </NavLink>
        <NavLink to="/trade" className={navClassName}>
          下单页面
        </NavLink>
        <NavLink to="/api-config" className={navClassName}>
          API 配置页面
        </NavLink>
      </nav>

      <Routes>
        <Route path="/" element={<Navigate to="/market" replace />} />
        <Route path="/market" element={<MarketPage />} />
        <Route path="/trade" element={<TradePage />} />
        <Route path="/api-config" element={<ApiConfigPage />} />
      </Routes>
    </div>
  );
}
