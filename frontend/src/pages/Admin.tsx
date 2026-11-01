import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { Empty, Json, StatusPill, Tabs } from "../components/common";
import { useApp } from "../context";

type Tab = "technicians" | "documents" | "bookings" | "models" | "audit" | "reset";

export default function Admin() {
  const [tab, setTab] = useState<Tab>("technicians");
  return (
    <div className="page">
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "technicians", label: "Technicians" }, { id: "documents", label: "Policy documents" },
        { id: "bookings", label: "Bookings" }, { id: "models", label: "Models & evaluations" },
        { id: "audit", label: "Audit log" }, { id: "reset", label: "Reset demo" },
      ]} />
      {tab === "technicians" && <Technicians />}
      {tab === "documents" && <Documents />}
      {tab === "bookings" && <AllBookings />}
      {tab === "models" && <Models />}
      {tab === "audit" && <Audit />}
      {tab === "reset" && <Reset />}
    </div>
  );
}

function useLoad<T>(path: string, pick: (r: any) => T) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const load = () => api(path).then((r) => setData(pick(r))).catch((e) => setError(errorMessage(e)));
  useEffect(() => { load(); }, [path]);
  return { data, error, load, setError };
}

function Technicians() {
  const { meta } = useApp();
  const { data, error, load, setError } = useLoad("/api/admin/technicians", (r) => r.technicians as any[]);
  const [editing, setEditing] = useState<any>(null);
  async function save() {
    try {
      const body = { ...editing };
      const id = body.id;
      delete body.id;
      await api(id ? `/api/admin/technicians/${id}` : "/api/admin/technicians", { method: id ? "PUT" : "POST", body });
      setEditing(null);
      load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  if (!data || !meta) return <p className="muted">Loading…</p>;
  return (
    <section className="panel">
      <div className="tech-head">
        <h2>Demo technicians (fictional)</h2>
        <button className="ghost" onClick={() => setEditing({ name: "", bio: "", years_experience: 1, rating: 4, is_active: true, charges: { plumbing: 299 }, localities: ["wakad"] })}>Add technician</button>
      </div>
      {error && <p className="error">{error}</p>}
      {editing && (
        <div className="editor">
          <label className="field"><span>Name</span><input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></label>
          <label className="field"><span>Active</span><input type="checkbox" checked={editing.is_active} onChange={(e) => setEditing({ ...editing, is_active: e.target.checked })} /></label>
          <fieldset className="field">
            <legend>Categories and visiting charge (₹)</legend>
            {meta.categories.map((c) => (
              <label key={c.code} className="row">
                <input type="checkbox" checked={c.code in editing.charges}
                  onChange={(e) => {
                    const ch = { ...editing.charges };
                    if (e.target.checked) ch[c.code] = 299; else delete ch[c.code];
                    setEditing({ ...editing, charges: ch });
                  }} />
                <span className="grow">{c.name}</span>
                {c.code in editing.charges && (
                  <input type="number" min={1} value={editing.charges[c.code]} className="num"
                    onChange={(e) => setEditing({ ...editing, charges: { ...editing.charges, [c.code]: +e.target.value } })} />
                )}
              </label>
            ))}
          </fieldset>
          <fieldset className="field">
            <legend>Localities</legend>
            <div className="chips">
              {meta.localities.map((l) => (
                <label key={l.code} className="chip">
                  <input type="checkbox" checked={editing.localities.includes(l.code)}
                    onChange={(e) => setEditing({ ...editing, localities: e.target.checked
                      ? [...editing.localities, l.code] : editing.localities.filter((x: string) => x !== l.code) })} />
                  {l.name}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="row">
            <button className="primary" onClick={save}>Save technician</button>
            <button className="ghost" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      )}
      <table className="table">
        <thead><tr><th>Name</th><th>Visiting charges</th><th>Localities</th><th>Status</th><th /></tr></thead>
        <tbody>
          {data.map((t) => (
            <tr key={t.id}>
              <td>{t.name}</td>
              <td>{Object.entries(t.charges).map(([c, v]) => `${c} ₹${v}`).join(", ")}</td>
              <td>{t.localities.join(", ")}</td>
              <td>{t.is_active ? "Active" : "Inactive"}</td>
              <td><button className="link" onClick={() => setEditing({ ...t })}>Edit</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">Categories are fixed to the three the ML model was trained on. Adding one needs new training data.</p>
    </section>
  );
}

function Documents() {
  const { data, error, load, setError } = useLoad("/api/admin/documents", (r) => r.documents as any[]);
  const [file, setFile] = useState<File | null>(null);
  const [chunks, setChunks] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  async function upload() {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setBusy(true);
    try {
      await api("/api/admin/documents", { form, method: "POST" });
      setFile(null);
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  async function ingest(id: number) {
    setBusy(true);
    try {
      const r = await api(`/api/admin/documents/${id}/ingest`, { method: "POST" });
      if (r.status === "failed") setError(`Ingestion failed: ${r.error}`);
      load();
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h2>Policy documents</h2>
      <p className="muted">Upload .md or .txt. Front matter <code>doc_key</code>, <code>title</code> and <code>version</code> are read if present. A new version becomes active only after ingestion succeeds; the old one is then superseded and no longer searched.</p>
      <div className="row">
        <input type="file" accept=".md,.txt,.markdown" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="Policy file" />
        <button className="primary" disabled={!file || busy} onClick={upload}>Upload</button>
      </div>
      {error && <p className="error">{error}</p>}
      {!data ? <p className="muted">Loading…</p> : (
        <table className="table">
          <thead><tr><th>Document</th><th>Version</th><th>Status</th><th>Ingestion</th><th>Chunks</th><th /></tr></thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.id}>
                <td>{d.title}<br /><small className="muted">{d.doc_key}</small></td>
                <td>v{d.version}</td>
                <td><StatusPill status={d.status} /></td>
                <td>{d.ingestion_status}{d.ingestion_error && <><br /><small className="error">{d.ingestion_error}</small></>}</td>
                <td>{d.chunk_count}</td>
                <td className="row">
                  {d.ingestion_status !== "succeeded" && <button className="link" disabled={busy} onClick={() => ingest(d.id)}>Ingest</button>}
                  <button className="link" onClick={() => api(`/api/admin/documents/${d.id}/chunks`).then((r) => setChunks({ doc: d, ...r }))}>Chunks</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {chunks && (
        <div className="chunks">
          <h3>{chunks.doc.title} v{chunks.doc.version}</h3>
          {chunks.chunks.map((c: any) => (
            <div key={c.index} className={c.quarantined ? "chunk quarantined" : "chunk"}>
              <strong>{c.section}</strong>{c.quarantined && <span className="error"> quarantined: {c.reason}</span>}
              <p>{c.content}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function AllBookings() {
  const { data, error } = useLoad("/api/admin/bookings", (r) => r.bookings as any[]);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!data.length) return <Empty>No bookings yet.</Empty>;
  return (
    <table className="table panel">
      <thead><tr><th>Reference</th><th>Customer</th><th>Technician</th><th>Visit</th><th>Service</th><th>Status</th></tr></thead>
      <tbody>
        {data.map((b) => (
          <tr key={b.id}><td>{b.reference}</td><td>{b.customer}</td><td>{b.technician?.name}</td><td>{b.slot.label}</td>
            <td>{b.category} · {b.locality}</td><td><StatusPill status={b.status} /></td></tr>
        ))}
      </tbody>
    </table>
  );
}

function Models() {
  const m = useLoad("/api/admin/model-versions", (r) => r.model_versions as any[]);
  const e = useLoad("/api/admin/evaluations", (r) => r.runs as any[]);
  return (
    <section className="panel">
      <h2>Model versions</h2>
      {m.data?.map((v) => (
        <div key={v.version} className="model">
          <strong>{v.version}</strong> {v.is_active && <StatusPill status="active" />}
          <p className="muted small">dataset {v.dataset_version}</p>
          <Json value={v.metrics} />
        </div>
      ))}
      <h2>Evaluation runs</h2>
      <p className="muted small">Run suites from the Learning Lab → Evaluation Lab, or with <code>python -m app.evaluation.run</code>.</p>
      {!e.data?.length ? <Empty>No evaluation runs yet.</Empty> : (
        <table className="table">
          <thead><tr><th>#</th><th>Suite</th><th>Status</th><th>Failures</th><th>Finished</th></tr></thead>
          <tbody>{e.data.map((r) => (
            <tr key={r.id}><td>{r.id}</td><td>{r.suite}</td><td><StatusPill status={r.status} /></td><td>{r.failures.length}</td>
              <td>{r.finished_at ? new Date(r.finished_at).toLocaleString("en-IN") : "—"}</td></tr>
          ))}</tbody>
        </table>
      )}
    </section>
  );
}

function Audit() {
  const { data, error } = useLoad("/api/admin/audit?limit=150", (r) => r.events as any[]);
  if (error) return <p className="error">{error}</p>;
  return (
    <table className="table panel">
      <thead><tr><th>When</th><th>Action</th><th>Outcome</th><th>Entity</th><th>Request</th></tr></thead>
      <tbody>
        {data?.map((ev) => (
          <tr key={ev.id}><td>{new Date(ev.at).toLocaleString("en-IN")}</td><td>{ev.action}</td><td>{ev.outcome}</td>
            <td>{ev.entity}</td><td><code>{ev.request_id}</code></td></tr>
        ))}
      </tbody>
    </table>
  );
}

function Reset() {
  const { signOut } = useApp();
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  async function reset() {
    setBusy(true);
    try {
      const r = await api("/api/admin/reset", { body: { confirm } });
      setMsg(`${r.note} Restored ${r.summary.technicians} technicians and ${r.summary.slots} slots.`);
      setTimeout(signOut, 2500);
    } catch (e) {
      setMsg(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel narrow">
      <h2>Reset demo data</h2>
      <p>This deletes every booking and audit event, and restores the fictional technicians, fresh slots for the next 7 days, demo accounts and the seeded policy documents. Model versions and evaluation runs are kept.</p>
      <label className="field"><span>Type RESET to confirm</span><input value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label>
      <button className="primary danger" disabled={confirm !== "RESET" || busy} onClick={reset}>{busy ? "Resetting…" : "Reset demo data"}</button>
      {msg && <p className="notice">{msg}</p>}
    </section>
  );
}
