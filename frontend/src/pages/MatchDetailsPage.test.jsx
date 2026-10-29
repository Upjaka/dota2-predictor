import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api/index.js";
import MatchDetailsPage from "./MatchDetailsPage.jsx";

vi.mock("../api/index.js", () => ({
  api: {
    getMatch: vi.fn(),
  },
}));

describe("MatchDetailsPage", () => {
  beforeEach(() => {
    api.getMatch.mockReset();
  });

  it("shows a series status separately from its completed map status", async () => {
    api.getMatch.mockResolvedValue({
      id: "series-1",
      status: "unknown",
      format: "BO3",
      games: [
        {
          id: "map-1",
          game_number: 1,
          status: "completed",
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/matches/series-1"]}>
        <Routes>
          <Route path="/matches/:matchId" element={<MatchDetailsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Статус уточняется")).toBeInTheDocument();
      expect(screen.getByText("Завершена")).toBeInTheDocument();
    });
  });

  it("shows the winner and final score for the individual completed map", async () => {
    api.getMatch.mockResolvedValue({
      id: "series-1",
      status: "live",
      format: "BO3",
      games: [
        {
          id: "map-1",
          game_number: 1,
          status: "completed",
          winner_side: "dire",
          winner_team_id: "dire-id",
          winner_team_name: "Dire Club",
          radiant_team: { id: "radiant-id", name: "Radiant Club" },
          dire_team: { id: "dire-id", name: "Dire Club" },
          radiant_score: 18,
          dire_score: 29,
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/matches/series-1"]}>
        <Routes>
          <Route path="/matches/:matchId" element={<MatchDetailsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Победитель карты: Dire Club · 18:29")).toBeInTheDocument();
    });
    expect(screen.getByText("Идёт")).toBeInTheDocument();
    expect(screen.getByText("Dire Club").closest("span")).toHaveClass(
      "game-card__team--winner",
    );
    expect(screen.getByText("Radiant Club").closest("span")).toHaveClass(
      "game-card__team--loser",
    );
  });

  it.each([
    ["scheduled", "Запланирована"],
    ["live", "Идёт"],
    ["completed", "Завершена"],
    ["cancelled", "Отменена"],
  ])("renders %s consistently for the series and its map", async (status, label) => {
    api.getMatch.mockResolvedValue({
      id: "series-1",
      status,
      format: "BO3",
      games: [
        {
          id: "map-1",
          game_number: 1,
          status,
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/matches/series-1"]}>
        <Routes>
          <Route path="/matches/:matchId" element={<MatchDetailsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText(label)).toHaveLength(2);
    });
  });
});
