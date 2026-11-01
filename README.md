# Dota 2 Draft Monitor

An initial modular-monolith foundation for monitoring professional Dota 2 matches and storing draft forecast history. OpenDota's live feed can expose the current hero lineups after hero assignments, while complete pick/ban order is available through match details after a map is completed. A forecast is queued as soon as the worker observes ten valid canonical heroes (five per side), including during a live map.

## Architecture

- `backend/app/api`: FastAPI routes; business logic does not live in route handlers.
- `backend/app/core`: settings and logging.
- `backend/app/db`, `models`, `schemas`: asynchronous SQLAlchemy setup, persistence entities, and API schemas.
- `backend/app/repositories`, `services`: persistence access and business workflows, including draft prediction orchestration.
- `backend/app/integrations`: HTTP adapters for Batru and OpenDota, hero mappings, and normalized interfaces.
- `backend/app/workers`: separate asyncio process for match polling, draft versioning, and prediction jobs.
- `backend/alembic`: migration configuration.
- `frontend/src`: React Router pages, FastAPI client, polling hook, and reusable match/draft components.

## Automated tests

### Backend

Install the backend and test dependencies, then run the default suite (FastAPI endpoints, prediction-service scenarios, and mocked Batru HTTP responses):

```powershell
cd backend
python -m pip install -r requirements-test.txt
python -m pytest
```

Default backend tests use an in-memory SQLite database only for service-level persistence scenarios; the FastAPI health endpoint uses a dependency override and never opens a database connection. They do not read production data or contact external APIs. PostgreSQL-specific repository/migration coverage is marked as an integration test and is skipped unless an explicitly separate test database is configured.

To run those PostgreSQL checks on a disposable local instance, from the repository root:

```powershell
docker compose -f docker-compose.test.yml up -d --wait
cd backend
$env:TEST_DATABASE_URL="postgresql+asyncpg://test:test@localhost:5433/dota_draft_predictor_test"
python -m pytest -m integration
Remove-Item Env:TEST_DATABASE_URL
cd ..
docker compose -f docker-compose.test.yml down
```

The integration test requires a database name ending in `_test` and a loopback host using `postgresql+asyncpg`. It applies migrations to that dedicated database, checks the resulting schema and repository reads, verifies the prediction uniqueness constraint, and rolls back its inserted rows. The test Compose service has no persistent volume; stopping/removing it discards its database. Never point `TEST_DATABASE_URL` at a production or primary development database.

### Frontend

```powershell
cd frontend
npm install
npm run test
```

`npm run test` performs one non-interactive Vitest run; `npm run test:watch` starts the local watch mode. React component and API-client tests use jsdom and mocked HTTP responses, so they do not require FastAPI or any external provider.

## Run with Docker Compose

1. Configure the database credentials and, optionally, the provider/worker settings listed below.
2. Build the backend and start PostgreSQL:

   ```powershell
   docker compose build
   docker compose up -d db
   ```

3. Apply database migrations explicitly (they are not run automatically):

   ```powershell
   docker compose run --rm api alembic upgrade head
   ```

4. Start the API, worker, and frontend:

   ```powershell
   docker compose up -d
   ```

5. Open the dashboard at <http://localhost:5173>. The API health endpoint is <http://localhost:8000/api/v1/health>; Swagger UI is at <http://localhost:8000/api/v1/docs>.

Run the frontend locally in PowerShell:

```powershell
cd frontend
npm install
$env:VITE_API_BASE_URL="http://localhost:8000"
$env:VITE_POLL_INTERVAL_MS="5000"
npm run dev
```

In Docker Compose, the same values come from the root `.env` and default to `http://localhost:8000` and `5000` milliseconds. Dashboard polling reads the backend only; the external OpenDota polling interval is configured separately. The API URL is used by JavaScript in the browser: **do not** set it to `http://api:8000`, because that Compose service name is not resolvable by the user's browser. For a remote deployment, set `VITE_API_BASE_URL` to a public/reachable API origin and add the exact frontend origin to the comma-separated `CORS_ORIGINS` allow-list (default `http://localhost:5173`). CORS middleware is already enabled in FastAPI.

