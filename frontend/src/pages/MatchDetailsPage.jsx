import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/index.js";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import LoadingState from "../components/LoadingState.jsx";

const MAP_STATUS = {
  unknown: "Статус уточняется",
  scheduled: "Запланирована",
  live: "Идёт",
  completed: "Завершена",
  cancelled: "Отменена",
};

const SERIES_STATUS = {
  unknown: "Статус уточняется",
  scheduled: "Запланирована",
  live: "Идёт",
  completed: "Завершена",
  cancelled: "Отменена",
};

function displayTime(value) {
  if (!value) return "Время неизвестно";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Время неизвестно" : date.toLocaleString();
}

export default function MatchDetailsPage() {
  const { matchId } = useParams();
  const [refresh, setRefresh] = useState(0);
  const [state, setState] = useState({ loading: true, match: null, error: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, match: null, error: null });
    api
      .getMatch(matchId)
      .then((match) => {
        if (active) setState({ loading: false, match, error: null });
      })
      .catch((error) => {
        if (active) setState({ loading: false, match: null, error: error.message });
      });
    return () => {
      active = false;
    };
  }, [matchId, refresh]);

  if (state.loading) {
    return (
      <main className="page-container page-container--narrow">
        <LoadingState label="Загружаем сведения о серии..." />
      </main>
    );
  }
  if (state.error) {
    return (
      <main className="page-container page-container--narrow">
        <ErrorState message={state.error} onRetry={() => setRefresh((value) => value + 1)} />
        <Link className="back-link" to="/">← Все матчи</Link>
      </main>
    );
  }

  const { match } = state;
  const games = [...match.games].sort((a, b) => a.game_number - b.game_number);
  return (
    <main className="page-container">
      <Link className="back-link" to="/">← Все матчи</Link>
      <section className="match-hero">
        <div>
          <p className="eyebrow">{match.league_name || "ПРОФЕССИОНАЛЬНАЯ СЕРИЯ"}</p>
          <h1>{match.format || "Серия"}</h1>
          <p className="match-hero__date">{displayTime(match.start_time)}</p>
        </div>
        <span className={`badge badge--${match.status === "live" ? "live" : "muted"}`}>
          <span className="status-dot" aria-hidden="true" />
          {SERIES_STATUS[match.status] || "Статус уточняется"}
        </span>
      </section>

      <section className="series-score panel">
        <div className="series-team">
          <span className="team-mark team-mark--one" aria-hidden="true">1</span>
          <strong>{match.team_one?.name || "Команда не указана"}</strong>
        </div>
        <span className="series-score__versus">VS</span>
        <div className="series-team series-team--right">
          <strong>{match.team_two?.name || "Команда не указана"}</strong>
          <span className="team-mark team-mark--two" aria-hidden="true">2</span>
        </div>
      </section>

      <section className="feed-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">СЕРИЯ</p>
            <h2>Карты</h2>
          </div>
          <span className="subtle-count">{games.length} карт</span>
        </div>

        {games.length ? (
          <div className="game-list">
            {games.map((game) => (
              <article className="game-card" key={game.id}>
                <div className="game-card__number">
                  <span>КАРТА</span>
                  <strong>{String(game.game_number).padStart(2, "0")}</strong>
                </div>
                <div className="game-card__main">
                  <div className="game-card__teams">
                    <span
                      className={
                        game.winner_team_id === game.radiant_team?.id
                          ? "game-card__team--winner"
                          : game.winner_team_id === game.dire_team?.id
                            ? "game-card__team--loser"
                            : undefined
                      }
                    >
                      {game.radiant_team?.name || "Radiant"}
                    </span>
                    <span className="versus">VS</span>
                    <span
                      className={
                        game.winner_team_id === game.dire_team?.id
                          ? "game-card__team--winner"
                          : game.winner_team_id === game.radiant_team?.id
                            ? "game-card__team--loser"
                            : undefined
                      }
                    >
                      {game.dire_team?.name || "Dire"}
                    </span>
                  </div>
                  <div className="game-card__meta">
                    <span className={`badge badge--${game.status === "live" ? "live" : "muted"}`}>
                      {MAP_STATUS[game.status] || "Статус уточняется"}
                    </span>
                    <span>{displayTime(game.started_at)}</span>
                    {game.duration_seconds != null ? (
                      <span>{Math.floor(game.duration_seconds / 60)} мин</span>
                    ) : null}
                  </div>
                  {game.status === "completed" ? (
                    <div className="game-card__result" role="status">
                      {(game.winner_side === "radiant" || game.winner_side === "dire") &&
                      game.winner_team_name
                        ? `Победитель карты: ${game.winner_team_name}`
                        : "Результат карты недоступен"}
                      {game.radiant_score != null && game.dire_score != null
                        ? ` · ${game.radiant_score}:${game.dire_score}`
                        : ""}
                    </div>
                  ) : null}
                  {game.details_error ? (
                    <div className="refresh-warning" role="status">
                      Ошибка получения деталей карты: {game.details_error}
                    </div>
                  ) : null}
                </div>
                <Link
                  className="button button--secondary"
                  to={`/games/${game.id}?match_id=${encodeURIComponent(match.id)}`}
                  state={{ game, match }}
                >
                  Драфт и прогноз <span aria-hidden="true">→</span>
                </Link>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Карты ещё не получены"
            message="У источника пока нет сведений о картах этой серии."
          />
        )}
      </section>
    </main>
  );
}
