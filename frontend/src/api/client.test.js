import { afterEach, describe, expect, it, vi } from "vitest";
import { getDashboard, getGameDraft, getMatches, getTournaments } from "./client.js";

function response(status, body) {
  const text = JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => text,
    json: async () => body,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API client", () => {
  it("loads a 20-match dashboard page in one HTTP request", async () => {
    const items = Array.from({ length: 20 }, (_, index) => ({
      id: `series-${index}`,
      status: "live",
      current_game: {
        id: `game-${index}`,
        game_number: 1,
        status: "live",
        details_error: null,
      },
      draft: {
        version: 2,
        pick_count: 10,
        is_complete: true,
        pick_order_is_chronological: true,
      },
      has_prediction: index === 0,
      prediction_job_status: index === 1 ? "running" : null,
    }));
    const fetch = vi.fn().mockResolvedValue(
      response(200, {
        items,
        total: 20,
        offset: 0,
        limit: 20,
        tournaments: [{ id: "42", name: "Autumn Cup" }],
      }),
    );
    vi.stubGlobal("fetch", fetch);

    const result = await getDashboard({ status: "live", limit: 20 });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(new URL(fetch.mock.calls[0][0]).pathname).toBe(
      "/api/v1/matches/dashboard",
    );
    expect(result.matches).toHaveLength(20);
    expect(result.matches[0].currentGame.id).toBe("game-0");
    expect(result.matches[0].forecastState).toBe("ready");
    expect(result.matches[1].forecastState).toBe("calculating");
    expect(result.tournaments).toEqual([{ id: "42", name: "Autumn Cup" }]);
  });

  it("requests the documented match-list contract and returns empty items", async () => {
    const fetch = vi.fn().mockResolvedValue(
      response(200, { items: [], total: 0, offset: 0, limit: 20 }),
    );
    vi.stubGlobal("fetch", fetch);

    const result = await getMatches({ status: "unknown", limit: 20 });

    expect(result.items).toEqual([]);
    expect(result.total).toBe(0);
    expect(fetch.mock.calls[0][0]).toContain("/api/v1/matches?");
    expect(fetch.mock.calls[0][0]).toContain("status=unknown");
  });

  it("adds the tournament identifier to match requests", async () => {
    const fetch = vi.fn().mockResolvedValue(
      response(200, { items: [], total: 0, offset: 0, limit: 20 }),
    );
    vi.stubGlobal("fetch", fetch);

    await getMatches({ status: "completed", tournamentId: "league/42" });

    const requestedUrl = new URL(fetch.mock.calls[0][0]);
    expect(requestedUrl.searchParams.get("status")).toBe("completed");
    expect(requestedUrl.searchParams.get("tournament_id")).toBe("league/42");
  });

  it("loads the distinct tournament options endpoint", async () => {
    const fetch = vi.fn().mockResolvedValue(
      response(200, [{ id: "league-42", name: "Autumn Cup" }]),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(getTournaments()).resolves.toEqual([
      { id: "league-42", name: "Autumn Cup" },
    ]);
    expect(fetch.mock.calls[0][0]).toContain("/api/v1/matches/tournaments");
  });

  it("treats a missing draft as not yet available", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response(404, {})),
    );

    await expect(getGameDraft("map-id")).resolves.toBeNull();
  });

  it("surfaces backend errors instead of returning success-shaped data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response(503, { error: { message: "Database unavailable." } }),
      ),
    );

    await expect(getMatches()).rejects.toThrow("Database unavailable.");
  });

  it("handles non-JSON HTTP errors without exposing a JSON parse failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => {
          throw new SyntaxError("Unexpected token '<'");
        },
      }),
    );

    await expect(getMatches()).rejects.toMatchObject({
      message: "Backend вернул ошибку (503).",
      status: 503,
    });
  });
});
