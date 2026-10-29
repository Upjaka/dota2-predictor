import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TeamDraft from "./TeamDraft.jsx";

describe("TeamDraft", () => {
  it("renders five hero slots for each side and leaves unpicked slots explicit", () => {
    render(
      <TeamDraft
        picks={[
          {
            side: "radiant",
            hero_name: "Axe",
            pick_order: 2,
          },
          {
            side: "dire",
            hero_name: "Bane",
            pick_order: 1,
          },
        ]}
      />,
    );

    expect(screen.getAllByText("1 / 5")).toHaveLength(2);
    expect(screen.getByText("Axe")).toBeInTheDocument();
    expect(screen.getByText("Bane")).toBeInTheDocument();
    expect(screen.getAllByText("Ожидает выбора")).toHaveLength(8);
    expect(screen.getAllByText("Слот свободен")).toHaveLength(8);
  });

  it("uses the team names assigned to each map side", () => {
    render(
      <TeamDraft
        radiantTeamName="GamerLegion"
        direTeamName="Team Liquid"
        picks={[
          { side: "radiant", hero_name: "Axe", pick_order: 1 },
          { side: "dire", hero_name: "Bane", pick_order: 2 },
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "GamerLegion" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Team Liquid" })).toBeInTheDocument();
    expect(screen.getAllByText("1 / 5")).toHaveLength(2);
    expect(screen.getByText("Axe")).toBeInTheDocument();
    expect(screen.getByText("Bane")).toBeInTheDocument();
  });

  it("falls back to side names when a team name is missing or blank", () => {
    render(<TeamDraft radiantTeamName=" " direTeamName={null} />);

    expect(screen.getByRole("heading", { name: "Radiant" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Dire" })).toBeInTheDocument();
    expect(screen.queryByText("undefined")).not.toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  it("renders an empty draft without broken image placeholders", () => {
    const { container } = render(<TeamDraft />);

    expect(screen.getAllByText("Ожидает выбора")).toHaveLength(10);
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it("renders the provider hero portrait without labeling roster order as pick order", () => {
    const { container } = render(
      <TeamDraft
        picks={[
          {
            side: "radiant",
            hero_name: "Anti-Mage",
            hero_image_url: "https://cdn.example/antimage.png",
            pick_order: null,
          },
        ]}
      />,
    );

    expect(screen.getByAltText("")).toHaveAttribute(
      "src",
      "https://cdn.example/antimage.png",
    );
    expect(screen.getByText("В составе")).toBeInTheDocument();
    expect(screen.queryByText("Пик 01")).not.toBeInTheDocument();
    fireEvent.error(container.querySelector("img"));
    expect(container.querySelector("img")).not.toBeVisible();
    expect(screen.getByText("A")).toBeInTheDocument();
  });
});
