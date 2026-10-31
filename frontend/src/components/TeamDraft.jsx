import HeroSlot from "./HeroSlot.jsx";

const ROLE_OPTIONS = [1, 2, 3, 4, 5];

function DraftSide({ side, teamName, picks, tone, roles, onRoleChange }) {
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
          <div className="hero-slot-with-role" key={`${side}-${index}`}>
            <HeroSlot pick={picks[index]} index={index + 1} />
            {picks[index] && onRoleChange ? (
              <label className="role-select">
                <span>Позиция героя</span>
                <select
                  aria-label={`Позиция: ${picks[index].hero_name}`}
                  value={roles?.[picks[index].id] || ""}
                  onChange={(event) => onRoleChange(picks[index].id, event.target.value)}
                >
                  <option value="">Выберите позицию</option>
                  {ROLE_OPTIONS.map((position) => (
                    <option key={position} value={`pos_${position}`}>Pos {position}</option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function TeamDraft({
  picks = [],
  radiantTeamName,
  direTeamName,
  roles,
  onRoleChange,
}) {
  const sorted = [...picks].sort((a, b) => a.pick_order - b.pick_order);
  const radiant = sorted.filter((pick) => pick.side === "radiant");
  const dire = sorted.filter((pick) => pick.side === "dire");

  return (
    <div className="draft-grid">
      <DraftSide side="radiant" teamName={radiantTeamName} tone="radiant" picks={radiant} roles={roles} onRoleChange={onRoleChange} />
      <DraftSide side="dire" teamName={direTeamName} tone="dire" picks={dire} roles={roles} onRoleChange={onRoleChange} />
    </div>
  );
}
