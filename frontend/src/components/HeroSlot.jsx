export default function HeroSlot({ pick, index }) {
  return (
    <div className={`hero-slot ${pick ? "hero-slot--picked" : ""}`}>
      <div className="hero-slot__portrait" aria-hidden="true">
        {pick ? (
          <>
            <span>{pick.hero_name?.slice(0, 1)?.toUpperCase() || "H"}</span>
            {pick.hero_image_url ? (
              <img
                src={pick.hero_image_url}
                alt=""
                loading="lazy"
                onError={(event) => {
                  event.currentTarget.hidden = true;
                }}
              />
            ) : null}
          </>
        ) : (
          <span className="hero-slot__index">{String(index).padStart(2, "0")}</span>
        )}
      </div>
      <div className="hero-slot__text">
        <span className="hero-slot__name">{pick?.hero_name || "Ожидает выбора"}</span>
        <span className="hero-slot__meta">
          {pick ? "В составе" : "Слот свободен"}
        </span>
      </div>
    </div>
  );
}
