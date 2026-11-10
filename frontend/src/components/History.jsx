const STATUS = { uploaded: "Needs mapping", mapped: "Ready to sync", synced: "Synced", partial: "Partly synced" };

export default function History({ items, activeId, onOpen }) {
  return (
    <div>
      <h3>Recent imports</h3>
      {!items.length && <p className="muted small">Imports you run will show up here.</p>}
      <ul className="history">
        {items.map((j) => (
          <li key={j.id}>
            <button className={`history-item ${j.id === activeId ? "active" : ""}`} onClick={() => onOpen(j.id)}>
              <span className="h-name">{j.filename}</span>
              <span className="h-meta">
                #{j.id} · {j.total_rows} rows · <span className={`h-status h-${j.status}`}>{STATUS[j.status]}</span>
              </span>
              {(j.status === "synced" || j.status === "partial") && (
                <span className="h-meta">
                  {j.created_rows} created · {j.updated_rows} updated
                  {j.failed_rows ? ` · ${j.failed_rows} failed` : ""}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
