import { useState } from "react";
import { errorMessage } from "../api";
import { useApp } from "../context";

const ACCOUNTS = [
  { email: "asha@demo.servicesaathi.local", label: "Asha", role: "Customer" },
  { email: "rohan@demo.servicesaathi.local", label: "Rohan", role: "Customer" },
  { email: "provider01@demo.servicesaathi.local", label: "Ramesh Kulkarni", role: "Provider (plumber)" },
  { email: "provider03@demo.servicesaathi.local", label: "Imran Shaikh", role: "Provider (electrician)" },
  { email: "admin@demo.servicesaathi.local", label: "Demo admin", role: "Admin" },
];

export default function Login() {
  const { signIn, meta } = useApp();
  const [email, setEmail] = useState(ACCOUNTS[0].email);
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signIn(email, password);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <section className="login-intro">
        <h1>Home repairs in Wakad, Hinjawadi, Baner and Aundh — booked from one sentence.</h1>
        <p>
          Describe the problem in your own words. A trained classifier picks the trade, the database finds a
          free technician, and nothing is booked until you confirm.
        </p>
        <p className="muted">
          AI mode: {meta?.ai.llm_enabled ? `hosted LLM (${meta.ai.llm_provider})` : "no hosted LLM — rules-based extraction and retrieval-only policy excerpts"}.
        </p>
      </section>
      <form className="panel login-form" onSubmit={submit}>
        <h2>Sign in to a demo account</h2>
        <fieldset className="account-picks">
          <legend>Demo accounts (password demo1234)</legend>
          {ACCOUNTS.map((a) => (
            <label key={a.email} className={email === a.email ? "pick on" : "pick"}>
              <input type="radio" name="acct" checked={email === a.email} onChange={() => setEmail(a.email)} />
              <span>{a.label}</span>
              <small>{a.role}</small>
            </label>
          ))}
        </fieldset>
        <label className="field">
          <span>Email</span>
          <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="muted small">
          Roles are checked by the server on every request. Picking an account here is just a shortcut for the
          demo credentials.
        </p>
      </form>
    </div>
  );
}
