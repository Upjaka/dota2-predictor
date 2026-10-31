import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { api, latestForDraft, POLL_INTERVAL_MS } from "../api/index.js";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import LoadingState from "../components/LoadingState.jsx";
import TeamDraft from "../components/TeamDraft.jsx";
import WinProbability from "../components/WinProbability.jsx";
import { usePolling } from "../hooks/usePolling.js";

function displayTime(value) {
  if (!value) return "Время неизвестно";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Время неизвестно" : date.toLocaleString();
}

function statusFor(draft, prediction, job, requestFailed) {
  if (prediction) return "ready";
  if (job?.failure_code === "hero_mapping") return "hero_mapping_error";
  if (job?.failure_code === "invalid_draft") return "invalid_draft";
  if (job?.status === "queued" || job?.status === "running") return "calculating";
  if (requestFailed) return "temporarily_unavailable";
  if (job?.status === "failed") return "temporarily_unavailable";
  if (job?.status === "succeeded" || draft?.is_complete) return "no_prediction";
  if (job) return "unknown";
  return "draft_forming";
}

function statusLabel(status) {
  const labels = {
    found: "Матч найден",
    draft_forming: "Драфт пока не получен",
    draft_partial: "Драфт неполный",
    roster_only: "Порядок пиков не подтверждён",
    draft_unavailable: "Драфт недоступен",
    draft_completed: "Драфт завершён",
    calculating: "Прогноз рассчитывается…",
    ready: "Прогноз готов",
    no_prediction: "Прогноз ещё не создан",
    hero_mapping_error: "Не сопоставлен герой",
    invalid_draft: "Некорректный драфт",
    temporarily_unavailable: "Прогноз временно недоступен",
    unknown: "Статус уточняется",
  };
  return labels[status] || labels.unknown;
}

function predictionMatchesRoles(prediction, picks, selectedRoles) {
  if (!prediction || !picks.length) return false;
  const ordered = [...picks].sort((a, b) => a.pick_order - b.pick_order);
  const roleNumbers = (side) =>
    ordered
      .filter((pick) => pick.side === side)
      .map((pick) => Number(selectedRoles[pick.id]?.slice(-1)));
  return (
    JSON.stringify(roleNumbers("radiant")) === JSON.stringify(prediction.radiant_roles) &&
    JSON.stringify(roleNumbers("dire")) === JSON.stringify(prediction.dire_roles)
  );
}

