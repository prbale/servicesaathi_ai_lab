import { NavLink, Navigate, Route, Routes, useParams } from "react-router-dom";
import { LABS } from "../labs/content";
import { ApiLab, BookingLab, DeploymentLab, EvaluationLab, ExtractionLab, MlLab, RagLab, SqlLab } from "../labs/experiments";

const EXPERIMENTS: Record<string, () => React.JSX.Element> = {
  api: ApiLab, sql: SqlLab, ml: MlLab, extraction: ExtractionLab, rag: RagLab, booking: BookingLab,
  evaluation: EvaluationLab, deployment: DeploymentLab,
};

export default function Lab() {
  return (
    <div className="lab">
      <nav className="lab-nav" aria-label="Labs">
        <p className="muted small">Each module stands alone. They follow the build order.</p>
        <ol>
          {LABS.map((l) => (
            <li key={l.id}><NavLink to={`/lab/${l.id}`}>{l.title}</NavLink></li>
          ))}
        </ol>
      </nav>
      <Routes>
        <Route path=":id" element={<LabPage />} />
        <Route path="*" element={<Navigate to="/lab/api" replace />} />
      </Routes>
    </div>
  );
}

function LabPage() {
  const { id } = useParams();
  const lab = LABS.find((l) => l.id === id);
  if (!lab) return <Navigate to="/lab/api" replace />;
  const Experiment = EXPERIMENTS[lab.id];
  return (
    <article className="lab-page">
      <h1>{lab.title} lab</h1>
      <p className="lede">{lab.concept}</p>
      <div className="lab-facts">
        <section><h3>Why it is in this app</h3><p>{lab.purpose}</p></section>
        <section><h3>Inputs</h3><p>{lab.inputs}</p></section>
        <section><h3>Outputs</h3><p>{lab.outputs}</p></section>
      </div>
      <section className="panel experiment">
        <h2>Try it</h2>
        <Experiment />
      </section>
      <div className="lab-facts two">
        <section>
          <h3>Where to read the code</h3>
          <ul className="files">
            {lab.files.map((f) => <li key={f.path}><code>{f.path}</code><span>{f.what}</span></li>)}
          </ul>
        </section>
        <section>
          <h3>Common mistakes</h3>
          <ul>{lab.mistakes.map((m) => <li key={m}>{m}</li>)}</ul>
        </section>
      </div>
      <section className="exercise">
        <h3>Exercise</h3>
        <p>{lab.exercise.task}</p>
        <details><summary>Expected behaviour</summary><p>{lab.exercise.expected}</p></details>
      </section>
    </article>
  );
}