The dashboard polls at the configured interval, skips a poll while the previous refresh is still in flight, and shows the last successful refresh time. A map page polls its draft, prediction history, and prediction-job states on the same interval; requests are aborted and timers cleared when the page unmounts.

Compose waits for PostgreSQL's health check before starting the API and worker, and for the API health check before starting the frontend. PostgreSQL data is persisted in the `postgres_data` volume. Run one worker instance; it is an independent process and does not run inside FastAPI requests.

To stop the services, run `docker compose down`. To also remove the local database volume, run `docker compose down -v`.

## Current scope

- The API exposes read-only versioned endpoints for health, matches, match games, drafts, prediction history, and prediction-job states.
- The frontend provides a match dashboard, series and map details, draft lineups, model forecast history, and automatic polling against FastAPI.
- SQLAlchemy models cover matches, teams, match games, heroes, versioned drafts, draft picks, predictions, and idempotent prediction jobs.
- Batru shortNames are synchronized from the official hero directory (`/api/data/heroes`, also used by the official Python SDK); the stable Dota 2 hero ID is used to associate entries. Local IDs and display names are never sent as substitutes.
- Batru's public win-rate endpoint accepts partial drafts as `radiant` and `dire` arrays of hero shortNames and returns percentage fields. Stored prediction probabilities are normalized to the application's 0–1 contract; user-facing forecasts credit batru.gg.
- Predictions are unique per draft and model identifier. The configured identifier (default `default`) is local metadata for the documented winrate endpoint; it is not sent as a selector.
- Provider-scoped external IDs prevent duplicate team, match, game, and hero records; prediction jobs and results are unique per draft version and model.
- Draft picks keep pick order separate from player position, and probabilities use constrained fixed-precision numeric columns.
- Alembic migrations define the database schema; migrations are deliberately not run automatically on application startup.
- The worker upserts series/maps, periodically refreshes a bounded number of map details, versions changed draft snapshots, and derives draft completion from the persisted canonical picks. New series default to `unknown`. The adapter maps `series_type` values 1 and 2 to BO3 and BO5, respectively; the OpenDota OpenAPI describes this field as an integer but does not publish an enum, and other values remain unmapped. A series becomes completed only when completed map results establish the winning score for its known format; an individual completed map alone does not complete the series. An active game from `/live` makes its series `live` unless it has already been completed.
- Prediction job states are `queued`, `running`, `succeeded`, and `failed`; map states are `unknown`, `scheduled`, `live`, `completed`, and `cancelled`. Series state becomes `live` while any known game is active and becomes `completed` only after known map results reach the winning score for a recognized series format. If the last known game ceases to be live before the series winning score is established, series state returns to `unknown`; one completed map does not complete a BO3/BO5 series.
- Provider and Batru calls happen outside database transactions. Batru transient failures use bounded retries with exponential backoff; stale running jobs are retried only up to `WORKER_JOB_MAX_ATTEMPTS`.

## Professional match data source

OpenDota is the initial provider because its official OpenAPI specification documents the `/proMatches` feed, `/live`, cursor parameter `less_than_match_id`, per-match detail at `/matches/{match_id}`, draft actions in `picks_bans`, and optional API-key authentication. A key is optional; the specification says a key increases rate limits but does not publish a guaranteed request quota or freshness SLA. STRATZ's linked GraphQL playground is available, but the supplied official pages did not expose a query/schema contract, authentication requirements, rate limits, or latency suitable for an implementation without guessing.

The OpenDota `/proMatches` operation returns recent professional-game records, not an ongoing-game feed; the worker uses it for history and completed results. The separate `/live` operation returns currently active games, but its published schema does not define the response fields and the feed can include non-professional games. The adapter therefore validates the observed live fields, accepts only non-deactivated entries with a positive league ID and two stable team IDs, and logs rejected entries. It polls `/live` and `/proMatches` independently, so failure of one does not block the other. The live feed currently provides no tournament name, series format, or scheduled fixtures; the worker reuses a known tournament name by league ID when available. It does not infer upcoming or live status from scheduled start times. OpenDota does not document a delivery-latency guarantee.