export default function GameDetailsPage() {
  const [selectedRoles, setSelectedRoles] = useState({});
  const [submittedRolePrediction, setSubmittedRolePrediction] = useState(null);
  const [rolePredictionError, setRolePredictionError] = useState(null);
  const [rolePredictionLoading, setRolePredictionLoading] = useState(false);
  const { gameId } = useParams();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const matchId = searchParams.get("match_id");
  const routeMatch = location.state?.match || null;
  const routeGame = location.state?.game || null;

  const loadGame = useCallback(
    async (signal) => {
      let match = routeMatch;
      let game = routeGame;
      if (matchId) {
        match = await api.getMatch(matchId, { signal });
        game = match.games?.find((item) => item.id === gameId) || game;
        if (!game) throw new Error("Карта не найдена в указанной серии.");
      }

      const [draftResult, predictionsResult, jobsResult] = await Promise.allSettled([
        api.getGameDraft(gameId, { signal }),
        api.getGamePredictions(gameId, { signal }),
        api.getGamePredictionJobs(gameId, { signal }),
      ]);
      if (predictionsResult.status === "rejected" && predictionsResult.reason.status === 404) {
        throw predictionsResult.reason;
      }
      if (jobsResult.status === "rejected" && jobsResult.reason.status === 404) {
        throw jobsResult.reason;
      }

      const draft = draftResult.status === "fulfilled" ? draftResult.value : null;
      const predictions =
        predictionsResult.status === "fulfilled" ? predictionsResult.value.items : [];
      const jobs = jobsResult.status === "fulfilled" ? jobsResult.value.items : [];
      const prediction = latestForDraft(predictions, draft);
      const rolePrediction = latestForDraft(
        predictions.filter((item) => item.model_name === "batru_plus"),
        draft,
      );
      const predictionJob = latestForDraft(jobs, draft);
      const requestsFailed =
        draftResult.status === "rejected" ||
        predictionsResult.status === "rejected" ||
        jobsResult.status === "rejected";

      return {
        game,
        match,
        draft,
        prediction,
        rolePrediction,
        predictionJob,
        draftError: draftResult.status === "rejected" ? draftResult.reason.message : null,
        predictionStatus: statusFor(
          draft,
          prediction,
          predictionJob,
          requestsFailed,
        ),
      };
    },
    [gameId, matchId, routeGame, routeMatch],
  );
  const { data, loading, refreshing, error, lastUpdated, refreshNow } = usePolling(
    loadGame,
    POLL_INTERVAL_MS,
  );
  const loadedDraft = data?.draft;
  const loadedPicks = loadedDraft?.picks || [];
  const savedRolePrediction = data?.rolePrediction;
  const allRolesSelected = loadedPicks.length === 10 && loadedPicks.every((pick) => selectedRoles[pick.id]);
  const rolePrediction = submittedRolePrediction?.draft_id === loadedDraft?.id
    ? submittedRolePrediction
    : predictionMatchesRoles(savedRolePrediction, loadedPicks, selectedRoles)
      ? savedRolePrediction
      : null;

  useEffect(() => {
    setSelectedRoles({});
    setSubmittedRolePrediction(null);
    setRolePredictionError(null);
  }, [loadedDraft?.id]);

  useEffect(() => {
    if (!savedRolePrediction || savedRolePrediction.draft_id !== loadedDraft?.id) return;
    setSelectedRoles((current) => {
      if (Object.keys(current).length) return current;
      const restored = {};
      const ordered = [...loadedPicks].sort((a, b) => a.pick_order - b.pick_order);
      const radiant = ordered.filter((pick) => pick.side === "radiant");
      const dire = ordered.filter((pick) => pick.side === "dire");
      radiant.forEach((pick, index) => {
        if (savedRolePrediction.radiant_roles?.[index]) {
          restored[pick.id] = `pos_${savedRolePrediction.radiant_roles[index]}`;
        }
      });
      dire.forEach((pick, index) => {
        if (savedRolePrediction.dire_roles?.[index]) {
          restored[pick.id] = `pos_${savedRolePrediction.dire_roles[index]}`;
        }
      });
      return restored;
    });
  }, [loadedDraft?.id, savedRolePrediction?.id]);

  const changeRole = (pickId, position) => {
    setSelectedRoles((current) => ({ ...current, [pickId]: position }));
    setSubmittedRolePrediction(null);
    setRolePredictionError(null);
  };

  const requestRolePrediction = async () => {
    if (!allRolesSelected || rolePredictionLoading) return;
    setRolePredictionLoading(true);
    setRolePredictionError(null);
    try {
      const result = await api.createRoleAwarePrediction(
        gameId,
        loadedPicks.map((pick) => ({ pick_id: pick.id, position: selectedRoles[pick.id] })),
      );
      setSubmittedRolePrediction(result);
    } catch (requestError) {
      setRolePredictionError(requestError.message || "Не удалось получить ролевой прогноз.");
    } finally {
      setRolePredictionLoading(false);
    }
  };

  if (loading && !data) {
    return (
      <main className="page-container page-container--narrow">
        <LoadingState label="Загружаем драфт и прогноз..." />
      </main>
    );
  }
  if (error && !data) {
    return (
      <main className="page-container page-container--narrow">
        <ErrorState message={error} onRetry={refreshNow} />
        <Link className="back-link" to={routeMatch ? `/matches/${routeMatch.id}` : "/"}>
          ← {routeMatch ? "К серии" : "Все матчи"}
        </Link>
      </main>
    );
  }

  const { game, match, draft, prediction, predictionJob, draftError, predictionStatus } = data;
  const mapTitle = game?.game_number ? `Карта ${game.game_number}` : "Драфт карты";
  const backToMatch = match || routeMatch;
  const picks = draft?.picks || [];
  const isDraftComplete = Boolean(draft?.is_complete);
  const missingHeroes = Math.max(
    0,
    5 - picks.filter((pick) => pick.side === "radiant").length,
  ) + Math.max(0, 5 - picks.filter((pick) => pick.side === "dire").length);
  const draftState = draftError
    ? "unknown"
    : isDraftComplete
      ? "draft_completed"
      : picks.length > 0
        ? draft.pick_order_is_chronological === false
          ? "roster_only"
          : "draft_partial"
        : "draft_unavailable";

  return (
    <main className="page-container">
      <Link className="back-link" to={backToMatch ? `/matches/${backToMatch.id}` : "/"}>
        ← {backToMatch ? "К серии" : "Все матчи"}
      </Link>

      <section className="page-intro page-intro--compact">
        <div>
          <p className="eyebrow">{match?.league_name || "ПРОФЕССИОНАЛЬНАЯ КАРТА"}</p>
          <h1>{mapTitle}</h1>
          <p className="page-intro__copy">
            {game?.started_at ? displayTime(game.started_at) : "Время начала неизвестно"}
            {game?.status ? ` · ${game.status}` : ""}
          </p>
        </div>
        {game?.duration_seconds != null ? (
          <div className="feed-stat">
            <span className="feed-stat__value">
              {Math.floor(game.duration_seconds / 60)}
              <small>м</small>
            </span>
            <span className="feed-stat__label">длительность</span>
          </div>
        ) : null}
      </section>

      <div className="game-status-strip" aria-live="polite">
        {match ? <span className="status-step status-step--done">{statusLabel("found")}</span> : null}
        <span className={`status-step ${isDraftComplete ? "status-step--done" : ""}`}>
          {!isDraftComplete && picks.length > 0
            ? `Не хватает ${missingHeroes} ${missingHeroes === 1 ? "героя" : "героев"}`
            : statusLabel(draftState)}
        </span>
        <span
          className={`status-step ${
            predictionStatus === "ready"
              ? "status-step--done"
              : ["temporarily_unavailable", "hero_mapping_error", "invalid_draft"].includes(
                  predictionStatus,
                )
                ? "status-step--warning"
                : ""
          }`}
        >
          {statusLabel(predictionStatus)}
        </span>
        {predictionJob?.attempt_count ? (
          <span className="game-status-strip__attempts">
            Попытка {predictionJob.attempt_count}
          </span>
        ) : null}
      </div>

      {game?.status === "completed" ? (
        <section className="map-result panel" aria-label="Итог карты">
          <div>
            <p className="eyebrow">ИТОГ КАРТЫ #{game.game_number}</p>
            <h2>
              {(game.winner_side === "radiant" || game.winner_side === "dire") &&
              game.winner_team_name
                ? `Победитель: ${game.winner_team_name}`
                : "Результат недоступен"}
            </h2>
          </div>
          {game.radiant_score != null && game.dire_score != null ? (
            <p className="map-result__score" aria-label="Счёт Radiant и Dire">
              <span>{game.radiant_team?.name || "Radiant"}</span>
              <strong>{game.radiant_score}:{game.dire_score}</strong>
              <span>{game.dire_team?.name || "Dire"}</span>
            </p>
          ) : null}
        </section>
      ) : null}

      {game?.details_error ? (
        <div className="refresh-warning" role="status">
          Ошибка получения деталей карты: {game.details_error}
        </div>
      ) : null}

      {error ? (
        <div className="refresh-warning" role="status">
          Обновить данные не удалось: {error}. Показана последняя полученная информация.
        </div>
      ) : null}

      <section className="feed-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">СОСТАВЫ</p>
            <h2>Драфт</h2>
          </div>
          <div className="feed-actions">
            <span className="last-updated">
              {refreshing
                ? "Обновление…"
                : lastUpdated
                  ? `Обновлено ${lastUpdated.toLocaleTimeString()}`
                  : ""}
            </span>
            <button
              className="button button--secondary"
              type="button"
              onClick={refreshNow}
              disabled={loading || refreshing}
            >
              Обновить
            </button>
          </div>
        </div>

        {draft ? (
          <div className="draft-wrap">
            <div className="draft-version">
              Версия {draft.version} <span>·</span> получена {displayTime(draft.received_at)}
            </div>
            <TeamDraft
              picks={picks}
              radiantTeamName={game?.radiant_team?.name}
              direTeamName={game?.dire_team?.name}
              roles={selectedRoles}
              onRoleChange={changeRole}
            />
            <div className="role-prediction-actions">
              <button
                className="button button--primary"
                type="button"
                onClick={requestRolePrediction}
                disabled={!allRolesSelected || rolePredictionLoading}
              >
                {rolePredictionLoading ? "Запрашиваем прогноз…" : "Прогноз с учётом ролей"}
              </button>
              {!allRolesSelected ? <span>Укажите позиции всех десяти героев.</span> : null}
              {rolePredictionError ? <p role="alert">{rolePredictionError}</p> : null}
            </div>
          </div>
        ) : (
          <EmptyState
            title={draftError ? "Сведения о драфте временно недоступны" : "Драфт пока недоступен"}
            message={
              draftError ||
              "Матч найден, но источник ещё не передал данные драфта. Состояние будет проверяться автоматически."
            }
          />
        )}
      </section>

      <WinProbability
        prediction={prediction}
        draft={draft}
        job={predictionJob}
        status={predictionStatus}
        variant="standard"
      />
      {rolePrediction ? (
        <WinProbability
          prediction={rolePrediction}
          draft={draft}
          status="ready"
          variant="role-aware"
        />
      ) : null}
      <p className="source-note source-note--plain">
        Вероятность — оценка модели по драфту, а не гарантия результата. Фактический результат
        карты отображается отдельно.
      </p>
    </main>
  );
}
