import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api/index.js";
import GameDetailsPage from "./GameDetailsPage.jsx";

vi.mock("../api/index.js", () => ({
  api: {
    getMatch: vi.fn(),
    getGameDraft: vi.fn(),
    getGamePredictions: vi.fn(),
    getGamePredictionJobs: vi.fn(),
    createRoleAwarePrediction: vi.fn(),
  },
  latestForDraft: vi.fn((items, draft) =>
    draft ? items.find((item) => item.draft_version === draft.version) || null : null,
  ),
  POLL_INTERVAL_MS: 60_000,
}));

const game = {
  id: "game-1",
  game_number: 1,
  status: "live",
};

function renderGameDetails(gameState = game, pathname = "/games/game-1") {
  const [routePath, query] = pathname.split("?");
  return render(
    <MemoryRouter
      initialEntries={[
        {
          pathname: routePath,
          search: query ? `?${query}` : "",
          state: { game: gameState },
        },
      ]}
    >
      <Routes>
        <Route path="/games/:gameId" element={<GameDetailsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("GameDetailsPage draft states", () => {
  beforeEach(() => {
    api.getMatch.mockReset();
    api.getGameDraft.mockReset();
    api.getGamePredictions.mockReset().mockResolvedValue({ items: [] });
    api.getGamePredictionJobs.mockReset().mockResolvedValue({ items: [] });
    api.createRoleAwarePrediction.mockReset();
  });

  it("labels a partial draft clearly and renders its real hero", async () => {
    api.getGameDraft.mockResolvedValue({
      version: 1,
      completed_at: "2026-10-28T15:00:00Z",
      is_complete: false,
      pick_order_is_chronological: false,
      received_at: "2026-10-28T14:00:00Z",
      picks: [
        {
          side: "radiant",
          pick_order: 1,
          hero_name: "Anti-Mage",
          hero_image_url: "https://cdn.example/antimage.png",
        },
      ],
    });

    renderGameDetails();

    await waitFor(() => {
      expect(screen.getByText("Не хватает 9 героев")).toBeInTheDocument();
      expect(screen.getByText("Anti-Mage")).toBeInTheDocument();
    });
    expect(screen.queryByText("Драфт завершён")).not.toBeInTheDocument();
    expect(screen.getByAltText("")).toHaveAttribute(
      "src",
      "https://cdn.example/antimage.png",
    );
  });

  it("renders a complete five-per-side draft as complete", async () => {
    api.getGameDraft.mockResolvedValue({
      version: 2,
      completed_at: null,
      is_complete: true,
      pick_order_is_chronological: true,
      received_at: "2026-10-28T14:00:00Z",
      picks: Array.from({ length: 10 }, (_, index) => ({
        side: index < 5 ? "radiant" : "dire",
        pick_order: index + 1,
        hero_name: `Hero ${index + 1}`,
      })),
    });
    api.getGamePredictionJobs.mockResolvedValue({
      items: [{ draft_version: 2, status: "queued", attempt_count: 0 }],
    });

    renderGameDetails();

    await waitFor(() => {
      expect(screen.getByText("Драфт завершён")).toBeInTheDocument();
      expect(screen.getByText("Hero 1")).toBeInTheDocument();
      expect(screen.getByText("Hero 10")).toBeInTheDocument();
      expect(screen.getAllByText("Прогноз рассчитывается…")).toHaveLength(2);
    });
    expect(screen.getAllByText("5 / 5")).toHaveLength(2);
    expect(screen.queryByText(/ожидает завершения карты/i)).not.toBeInTheDocument();
  });

  it("requires all ten roles and displays a saved role-aware forecast", async () => {
    const picks = Array.from({ length: 10 }, (_, index) => ({
      id: `pick-${index + 1}`,
      side: index < 5 ? "radiant" : "dire",
      pick_order: index + 1,
      hero_name: `Hero ${index + 1}`,
    }));
    api.getGameDraft.mockResolvedValue({ version: 1, id: "draft-1", is_complete: true, picks });
    api.createRoleAwarePrediction.mockResolvedValue({
      id: "prediction-role-1",
      draft_id: "draft-1",
      draft_version: 1,
      model_name: "batru_plus",
      radiant_probability: "0.62",
      dire_probability: "0.38",
      radiant_roles: [1, 2, 3, 4, 5],
      dire_roles: [1, 2, 3, 4, 5],
    });

    renderGameDetails();

    const button = await screen.findByRole("button", { name: "Прогноз с учётом ролей" });
    expect(button).toBeDisabled();
    for (let index = 0; index < picks.length; index += 1) {
      fireEvent.change(screen.getByRole("combobox", { name: `Позиция: Hero ${index + 1}` }), {
        target: { value: `pos_${index % 5 + 1}` },
      });
    }
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => {
      expect(api.createRoleAwarePrediction).toHaveBeenCalledWith(
        "game-1",
        picks.map((pick, index) => ({ pick_id: pick.id, position: `pos_${index % 5 + 1}` })),
      );
      expect(screen.getByText("62%")).toBeInTheDocument();
      expect(screen.getByText("38%")).toBeInTheDocument();
    });
    expect(screen.getByText("Batru Plus (с учётом ролей)")).toBeInTheDocument();
  });

  it("uses the selected map's sides when teams swap sides within a series", async () => {
    api.getMatch.mockResolvedValue({
      games: [
        {
          id: "game-1",
          radiant_team: { name: "GamerLegion" },
          dire_team: { name: "Team Liquid" },
        },
        {
          id: "game-2",
          radiant_team: { name: "Team Liquid" },
          dire_team: { name: "GamerLegion" },
        },
      ],
    });
    api.getGameDraft.mockResolvedValue({
      version: 1,
      is_complete: false,
      picks: [],
    });

    renderGameDetails(game, "/games/game-2?match_id=match-1");

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Team Liquid" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "GamerLegion" })).toBeInTheDocument();
    });
    expect(api.getMatch).toHaveBeenCalledWith("match-1", expect.anything());
    expect(screen.getAllByText("0 / 5")).toHaveLength(2);
  });

  it("renders a finished forecast while the map is live", async () => {
    api.getGameDraft.mockResolvedValue({
      version: 3,
      is_complete: true,
      picks: Array.from({ length: 10 }, (_, index) => ({
        side: index < 5 ? "radiant" : "dire",
        pick_order: index + 1,
        hero_name: `Hero ${index + 1}`,
      })),
    });
    api.getGamePredictions.mockResolvedValue({
      items: [
        {
          draft_version: 3,
          radiant_probability: "0.61",
          dire_probability: "0.39",
          model_name: "test-model",
        },
      ],
    });
    api.getGamePredictionJobs.mockResolvedValue({
      items: [{ draft_version: 3, status: "succeeded", attempt_count: 1 }],
    });

    renderGameDetails();

    await waitFor(() => {
      expect(screen.getByText("61%")).toBeInTheDocument();
      expect(screen.getByText("39%")).toBeInTheDocument();
    });
    expect(screen.getByText("Прогноз готов")).toBeInTheDocument();
  });

  it("shows a prediction failure separately from an incomplete draft", async () => {
    api.getGameDraft.mockResolvedValue({
      version: 4,
      is_complete: true,
      picks: Array.from({ length: 10 }, (_, index) => ({
        side: index < 5 ? "radiant" : "dire",
        pick_order: index + 1,
        hero_name: `Hero ${index + 1}`,
      })),
    });
    api.getGamePredictionJobs.mockResolvedValue({
      items: [
        {
          draft_version: 4,
          status: "failed",
          failure_code: "batru_unavailable",
          last_error: "Batru HTTP 503",
        },
      ],
    });

    renderGameDetails();

    await waitFor(() => {
      expect(screen.getByText("Временно недоступен")).toBeInTheDocument();
      expect(screen.getByText("Batru HTTP 503")).toBeInTheDocument();
    });
    expect(screen.queryByText(/не хватает/i)).not.toBeInTheDocument();
  });

  it("does not describe an unavailable draft as if picks are being made", async () => {
    api.getGameDraft.mockResolvedValue(null);

    renderGameDetails();

    await waitFor(() => {
      expect(screen.getByText("Драфт недоступен")).toBeInTheDocument();
      expect(screen.getByText("Драфт пока недоступен")).toBeInTheDocument();
    });
  });

  it("shows an individual completed map outcome and final score", async () => {
    renderGameDetails({
      ...game,
      status: "completed",
      winner_side: "dire",
      winner_team_name: "Dire Club",
      radiant_team: { name: "Radiant Club" },
      dire_team: { name: "Dire Club" },
      radiant_score: 24,
      dire_score: 31,
    });

    await waitFor(() => {
      expect(screen.getByRole("region", { name: "Итог карты" })).toHaveTextContent(
        "ИТОГ КАРТЫ #1",
      );
      expect(screen.getByText("Победитель: Dire Club")).toBeInTheDocument();
      expect(screen.getByLabelText("Счёт Radiant и Dire")).toHaveTextContent(
        "Radiant Club24:31Dire Club",
      );
    });
  });

  it("does not show a final outcome for a live map", async () => {
    api.getGameDraft.mockResolvedValue(null);
    renderGameDetails();

    await waitFor(() => {
      expect(screen.getByText("Драфт пока недоступен")).toBeInTheDocument();
    });
    expect(screen.queryByRole("region", { name: "Итог карты" })).not.toBeInTheDocument();
  });
});
