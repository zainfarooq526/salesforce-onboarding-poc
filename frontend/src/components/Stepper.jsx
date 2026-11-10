const STEPS = ["Upload CSV", "Map fields", "Review & dedupe", "Sync results"];

export default function Stepper({ step }) {
  return (
    <ol className="stepper">
      {STEPS.map((label, i) => (
        <li key={label} className={i < step ? "done" : i === step ? "current" : ""}>
          <span className="dot">{i < step ? "✓" : i + 1}</span>
          <span className="label">{label}</span>
        </li>
      ))}
    </ol>
  );
}