The worker calls these provider methods; they can also be called directly from a one-off sync workflow:

```python
from app.integrations.opendota_provider import OpenDotaProvider

provider = OpenDotaProvider.from_settings()
live = await provider.get_live_matches()
latest = await provider.get_current_matches()
if latest:
    provider_match_id = latest[0].provider_match_id
    details = await provider.get_match_details(provider_match_id)
    game_map = details.map
    status = game_map.status
hero_directory = await provider.get_hero_directory()
```

The result is normalized and retains provider match, series, game, team, and hero IDs for idempotent upserts/resynchronization. OpenDota's `/heroes` directory provides external hero IDs and localized names needed to seed `Hero` rows; it does not guess hero names from numeric IDs. Missing team IDs, start times, and drafts remain `None`; malformed individual feed entries are logged and skipped rather than failing the whole batch. Since the feed does not provide game order within a series, the worker assigns `game_number` by first observation, sorting each fetched batch by start time when available. It is an internal ordinal, not a provider-confirmed game number. The series row remains `unknown` rather than inferring series completion from one finished map.

For match details, the provider documents pick/ban actions and their `is_pick`, `hero_id`, `team`, and `order` fields. The API description does not enumerate the `team` values; the adapter recognizes the observed response values `0` (Radiant) and `1` (Dire), and logs unknown-side actions. It exposes picked heroes only, keeps `pick_order` separate from `position`, and always normalizes position as `unknown`. Draft completion is derived internally from persisted canonical hero records: exactly ten distinct heroes, five assigned to each side, all for the same map. Provider completion flags and map status do not determine draft completion.

OpenDota's observed `/live` response may include `players` records representing the active player roster for that game; each record includes `account_id`, `hero_id`, `team`, and `team_slot` (other player metadata may also be present). A positive `hero_id` is the hero assigned to that active player, not a pick-event record. The adapter persists assigned heroes as the game's current roster, with `team=0` mapped to Radiant and `team=1` to Dire. An unassigned `hero_id=0`, missing player data, or metadata-only poll does not clear stored picks. `team_slot` supplies stable roster ordering for storage only. These snapshots mark `pick_order_is_chronological=false`; the API does not expose the synthetic storage order as `pick_order`, and the UI labels the entries as heroes in the roster / says pick order is unknown. Match details (`picks_bans`) remain the source of actual pick order after the game is available there. As soon as a complete ten-hero draft is recognized, the worker queues its forecast regardless of map status. `Draft.completed_at` records when the worker first observed a complete persisted lineup; the API's `is_complete` value is derived from the current persisted picks and remains authoritative if that timestamp is stale or missing.

OpenDota configuration: `OPENDOTA_BASE_URL`, optional `OPENDOTA_API_KEY`, `OPENDOTA_TIMEOUT_SECONDS`, `OPENDOTA_MAX_RETRIES`, and `OPENDOTA_RETRY_BACKOFF_SECONDS`. The key is passed only as the documented `api_key` query parameter and is read from `.env`, never embedded in code. The client uses bounded timeouts, bounded retries for network/408/429/5xx failures, honors `Retry-After` where parseable, and does not retry other HTTP errors or invalid response bodies.

Worker settings (all are read from environment variables): `WORKER_POLL_INTERVAL_SECONDS` (default `30`), `WORKER_MAX_DETAILS_PER_CYCLE` (default `10`), `WORKER_DETAILS_RECHECK_SECONDS` (default `3600`), `WORKER_DETAILS_RETRY_SECONDS` (default `60`), `WORKER_JOB_STALE_SECONDS` (default `300`), and `WORKER_JOB_MAX_ATTEMPTS` (default `3`). Failed detail requests and maps whose full draft is not available yet are retried on the shorter interval; the per-cycle detail cap still bounds API load. The 30-second cycle refreshes live games frequently while keeping API calls bounded; OpenDota publishes no guaranteed request quota, so adjust the interval and per-cycle cap to the account's actual provider limits. `PREDICTION_MODEL_NAME` defaults to `default`.

