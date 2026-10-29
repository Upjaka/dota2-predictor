import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EmptyState from "./EmptyState.jsx";
import ErrorState from "./ErrorState.jsx";
import LoadingState from "./LoadingState.jsx";

describe("data states", () => {
  it("announces loading progress accessibly", () => {
    render(<LoadingState label="Загружаем серии" />);

    expect(screen.getByRole("status")).toHaveTextContent("Загружаем серии");
  });

  it("shows a clear empty-state title and explanation", () => {
    render(<EmptyState title="Пока пусто" message="Матчей нет." />);

    expect(screen.getByRole("heading", { name: "Пока пусто" })).toBeInTheDocument();
    expect(screen.getByText("Матчей нет.")).toBeInTheDocument();
  });

  it("announces errors and invokes retry only when requested", () => {
    const retry = vi.fn();
    render(<ErrorState message="Сервис недоступен" onRetry={retry} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Сервис недоступен");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
