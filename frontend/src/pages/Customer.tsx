import { useEffect, useState } from "react";
import { api, ApiError, errorMessage, newIdempotencyKey } from "../api";
import { Empty, PolicyAnswer, Provenance, SafetyNotice, StatusPill, Tabs, Ticket } from "../components/common";
import { useApp } from "../context";

type Tab = "book" | "bookings" | "policy";

export default function Customer() {
  const [tab, setTab] = useState<Tab>("book");
  return (
    <div className="page">
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "book", label: "Book a service" },
        { id: "bookings", label: "My bookings" },
        { id: "policy", label: "Ask about policies" },
      ]} />
      {tab === "book" && <BookFlow onBooked={() => undefined} />}
      {tab === "bookings" && <MyBookings />}
      {tab === "policy" && <PolicyAsk />}
    </div>
  );
}

const EXAMPLE = "My kitchen tap is leaking. I need a plumber tomorrow morning in Wakad.";

function BookFlow({ onBooked }: { onBooked: () => void }) {
  const { meta } = useApp();
  const [text, setText] = useState("");
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [choice, setChoice] = useState<{ tech: any; slot: any } | null>(null);
  const [booked, setBooked] = useState<any>(null);

  async function interpret(nextOverrides = overrides) {
    if (text.trim().length < 3) return setError("Describe the problem in a few words first.");
    setBusy(true);
    setError("");
    setChoice(null);
    try {
      setResult(await api("/api/requests/interpret", { body: { text, overrides: nextOverrides } }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function setField(field: string, value: string) {
    const next = { ...overrides, [field]: value };
    setOverrides(next);
    interpret(next);
  }

  function restart() {
    setText("");
    setOverrides({});
    setResult(null);
    setChoice(null);
    setBooked(null);
  }

  if (booked)
    return (
      <div className="done">
        <Ticket booking={booked} />
        <div className="row">
          <button className="primary" onClick={restart}>Book another service</button>
        </div>
      </div>
    );

  const ex = result?.extraction;
  return (
    <div className="split">
      <section className="panel request">
        <h2>What needs fixing?</h2>
        <p className="muted">Write it the way you would tell a neighbour. Mention the area and when suits you.</p>
        <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder={EXAMPLE}
          aria-label="Describe your problem" />
        <div className="row">
          <button className="primary" disabled={busy} onClick={() => { setOverrides({}); interpret({}); }}>
            {busy ? "Reading your request…" : "Find a technician"}
          </button>
          {!text && <button className="ghost" onClick={() => setText(EXAMPLE)}>Use the example</button>}
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {ex && <SafetyNotice text={ex.safety_notice} />}
        {ex?.questions?.length > 0 && (
          <div className="questions">
            {ex.questions.map((q: any) => (
              <div key={q.field} className="question">
                <p>{q.question}</p>
                {q.options.length ? (
                  <div className="chips">
                    {q.options.map((o: any) => (
                      <button key={o.value} className="chip" onClick={() => setField(q.field, o.value)}>{o.label}</button>
                    ))}
                  </div>
                ) : (
                  <FreeAnswer onSubmit={(v) => setField(q.field, v)} />
                )}
              </div>
            ))}
          </div>
        )}
        {ex?.notes?.map((n: string) => <p key={n} className="notice">{n}</p>)}
      </section>

      <section className="panel jobcard" aria-label="Your request">
        <h2>Your request</h2>
        {!ex ? (
          <Empty>Your details appear here once we read your request. You can correct anything before booking.</Empty>
        ) : (
          <>
            <p className="method">{ex.method_label}</p>
            <JobCard ex={ex} meta={meta} onEdit={setField} />
          </>
        )}
      </section>

      {result?.ready && (
        <section className="panel results">
          <h2>Available technicians</h2>
          {result.search.widened && <p className="notice">{result.search.widened}</p>}
          <p className="muted">{result.search.charges_note}</p>
          {result.search.technicians.length === 0 ? (
            <Empty>No free slots in the next 7 days for this service and area. Try another area or day.</Empty>
          ) : (
            <ul className="techs">
              {result.search.technicians.map((t: any) => (
                <li key={t.technician_id} className="tech">
                  <div className="tech-head">
                    <strong>{t.name}</strong>
                    <span className="charge">₹{t.visiting_charge_inr} visit</span>
                  </div>
                  <ul className="reasons">{t.match_reasons.map((r: string) => <li key={r}>{r}</li>)}</ul>
                  <div className="slots">
                    {t.slots.slice(0, 8).map((s: any) => (
                      <button key={s.slot_id}
                        className={choice?.slot.slot_id === s.slot_id ? "slot on" : "slot"}
                        onClick={() => setChoice({ tech: t, slot: s })}>{s.label}</button>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {choice && ex && (
        <Confirm ex={ex} choice={choice} onCancel={() => setChoice(null)}
          onBooked={(b) => { setBooked(b); onBooked(); }}
          onPickAlternative={(tech, slot) => setChoice({ tech, slot })} />
      )}
    </div>
  );
}

function FreeAnswer({ onSubmit }: { onSubmit: (v: string) => void }) {
  const [v, setV] = useState("");
  return (
    <div className="row">
      <input value={v} onChange={(e) => setV(e.target.value)} aria-label="Your answer" />
      <button className="ghost" onClick={() => v.trim() && onSubmit(v.trim())}>Add</button>
    </div>
  );
}

function JobCard({ ex, meta, onEdit }: { ex: any; meta: any; onEdit: (f: string, v: string) => void }) {
  const [editing, setEditing] = useState<string | null>(null);
  const days = Array.from({ length: 8 }, (_, i) => {
    const d = new Date(meta.today + "T00:00:00");
    d.setDate(d.getDate() + i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    return { value: iso, label: d.toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short" }) };
  });
  const rows = [
    { f: "issue_description", label: "Problem", show: ex.issue_description.value },
    { f: "predicted_category", label: "Service", show: ex.predicted_category.display },
    { f: "locality", label: "Area", show: ex.locality.display },
    { f: "preferred_date", label: "Day", show: ex.preferred_date.display },
    { f: "time_window", label: "Time", show: ex.time_window.display },
  ];
  function editor(f: string) {
    const commit = (v: string) => { setEditing(null); if (v) onEdit(f, v); };
    if (f === "issue_description")
      return <EditText initial={ex.issue_description.value ?? ""} onDone={commit} />;
    const opts = f === "predicted_category" ? meta.categories.map((c: any) => ({ value: c.code, label: c.name }))
      : f === "locality" ? meta.localities.map((l: any) => ({ value: l.code, label: l.name }))
      : f === "preferred_date" ? days
      : ["morning", "afternoon", "evening", "any"].map((w) => ({ value: w, label: w }));
    return (
      <select autoFocus defaultValue="" onChange={(e) => commit(e.target.value)} onBlur={() => setEditing(null)}>
        <option value="" disabled>Choose…</option>
        {opts.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }
  return (
    <dl className="card-rows">
      {rows.map((r) => (
        <div key={r.f} className={ex[r.f].value ? "card-row" : "card-row missing"}>
          <dt>{r.label}</dt>
          <dd>
            {editing === r.f ? editor(r.f) : <span className="val">{r.show ?? "—"}</span>}
            <Provenance f={ex[r.f]} />
          </dd>
          {editing !== r.f && <button className="link" onClick={() => setEditing(r.f)}>Change</button>}
        </div>
      ))}
    </dl>
  );
}

function EditText({ initial, onDone }: { initial: string; onDone: (v: string) => void }) {
  const [v, setV] = useState(initial);
  return (
    <span className="row">
      <input autoFocus value={v} onChange={(e) => setV(e.target.value)} aria-label="Problem description" />
      <button className="ghost" onClick={() => onDone(v.trim())}>Save</button>
    </span>
  );
}

function Confirm({ ex, choice, onCancel, onBooked, onPickAlternative }: {
  ex: any; choice: { tech: any; slot: any }; onCancel: () => void; onBooked: (b: any) => void;
  onPickAlternative: (tech: any, slot: any) => void;
}) {
  // One key per summary: a double-click or network retry cannot create two bookings.
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { setKey(newIdempotencyKey()); setError(""); }, [choice.slot.slot_id]);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      const r = await api("/api/bookings", {
        headers: { "Idempotency-Key": key },
        body: {
          slot_id: choice.slot.slot_id, technician_id: choice.tech.technician_id,
          category: ex.predicted_category.value, locality: ex.locality.value,
          issue_description: ex.issue_description.value,
        },
      });
      onBooked(r.booking);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail?.code === "slot_taken") setConflict(e.detail);
      else setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel confirm" aria-label="Review and confirm">
      <h2>Review and confirm</h2>
      <dl className="ticket-grid">
        <dt>Technician</dt><dd>{choice.tech.name}</dd>
        <dt>Visit</dt><dd>{choice.slot.label} (one hour)</dd>
        <dt>Service</dt><dd>{ex.predicted_category.display} in {ex.locality.display}</dd>
        <dt>Problem</dt><dd>{ex.issue_description.value}</dd>
        <dt>Visiting charge</dt><dd>₹{choice.tech.visiting_charge_inr}</dd>
      </dl>
      <p className="muted small">
        The visiting charge covers the visit and diagnosis. The repair is quoted separately after diagnosis.
        Nothing is reserved until you confirm.
      </p>
      {conflict && (
        <div className="conflict" role="alert">
          <p><strong>{conflict.message}</strong></p>
          {conflict.alternatives?.length ? conflict.alternatives.map((t: any) => (
            <div key={t.technician_id} className="alt">
              <span>{t.name} · ₹{t.visiting_charge_inr}</span>
              <div className="slots">
                {t.slots.slice(0, 4).map((s: any) => (
                  <button key={s.slot_id} className="slot" onClick={() => { setConflict(null); onPickAlternative(t, s); }}>{s.label}</button>
                ))}
              </div>
            </div>
          )) : <p>No other free slots that day. Try another day.</p>}
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="row">
        <button className="primary" disabled={busy || !!conflict} onClick={confirm}>
          {busy ? "Confirming…" : "Confirm booking"}
        </button>
        <button className="ghost" onClick={onCancel}>Choose another slot</button>
      </div>
    </section>
  );
}

function MyBookings() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const load = () => api("/api/bookings/mine").then((r) => setRows(r.bookings)).catch((e) => setError(errorMessage(e)));
  useEffect(() => { load(); }, []);
  async function cancel(id: number) {
    if (!window.confirm("Cancel this booking? The slot will be released for others.")) return;
    try {
      await api(`/api/bookings/${id}/cancel`, { method: "POST" });
      load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p className="muted">Loading bookings…</p>;
  if (!rows.length) return <Empty>No bookings yet. Describe a problem on the “Book a service” tab to make one.</Empty>;
  return (
    <ul className="booking-list">
      {rows.map((b) => (
        <li key={b.id} className="panel booking">
          <div className="tech-head">
            <strong>{b.reference}</strong>
            <StatusPill status={b.status} />
          </div>
          <p>{b.technician?.name} · {b.slot.label} · {b.category} in {b.locality} · ₹{b.visiting_charge_inr} visit</p>
          <p className="muted">“{b.issue_description}”</p>
          <ol className="history">
            {b.history.map((h: any, i: number) => (
              <li key={i}>{(h.to as string).replace(/_/g, " ")} <small>{new Date(h.at).toLocaleString("en-IN")}</small></li>
            ))}
          </ol>
          {b.can_cancel && <button className="ghost danger" onClick={() => cancel(b.id)}>Cancel booking</button>}
          {b.status === "confirmed" && !b.can_cancel && (
            <p className="muted small">Online cancellation closes 2 hours before the visit.</p>
          )}
        </li>
      ))}
    </ul>
  );
}

const SAMPLE_QUESTIONS = [
  "How late can I cancel my booking for free?",
  "Does the visiting charge include spare parts?",
  "Do you service air conditioners?",
  "How much does an electrician charge?",
];

function PolicyAsk() {
  const [q, setQ] = useState("");
  const [out, setOut] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function ask(question = q) {
    if (question.trim().length < 3) return;
    setQ(question);
    setBusy(true);
    setError("");
    try {
      setOut(await api("/api/policy/ask", { body: { question } }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel narrow">
      <h2>Ask about charges, cancellations, coverage or safety</h2>
      <p className="muted">Answers come only from the (fictional) demo policies, with sources. Live prices and free slots come from the booking system.</p>
      <form className="row" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type a question" aria-label="Question" />
        <button className="primary" disabled={busy}>{busy ? "Looking…" : "Ask"}</button>
      </form>
      <div className="chips">
        {SAMPLE_QUESTIONS.map((s) => <button key={s} className="chip" onClick={() => ask(s)}>{s}</button>)}
      </div>
      {error && <p className="error">{error}</p>}
      {out && <PolicyAnswer out={out} />}
    </section>
  );
}
