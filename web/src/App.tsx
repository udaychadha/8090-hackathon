import {
  Component,
  useEffect,
  useState,
  type ErrorInfo,
  type ReactNode,
} from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Logo } from "./components/Logo";
import { ErrorState } from "./components/common";
import { RunPage, NewRunPage } from "./pages/Runs";
import { LeaderboardPage, TearsheetPage, GraveyardPage } from "./pages/Results";
import { EvalsPage } from "./pages/Evals";
import { DataPage } from "./pages/Data";

function stored(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function Header() {
  const [accent, setAccent] = useState(() => stored("arena-accent", "mono"));
  const [theme, setTheme] = useState(() => stored("arena-theme", "night"));
  const location = useLocation();
  useEffect(() => {
    document.documentElement.dataset.accent = accent;
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("arena-accent", accent);
      localStorage.setItem("arena-theme", theme);
    } catch {
      /* Preferences still work for this session. */
    }
  }, [accent, theme]);
  return (
    <header className="header">
      <div className="header-inner">
        <Link className="brand" to="/runs">
          <Logo />
          <span>Arena</span>
        </Link>
        <nav className="nav" aria-label="Primary">
          <NavLink to="/new">New run</NavLink>
          <NavLink to="/runs">Run</NavLink>
          <NavLink
            to="/leaderboard"
            aria-current={
              location.pathname.startsWith("/variants") ? "page" : undefined
            }
          >
            Leaderboard
          </NavLink>
          <NavLink to="/data">Data</NavLink>
          <NavLink to="/graveyard">Graveyard</NavLink>
          <NavLink to="/evals">Evals</NavLink>
        </nav>
        <div className="header-actions">
          <div className="accents" role="group" aria-label="Accent colour">
            {["mono", "iris", "sky"].map((value) => (
              <button
                key={value}
                className={`accent-button ${value}`}
                aria-label={`${value[0].toUpperCase() + value.slice(1)} accent`}
                aria-pressed={value === accent}
                title={`${value} accent`}
                onClick={() => setAccent(value)}
              >
                <span />
              </button>
            ))}
          </div>
          <button
            className="theme-button"
            aria-label={
              theme === "night"
                ? "Switch to light theme"
                : "Switch to dark theme"
            }
            title={theme === "night" ? "Light theme" : "Dark theme"}
            onClick={() => setTheme(theme === "night" ? "paper" : "night")}
          >
            {theme === "night" ? "☾" : "☼"}
          </button>
          <Link className="button" to="/new">
            ＋ New run
          </Link>
          <Link className="button primary" to="/new">
            ▷ Test in arena
          </Link>
        </div>
      </div>
    </header>
  );
}
class PageBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(
      "Interface rendering failed",
      error.message,
      info.componentStack,
    );
  }
  render() {
    return this.state.failed ? (
      <ErrorState
        message="This screen could not be displayed. Reload to read the recorded evidence again."
        retry={() => window.location.reload()}
      />
    ) : (
      this.props.children
    );
  }
}
export default function App() {
  const location = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);
  return (
    <>
      <Header />
      <main id="main">
        <PageBoundary key={location.pathname}>
          <Routes>
            <Route path="/" element={<RunPage />} />
            <Route path="/new" element={<NewRunPage />} />
            <Route path="/runs" element={<RunPage />} />
            <Route path="/runs/:runId" element={<RunPage />} />
            <Route path="/leaderboard" element={<LeaderboardPage />} />
            <Route path="/variants/:variantId" element={<TearsheetPage />} />
            <Route path="/graveyard" element={<GraveyardPage />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="/data" element={<DataPage />} />
            <Route
              path="*"
              element={
                <>
                  <h1>Page not found</h1>
                  <Link className="button" to="/runs">
                    Open run history
                  </Link>
                </>
              }
            />
          </Routes>
        </PageBoundary>
      </main>
      <footer className="footer">
        <span>FINANCIAL MODELS IN THE ARENA</span>
        <span>Backtest only · no orders · deterministic verdicts</span>
      </footer>
    </>
  );
}
