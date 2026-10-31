import { useCallback, useState } from "react";
import { api, POLL_INTERVAL_MS } from "../api/index.js";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import LoadingState from "../components/LoadingState.jsx";
import MatchList from "../components/MatchList.jsx";
import { usePolling } from "../hooks/usePolling.js";

function formatUpdatedAt(value) {
  return value ? value.toLocaleTimeString() : "Ещё не обновлялось";
}

export default function DashboardPage() {
  const [status, setStatus] = useState("");
  const [tournamentId, setTournamentId] = useState("");
  const [sortOrder, setSortOrder] = useState("desc");
  const [offset, setOffset] = useState(0);
  const limit = 20;
  const loadMatches = useCallback(
    (signal) =>
      api.getDashboard(
        { status, tournamentId, sortOrder, offset, limit },
        { signal },
      ),
    [status, tournamentId, sortOrder, offset, limit],
  );
  const { data, loading, refreshing, error, lastUpdated, refreshNow } = usePolling(
    loadMatches,
    POLL_INTERVAL_MS,
  );
  const matches = data?.matches || [];
  const tournaments = data?.tournaments || [];
  const tournamentsLoading = loading && data === null;
  const total = data?.total || 0;
  const filtersActive = Boolean(status || tournamentId);

  function updateStatus(value) {
    setStatus(value);
    setOffset(0);
  }

  function updateTournament(value) {
    setTournamentId(value);
    setOffset(0);
  }

  function resetFilters() {
    setStatus("");
    setTournamentId("");
    setOffset(0);
  }

  return (
    <main className="page-container">
      <section className="page-intro">
        <div>
          <p className="eyebrow">ПРОФЕССИОНАЛЬНАЯ СЦЕНА · DOTA 2</p>
          <h1>Матчи и драфты</h1>
          <p className="page-intro__copy">
            Серии, карты и прогнозы из подключённого источника данных.
          </p>
        </div>
        <div className="feed-stat">
          <span className="feed-stat__value">{total}</span>
          <span className="feed-stat__label">серий в выборке</span>
        </div>
      </section>

      <section className="feed-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">ЦЕНТР МАТЧЕЙ</p>
            <h2>Профессиональные матчи</h2>
          </div>
          <div className="feed-actions">
            <span className="last-updated">
              {refreshing ? "Обновление…" : `Обновлено ${formatUpdatedAt(lastUpdated)}`}
            </span>
            <button
              className="button button--secondary refresh-button"
              type="button"
              onClick={refreshNow}
              disabled={loading || refreshing}
            >
              <span aria-hidden="true">↻</span>
              Обновить
            </button>
          </div>
        </div>

        <div className="feed-toolbar">
          <label className="field">
            <span>Статус серии</span>
            <select
              value={status}
              onChange={(event) => updateStatus(event.target.value)}
            >
              <option value="">Все статусы</option>
              <option value="scheduled">Запланирован</option>
              <option value="live">Идёт</option>
              <option value="completed">Завершён</option>
              <option value="cancelled">Отменён</option>
              <option value="unknown">Уточняется</option>
            </select>
          </label>
          <label className="field">
            <span>Турнир</span>
            <select
              value={tournamentId}
              onChange={(event) => updateTournament(event.target.value)}
              disabled={tournamentsLoading}
            >
              <option value="">Все турниры</option>
              {tournaments.map((tournament) => (
                <option key={tournament.id} value={tournament.id}>
                  {tournament.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Время начала</span>
            <select
              value={sortOrder}
              onChange={(event) => {
                setSortOrder(event.target.value);
                setOffset(0);
              }}
            >
              <option value="desc">Сначала новые</option>
              <option value="asc">Сначала старые</option>
            </select>
          </label>
          {filtersActive ? (
            <button
              className="button button--secondary filter-reset"
              type="button"
              onClick={resetFilters}
            >
              Сбросить фильтры
            </button>
          ) : null}
        </div>

        {loading ? (
          <LoadingState label="Загружаем профессиональные серии..." />
        ) : error && matches.length === 0 ? (
          <ErrorState message={error} onRetry={refreshNow} />
        ) : (
          <>
            {error ? (
              <div className="refresh-warning" role="status">
                Не удалось обновить список: {error}. Показаны последние загруженные данные.
              </div>
            ) : null}
            {matches.length ? (
              <>
                <MatchList matches={matches} />
                {total > matches.length ? (
                  <p className="feed-note">
                    Показано {offset + matches.length} из {total}.
                  </p>
                ) : null}
                {total > limit ? (
                  <nav className="match-pagination" aria-label="Пагинация матчей">
                    <button
                      className="button button--secondary"
                      type="button"
                      onClick={() => setOffset(Math.max(0, offset - limit))}
                      disabled={offset === 0 || loading || refreshing}
                    >
                      Назад
                    </button>
                    <span>
                      {offset + 1}–{Math.min(offset + matches.length, total)} из {total}
                    </span>
                    <button
                      className="button button--secondary"
                      type="button"
                      onClick={() => setOffset(offset + limit)}
                      disabled={offset + limit >= total || loading || refreshing}
                    >
                      Далее
                    </button>
                  </nav>
                ) : null}
              </>
            ) : (
              <EmptyState
                title={filtersActive ? "Матчи не найдены" : "Матчей пока нет"}
                message={
                  filtersActive
                    ? "По выбранным фильтрам серий нет. Измените условия или сбросьте фильтры."
                    : "Backend пока не вернул матчи. Проверьте работу worker и источник данных."
                }
              />
            )}
          </>
        )}
      </section>

      <aside className="source-note">
        <span className="source-note__mark" aria-hidden="true">i</span>
        <p>
          OpenDota получает активные игры из отдельного потока; расписание и драфты доступны
          не для всех матчей. Прогноз может быть послематчевым. Обновление выполняется каждые{" "}
          {Math.round(POLL_INTERVAL_MS / 1000)} секунд.
        </p>
      </aside>
    </main>
  );
}
