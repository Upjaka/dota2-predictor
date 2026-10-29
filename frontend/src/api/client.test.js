import { afterEach, describe, expect, it, vi } from "vitest";
import { getGameDraft, getMatches, getTournaments } from "./client.js";

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