Official references: [OpenDota OpenAPI](https://api.opendota.com/api), [OpenDota API docs](https://docs.opendota.com/), [OpenDota API keys](https://www.opendota.com/api-keys), and [STRATZ GraphQL playground](https://api.stratz.com/graphiql).

## Batru draft predictions

The Batru adapter follows the documented `POST https://batru.gg/api/winrate` request with JSON `radiant` and `dire` arrays. The official SDK documents the response fields `radiant_win_rate` and `dire_win_rate` as percentages; the adapter validates the 0–100 range and normalizes them to the 0–1 values stored in PostgreSQL. It uses the default endpoint model and does not send positions or player IDs.

Before requesting a prediction, each picked `Hero` must have an explicit row in `batru_hero_mappings`. Populate the mapping only with canonical `shortName` values from Batru's published hero roster; do not use display names or assume another provider's hero ID has the same format. Completion means exactly five valid, distinct canonical heroes per side in the same game. Map completion is not required.

The callable entry point is `PredictionService.from_settings(session).predict_draft(draft_id)`. It is not exposed as a public route. The worker invokes it for each internally validated complete draft, including live or scheduled maps; if a Batru hero mapping is missing, the job is recorded as failed with a reason and no display-name substitution is attempted. The service releases its database transaction before the Batru request, then rechecks for an existing result before storing one. A database uniqueness constraint guarantees one persisted prediction per draft version and model.

### Verifying the worker

Follow structured key/value events and per-match identifiers:

```powershell
docker compose logs -f worker
```

Look for `event=worker_started`, `event=match_feed_received`, `event=match_upserted`, `event=draft_incomplete`, `event=draft_complete`, and `event=prediction_succeeded` / `event=prediction_failed`. Provider outages and HTTP 429/5xx retries are logged without stopping later cycles or other matches.

Inspect persisted maps, draft versions, jobs, and predictions in PostgreSQL:

```sql
SELECT m.external_match_id AS series_id,
       g.external_game_id AS map_id,
       g.game_number,
       g.status AS map_status,
       d.version AS draft_version,
       d.completed_at,
       j.status AS job_status,
       j.attempt_count,
       j.last_error,
       p.model_name,
       p.radiant_probability,
       p.dire_probability
FROM match_games AS g
JOIN matches AS m ON m.id = g.match_id
LEFT JOIN drafts AS d ON d.match_game_id = g.id
LEFT JOIN prediction_jobs AS j ON j.draft_id = d.id
LEFT JOIN predictions AS p
  ON p.draft_id = d.id AND p.model_name = j.model_name
ORDER BY g.started_at DESC NULLS LAST, d.version DESC;
```

`docker compose exec db psql -U dota2_analyzer -d dota2_analyzer` opens a PostgreSQL shell with the example credentials; substitute your configured user and database if different. Any SQL client can also connect to `localhost:5432`.

Network timeouts and HTTP 408, 429, and 5xx responses receive bounded retries. Other non-success HTTP responses and malformed provider responses are not retried. A 429 `Retry-After` value is honored up to 30 seconds; other transient retries use bounded exponential backoff. The public endpoint is documented as keyless, so no API key is required or configured. Batru documents per-IP rate limits and says hosted calls are logged; keep call volume reasonable.

Configuration is available through `.env`: `BATRU_BASE_URL`, `BATRU_TIMEOUT_SECONDS`, `BATRU_MAX_RETRIES`, and `BATRU_RETRY_BACKOFF_SECONDS`. Defaults target the documented Batru host, use an 8-second timeout, and allow two retries. The `PREDICTION_MODEL_NAME` value identifies this endpoint in local history; Batru itself has no model selector. Recreate the worker after changing `.env` so settings are passed into the container.

Batru's documented response does not include a model version. The configured local identifier (default `default`) distinguishes this endpoint path only; it cannot separate upstream model releases in prediction history.

Official contract references: [Batru developer documentation](https://batru.gg/developers), [Dota 2 methodology](https://batru.gg/dota2/methodology), and the [official Python SDK documentation](https://pypi.org/project/batru/).

## Read API examples

All application API routes use the `/api/v1` prefix. Match list responses have `items`, `total`, `offset`, and `limit`; an empty database returns `items: []` and `total: 0`.

```text
GET /api/v1/health
GET /api/v1/matches?status=completed&tournament_id=42&offset=0&limit=20&sort_order=asc
GET /api/v1/matches/tournaments
GET /api/v1/matches/{match_id}
GET /api/v1/matches/{match_id}/games
GET /api/v1/games/{game_id}/draft
GET /api/v1/games/{game_id}/predictions
GET /api/v1/games/{game_id}/prediction-jobs
```

The optional `status` filter supports the series statuses `unknown`, `scheduled`, `live`, `completed`, and `cancelled`; it filters series, not individual maps. `tournament_id` filters by the provider's stable league ID. When both are provided, they are combined with AND before sorting and pagination. Unsupported status values and malformed tournament IDs return `422`. `/matches/tournaments` returns unique leagues currently represented by stored matches as `{id, name}` records; matches without league data remain in the unfiltered result. OpenDota league IDs and names are persisted as new matches are synchronized.

`sort_order` sorts matches by their earliest known map start time (`asc` by default, `desc` supported); matches without a known start time are listed last. List sizes are capped at 100. The draft endpoint returns the highest stored draft version and includes `is_complete`, derived from its current persisted canonical picks; the legacy `completed_at` timestamp is informational, not the completion authority. A missing match or game returns `404`; an existing game without a stored draft also returns `404`. Prediction history is an empty `items` array when the game exists but has no predictions.

The prediction-jobs endpoint returns an `items` list for an existing game, including each draft version's model, state, attempt count, and last error. Job states are `queued`, `running`, `succeeded`, and `failed`; an empty list means no job has been created for that map yet. Match-game responses include `details_error` when the worker's most recent provider-details retrieval failed; a successful refresh clears it.

## Application logs and diagnostics

Backend and worker logs use the same UTC timestamp format with millisecond precision and are written to stdout/stderr. Set `LOG_LEVEL=DEBUG` in `.env` and recreate `api` and `worker` to enable detailed Python logs; the default is `INFO`. Frontend request diagnostics are disabled by default; set `VITE_DEBUG_LOGGING=true` and restart the frontend dev server to log request start, response status, and duration in the browser console. Logs include request paths and correlation IDs, but not request bodies or API responses.

Each HTTP request has an `X-Request-ID`, returned in the response and logged by the API. The worker creates a `cycle_id` per polling cycle, carried by its logs across live-feed retrieval and match ingestion. This project uses a polling worker and HTTP polling frontend; it currently has no Celery or WebSocket components.

```powershell
docker compose logs -f api worker
docker compose logs --since 30m api worker
docker compose logs --since 30m worker | Select-String 'cycle=YOUR_CYCLE_ID'
docker compose logs --since 30m worker | Select-String 'match_id=YOUR_MATCH_ID'
```

## Database migrations

Start PostgreSQL and apply the schema migration before starting the API and worker:

```powershell
docker compose up -d db
docker compose run --rm api alembic upgrade head
docker compose up -d
```

The Batru hero-mapping, per-model prediction, worker lifecycle, map-details error, and stable league ID migrations are included in this upgrade.

Create a later migration after changing models with:

```powershell
docker compose exec api alembic revision --autogenerate -m "describe the schema change"
```

Review generated migration operations before applying them. To inspect the current revision, run `docker compose exec api alembic current`.
