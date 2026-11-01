import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import MatchList from "./MatchList.jsx";

describe("MatchList", () => {
  it("renders teams, tournament, map, draft and forecast states", () => {
    render(
      <MemoryRouter>
        <MatchList
          matches={[
            {
              id: "series-1",
              status: "live",
              start_time: "2026-10-27T12:00:00Z",
              team_one: { name: "Radiant Club" },
              team_two: { name: "Dire Club" },
              league_name: "Autumn Cup",
              format: "BO3",
              currentGame: { game_number: 2, status: "live" },
              draft: {
                completed_at: null,
                is_complete: true,
                pick_order_is_chronological: false,
                picks: [
                  { hero_name: "Axe", hero_image_url: null, side: "radiant" },
                  { hero_name: "Puck", hero_image_url: null, side: "dire" },
                ],
              },
              forecastState: "calculating",
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Radiant Club")).toBeInTheDocument();
    expect(screen.getByText("Dire Club")).toBeInTheDocument();
    expect(screen.getByText("Autumn Cup")).toBeInTheDocument();
    expect(screen.getByText("Axe")).toBeInTheDocument();
    expect(screen.getByText("Puck")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    expect(
      screen.getByText("Драфт завершён"),
    ).toBeInTheDocument();
    expect(screen.getByText("Рассчитывается")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /о серии/i })).toHaveAttribute(
      "href",
      "/matches/series-1",
    );
  });

  it("uses safe labels for unknown match and forecast statuses", () => {
    render(
      <MemoryRouter>
        <MatchList
          matches={[
            {
              id: "series-unknown",
              status: "provider_future_state",
              team_one: null,
              team_two: null,
              forecastState: "provider_future_state",
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Матч найден · статус уточняется")).toBeInTheDocument();
    expect(screen.getByText("Статус уточняется")).toBeInTheDocument();
    expect(screen.getAllByText("Команда не указана")).toHaveLength(2);
  });

  it.each([
    ["scheduled", "Запланирован"],
    ["live", "Идёт"],
    ["completed", "Завершён"],
    ["cancelled", "Отменён"],
  ])("renders the %s match status", (status, label) => {
    render(
      <MemoryRouter>
        <MatchList
          matches={[
            {
              id: `series-${status}`,
              status,
              team_one: { name: "Team One" },
              team_two: { name: "Team Two" },
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("shows a completed map winner and distinguishes the losing team", () => {
    render(
      <MemoryRouter>
        <MatchList
          matches={[
            {
              id: "series-result",
              status: "completed",
              team_one: { id: "dire-id", name: "Dire Club" },
              team_two: { id: "radiant-id", name: "Radiant Club" },
              currentGame: {
                game_number: 2,
                status: "completed",
                winner_side: "radiant",
                winner_team_id: "radiant-id",
                winner_team_name: "Radiant Club",
                radiant_score: 30,
                dire_score: 21,
                duration_seconds: 1821,
              },
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(
      screen.getByText("Победитель карты #2: Radiant Club · 30 мин"),
    ).toBeInTheDocument();
    expect(screen.getByText("Radiant Club").closest(".match-card__team")).toHaveClass(
      "match-card__team--winner",
    );
    expect(screen.getByText("Dire Club").closest(".match-card__team")).toHaveClass(
      "match-card__team--loser",
    );
  });

  it("shows a neutral label when a completed map has no verified result", () => {
    render(
      <MemoryRouter>
        <MatchList
          matches={[
            {
              id: "series-unknown-result",
              status: "completed",
              currentGame: {
                game_number: 1,
                status: "completed",
                winner_side: "unknown",
              },
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Результат карты #1 недоступен")).toBeInTheDocument();
  });

  it("does not display stale result fields for a live map", () => {
    render(
      <MemoryRouter>
        <MatchList
          matches={[
            {
              id: "series-live-result",
              status: "live",
              currentGame: {
                game_number: 1,
                status: "live",
                winner_side: "dire",
                winner_team_name: "Dire Club",
              },
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.queryByText(/Победитель карты/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Результат карты/)).not.toBeInTheDocument();
  });
});
