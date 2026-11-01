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
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
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


CONFIDENCE_BANDS = (
    ("50–55%", Decimal("0.50"), Decimal("0.55")),
    ("55–58%", Decimal("0.55"), Decimal("0.58")),
    ("58–60%", Decimal("0.58"), Decimal("0.60")),
    ("60–65%", Decimal("0.60"), Decimal("0.65")),
    ("65–70%", Decimal("0.65"), Decimal("0.70")),
    ("70% и выше", Decimal("0.70"), None),
)
CONFIDENCE_THRESHOLDS = tuple(
    Decimal(value) for value in ("0.50", "0.55", "0.58", "0.60", "0.65", "0.70")
)


def _confidence_band_index(confidence: Decimal) -> int | None:
    for index, (_label, lower, upper) in enumerate(CONFIDENCE_BANDS):
        if confidence >= lower and (upper is None or confidence < upper):
            return index
    return None


def _scored_forecasts(evaluations: list[Evaluation]) -> list[tuple[Evaluation, Decimal, bool]]:
    scored: list[tuple[Evaluation, Decimal, bool]] = []
    for item in evaluations:
        if not _valid(item):
            continue
        favorite, confidence, actual = _winner_and_confidence(item)
        if favorite is not None and confidence is not None:
            scored.append((item, confidence, favorite == actual))
    return scored


def _confidence_range_stats(evaluations: list[Evaluation]) -> list[dict[str, object]]:
    """Return mutually exclusive confidence-band stats using unrounded Decimal values."""
    scored = _scored_forecasts(evaluations)
    result = []
    for band_index, (label, _lower, _upper) in enumerate(CONFIDENCE_BANDS):
        band = [
            (item, confidence, correct)
            for item, confidence, correct in scored
            if _confidence_band_index(confidence) == band_index
        ]
        count = len(band)
        correct_count = sum(correct for _, _, correct in band)
        rate = Decimal(correct_count) / count if count else None
        average = sum((confidence for _, confidence, _ in band), Decimal(0)) / count if count else None
        result.append({
            "band": label,
            "count": count,
            "correct": correct_count,
            "incorrect": count - correct_count,
            "win_rate": rate,
            "average_confidence": average,
            "deviation": rate - average if rate is not None and average is not None else None,
        })
    return result


def _confidence_threshold_stats(evaluations: list[Evaluation]) -> list[dict[str, object]]:
    """Return cumulative stats for forecasts strictly above each threshold."""
    scored = _scored_forecasts(evaluations)
    total = len(scored)
    result = []
    for threshold in CONFIDENCE_THRESHOLDS:
        selected = [(item, confidence, correct) for item, confidence, correct in scored if confidence > threshold]
        count = len(selected)
        correct_count = sum(correct for _, _, correct in selected)
        result.append({
            "threshold": threshold,
            "count": count,
            "correct": correct_count,
            "incorrect": count - correct_count,
            "win_rate": Decimal(correct_count) / count if count else None,
            "average_confidence": sum((confidence for _, confidence, _ in selected), Decimal(0)) / count if count else None,
            "sample_share": Decimal(count) / total if total else None,
        })
    return result


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


def _write_confidence_tables(
    ws,
    evaluations: list[Evaluation],
    kind: str,
    start_row: int,
    sheet_index: int,
    type_index: int,
) -> int:
    """Write the two independent confidence analyses for one forecast type."""
    bands = _confidence_range_stats(evaluations)
    thresholds = _confidence_threshold_stats(evaluations)
    left_col, right_col = 1, 10
    ws.cell(start_row, left_col, f"Точность по диапазонам уверенности — {kind}")
    ws.cell(start_row, right_col, f"Накопительная точность по порогам — {kind}")
    for col in (left_col, right_col):
        cell = ws.cell(start_row, col)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")

    band_headers = ["Диапазон", "Прогнозов", "Правильных", "Неправильных", "Винрейт", "Средняя уверенность", "Отклонение, п.п."]
    threshold_headers = ["Порог", "Прогнозов", "Правильных", "Неправильных", "Винрейт", "Средняя уверенность", "Доля выборки"]
    header_row = start_row + 1
    for offset, header in enumerate(band_headers):
        ws.cell(header_row, left_col + offset, header)
    for offset, header in enumerate(threshold_headers):
        ws.cell(header_row, right_col + offset, header)

    first_data_row = header_row + 1
    for row_offset, values in enumerate(bands):
        row = first_data_row + row_offset
        ws.cell(row, left_col, values["band"])
        for offset, key in enumerate(("count", "correct", "incorrect"), 1):
            ws.cell(row, left_col + offset, values[key])
        for offset, key in enumerate(("win_rate", "average_confidence", "deviation"), 4):
            value = values[key]
            cell = ws.cell(row, left_col + offset, float(value) if value is not None else None)
            if key == "deviation":
                cell.number_format = '+0.00% "п.п.";-0.00% "п.п.";0.00% "п.п."'
            else:
                cell.number_format = "0.00%"

    for row_offset, values in enumerate(thresholds):
        row = first_data_row + row_offset
        ws.cell(row, right_col, f">{float(values['threshold']):.0%}")
        for offset, key in enumerate(("count", "correct", "incorrect"), 1):
            ws.cell(row, right_col + offset, values[key])
        for offset, key in enumerate(("win_rate", "average_confidence", "sample_share"), 4):
            value = values[key]
            ws.cell(row, right_col + offset, float(value) if value is not None else None).number_format = "0.00%"

    last_data_row = first_data_row + len(bands) - 1
    table_specs = (
        (f"ConfidenceBands{sheet_index}_{type_index}", f"A{header_row}:G{last_data_row}", "TableStyleMedium4"),
        (f"ConfidenceThresholds{sheet_index}_{type_index}", f"J{header_row}:P{last_data_row}", "TableStyleMedium4"),
    )
    for name, ref, style in table_specs:
        table = Table(displayName=name, ref=ref)
        table.tableStyleInfo = TableStyleInfo(name=style, showRowStripes=True)
        ws.add_table(table)
    return last_data_row


