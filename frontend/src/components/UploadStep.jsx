import { useRef, useState } from "react";

export default function UploadStep({ busy, onUpload, onSample }) {
  const input = useRef(null);
  const [dragging, setDragging] = useState(false);

  const pick = (files) => {
    const file = files?.[0];
    if (file) onUpload(file);
  };

  return (
    <section>
      <h2>Upload a lead list</h2>
      <p className="muted">
        Any CSV export works: trade-show lists, spreadsheets, another CRM. Column names don't need to match
        Salesforce; you'll map them next.
      </p>
      <div
        className={`dropzone ${dragging ? "dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          pick(e.dataTransfer.files);
        }}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
      >
        <div className="drop-icon">⬆</div>
        <strong>{busy ? "Reading file…" : "Drop a CSV here or click to browse"}</strong>
        <span className="muted">Comma, semicolon or tab separated · up to 10,000 rows</span>
        <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => pick(e.target.files)} />
      </div>
      <div className="row">
        <span className="muted">No file handy?</span>
        <button className="secondary" disabled={busy} onClick={onSample}>
          Use the sample file (24 messy leads)
        </button>
      </div>
    </section>
  );
}
