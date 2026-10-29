export default function ErrorState({ message, onRetry }) {
  return (
    <div className="state-panel state-panel--error" role="alert">
      <span className="state-panel__symbol" aria-hidden="true">!</span>
      <div>
        <h2>Не удалось загрузить данные</h2>
        <p>{message || "Попробуйте обновить страницу позже."}</p>
      </div>
      {onRetry ? (
        <button className="button button--secondary" type="button" onClick={onRetry}>
          Повторить
        </button>
      ) : null}
    </div>
  );
}
