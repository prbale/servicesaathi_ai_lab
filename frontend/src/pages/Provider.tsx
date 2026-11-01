import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { Empty, StatusPill, Tabs } from "../components/common";
import { useApp } from "../context";

type Tab = "jobs" | "slots";
const LABEL: Record<string, string> = {
  en_route: "Mark on the way", in_progress: "Start work", completed: "Mark completed",
  cancelled_by_provider: "Cancel (I can't attend)",
};

export default function Provider() {
  const [tab, setTab] = useState<Tab>("jobs");
  const [me, setMe] = useState<any>(null);
  useEffect(() => { api("/api/provider/me").then(setMe).catch(() => undefined); }, []);
  return (
    <div className="page">
      {me && (
        <p className="muted">
          {me.name} · {me.categories.map((c: any) => `${c.code} ₹${c.visiting_charge_inr}`).join(", ")} · serves{" "}
          {me.localities.join(", ")}
        </p>
      )}
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: "jobs", label: "Assigned bookings" }, { id: "slots", label: "My slots" }]} />
      {tab === "jobs" ? <Jobs /> : <Slots />}
    </div>
  );
}

function Jobs() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const load = () => api("/api/provider/bookings").then((r) => setRows(r.bookings)).catch((e) => setError(errorMessage(e)));
  useEffect(() => { load(); }, []);
  async function move(id: number, to: string) {
    setError("");
    try {
      await api(`/api/provider/bookings/${id}/status`, { body: { to_status: to, reason: "" } });
      load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  if (!rows) return <p className="muted">Loading…</p>;
  return (
    <>
      {error && <p className="error" role="alert">{error}</p>}
      {!rows.length ? <Empty>No bookings assigned to you yet. They appear here when a customer confirms one of your slots.</Empty> : (
        <ul className="booking-list">
          {rows.map((b) => (
            <li key={b.id} className="panel booking">
              <div className="tech-head"><strong>{b.reference}</strong><StatusPill status={b.status} /></div>
              <p>{b.slot.label} · {b.category} in {b.locality} · ₹{b.visiting_charge_inr} visit</p>
              <p className="muted">“{b.issue_description}”</p>
              <div className="row">
                {b.allowed_transitions.map((t: string) => (
                  <button key={t} className={t.startsWith("cancel") ? "ghost danger" : "ghost"} onClick={() => move(b.id, t)}>{LABEL[t] ?? t}</button>
                ))}
                {!b.allowed_transitions.length && <span className="muted small">No further changes allowed.</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Slots() {
  const { meta } = useApp();
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const [date, setDate] = useState(meta?.today ?? "");
  const [hour, setHour] = useState(9);
  const load = () => api("/api/provider/slots").then((r) => setRows(r.slots)).catch((e) => setError(errorMessage(e)));
  useEffect(() => { load(); }, []);
  async function run(fn: () => Promise<any>) {
    setError("");
    try { await fn(); load(); } catch (e) { setError(errorMessage(e)); }
  }
  return (
    <section className="panel">
      <h2>Publish a one-hour slot</h2>
      <div className="row">
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Date" />
        <select value={hour} onChange={(e) => setHour(+e.target.value)} aria-label="Start hour">
          {Array.from({ length: 16 }, (_, i) => i + 6).map((h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
        </select>
        <button className="primary" onClick={() => run(() => api("/api/provider/slots", { body: { date, hour } }))}>Add slot</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <p className="muted small">Slots with an active booking are locked: the database refuses to move or delete them.</p>
      {!rows ? <p className="muted">Loading…</p> : !rows.length ? <Empty>No future slots. Add one above.</Empty> : (
        <table className="table">
          <thead><tr><th>Slot</th><th>State</th><th /></tr></thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.slot_id}>
                <td>{s.label}</td>
                <td>{s.locked ? `Booked (${s.booking_reference})` : s.is_withdrawn ? "Withdrawn" : "Free"}</td>
                <td>
                  {!s.locked && !s.is_withdrawn && (
                    <button className="link" onClick={() => run(() => api(`/api/provider/slots/${s.slot_id}`, { method: "DELETE" }))}>Remove</button>
                  )}
                  {s.locked && (
                    <button className="link" title="Try it: the server will refuse"
                      onClick={() => run(() => api(`/api/provider/slots/${s.slot_id}`, { method: "DELETE" }))}>Try removing</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
