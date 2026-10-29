import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import WinProbability from "./WinProbability.jsx";

describe("WinProbability", () => {
  it("renders both probabilities, timestamp, model and uncertainty notice", () => {
    const calculatedAt = "2026-10-27T12:00:00Z";
    render(
      <WinProbability
        prediction={{
          radiant_probability: "0.625",
          dire_probability: "0.375",
          calculated_at: calculatedAt,
          model_name: "test-model",
        }}
      />,
    );

    expect(screen.getByText("62.5%")).toBeInTheDocument();
    expect(screen.getByText("37.5%")).toBeInTheDocument();
    expect(screen.getByText(new Date(calculatedAt).toLocaleString())).toBeInTheDocument();
    expect(screen.getByText("test-model")).toBeInTheDocument();
    expect(screen.getByText(/не гарантируют исход карты/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "batru.gg" })).toHaveAttribute(
      "href",
      "https://batru.gg?utm_source=draftwatch",
    );
  });

  it("shows queued calculation attempts without implying a prediction exists", () => {
    render(
      <WinProbability
        prediction={null}
        draft={{ completed_at: "2026-10-27T12:00:00Z" }}
        job={{ status: "queued", attempt_count: 2 }}
        status="calculating"
      />,
    );

    expect(screen.getByText("Прогноз рассчитывается…")).toBeInTheDocument();
    expect(screen.getByText(/в очереди · попытка 2/i)).toBeInTheDocument();
    expect(screen.queryByText("Прогноз получен")).not.toBeInTheDocument();
  });

  it("maps an unknown task state to a safe status message", () => {
    render(
      <WinProbability
        prediction={null}
        job={{ status: "new-provider-state" }}
        status="unknown"
      />,
    );

    expect(screen.getByText("Статус уточняется")).toBeInTheDocument();
    expect(screen.getByText(/неизвестный статус задачи/i)).toBeInTheDocument();
  });

  it("distinguishes an unverified hero mapping from Batru being unavailable", () => {
    const mappingError = "No verified Batru shortName mapping for: Anti-Mage.";
    const { rerender } = render(
      <WinProbability
        prediction={null}
        job={{ status: "failed", failure_code: "hero_mapping", last_error: mappingError }}
        status="hero_mapping_error"
      />,
    );

    expect(screen.getByText("Не сопоставлен герой")).toBeInTheDocument();
    expect(screen.getByText(mappingError)).toBeInTheDocument();
    expect(screen.queryByText("Прогноз получен")).not.toBeInTheDocument();

    rerender(
      <WinProbability
        prediction={null}
        job={{ status: "failed", failure_code: "batru_unavailable", last_error: "HTTP 503" }}
        status="temporarily_unavailable"
      />,
    );

    expect(screen.getByText("Временно недоступен")).toBeInTheDocument();
    expect(screen.getByText("HTTP 503")).toBeInTheDocument();
  });

  it("does not describe a completed draft without a job as a Batru outage", () => {
    render(
      <WinProbability
        prediction={null}
        draft={{ completed_at: "2026-10-27T12:00:00Z" }}
        job={null}
        status="no_prediction"
      />,
    );

    expect(screen.getByText("Прогноз ещё не создан")).toBeInTheDocument();
    expect(screen.getByText(/задача прогнозирования ещё не появилась/i)).toBeInTheDocument();
    expect(screen.queryByText("Прогноз получен")).not.toBeInTheDocument();
  });
});
