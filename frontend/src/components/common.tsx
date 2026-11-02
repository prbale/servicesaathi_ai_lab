import type { ReactNode } from "react";

export function Provenance({ f }: { f: any }) {
  if (!f || f.source === "missing") return <span className="prov missing">not given yet</span>;
  const text: Record<string, string> = {
    user_text: f.evidence ? `from your words: “${f.evidence}”` : "from your words",
    inferred: f.evidence ? `inferred from “${f.evidence}”` : "inferred",
    ml_model: `predicted by the model (${f.evidence ?? ""})`,
    llm: "proposed by the AI model",
    user_edit: "you set this",
  };
  return <span className={`prov ${f.source}`}>{text[f.source] ?? f.source}</span>;
}

export function SafetyNotice({ text }: { text?: string | null }) {
  if (!text) return null;
  return (
    <div className="safety" role="alert">
      <strong>Stop and stay safe.</strong>
      <p>{text}</p>
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const labels: Record<string, string> = {
    confirmed: "Confirmed",
    en_route: "Technician on the way",
    in_progress: "Work in progress",
    completed: "Completed",
    cancelled_by_customer: "Cancelled by you",
    cancelled_by_provider: "Cancelled by technician",
    succeeded: "Succeeded",
    failed: "Failed",
    superseded: "Superseded",
    active: "Active",
  };
  const label = labels[status] ?? status.replace(/_/g, " ");
  return <span className={`pill s-${status}`}>{label}</span>;
}

export function Ticket({ booking, title }: { booking: any; title?: string }) {
  return (
    <div className="ticket" aria-live="polite">
      <div className="ticket-stub">
        <div className="ticket-head">
          <span>{title ?? "Booking confirmed"}</span>
          <StatusPill status={booking.status} />
        </div>
        <div className="ticket-ref">{booking.reference}</div>
      </div>
      <div className="ticket-body">
      <dl className="ticket-grid">
        <dt>Technician</dt>
        <dd>{booking.technician?.name}</dd>
        <dt>Visit</dt>
        <dd>{booking.slot?.label}</dd>
        <dt>Service</dt>
        <dd><span className="cap">{booking.category}</span> in <span className="cap">{booking.locality}</span></dd>
        <dt>Visiting charge</dt>
        <dd>₹{booking.visiting_charge_inr} <small>(not the final repair price)</small></dd>
      </dl>
      <p className="ticket-issue">“{booking.issue_description}”</p>
      </div>
    </div>
  );
}

export function Json({ value }: { value: any }) {
  return <pre className="code">{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (t: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className={value === t.id ? "tab on" : "tab"}
          onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function Citations({ citations }: { citations: any[] }) {
  if (!citations?.length) return null;
  return (
    <ol className="cites">
      {citations.map((c, i) => (
        <li key={i}>
          {c.title} · version {c.version} · <em>{c.section}</em>
        </li>
      ))}
    </ol>
  );
}

export function PolicyAnswer({ out }: { out: any }) {
  return (
    <div className={`answer mode-${out.mode}`}>
      <p className="answer-mode">{out.mode_label}</p>
      <SafetyNotice text={out.safety_notice} />
      {out.diy_notice && <p className="notice">{out.diy_notice}</p>}
      <p>{out.answer}</p>
      {out.excerpts?.map((x: any, i: number) => (
        <blockquote key={i} className="excerpt">
          <p>{x.text}</p>
          <cite>[{i + 1}] {x.citation.title} · v{x.citation.version} · {x.citation.section}</cite>
        </blockquote>
      ))}
      {out.mode === "llm" && <Citations citations={out.citations} />}
    </div>
  );
}
