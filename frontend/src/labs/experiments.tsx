import { useEffect, useState } from "react";
import { api, errorMessage, rawCall } from "../api";
import { Json, PolicyAnswer, Provenance, StatusPill } from "../components/common";
import { TraceView } from "../components/TraceView";
import { useApp } from "../context";

function useRun() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError("");
    try {
      return await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run };
}

// ------------------------------------------------------------------ 1. Python & API
export function ApiLab() {
  const { meta } = useApp();
  const tomorrow = meta ? new Date(new Date(meta.today + "T00:00:00").getTime() + 864e5).toISOString().slice(0, 10) : "";
  const presets = {
    valid: JSON.stringify({ category: "plumbing", locality: "wakad", preferred_date: tomorrow, time_window: "morning" }, null, 2),
    invalid: JSON.stringify({ category: "carpentry", locality: "wakad", preferred_date: "next week" }, null, 2),
  };
  const [body, setBody] = useState(presets.valid);
  const [res, setRes] = useState<any>(null);
  const [auth, setAuth] = useState(true);
  async function send() {
    const r = auth ? await rawCall("POST", "/api/technicians/search", body)
      : await fetch("/api/technicians/search", { method: "POST", headers: { "Content-Type": "application/json" }, body })
        .then(async (x) => ({ status: x.status, ms: 0, headers: {}, body: await x.text() }));
    setRes(r);
  }
  let pretty = res?.body;
  try { pretty = JSON.stringify(JSON.parse(res.body), null, 2); } catch { /* not JSON */ }
  return (
    <div className="exp-grid">
      <div>
        <p className="small"><code>POST /api/technicians/search</code></p>
        <div className="row">
          <button className="chip" onClick={() => setBody(presets.valid)}>Valid body</button>
          <button className="chip" onClick={() => setBody(presets.invalid)}>Invalid body</button>
          <label className="chip"><input type="checkbox" checked={auth} onChange={(e) => setAuth(e.target.checked)} /> Send bearer token</label>
        </div>
        <textarea className="code-input" rows={9} value={body} onChange={(e) => setBody(e.target.value)} aria-label="Request body" />
        <button className="primary" onClick={send}>Send request</button>
      </div>
      <div>
        {res ? (
          <>
            <p><strong>HTTP {res.status}</strong> {res.ms ? `· ${res.ms} ms` : ""}</p>
            <pre className="code tall">{pretty}</pre>
          </>
        ) : <p className="muted">The raw response appears here.</p>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ 2. SQL
export function SqlLab() {
  const [queries, setQueries] = useState<any[]>([]);
  const [sel, setSel] = useState<string>("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [explain, setExplain] = useState(false);
  const [out, setOut] = useState<any>(null);
  const { busy, error, run } = useRun();
  useEffect(() => {
    api("/api/labs/sql/queries").then((r) => { setQueries(r.queries); setSel(r.queries[0].id); });
  }, []);
  const q = queries.find((x) => x.id === sel);
  useEffect(() => {
    if (q) setParams(Object.fromEntries(Object.entries(q.params).map(([k, v]: any) => [k, v[0]])));
    setOut(null);
  }, [sel]);
  if (!q) return <p className="muted">Loading queries…</p>;
  return (
    <div>
      <div className="row wrap">
        <select value={sel} onChange={(e) => setSel(e.target.value)} aria-label="Query">
          {queries.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
        </select>
        {Object.entries(q.params).map(([k, opts]: any) => (
          <label key={k} className="row"><span className="small">{k}</span>
            <select value={params[k] ?? ""} onChange={(e) => setParams({ ...params, [k]: e.target.value })}>
              {opts.map((o: string) => <option key={o}>{o}</option>)}
            </select>
          </label>
        ))}
        <label className="chip"><input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} /> EXPLAIN</label>
        <button className="primary" disabled={busy} onClick={() => run(async () => setOut(await api("/api/labs/sql/run", { body: { query_id: sel, params, explain } })))}>Run read-only</button>
      </div>
      <p className="small">Concepts: {q.concepts.join(", ")}</p>
      <pre className="code">{q.sql}</pre>
      <p>{q.explain}</p>
      {error && <p className="error">{error}</p>}
      {out && (
        <div className="scroll-x">
          <p className="small muted">{out.rows.length} row(s) · READ ONLY transaction · params {JSON.stringify(out.params)}</p>
          <table className="table">
            <thead><tr>{out.columns.map((c: string) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{out.rows.map((r: any[], i: number) => <tr key={i}>{r.map((v, j) => <td key={j}>{v ?? "∅"}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ 3. ML
function Bars({ scores, threshold }: { scores: Record<string, number>; threshold?: number }) {
  return (
    <div className="bars">
      {Object.entries(scores).map(([k, v]) => (
        <div key={k} className="bar-row">
          <span>{k}</span>
          <div className="bar"><div style={{ width: `${v * 100}%` }} />{threshold && <i style={{ left: `${threshold * 100}%` }} title="threshold" />}</div>
          <span className="num">{v.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

function Confusion({ m }: { m: any }) {
  return (
    <table className="table confusion">
      <thead><tr><th>true ↓ / predicted →</th>{m.labels.map((l: string) => <th key={l}>{l}</th>)}</tr></thead>
      <tbody>{m.rows_true.map((t: string, i: number) => (
        <tr key={t}><th>{t}</th>{m.matrix[i].map((v: number, j: number) => <td key={j} className={i === j ? "diag" : v ? "off" : ""}>{v}</td>)}</tr>
      ))}</tbody>
    </table>
  );
}

export function MlLab() {
  const [text, setText] = useState("Water heater trips the switch");
  const [out, setOut] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const { busy, error, run } = useRun();
  useEffect(() => { api("/api/labs/ml/report").then(setReport).catch(() => undefined); }, []);
  return (
    <div>
      <div className="row">
        <input value={text} onChange={(e) => setText(e.target.value)} aria-label="Problem description" />
        <button className="primary" disabled={busy} onClick={() => run(async () => setOut(await api("/api/labs/ml/predict", { body: { text } })))}>Classify</button>
      </div>
      {error && <p className="error">{error}</p>}
      {out && (
        <div className="exp-grid">
          <div>
            <h3>Model ({out.model.confident ? `predicts ${out.model.category}` : "not confident — would ask the customer"})</h3>
            <Bars scores={out.model.scores} threshold={out.model.threshold} />
            <p className="small muted">Line = threshold {out.model.threshold}. {out.model.note}</p>
            <h3>Features that pushed the top score</h3>
            <ul className="small">{out.top_features.map((f: any) => <li key={f.feature}><code>{f.feature}</code> +{f.contribution}</li>)}</ul>
          </div>
          <div>
            <h3>Keyword baseline</h3>
            <p>{out.keyword_baseline.category ?? "no prediction"} <span className="muted small">({out.keyword_baseline.reason})</span></p>
            <Json value={out.keyword_baseline.counts} />
          </div>
        </div>
      )}
      {report && (
        <details className="report" open>
          <summary>Actual training and evaluation results ({report.model_version})</summary>
          <p className="small">Trained {report.trained_at} · dataset {report.dataset_version} · splits {JSON.stringify(report.split_sizes)}</p>
          <table className="table">
            <thead><tr><th>Held-out test</th><th>Accuracy</th><th>Macro F1</th></tr></thead>
            <tbody>
              <tr><td>TF-IDF + logistic regression</td><td>{report.test.model.accuracy}</td><td>{report.test.model.macro_f1}</td></tr>
              <tr><td>Keyword baseline</td><td>{report.test.keyword_baseline.accuracy}</td><td>{report.test.keyword_baseline.macro_f1}</td></tr>
            </tbody>
          </table>
          <div className="exp-grid">
            <div><h3>Model confusion matrix</h3><Confusion m={report.test.model.confusion_matrix} /></div>
            <div><h3>Per-category precision / recall</h3>
              <table className="table"><tbody>{Object.entries(report.test.model.per_category).map(([k, v]: any) => (
                <tr key={k}><td>{k}</td><td>P {v.precision}</td><td>R {v.recall}</td></tr>))}</tbody></table>
            </div>
          </div>
          <p className="small">Threshold {report.threshold} (chosen on validation). With it: in-scope coverage {report.test.model_with_threshold.in_scope.coverage}, out-of-scope requests caught {report.test.model_with_threshold.out_of_scope.asked_user}/{report.test.model_with_threshold.out_of_scope.n}.</p>
          <ul className="small">{report.caveats.map((c: string) => <li key={c}>{c}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ 4. Extraction
const FIELDS = ["issue_description", "predicted_category", "locality", "preferred_date", "time_window"];
function FieldTable({ ex }: { ex: any }) {
  return (
    <>
      <p className="small method">{ex.method_label}</p>
      <table className="table">
        <tbody>{FIELDS.map((f) => (
          <tr key={f}><th>{f}</th><td>{ex[f].display ?? ex[f].value ?? "—"}<br /><Provenance f={ex[f]} /></td></tr>
        ))}</tbody>
      </table>
      <p className="small">Missing: {ex.missing_fields.join(", ") || "none"}</p>
      {ex.notes.map((n: string) => <p key={n} className="notice small">{n}</p>)}
    </>
  );
}

export function ExtractionLab() {
  const [text, setText] = useState("MCB keeps tripping. I am in Kothrud, tomorrow afternoon");
  const [out, setOut] = useState<any>(null);
  const { busy, error, run } = useRun();
  return (
    <div>
      <div className="row">
        <input value={text} onChange={(e) => setText(e.target.value)} aria-label="Customer sentence" />
        <button className="primary" disabled={busy} onClick={() => run(async () => setOut(await api("/api/labs/extraction", { body: { text } })))}>Extract</button>
      </div>
      {error && <p className="error">{error}</p>}
      {out && (
        <div className="exp-grid">
          <div><h3>Rules-based</h3><FieldTable ex={out.rules} /></div>
          <div>
            <h3>Hosted LLM + validation</h3>
            {out.llm ? <><FieldTable ex={out.llm} /><details><summary>Raw LLM fields before validation</summary><Json value={out.llm_raw} /></details></>
              : <p className="muted">LLM: {out.llm_status}. Set LLM_PROVIDER, LLM_MODEL and LLM_API_KEY to compare.</p>}
          </div>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ 5. RAG
export function RagLab() {
  const [q, setQ] = useState("Is there a cancellation fee if I cancel 3 hours before?");
  const [k, setK] = useState(5);
  const [out, setOut] = useState<any>(null);
  const [chunks, setChunks] = useState<any[] | null>(null);
  const { busy, error, run } = useRun();
  return (
    <div>
      <div className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Question" />
        <label className="row small">k <input type="number" min={1} max={10} value={k} className="num" onChange={(e) => setK(+e.target.value)} /></label>
        <button className="primary" disabled={busy} onClick={() => run(async () => setOut(await api("/api/labs/rag/query", { body: { question: q, k } })))}>Retrieve and answer</button>
      </div>
      {error && <p className="error">{error}</p>}
      {out && (
        <div className="exp-grid">
          <div>
            <h3>Retrieved chunks</h3>
            <p className="small muted">{out.retrieval.embedding_model} · threshold {out.retrieval.threshold} · route: {out.answer.route}</p>
            {out.retrieval.passages.map((p: any) => (
              <div key={p.chunk_id} className={p.similarity >= out.retrieval.threshold ? "chunk" : "chunk below"}>
                <div className="tech-head"><strong>{p.title} v{p.version} · {p.section}</strong><span className="num">{p.similarity.toFixed(3)}</span></div>
                <p className="small">{p.content}</p>
              </div>
            ))}
          </div>
          <div><h3>Answer</h3><PolicyAnswer out={out.answer} /><details><summary>Trace</summary><TraceView trace={out.trace} /></details></div>
        </div>
      )}
      <details onToggle={(e) => (e.target as HTMLDetailsElement).open && !chunks && api("/api/labs/rag/chunks").then((r) => setChunks(r.chunks))}>
        <summary>Browse all stored chunks (including superseded versions)</summary>
        {chunks?.map((c) => (
          <div key={c.chunk_id} className={c.doc_status === "active" ? "chunk" : "chunk below"}>
            <strong>{c.title} v{c.version}</strong> <StatusPill status={c.doc_status} /> · {c.section}{c.quarantined && <span className="error"> quarantined</span>}
            <p className="small">{c.content}</p>
          </div>
        ))}
      </details>
    </div>
  );
}

// ------------------------------------------------------------------ 6. Booking rules
export function BookingLab() {
  const [out, setOut] = useState<any>(null);
  const { busy, error, run } = useRun();
  return (
    <div>
      <p>Two lab accounts (racer A and racer B) confirm the same slot at the same instant through the real booking service, each on its own database connection.</p>
      <button className="primary" disabled={busy} onClick={() => run(async () => setOut(await api("/api/labs/booking-race", { body: {} })))}>
        {busy ? "Racing…" : "Run the race"}
      </button>
      {error && <p className="error">{error}</p>}
      {out && (
        <>
          <p>Slot #{out.slot.slot_id} · {out.slot.label}</p>
          <div className="exp-grid">
            {out.attempts.map((a: any) => (
              <div key={a.racer} className={a.outcome === "success" ? "race win" : "race lose"}>
                <h3>Racer {a.racer}: {a.outcome}</h3>
                <p>{a.reference ?? a.message}</p>
                {a.alternatives_offered !== undefined && <p className="small">{a.alternatives_offered} alternative technician(s) offered</p>}
                <ul className="small">{a.checks.map((c: any, i: number) => <li key={i}>{c.passed ? "✓" : "✗"} {c.rule}{c.detail ? ` — ${c.detail}` : ""}</li>)}</ul>
              </div>
            ))}
          </div>
          <h3>Rows in the bookings table for this slot</h3>
          <table className="table"><thead><tr><th>Reference</th><th>Racer</th><th>Status</th></tr></thead>
            <tbody>{out.database_rows_for_slot.map((r: any) => <tr key={r.reference}><td>{r.reference}</td><td>{r.racer}</td><td>{r.status}</td></tr>)}</tbody></table>
          <p><strong>Active bookings for this slot at race end: {out.active_bookings_for_slot}</strong></p>
          <p className="small muted">{out.cleanup}</p>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ 7. Evaluation
export function EvaluationLab() {
  const [latest, setLatest] = useState<any>({});
  const [suite, setSuite] = useState("policy");
  const { busy, error, run } = useRun();
  const load = () => api("/api/labs/evaluations").then((r) => setLatest(r.latest));
  useEffect(() => { load(); }, []);
  const r = latest[suite];
  return (
    <div>
      <div className="row">
        {["ml", "extraction", "retrieval", "policy"].map((s) => (
          <button key={s} className={suite === s ? "chip on" : "chip"} onClick={() => setSuite(s)}>{s}</button>
        ))}
        <button className="primary" disabled={busy} onClick={() => run(async () => { await api("/api/labs/evaluations/run", { body: { suite } }); await load(); })}>
          {busy ? "Running…" : `Run ${suite} suite`}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {!r ? <p className="muted">No stored run for this suite yet. Run it.</p> : (
        <>
          <p className="small">Run #{r.id} · {r.status} · finished {r.finished_at ? new Date(r.finished_at).toLocaleString("en-IN") : "—"}</p>
          {r.error && <pre className="code error">{r.error}</pre>}
          <Json value={r.summary} />
          <h3>Failures ({r.failures.length})</h3>
          {r.failures.length ? r.failures.map((f: any, i: number) => <Json key={i} value={f} />) : <p className="muted">None in this run.</p>}
          <p className="small muted">Automated metrics only. Human review of answer quality is recorded separately in docs/evaluation-report.md.</p>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ 8. Deployment
export function DeploymentLab() {
  const [dep, setDep] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const load = () => {
    api("/api/labs/deployment").then(setDep);
    fetch("/api/health").then(async (r) => setHealth({ status: r.status, body: await r.json() }));
  };
  useEffect(load, []);
  if (!dep || !health) return <p className="muted">Loading…</p>;
  return (
    <div className="exp-grid">
      <div>
        <h3>Health check · HTTP {health.status}</h3>
        <Json value={health.body} />
        <button className="ghost" onClick={load}>Refresh</button>
      </div>
      <div>
        <h3>Environment variables</h3>
        <table className="table"><tbody>{dep.environment.map((e: any) => (
          <tr key={e.name}><td><code>{e.name}</code></td><td>{e.set ? (e.value ?? "set (hidden)") : "default"}</td></tr>
        ))}</tbody></table>
        {dep.warnings.map((w: string) => <p key={w} className="notice small">{w}</p>)}
        <p className="small">Migration <code>{dep.migration_revision}</code> · model <code>{dep.model?.model_version ?? "not loaded"}</code> · in container: {String(dep.running_in_container)}</p>
        <p className="small muted">{dep.note}</p>
      </div>
    </div>
  );
}
