import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DashboardPage from "./DashboardPage.jsx";

const { api } = vi.hoisted(() => ({
  api: {
    getDashboard: vi.fn(),
  },
}));

vi.mock("../api/index.js", () => ({
  api,
  POLL_INTERVAL_MS: 60000,
}));

const match = {
  id: "series-1",
  status: "completed",
  team_one: { name: "Team One" },
  team_two: { name: "Team Two" },
  league_name: "Autumn Cup",
};

function renderPage() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
}

describe("DashboardPage match filters", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getDashboard.mockImplementation(
      async ({ offset = 0, limit = 20 } = {}) => ({
        matches: [],
        total: 0,
        offset,
        limit,
        tournaments: [{ id: "league-42", name: "Autumn Cup" }],
      }),
    );
  });

  it("loads all 20 cards through one dashboard API call", async () => {
    api.getDashboard.mockResolvedValue({
      matches: Array.from({ length: 20 }, (_, index) => ({
        ...match,
        id: `series-${index}`,
        team_one: { name: `Team ${index}` },
      })),
      total: 20,
      offset: 0,
      limit: 20,
      tournaments: [{ id: "league-42", name: "Autumn Cup" }],
    });

    renderPage();

    expect(await screen.findByText("Team 19")).toBeInTheDocument();
    expect(api.getDashboard).toHaveBeenCalledTimes(1);
  });

  it("renders supported statuses and real tournament options", async () => {
    renderPage();

    expect(await screen.findByRole("option", { name: "Запланирован" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Идёт" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Завершён" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Отменён" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Уточняется" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Autumn Cup" })).toHaveValue(
      "league-42",
    );
    expect(screen.getByRole("option", { name: "Все турниры" })).toHaveValue("");
  });

  it("sends both filters together and resets to the first page when they change", async () => {
    api.getDashboard.mockImplementation(
      async ({ offset = 0, limit = 20 } = {}) => ({
        matches: [match],
        total: 45,
        offset,
        limit,
        tournaments: [{ id: "league-42", name: "Autumn Cup" }],
      }),
    );
    renderPage();

    const statusFilter = await screen.findByLabelText("Статус серии");
    const tournamentFilter = screen.getByLabelText("Турнир");
    await screen.findByRole("option", { name: "Autumn Cup" });

    fireEvent.change(statusFilter, { target: { value: "completed" } });
    fireEvent.change(tournamentFilter, { target: { value: "league-42" } });

    await waitFor(() => {
      expect(api.getDashboard).toHaveBeenLastCalledWith(
        {
          status: "completed",
          tournamentId: "league-42",
          sortOrder: "desc",
          offset: 0,
          limit: 20,
        },
        expect.any(Object),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Далее" }));
    await waitFor(() => {
      expect(api.getDashboard).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 20 }),
        expect.any(Object),
      );
    });

    fireEvent.change(statusFilter, { target: { value: "unknown" } });
    await waitFor(() => {
      expect(api.getDashboard).toHaveBeenLastCalledWith(
        expect.objectContaining({
          status: "unknown",
          tournamentId: "league-42",
          offset: 0,
        }),
        expect.any(Object),
      );
    });
  });

  it("sends only the selected tournament when the status filter is unset", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("Турнир"), {
      target: { value: "league-42" },
    });

    await waitFor(() => {
      expect(api.getDashboard).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "", tournamentId: "league-42", offset: 0 }),
        expect.any(Object),
      );
    });
  });

  it("renders a live match in the default feed and applies the live filter", async () => {
    api.getDashboard.mockImplementation(
      async ({ offset = 0, limit = 20 } = {}) => ({
        matches: [
          {
            ...match,
            status: "live",
            team_one: { name: "Team Yandex" },
            team_two: { name: "Astra Invicta" },
          },
        ],
        total: 1,
        offset,
        limit,
        tournaments: [{ id: "league-42", name: "Autumn Cup" }],
      }),
    );
    renderPage();

    expect(await screen.findByText("Team Yandex")).toBeInTheDocument();
    expect(screen.getByText("Astra Invicta")).toBeInTheDocument();
    expect(screen.getAllByText("Идёт")).toHaveLength(2);
    expect(api.getDashboard).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: "" }),
      expect.any(Object),
    );

    fireEvent.change(await screen.findByLabelText("Статус серии"), {
      target: { value: "live" },
    });
    await waitFor(() => {
      expect(api.getDashboard).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "live", offset: 0 }),
        expect.any(Object),
      );
    });
  });

  it("resets both filters and loads the unfiltered first page", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("Статус серии"), {
      target: { value: "completed" },
    });
    fireEvent.change(screen.getByLabelText("Турнир"), {
      target: { value: "league-42" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Сбросить фильтры" }));

    await waitFor(() => {
      expect(api.getDashboard).toHaveBeenLastCalledWith(
        {
          status: "",
          tournamentId: "",
          sortOrder: "desc",
          offset: 0,
          limit: 20,
        },
        expect.any(Object),
      );
    });
  });

  it("displays an empty filtered result differently from an API error", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("Статус серии"), {
      target: { value: "completed" },
    });
    expect(await screen.findByText("Матчи не найдены")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    api.getDashboard.mockRejectedValue(new Error("API недоступен"));
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByText("API недоступен")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("reports tournament loading errors and allows retry", async () => {
    api.getDashboard
      .mockRejectedValueOnce(new Error("Турниры недоступны"))
      .mockResolvedValueOnce({
        matches: [],
        total: 0,
        offset: 0,
        limit: 20,
        tournaments: [{ id: "league-42", name: "Autumn Cup" }],
      });
    renderPage();

    expect(await screen.findByText("Турниры недоступны")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByRole("option", { name: "Autumn Cup" })).toHaveValue(
      "league-42",
    );
    expect(screen.queryByText("Турниры недоступны")).not.toBeInTheDocument();
  });

  it("keeps selected filters during polling refreshes", async () => {
    vi.useFakeTimers();
    try {
      renderPage();
      const statusFilter = screen.getByLabelText("Статус серии");
      fireEvent.change(statusFilter, { target: { value: "completed" } });
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      await act(async () => {
        vi.advanceTimersByTime(60000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(api.getDashboard).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "completed", tournamentId: "" }),
        expect.any(Object),
      );
      expect(api.getDashboard).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });
});
