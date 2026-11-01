"""Generate a read-only Excel report from stored match and prediction history.

Predictions are linked to maps through Prediction -> Draft -> MatchGame.
For each map and prediction type, the latest stored forecast is used regardless
of when it was recorded. Only maps without a known result are excluded from
accuracy calculations.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
import sys

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo
from sqlalchemy import select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Support both `python backend/scripts/...` from the repository root and
# `python scripts/...` from the backend directory on Windows.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models import Draft, Match, MatchGame, Prediction, Team


@dataclass(frozen=True)
class Forecast:
    radiant: Decimal
    dire: Decimal
    model: str
    role_signature: str
    calculated_at: datetime | None

    @property
    def kind(self) -> str:
        return "С учётом ролей" if self.role_signature != "default" else "Обычный"


@dataclass(frozen=True)
class MapRow:
    game_id: str
    external_id: str | None
    game_number: int
    started_at: datetime | None
    status: str
    radiant_won: bool | None
    radiant_team: str | None
    dire_team: str | None
    tournament_id: str | None
    tournament: str | None
    series_id: str
    format: str | None
    radiant_score: int | None
    dire_score: int | None
    forecasts: tuple[Forecast, ...]


@dataclass(frozen=True)
class Evaluation:
    row: MapRow
    kind: str | None
    forecast: Forecast | None
    reason: str | None


def evaluate_maps(maps: list[MapRow], prediction_type: str | None = None) -> list[Evaluation]:
    """Choose latest stored forecast per map and type, then classify it."""
    evaluations: list[Evaluation] = []
    for row in maps:
        grouped: dict[str, list[Forecast]] = defaultdict(list)
        for forecast in row.forecasts:
            kind = forecast.kind
            if prediction_type and kind != prediction_type:
                continue
            grouped[kind].append(forecast)

        kinds = sorted(grouped)
        if not kinds:
            evaluations.append(Evaluation(row, prediction_type, None, "Нет прогноза"))
            continue
        for kind in kinds:
            candidates = grouped.get(kind, [])
            chosen = max(candidates, key=lambda item: (_comparable(item.calculated_at), item.model, item.role_signature))
            reason = _forecast_problem(row, chosen)
            evaluations.append(Evaluation(row, kind, chosen, reason))
    return evaluations


def _comparable(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min
    return value.replace(tzinfo=None)


def _forecast_problem(row: MapRow, forecast: Forecast) -> str | None:
    if not row.radiant_team or not row.dire_team or row.radiant_team == row.dire_team:
        return "Невозможно сопоставить команды"
    if row.radiant_won is None:
        return "Нет фактического результата"
    try:
        radiant, dire = Decimal(forecast.radiant), Decimal(forecast.dire)
    except (InvalidOperation, TypeError, ValueError):
        return "Некорректные вероятности"
    if not radiant.is_finite() or not dire.is_finite() or not (0 <= radiant <= 1 and 0 <= dire <= 1):
        return "Некорректные вероятности"
    if abs(radiant + dire - 1) > Decimal("0.0002"):
        return "Некорректные вероятности"
    if radiant == dire:
        return "Неоднозначные вероятности"
    return None


def _winner_and_confidence(evaluation: Evaluation) -> tuple[str | None, Decimal | None, str | None]:
    if evaluation.forecast is None:
        return None, None, None
    row, forecast = evaluation.row, evaluation.forecast
    if not row.radiant_team or not row.dire_team or forecast.radiant == forecast.dire:
        return None, None, None
    if forecast.radiant > forecast.dire:
        return row.radiant_team, forecast.radiant, row.radiant_team if row.radiant_won else row.dire_team
    return row.dire_team, forecast.dire, row.dire_team if row.radiant_won is False else row.radiant_team


def _valid(evaluation: Evaluation) -> bool:
    return evaluation.reason is None and evaluation.forecast is not None


def _stats(evaluations: list[Evaluation]) -> dict[str, int | float | None]:
    completed = len({item.row.game_id for item in evaluations})
    valid = [item for item in evaluations if _valid(item)]
    correct = sum(_winner_and_confidence(item)[0] == _winner_and_confidence(item)[2] for item in valid)
    return {
        "completed": completed,
        "valid": len(valid),
        "correct": correct,
        "incorrect": len(valid) - correct,
        "accuracy": correct / len(valid) if valid else None,
    }


def _team_stats(evaluations: list[Evaluation]) -> list[tuple[str, str, int, int, int, float | None]]:
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for item in evaluations:
        if not _valid(item):
            continue
        favorite, _, actual = _winner_and_confidence(item)
        if favorite:
            key = (item.kind or "Нет прогноза", favorite)
            counts[key][0] += 1
            counts[key][1] += favorite == actual
    return [
        (kind, name, total, wins, total - wins, wins / total if total else None)
        for (kind, name), (total, wins) in sorted(counts.items(), key=lambda pair: (pair[0][0], -pair[1][0], -pair[1][1], pair[0][1].casefold()))
    ]


async def load_maps(tournament: str | None = None) -> list[MapRow]:
    """Load compact rows in a read-only PostgreSQL transaction (constant query count)."""
    database_url = _database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION READ ONLY"))
                stmt = (
                    select(
                        MatchGame.id, MatchGame.external_game_id, MatchGame.game_number,
                        MatchGame.started_at, MatchGame.status, MatchGame.radiant_won,
                        MatchGame.radiant_score, MatchGame.dire_score,
                        Match.league_id, Match.league_name, Match.external_match_id, Match.format,
                        Team.name.label("radiant_name"),
                    )
                    .join(Match, MatchGame.match_id == Match.id)
                    .outerjoin(Team, Team.id == MatchGame.radiant_team_id)
                    .where(MatchGame.status == "completed")
                    .order_by(MatchGame.started_at, MatchGame.id)
                )
                rows = (await session.execute(stmt)).all()
                # Fetch the opposite side and all forecasts in two batched queries.
                ids = [item.id for item in rows]
                if not ids:
                    return []
                side_rows = (await session.execute(
                    select(MatchGame.id, Team.name)
                    .outerjoin(Team, Team.id == MatchGame.dire_team_id)
                    .where(MatchGame.id.in_(ids))
                )).all()
                dire_names = {game_id: name for game_id, name in side_rows}
                prediction_rows = (await session.execute(
                    select(
                        Draft.match_game_id, Prediction.radiant_probability,
                        Prediction.dire_probability, Prediction.model_name,
                        Prediction.role_signature, Prediction.calculated_at,
                    )
                    .join(Prediction, Prediction.draft_id == Draft.id)
                    .where(Draft.match_game_id.in_(ids))
                    .order_by(Prediction.calculated_at)
                )).all()
                forecasts: dict[object, list[Forecast]] = defaultdict(list)
                for game_id, radiant, dire, model, roles, calculated in prediction_rows:
                    forecasts[game_id].append(Forecast(radiant, dire, model, roles, calculated))
                result = [MapRow(
                    game_id=str(item.id), external_id=item.external_game_id,
                    game_number=item.game_number, started_at=item.started_at,
                    status=item.status, radiant_won=item.radiant_won,
                    radiant_team=item.radiant_name, dire_team=dire_names.get(item.id),
                    tournament_id=item.league_id, tournament=item.league_name,
                    series_id=item.external_match_id, format=item.format,
                    radiant_score=item.radiant_score, dire_score=item.dire_score,
                    forecasts=tuple(forecasts[item.id]),
                ) for item in rows]
                if tournament:
                    needle = tournament.casefold()
                    result = [item for item in result if needle in (item.tournament_id or "").casefold() or needle in (item.tournament or "").casefold()]
                return result
    finally:
        await engine.dispose()


def _database_url() -> str | URL:
    """Use app DATABASE_URL, or the repository .env's Compose DB settings locally."""
    direct_url = os.environ.get("DATABASE_URL")
    if direct_url:
        return direct_url
    try:
        from dotenv import dotenv_values
        env_values = dotenv_values(BACKEND_DIR.parent / ".env")
    except ImportError as exc:
        raise ValueError("Не найдена настройка DATABASE_URL и недоступен разбор .env") from exc
    values = {**env_values, **os.environ}
    database = values.get("POSTGRES_DB")
    username = values.get("POSTGRES_USER")
    password = values.get("POSTGRES_PASSWORD")
    if not (database and username and password):
        raise ValueError("DATABASE_URL или POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD не настроены")
    try:
        port = int(values.get("POSTGRES_PORT", "5432"))
    except ValueError as exc:
        raise ValueError("Некорректный POSTGRES_PORT") from exc
    return URL.create(
        "postgresql+asyncpg", username=username, password=password,
        host=values.get("POSTGRES_HOST", "localhost"), port=port, database=database,
    )


