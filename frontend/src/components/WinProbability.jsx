function asPercentage(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Math.round(number * 1000) / 10;
}

function emptyMessageFor(status, job) {
  if (status === "calculating") {
    return `Задача ${job?.status === "queued" ? "в очереди" : "в обработке"}${
      job?.attempt_count ? ` · попытка ${job.attempt_count}` : ""
    }.`;
  }
  if (status === "temporarily_unavailable") {
    return (
      job?.last_error ||
      "Backend не вернул готовый прогноз. Состояние задачи будет проверено повторно."
    );
  }
  if (status === "hero_mapping_error") {
    return (
      job?.last_error ||
      "Для одного или нескольких героев отсутствует подтверждённое соответствие Batru."
    );
  }
  if (status === "invalid_draft") {
    return job?.last_error || "Данные драфта не прошли проверку.";
  }
  if (status === "no_prediction") {
    return job?.status === "succeeded"
      ? "Задача завершилась, но результат прогноза не найден. Вероятности не подменяются."
      : "Драфт полный. Задача прогнозирования ещё не появилась; состояние проверяется автоматически.";
  }
  if (status === "unknown") {
    return "Backend вернул неизвестный статус задачи. Он отображён как неопределённый.";
  }
  return "Прогноз появится после получения всех десяти сопоставленных героев.";
}

export default function WinProbability({
  prediction,
  draft,
  job,
  status,
  variant = "standard",
}) {
  const isRoleAware = variant === "role-aware";
  const panelClass = isRoleAware
    ? "panel forecast-panel forecast-panel--role-aware"
    : "panel forecast-panel forecast-panel--standard";
  const eyebrow = isRoleAware ? "ПРОГНОЗ С УЧЁТОМ РОЛЕЙ" : "ОБЫЧНЫЙ ПРОГНОЗ · ТОЛЬКО ПИК";
  const heading = isRoleAware
    ? "Вероятность победы с учётом ролей"
    : "Вероятность победы по пику";

  if (!prediction) {
    const picks = draft?.picks || [];
    const missingHeroes = Math.max(
      0,
      5 - picks.filter((pick) => pick.side === "radiant").length,
    ) + Math.max(0, 5 - picks.filter((pick) => pick.side === "dire").length);
    const incompleteMessage =
      status === "draft_forming" && picks.length > 0
        ? `Не хватает ${missingHeroes} ${missingHeroes === 1 ? "героя" : "героев"} для полного драфта.`
        : null;
    const statusLabels = {
      draft_forming: "Ожидает завершения драфта",
      calculating: "Прогноз рассчитывается…",
      no_prediction: "Прогноз ещё не создан",
      hero_mapping_error: "Не сопоставлен герой",
      invalid_draft: "Некорректный драфт",
      temporarily_unavailable: "Временно недоступен",
      unknown: "Статус уточняется",
    };
    return (
      <section className={panelClass}>
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h2>{heading}</h2>
          </div>
          <span
            className={`badge ${
              ["temporarily_unavailable", "hero_mapping_error", "invalid_draft"].includes(status)
                ? "badge--warning"
                : status === "calculating"
                  ? "badge--pending"
                  : "badge--muted"
            }`}
          >
            {statusLabels[status] || "Статус уточняется"}
          </span>
        </div>
        <div className="forecast-empty">
          {incompleteMessage || emptyMessageFor(status, job)}
        </div>
        <p className="disclaimer">
          Прогноз — оценка модели по драфту, а не гарантия результата карты.
        </p>
      </section>
    );
  }

  const radiant = asPercentage(prediction.radiant_probability);
  const dire = asPercentage(prediction.dire_probability);
  return (
    <section className={panelClass}>
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{heading}</h2>
        </div>
        <span className="badge badge--success">Прогноз получен</span>
      </div>
      <div className="probability-row">
        <div className="probability-row__label probability-row__label--radiant">
          <span>Radiant</span>
          <strong>{radiant === null ? "—" : `${radiant}%`}</strong>
        </div>
        <div className="probability-row__label probability-row__label--dire">
          <span>Dire</span>
          <strong>{dire === null ? "—" : `${dire}%`}</strong>
        </div>
      </div>
      <div className="probability-track" aria-label="Сравнение вероятностей">
        <span style={{ width: `${radiant ?? 50}%` }} />
      </div>
      <dl className="forecast-meta">
        <div>
          <dt>Получен</dt>
          <dd>
            {prediction.calculated_at
              ? new Date(prediction.calculated_at).toLocaleString()
              : "Время неизвестно"}
          </dd>
        </div>
        <div>
          <dt>Модель</dt>
          <dd>
            {prediction.model_name === "batru_plus"
              ? "Batru Plus (с учётом ролей)"
              : prediction.model_name || "Не указана"}
          </dd>
        </div>
      </dl>
      <p className="disclaimer">
        Вероятности отражают оценку модели по драфту и не гарантируют исход карты.
        {" "}Источник прогноза:{" "}
        <a href="https://batru.gg?utm_source=draftwatch">batru.gg</a>.
      </p>
    </section>
  );
}
