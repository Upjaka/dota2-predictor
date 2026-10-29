import { Link, Route, Routes } from "react-router-dom";
import ServiceStatus from "./components/ServiceStatus.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import GameDetailsPage from "./pages/GameDetailsPage.jsx";
import MatchDetailsPage from "./pages/MatchDetailsPage.jsx";
import NotFoundPage from "./pages/NotFoundPage.jsx";
import { useApiHealth } from "./hooks/useApiHealth.js";

export default function App() {
  const health = useApiHealth();

  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="site-header__inner">
          <Link className="brand" to="/" aria-label="Dota 2 Draftwatch — главная">
            <span className="brand__mark" aria-hidden="true">D</span>
            <span className="brand__name">
              DRAFT<span>WATCH</span>
            </span>
          </Link>
          <div className="site-header__right">
            <ServiceStatus health={health} />
          </div>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/matches/:matchId" element={<MatchDetailsPage />} />
        <Route path="/games/:gameId" element={<GameDetailsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>

      <footer className="site-footer">
        <span>DRAFTWATCH <span className="footer-separator">/</span> ПРОФЕССИОНАЛЬНАЯ СЦЕНА</span>
        <span>Вероятности — оценка модели, не гарантия результата.</span>
      </footer>
    </div>
  );
}
