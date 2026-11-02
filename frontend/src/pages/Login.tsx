import { useState } from "react";
import { errorMessage } from "../api";
import { useApp } from "../context";

const DEMO_PASSWORD = "demo1234";
const DEMO_LOGINS = [
  { email: "asha@demo.servicesaathi.local", title: "Customer", detail: "Book and manage home services", icon: "C" },
  { email: "provider01@demo.servicesaathi.local", title: "Ramesh Kulkarni", detail: "Service partner · Plumbing", icon: "P" },
  { email: "provider02@demo.servicesaathi.local", title: "Sunita Pawar", detail: "Service partner · Plumbing & appliances", icon: "P" },
  { email: "provider03@demo.servicesaathi.local", title: "Imran Shaikh", detail: "Service partner · Electrical", icon: "P" },
  { email: "admin@demo.servicesaathi.local", title: "Administrator", detail: "Explore the admin workspace", icon: "A" },
];

export default function Login() {
  const { signIn } = useApp();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function signInWith(loginEmail: string, loginPassword: string) {
    setBusy(true);
    setError("");
    try {
      await signIn(loginEmail, loginPassword);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await signInWith(email, password);
  }

  return (
    <div className="login">
      <section className="login-intro">
        <span className="login-eyebrow"><span className="login-eyebrow-dot" /> HOME SERVICES, MADE SIMPLE</span>
        <h1>Home help, without the hassle.</h1>
        <p>
          From a leaky tap to an appliance that needs attention, finding trusted local help starts with a few words.
        </p>
        <div className="login-services" aria-label="Service areas">
          <span>Plumbing</span><span>Electrical</span><span>Appliance repair</span>
        </div>
        <div className="login-promise">
          <div className="login-promise-heading">
            <span className="login-promise-icon" aria-hidden="true">✓</span>
            <div><strong>You're in control at every step</strong><span>Clear choices. No surprises.</span></div>
          </div>
          <ol className="login-steps">
            <li><span>01</span><div><strong>Tell us what needs fixing</strong><small>Use your own words—no forms to figure out.</small></div></li>
            <li><span>02</span><div><strong>Choose a local professional</strong><small>See available times and the visit charge.</small></div></li>
            <li><span>03</span><div><strong>Confirm when you're ready</strong><small>Your booking is only made with your approval.</small></div></li>
          </ol>
        </div>
        <p className="login-location">Serving Wakad · Hinjawadi · Baner · Aundh</p>
      </section>
      <form className="panel login-form" onSubmit={submit}>
        <div className="login-form-heading">
          <span className="login-form-kicker">WELCOME TO SERVICESAATHI</span>
          <h2>Sign in</h2>
          <p>Enter your account details to continue.</p>
        </div>
        <label className="field">
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username"
            placeholder="you@example.com" required />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password" placeholder="Enter your password" required />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary login-submit" disabled={busy}>{busy ? "Signing in…" : "Sign in to your account"}<span aria-hidden="true">→</span></button>

        <div className="login-demo">
          <div className="login-divider"><span>OR EXPLORE A DEMO</span></div>
          <p className="login-demo-intro">Choose a role to sign in instantly—no account setup needed.</p>
          <div className="demo-login-grid">
            {DEMO_LOGINS.map((demo) => (
              <button key={demo.email} type="button" className="demo-login-button" disabled={busy}
                onClick={() => { setEmail(demo.email); setPassword(DEMO_PASSWORD); signInWith(demo.email, DEMO_PASSWORD); }}>
                <span className="demo-login-icon" aria-hidden="true">{demo.icon}</span>
                <span className="demo-login-copy"><strong>{demo.title}</strong><small>{demo.detail}</small></span>
                <span className="demo-login-arrow" aria-hidden="true">→</span>
              </button>
            ))}
          </div>
          <p className="login-demo-note">Demo environment · Sample accounts and fictional service data</p>
        </div>
      </form>
    </div>
  );
}
