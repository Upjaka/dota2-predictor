import HeroSlot from "./HeroSlot.jsx";

function DraftSide({ side, teamName, picks, tone }) {
  const fallbackName = side === "radiant" ? "Radiant" : "Dire";
  const title = typeof teamName === "string" && teamName.trim() ? teamName.trim() : fallbackName;

  return (
    <section className={`draft-side draft-side--${tone}`}>
      <header className="draft-side__header">
        <div>
          <span className="draft-side__eyebrow">{side === "radiant" ? "СВЕТ" : "ТЬМА"}</span>
          <h3>{title}</h3>
        </div>
        <span className="draft-side__count">{picks.length} / 5</span>
      </header>
      <div className="hero-list">
        {Array.from({ length: 5 }, (_, index) => (
          <HeroSlot key={`${side}-${index}`} pick={picks[index]} index={index + 1} />
        ))}
      </div>
    </section>
  );
}

export default function TeamDraft({
  picks = [],
  radiantTeamName,
  direTeamName,
}) {
  const sorted = [...picks].sort((a, b) => a.pick_order - b.pick_order);
  const radiant = sorted.filter((pick) => pick.side === "radiant");
  const dire = sorted.filter((pick) => pick.side === "dire");

  return (
    <div className="draft-grid">
      <DraftSide side="radiant" teamName={radiantTeamName} tone="radiant" picks={radiant} />
      <DraftSide side="dire" teamName={direTeamName} tone="dire" picks={dire} />
    </div>
  );
}
