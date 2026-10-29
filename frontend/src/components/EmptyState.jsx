export default function EmptyState({
  title = "Матчей пока нет",
  message = "Когда появятся данные, они отобразятся здесь.",
}) {
  return (
    <div className="state-panel state-panel--empty">
      <span className="empty-mark" aria-hidden="true">—</span>
      <h2>{title}</h2>
      <p>{message}</p>
    </div>
  );
}
