import { Json } from "./common";

const NAMES: Record<string, string> = {
  input: "Input", extraction: "Extraction", ml_classification: "ML classification", validation: "Validation",
  technician_matching: "Technician matching (SQL)", booking_rules: "Booking rules", routing: "Question routing",
  retrieval: "Retrieval (pgvector)", structured_query: "Structured query", answer_generation: "Answer generation",
  abstain: "Abstention",
};

export function TraceView({ trace }: { trace: any }) {
  const usage = trace.steps.map((s: any) => s.data?.llm_usage).filter(Boolean);
  return (
    <div className="trace">
      <dl className="trace-meta">
        <dt>Request ID</dt><dd><code>{trace.request_id}</code></dd>
        <dt>Total</dt><dd>{trace.total_latency_ms} ms</dd>
        <dt>Outcome</dt><dd>{trace.outcome}</dd>
        {trace.audit_ref && <><dt>Audit event</dt><dd>#{trace.audit_ref}</dd></>}
      </dl>
      {usage.length > 0 ? usage.map((u: any, i: number) => (
        <p key={i} className="small">
          LLM {u.provider}/{u.model}: {u.input_tokens ?? "?"} in / {u.output_tokens ?? "?"} out tokens
          {u.estimated_cost_usd ? ` · ${u.estimated_cost_usd.label}: $${u.estimated_cost_usd.value}` : " · cost not estimated (no prices configured)"}
        </p>
      )) : <p className="small muted">No hosted LLM call in this request, so no tokens or cost.</p>}
      <ol className="steps">
        {trace.steps.map((s: any, i: number) => (
          <li key={i} className={s.error ? "step err" : "step"}>
            <details open={["ml_classification", "booking_rules", "retrieval", "routing"].includes(s.component)}>
              <summary>
                <span>{NAMES[s.component] ?? s.component}</span>
                {s.latency_ms !== null && <span className="ms">{s.latency_ms} ms</span>}
              </summary>
              {s.description && <p className="small muted">{s.description}</p>}
              {s.error && <p className="error small">{s.error}</p>}
              <Json value={s.data} />
            </details>
          </li>
        ))}
      </ol>
    </div>
  );
}
