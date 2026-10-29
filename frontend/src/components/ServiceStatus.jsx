export default function ServiceStatus({ health }) {
  const isOnline = health.status === "ok";
  const label =
    health.status === "loading"
      ? "Connecting to API..."
      : isOnline
        ? "API and database connected"
        : health.message || "API unavailable";

  return (
    <div
      className={`service-status ${isOnline ? "service-status--online" : ""} ${
        health.status === "error" ? "service-status--offline" : ""
      }`}
      title={health.message || undefined}
    >
      <span className="service-status__dot" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