def _safe_sheet_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[\\/*?:\[\]]", "_", name).strip("' ") or "Турнир"
    base = base[:31]
    candidate, index = base, 2
    while candidate.casefold() in used:
        suffix = f" ({index})"
        candidate = f"{base[:31-len(suffix)]}{suffix}"
        index += 1
    used.add(candidate.casefold())
    return candidate


HEADERS = ["Дата", "Турнир", "Матч / карта", "Match ID", "Radiant", "Dire", "Фаворит", "Уверенность", "Победитель", "Результат", "P(Radiant)", "P(Dire)", "Тип прогноза", "Модель", "Время прогноза", "Причина исключения", "Счёт"]


def _write_sheet(workbook: Workbook, title: str, evaluations: list[Evaluation], *, overall: bool = False) -> None:
    ws = workbook.create_sheet(title)
    ws.append(["Сводная статистика по типам прогнозов", "Завершено карт", "Валидных", "Правильных", "Неправильных", "Точность"])
    ws.append(["Всего завершённых карт", len({item.row.game_id for item in evaluations})])
    kinds = sorted({item.kind for item in evaluations if item.kind} or {"Нет прогноза"})
    for kind in kinds:
        values = _stats([item for item in evaluations if item.kind == kind])
        ws.append([kind, values["completed"], values["valid"], values["correct"], values["incorrect"], values["accuracy"]])
        ws.cell(ws.max_row, 6).number_format = "0.00%"
    if overall:
        ws.append(["Учтённых турниров", len({item.row.tournament_id for item in evaluations if item.row.tournament_id})])
    for cell in ws[1][:6]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    start = ws.max_row + 2
    for col, header in enumerate(HEADERS, 1):
        ws.cell(start, col, header)
    for index, item in enumerate(sorted(evaluations, key=lambda x: (x.row.started_at or datetime.min, x.row.game_number, x.row.game_id, x.kind or "")), start + 1):
        row, forecast = item.row, item.forecast
        favorite, confidence, winner = _winner_and_confidence(item)
        result = ("Правильный" if favorite == winner else "Неправильный") if _valid(item) else None
        ws.append([
            _excel_datetime(row.started_at), row.tournament, f"{row.series_id} — карта {row.game_number}",
            row.external_id or row.game_id, row.radiant_team, row.dire_team, favorite,
            float(confidence) if confidence is not None else None, winner, result,
            float(forecast.radiant) if forecast else None, float(forecast.dire) if forecast else None,
            item.kind, forecast.model if forecast else None, _excel_datetime(forecast.calculated_at) if forecast else None,
            item.reason, f"{row.radiant_score} : {row.dire_score}" if row.radiant_score is not None and row.dire_score is not None else None,
        ])
    last = start + len(evaluations)
    if evaluations:
        ref = f"A{start}:Q{last}"
        table = Table(displayName=f"MatchHistory{len(workbook.worksheets)}", ref=ref)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False)
        ws.add_table(table)
        # Excel Tables own their AutoFilter in table*.xml. A second worksheet
        # AutoFilter over the same range makes Excel repair and discard tables.
        ws.freeze_panes = f"A{start+1}"
        ws.conditional_formatting.add(f"J{start+1}:J{last}", CellIsRule(operator="equal", formula=['"Правильный"'], fill=PatternFill("solid", fgColor="C6EFCE")))
        ws.conditional_formatting.add(f"J{start+1}:J{last}", CellIsRule(operator="equal", formula=['"Неправильный"'], fill=PatternFill("solid", fgColor="FFC7CE")))
        for r in range(start + 1, last + 1):
            ws.cell(r, 1).number_format = "yyyy-mm-dd hh:mm"
            ws.cell(r, 15).number_format = "yyyy-mm-dd hh:mm"
            for c in (8, 11, 12):
                ws.cell(r, c).number_format = "0.00%"
    team_start = 2
    team_col = 19
    ws.cell(1, team_col, "Статистика прогнозов по командам")
    ws.cell(1, team_col).font = Font(bold=True, color="FFFFFF")
    ws.cell(1, team_col).fill = PatternFill("solid", fgColor="1F4E78")
    for col, header in enumerate(["Тип прогноза", "Команда", "Предиктов", "Правильных", "Неправильных", "Винрейт"], team_col):
        ws.cell(team_start, col, header)
    for offset, values in enumerate(_team_stats(evaluations), team_start + 1):
        for col, value in enumerate(values, team_col):
            ws.cell(offset, col, value)
        ws.cell(offset, team_col + 5).number_format = "0.00%"
    if _team_stats(evaluations):
        end = team_start + len(_team_stats(evaluations))
        table = Table(displayName=f"TeamStats{len(workbook.worksheets)}", ref=f"S{team_start}:X{end}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium4", showRowStripes=True)
        ws.add_table(table)
    excluded = Counter((item.kind or "Не определён", item.reason) for item in evaluations if item.reason)
    reason_row = max(last + 3, 12)
    ws.cell(reason_row, 1, "Исключённые из точности по типам")
    ws.cell(reason_row, 1).font = Font(bold=True)
    for col, header in enumerate(["Тип прогноза", "Причина", "Карт"], 1):
        ws.cell(reason_row + 1, col, header)
    for offset, ((kind, reason), count) in enumerate(sorted(excluded.items()), reason_row + 2):
        ws.cell(offset, 1, kind)
        ws.cell(offset, 2, reason)
        ws.cell(offset, 3, count)
    widths = {1: 19, 2: 28, 3: 25, 4: 22, 5: 22, 6: 22, 7: 22, 8: 15, 9: 22, 10: 17, 11: 14, 12: 14, 13: 20, 14: 18, 15: 20, 16: 42, 17: 12, 19: 20, 20: 28, 21: 14, 22: 16, 23: 18, 24: 14}
    for column, width in widths.items():
        ws.column_dimensions[ws.cell(1, column).column_letter].width = width
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=cell.column in (2, 7, 9, 13, 16, 19))


def _excel_datetime(value: datetime | None) -> datetime | None:
    """Excel lacks timezone-aware cells; preserve instants as UTC wall time."""
    if value is None or value.tzinfo is None:
        return value
    from datetime import timezone
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def create_workbook(evaluations: list[Evaluation], output_path: Path) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    used: set[str] = set()
    _write_sheet(workbook, _safe_sheet_name("Общая статистика", used), evaluations, overall=True)
    tournaments: dict[tuple[str, str], list[Evaluation]] = defaultdict(list)
    for item in evaluations:
        if item.row.tournament_id:
            tournaments[(item.row.tournament_id, item.row.tournament or item.row.tournament_id)].append(item)
    for (_tournament_id, name), items in sorted(tournaments.items(), key=lambda pair: pair[0][1].casefold()):
        _write_sheet(workbook, _safe_sheet_name(name, used), items)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Создать локальный Excel-отчёт по историческим прогнозам из PostgreSQL.")
    parser.add_argument("-o", "--output", type=Path, help="Путь выходного .xlsx (по умолчанию reports/predictions_ГГГГММДД_ЧЧММСС.xlsx)")
    parser.add_argument("--tournament", help="Фильтр по части ID или названия турнира")
    parser.add_argument("--prediction-type", choices=["standard", "role-aware"], help="Тип прогноза: standard (обычный) или role-aware (с учётом ролей)")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> Path:
    now = datetime.now().astimezone()
    output = args.output or Path("reports") / f"predictions_{now:%Y%m%d_%H%M%S}.xlsx"
    if output.suffix.lower() != ".xlsx":
        raise ValueError("Путь отчёта должен иметь расширение .xlsx")
    maps = await load_maps(args.tournament)
    prediction_type = {"standard": "Обычный", "role-aware": "С учётом ролей"}.get(args.prediction_type)
    evaluations = evaluate_maps(maps, prediction_type)
    create_workbook(evaluations, output)
    return output


def main() -> int:
    args = parse_args()
    try:
        output = asyncio.run(_run(args))
    except SQLAlchemyError as exc:
        # Driver exception strings may contain the full connection URL.
        print(f"Не удалось прочитать базу или сохранить отчёт ({type(exc).__name__}). Проверьте DATABASE_URL и доступность PostgreSQL.", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        # Pydantic validation messages can echo unrelated .env values; keep the
        # CLI diagnostic generic and direct the user to configuration instead.
        if type(exc).__name__ == "ValidationError":
            print("Конфигурация приложения некорректна. Проверьте DATABASE_URL в окружении или .env.", file=sys.stderr)
        else:
            print(f"Не удалось создать отчёт: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"Отчёт создан: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
