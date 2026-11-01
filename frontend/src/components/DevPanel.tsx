import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { useApp } from "../context";
import { TraceView } from "./TraceView";

/** Developer Mode: shows how the latest request was processed, and replays seeded scenarios. */
export function DevPanel() {
  const { lastTrace } = useApp();
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [replay, setReplay] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { api("/api/dev/scenarios").then((r) => setScenarios(r.scenarios)).catch(() => undefined); }, []);

  async function run(s: any) {
    setError("");
    try {
      const path = s.kind === "request" ? "/api/requests/interpret" : "/api/policy/ask";
      const body = s.kind === "request" ? { text: s.text } : { question: s.text };
      const r = await api(path, { body });
      setReplay({ scenario: s, response: r });
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  const trace = replay?.response?.trace ?? lastTrace;
  return (
    <aside className="devpanel" aria-label="Request processing trace">
      <h2>How this request was processed</h2>
      <p className="muted small">Observable evidence only: inputs, validated fields, component timings, SQL shape, retrieved passages. No hidden reasoning, secrets or passwords.</p>
      <details>
        <summary>Replay a seeded scenario</summary>
        <div className="chips">
          {scenarios.map((s) => <button key={s.id} className="chip" onClick={() => run(s)}>{s.label}</button>)}
        </div>
      </details>
      {error && <p className="error">{error}</p>}
      {replay && <p className="small">Replayed: “{replay.scenario.text}”</p>}
      {trace ? <TraceView trace={trace} /> : <p className="muted">Make a request with Developer mode on and its trace appears here.</p>}
    </aside>
  );
}