def _section_title(ws, row: int, title: str, end_col: int) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=end_col)
    cell = ws.cell(row, 1, title)
    cell.font = Font(bold=True, color="FFFFFF", size=12)
    cell.fill = PatternFill("solid", fgColor="1F4E78")
    cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[row].height = 23


def _write_sheet(workbook: Workbook, title: str, evaluations: list[Evaluation], *, overall: bool = False) -> None:
    ws = workbook.create_sheet(title)
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.autoPageBreaks = False

    stats = _stats(evaluations)
    scored = _scored_forecasts(evaluations)
    avg_confidence = sum((confidence for _, confidence, _ in scored), Decimal(0)) / len(scored) if scored else None
    tournament_count = len({item.row.tournament_id for item in evaluations if item.row.tournament_id})

    _section_title(ws, 1, "DraftWatch · общая сводка" if overall else f"DraftWatch · {title}", 8)
    cards = [
        ("Валидных прогнозов", stats["valid"], "#,##0"),
        ("Правильных", stats["correct"], "#,##0"),
        ("Неправильных", stats["incorrect"], "#,##0"),
        ("Точность", stats["accuracy"], "0.00%"),
        ("Средняя уверенность", float(avg_confidence) if avg_confidence is not None else None, "0.00%"),
        ("Турниров", tournament_count if overall else 1, "#,##0"),
    ]
    for index, (label, value, number_format) in enumerate(cards):
        col = index * 2 + 1
        ws.merge_cells(start_row=2, start_column=col, end_row=2, end_column=col + 1)
        ws.merge_cells(start_row=3, start_column=col, end_row=3, end_column=col + 1)
        label_cell = ws.cell(2, col, label)
        value_cell = ws.cell(3, col, value)
        label_cell.font = Font(color="44546A", bold=True, size=10)
        label_cell.fill = PatternFill("solid", fgColor="D9E2F3")
        value_cell.font = Font(color="1F1F1F", bold=True, size=16)
        value_cell.fill = PatternFill("solid", fgColor="F2F6FC")
        value_cell.number_format = number_format
        label_cell.alignment = value_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 28
    ws.row_dimensions[3].height = 32

    kinds = sorted({item.kind for item in evaluations if item.kind} or {"Нет прогноза"})
    _section_title(ws, 5, "Сводка по типам прогнозов", 6)
    summary_headers = ["Тип прогноза", "Завершено карт", "Валидных", "Правильных", "Неправильных", "Точность"]
    for col, header in enumerate(summary_headers, 1):
        cell = ws.cell(6, col, header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="5B7FA3")
    for row_index, kind in enumerate(kinds, 7):
        values = _stats([item for item in evaluations if item.kind == kind])
        row_values = [kind, values["completed"], values["valid"], values["correct"], values["incorrect"], values["accuracy"]]
        for col, value in enumerate(row_values, 1):
            ws.cell(row_index, col, value)
        ws.cell(row_index, 6).number_format = "0.00%"

    cursor = 7 + len(kinds) + 1
    confidence_last = cursor
    table_type_index = 0
    for kind in sorted({item.kind for item in evaluations if item.kind}):
        type_evaluations = [item for item in evaluations if item.kind == kind]
        if not _scored_forecasts(type_evaluations):
            continue
        table_type_index += 1
        _section_title(ws, cursor, f"Качество по уверенности · {kind}", 16)
        confidence_last = _write_confidence_tables(ws, type_evaluations, kind, cursor + 1, len(workbook.worksheets), table_type_index)
        cursor = confidence_last + 2

    # A chart makes the non-overlapping confidence bands easy to compare.
    band_table = next((table for table in ws.tables.values() if table.displayName.startswith("ConfidenceBands")), None)
    if band_table:
        from openpyxl.utils.cell import range_boundaries
        min_col, min_row, max_col, max_row = range_boundaries(band_table.ref)
        chart = BarChart()
        chart.type = "col"
        chart.style = 10
        chart.title = "Точность по диапазонам уверенности"
        chart.y_axis.title = "Точность"
        chart.y_axis.numFmt = "0%"
        chart.y_axis.scaling.min = 0
        chart.y_axis.scaling.max = 1
        chart.x_axis.title = "Уверенность"
        chart.add_data(Reference(ws, min_col=min_col + 4, min_row=min_row, max_row=max_row), titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=min_col, min_row=min_row + 1, max_row=max_row))
        chart.height, chart.width = 7, 15
        ws.add_chart(chart, f"A{cursor}")
        cursor += 16

    team_stats = _team_stats(evaluations)
    if team_stats:
        _section_title(ws, cursor, "Прогнозы в пользу команд", 6)
        team_start = cursor + 1
        for col, header in enumerate(["Тип прогноза", "Команда", "Прогнозов", "Правильных", "Неправильных", "Винрейт"], 1):
            ws.cell(team_start, col, header)
        for row_index, values in enumerate(team_stats, team_start + 1):
            for col, value in enumerate(values, 1):
                ws.cell(row_index, col, value)
            ws.cell(row_index, 6).number_format = "0.00%"
        end = team_start + len(team_stats)
        table = Table(displayName=f"TeamStats{len(workbook.worksheets)}", ref=f"A{team_start}:F{end}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium4", showRowStripes=True)
        ws.add_table(table)
        cursor = end + 2

    excluded = Counter((item.kind or "Не определён", item.reason) for item in evaluations if item.reason)
    if excluded:
        _section_title(ws, cursor, "Исключённые из расчёта точности", 3)
        reason_start = cursor + 1
        for col, header in enumerate(["Тип прогноза", "Причина", "Карт"], 1):
            ws.cell(reason_start, col, header)
        for row_index, ((kind, reason), count) in enumerate(sorted(excluded.items()), reason_start + 1):
            ws.cell(row_index, 1, kind)
            ws.cell(row_index, 2, reason)
            ws.cell(row_index, 3, count)
        end = reason_start + len(excluded)
        table = Table(displayName=f"Exclusions{len(workbook.worksheets)}", ref=f"A{reason_start}:C{end}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium4", showRowStripes=True)
        ws.add_table(table)
        cursor = end + 2

    start = cursor + 1
    _section_title(ws, start, "История матчей и прогнозов", len(HEADERS))
    table_start = start + 1
    for col, header in enumerate(HEADERS, 1):
        ws.cell(table_start, col, header)
    ordered = sorted(evaluations, key=lambda x: (x.row.started_at or datetime.min, x.row.game_number, x.row.game_id, x.kind or ""))
    for row_index, item in enumerate(ordered, table_start + 1):
        row, forecast = item.row, item.forecast
        favorite, confidence, winner = _winner_and_confidence(item)
        result = ("Правильный" if favorite == winner else "Неправильный") if _valid(item) else None
        values = [
            _excel_datetime(row.started_at), row.tournament, f"{row.series_id} — карта {row.game_number}",
            row.external_id or row.game_id, row.radiant_team, row.dire_team, favorite,
            float(confidence) if confidence is not None else None, winner, result,
            float(forecast.radiant) if forecast else None, float(forecast.dire) if forecast else None,
            item.kind, forecast.model if forecast else None, _excel_datetime(forecast.calculated_at) if forecast else None,
            item.reason, f"{row.radiant_score} : {row.dire_score}" if row.radiant_score is not None and row.dire_score is not None else None,
        ]
        for col, value in enumerate(values, 1):
            ws.cell(row_index, col, value)
        ws.cell(row_index, 1).number_format = ws.cell(row_index, 15).number_format = "yyyy-mm-dd hh:mm"
        for col in (8, 11, 12):
            ws.cell(row_index, col).number_format = "0.00%"
    if ordered:
        last = table_start + len(ordered)
        table = Table(displayName=f"MatchHistory{len(workbook.worksheets)}", ref=f"A{table_start}:Q{last}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False)
        ws.add_table(table)
        ws.conditional_formatting.add(f"J{table_start+1}:J{last}", CellIsRule(operator="equal", formula=['"Правильный"'], fill=PatternFill("solid", fgColor="C6EFCE")))
        ws.conditional_formatting.add(f"J{table_start+1}:J{last}", CellIsRule(operator="equal", formula=['"Неправильный"'], fill=PatternFill("solid", fgColor="FFC7CE")))

    widths = {1: 24, 2: 32, 3: 29, 4: 24, 5: 22, 6: 22, 7: 23, 8: 15, 9: 23, 10: 18, 11: 15, 12: 15, 13: 22, 14: 24, 15: 22, 16: 38, 17: 14}
    for column, width in widths.items():
        ws.column_dimensions[get_column_letter(column)].width = width
    for row in ws.iter_rows():
        for cell in row:
            if cell.alignment == Alignment():
                cell.alignment = Alignment(vertical="top", wrap_text=cell.column in (2, 3, 5, 6, 7, 9, 13, 14, 16))


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
