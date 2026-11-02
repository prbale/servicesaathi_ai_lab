import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { DevPanel } from "./components/DevPanel";
import { useApp } from "./context";
import Admin from "./pages/Admin";
import Customer, { MyBookings, PolicyAsk } from "./pages/Customer";
import Lab from "./pages/Lab";
import Login from "./pages/Login";
import Provider from "./pages/Provider";

const HOME = { customer: "/customer", provider: "/provider", admin: "/admin" } as const;

export default function App() {
  const { user, meta, signOut, devMode, setDevMode, ready } = useApp();
  if (!ready) return <div className="shell"><p className="main muted">Restoring your session…</p></div>;
  return (
    <div className={devMode && user ? "shell with-dev" : "shell"}>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span>ServiceSaathi <em>AI Lab</em></span>
        </div>
        {user && (
          <nav className="nav" aria-label="Main">
            {user.role === "customer" ? (
              <>
                <NavLink to="/customer" end>Book a service</NavLink>
                <NavLink to="/customer/bookings">My bookings</NavLink>
                <NavLink to="/customer/policies">Ask about policies</NavLink>
              </>
            ) : (
              <NavLink to={HOME[user.role]}>
                {user.role === "provider" ? "My jobs" : "Admin"}
              </NavLink>
            )}
            <NavLink to="/lab">Learning Lab</NavLink>
          </nav>
        )}
        {user && (
          <div className="topbar-right">
            <label className="switch">
              <input type="checkbox" checked={devMode} onChange={(e) => setDevMode(e.target.checked)} />
              <span>Developer mode</span>
            </label>
            <span className="who">{user.display_name}</span>
            <button className="ghost" onClick={signOut}>Sign out</button>
          </div>
        )}
      </header>
      <div className="demo-strip" role="note">
        {meta?.banner ?? "Learning demo — fictional providers and simulated bookings."}
      </div>
      <div className="body">
      <main className="main">
        <Routes>
          <Route path="/login" element={user ? <Navigate to={HOME[user.role]} /> : <Login />} />
          <Route path="/customer" element={<Guard role="customer"><Customer /></Guard>} />
          <Route path="/customer/bookings" element={<Guard role="customer"><MyBookings /></Guard>} />
          <Route path="/customer/policies" element={<Guard role="customer"><PolicyAsk /></Guard>} />
          <Route path="/provider" element={<Guard role="provider"><Provider /></Guard>} />
          <Route path="/admin" element={<Guard role="admin"><Admin /></Guard>} />
          <Route path="/lab/*" element={<Guard><Lab /></Guard>} />
          <Route path="*" element={<Navigate to={user ? HOME[user.role] : "/login"} />} />
        </Routes>
      </main>
      {devMode && user && <DevPanel />}
      </div>
    </div>
  );
}

function Guard({ role, children }: { role?: string; children: React.ReactNode }) {
  const { user } = useApp();
  if (!user) return <Navigate to="/login" />;
  if (role && user.role !== role)
    return (
      <div className="panel">
        <h2>This area is for {role} accounts</h2>
        <p>You are signed in as a {user.role}. The server would refuse these requests anyway.</p>
      </div>
    );
  return <>{children}</>;
}
