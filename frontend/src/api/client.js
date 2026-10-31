export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/+$/, "");

const configuredPollInterval = Number(import.meta.env.VITE_POLL_INTERVAL_MS);
export const POLL_INTERVAL_MS =
  Number.isFinite(configuredPollInterval) && configuredPollInterval >= 5000
    ? configuredPollInterval
    : 30000;

async function request(path, { signal } = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { signal });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("Не удалось подключиться к backend. Проверьте адрес API.");
  }

  if (!response.ok) {
    let message = `Backend вернул ошибку (${response.status}).`;
    try {
      const body = await response.json();
      message = body.error?.message || body.detail || message;
    } catch {
      // Error responses are not guaranteed to contain JSON.
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  if (response.status === 204) return null;
  const body = await response.text();
  if (!body.trim()) return null;
  try {
    return JSON.parse(body);
  } catch {
    throw new Error("Backend вернул ответ в неподдерживаемом формате.");
  }
}

function emptyListResponse({ offset = 0, limit = 20 } = {}) {
  return { items: [], total: 0, offset, limit };
}

export async function getHealth({ signal } = {}) {
  const result = await request("/api/v1/health", { signal });
  if (!result || typeof result.status !== "string") {
    throw new Error("Backend вернул пустой или некорректный статус health.");
  }
  return result;
}

export async function getMatches(
  {
    status = "",
    tournamentId = "",
    sortOrder = "desc",
    offset = 0,
    limit = 20,
  } = {},
  { signal } = {},
) {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
    sort_order: sortOrder,
  });
  if (status) params.set("status", status);
  if (tournamentId) params.set("tournament_id", tournamentId);
  const result = await request(`/api/v1/matches?${params}`, { signal });
  if (result == null) return emptyListResponse({ offset, limit });
  if (!Array.isArray(result.items)) {
    throw new Error("Backend вернул список матчей в неожиданном формате.");
  }
  return { ...result, items: result.items };
}

export async function getDashboard(
  {
    status = "",
    tournamentId = "",
    sortOrder = "desc",
    offset = 0,
    limit = 20,
  } = {},
  { signal } = {},
) {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
    sort_order: sortOrder,
  });
  if (status) params.set("status", status);
  if (tournamentId) params.set("tournament_id", tournamentId);

  const result = await request(`/api/v1/matches/dashboard?${params}`, { signal });
  if (
    !result ||
    !Array.isArray(result.items) ||
    !Array.isArray(result.tournaments)
  ) {
    throw new Error("Backend вернул некорректные данные Dashboard.");
  }

  return {
    ...result,
    matches: result.items.map((item) => {
      const predictionJob = item.prediction_job_status
        ? { status: item.prediction_job_status }
        : null;
      return {
        ...item,
        currentGame: item.current_game,
        forecastState: forecastState(
          item.draft,
          item.has_prediction ? {} : null,
          predictionJob,
        ),
      };
    }),
  };
}

export async function getTournaments({ signal } = {}) {
  const result = await request("/api/v1/matches/tournaments", { signal });
  if (
    !Array.isArray(result) ||
    result.some(
      (tournament) =>
        !tournament ||
        typeof tournament.id !== "string" ||
        typeof tournament.name !== "string",
    )
  ) {
    throw new Error("Backend вернул список турниров в неожиданном формате.");
  }
  return result;
}

export async function getMatch(matchId, { signal } = {}) {
  const result = await request(
    `/api/v1/matches/${encodeURIComponent(matchId)}`,
    { signal },
  );
  if (!result || !Array.isArray(result.games)) {
    throw new Error("Backend вернул пустые или некорректные сведения о матче.");
  }
  return result;
}

export async function getMatchGames(matchId, { signal } = {}) {
  const result = await request(
    `/api/v1/matches/${encodeURIComponent(matchId)}/games`,
    { signal },
  );
  if (result == null) return [];
  if (!Array.isArray(result)) {
    throw new Error("Backend вернул карты матча в неожиданном формате.");
  }
  return result;
}

export async function getGameDraft(gameId, { signal } = {}) {
  try {
    return await request(
      `/api/v1/games/${encodeURIComponent(gameId)}/draft`,
      { signal },
    );
  } catch (error) {
    if (error.status === 404) return null;
    throw error;
  }
}

export async function getGamePredictions(gameId, { signal } = {}) {
  const result = await request(
    `/api/v1/games/${encodeURIComponent(gameId)}/predictions`,
    { signal },
  );
  if (result == null) return { game_id: gameId, items: [] };
  if (!Array.isArray(result.items)) {
    throw new Error("Backend вернул прогнозы в неожиданном формате.");
  }
  return { game_id: gameId, items: result.items };
}

export async function getGamePredictionJobs(gameId, { signal } = {}) {
  const result = await request(
    `/api/v1/games/${encodeURIComponent(gameId)}/prediction-jobs`,
    { signal },
  );
  if (result == null) return { game_id: gameId, items: [] };
  if (!Array.isArray(result.items)) {
    throw new Error("Backend вернул статусы задач прогноза в неожиданном формате.");
  }
  return { game_id: gameId, items: result.items };
}

export function latestForDraft(items, draft) {
  if (!draft) return null;
  return (
    items
      .filter((item) => item.draft_version === draft.version)
      .sort((a, b) => {
        const timestamp = (item) =>
          new Date(
            item.calculated_at || item.last_attempt_at || item.created_at || 0,
          ).getTime() || 0;
        return timestamp(b) - timestamp(a);
      })[0] || null
  );
}

function forecastState(draft, prediction, job) {
  if (prediction) return "ready";
  if (job?.status === "failed") return "temporarily_unavailable";
  if (job?.status === "queued" || job?.status === "running") return "calculating";
  if (job && job.status !== "succeeded") return "unknown";
  if (draft?.is_complete) return "no_prediction";
  if (draft) return "draft_forming";
  return "draft_forming";
}
