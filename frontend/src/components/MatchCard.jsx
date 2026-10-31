import { Link } from "react-router-dom";

const MATCH_STATUS = {
  unknown: { label: "Матч найден · статус уточняется", tone: "muted" },
  scheduled: { label: "Запланирован", tone: "pending" },
  live: { label: "Идёт", tone: "live" },
  completed: { label: "Завершён", tone: "muted" },
  cancelled: { label: "Отменён", tone: "muted" },
};

const GAME_STATUS = {
  unknown: "Уточняется",
  scheduled: "Запланирована",
  live: "Идёт",
  completed: "Завершена",
  cancelled: "Отменена",
};

const FORECAST_STATUS = {
  ready: "Готов",
  calculating: "Рассчитывается",
  no_prediction: "Задача ожидается",
  temporarily_unavailable: "Временно недоступен",
  draft_forming: "Ожидает драфт",
  unknown: "Статус уточняется",
};

function formatTime(value) {
  if (!value) return "Время неизвестно";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Время неизвестно" : date.toLocaleString();
}

function draftStatus(overview) {
  if (overview.detailsUnavailable) return "Данные драфта недоступны";
  if (!overview.draft) return "Драфт пока не получен";
  if (overview.draft.is_complete) return "Драфт завершён";
  const pickCount = overview.draft.pick_count ?? overview.draft.picks?.length ?? 0;
  if (overview.draft.pick_order_is_chronological === false) {
    return `Составы: ${pickCount} / 10 героев · порядок пиков неизвестен`;
  }
  return `${pickCount} пиков · драфт неполный`;
}

export default function MatchCard({ match }) {
  const status = MATCH_STATUS[match.status] || MATCH_STATUS.unknown;
  const detailsError = match.detailsError || match.currentGame?.details_error;
  const game = match.currentGame;
  const hasCompletedGameResult = game?.status === "completed";
  const winningTeamId = hasCompletedGameResult ? game.winner_team_id : null;
  const teamOneWon = winningTeamId && winningTeamId === match.team_one?.id;
  const teamTwoWon = winningTeamId && winningTeamId === match.team_two?.id;
  return (
    <article className="match-card">
      <div className="match-card__top">
        <span className={`badge badge--${status.tone}`}>
          <span className="status-dot" aria-hidden="true" />
          {status.label}
        </span>
        <span className="match-card__time">{formatTime(match.start_time)}</span>
      </div>

      <div className="match-card__teams">
        <div
          className={`match-card__team${teamOneWon ? " match-card__team--winner" : ""}${
            teamTwoWon ? " match-card__team--loser" : ""
          }`}
        >
          <span className="team-mark team-mark--one" aria-hidden="true">1</span>
          <strong>{match.team_one?.name || "Команда не указана"}</strong>
        </div>
        <span className="versus">VS</span>
        <div
          className={`match-card__team${teamTwoWon ? " match-card__team--winner" : ""}${
            teamOneWon ? " match-card__team--loser" : ""
          }`}
        >
          <span className="team-mark team-mark--two" aria-hidden="true">2</span>
          <strong>{match.team_two?.name || "Команда не указана"}</strong>
        </div>
      </div>
      {hasCompletedGameResult ? (
        <div className="match-card__result" role="status">
          {(game.winner_side === "radiant" || game.winner_side === "dire") &&
          game.winner_team_name
            ? `Победитель карты #${game.game_number}: ${game.winner_team_name}`
            : `Результат карты #${game.game_number} недоступен`}
          {game.radiant_score != null && game.dire_score != null
            ? ` · ${game.radiant_score}:${game.dire_score}`
            : ""}
        </div>
      ) : null}

      <div className="match-card__meta">
        <span>{match.league_name || "Турнир не указан"}</span>
        {match.format ? <span>{match.format}</span> : null}
      </div>

      <div className="match-card__bottom">
        <div className="match-facts">
          <div>
            <span className="fact-label">Карта</span>
            <strong>{match.currentGame ? `#${match.currentGame.game_number}` : "—"}</strong>
          </div>
          <div>
            <span className="fact-label">Статус карты</span>
            <strong>
              {match.currentGame
                ? GAME_STATUS[match.currentGame.status] || "Уточняется"
                : "Нет данных"}
            </strong>
          </div>
          <div>
            <span className="fact-label">Драфт</span>
            <strong>{draftStatus(match)}</strong>
          </div>
          <div>
            <span className="fact-label">Прогноз</span>
            <strong>
              {FORECAST_STATUS[match.forecastState] || "Статус уточняется"}
            </strong>
          </div>
        </div>
        <Link className="text-link" to={`/matches/${match.id}`}>
          О серии <span aria-hidden="true">→</span>
        </Link>
      </div>
      {detailsError ? (
        <div className="refresh-warning" role="status">
          Не удалось получить все сведения карты: {detailsError}
        </div>
      ) : null}
    </article>
  );
}
