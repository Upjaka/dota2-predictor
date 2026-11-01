from datetime import datetime, timedelta, timezone
from decimal import Decimal

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries

from scripts.generate_prediction_report import (
    Forecast,
    MapRow,
    _confidence_band_index,
    _confidence_range_stats,
    _confidence_threshold_stats,
    _stats,
    _team_stats,
    create_workbook,
    evaluate_maps,
)


NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


def make_map(index=1, *, radiant_won=True, radiant="Radiant FC", dire="Dire FC", forecasts=None, tournament="Cup"):
    return MapRow(
        game_id=f"game-{index}", external_id=f"match-{index}", game_number=1,
        started_at=NOW, status="completed", radiant_won=radiant_won,
        radiant_team=radiant, dire_team=dire, tournament_id="cup-id",
        tournament=tournament, series_id=f"series-{index}", format="BO3",
        radiant_score=2 if radiant_won is True else None,
        dire_score=0 if radiant_won is True else None,
        forecasts=tuple(forecasts or ()),
    )


def forecast(radiant="0.7", dire="0.3", *, when=NOW - timedelta(minutes=10), role="default"):
    return Forecast(Decimal(radiant), Decimal(dire), "batru", role, when)


def test_correct_and_incorrect_predictions_with_each_side_favorite():
    evaluations = evaluate_maps([
        make_map(1, radiant_won=True, forecasts=[forecast()]),
        make_map(2, radiant_won=False, forecasts=[forecast()]),
        make_map(3, radiant_won=False, forecasts=[forecast("0.2", "0.8")]),
    ])
    assert [item.reason for item in evaluations] == [None, None, None]
    assert _stats(evaluations)["correct"] == 2
    assert _stats(evaluations)["incorrect"] == 1
    assert _team_stats(evaluations) == [
        ("Обычный", "Radiant FC", 2, 1, 1, 0.5),
        ("Обычный", "Dire FC", 1, 1, 0, 1.0),
    ]


def test_ambiguous_missing_result_and_missing_forecast_are_excluded():
    evaluations = evaluate_maps([
        make_map(1, forecasts=[forecast("0.5", "0.5")]),
        make_map(2, radiant_won=None, forecasts=[forecast()]),
        make_map(3),
        make_map(4, radiant="Radiant FC", dire=None, forecasts=[forecast()]),
    ])
    assert [item.reason for item in evaluations] == [
        "Неоднозначные вероятности", "Нет фактического результата", "Нет прогноза", "Невозможно сопоставить команды"
    ]
    assert _stats(evaluations)["valid"] == 0


def test_latest_forecast_is_used_even_after_map_start_or_without_map_time():
    older = forecast("0.6", "0.4", when=NOW - timedelta(minutes=20))
    newer = forecast("0.8", "0.2", when=NOW - timedelta(minutes=5))
    late = forecast("0.9", "0.1", when=NOW + timedelta(minutes=1))
    selected = evaluate_maps([make_map(forecasts=[older, newer, late])])
    assert selected[0].forecast == late
    assert selected[0].reason is None
    assert sum(row["count"] for row in _confidence_range_stats(selected)) == 1
    assert _confidence_threshold_stats(selected)[0]["count"] == 1
    no_map_time = make_map(forecasts=[late])
    no_map_time = MapRow(**{**no_map_time.__dict__, "started_at": None})
    assert evaluate_maps([no_map_time])[0].forecast == late


def test_forecast_types_and_tournaments_remain_separate():
    items = evaluate_maps([
        make_map(1, forecasts=[forecast(), forecast("0.2", "0.8", role="abc")], tournament="Cup A"),
        make_map(2, forecasts=[forecast()], tournament="Cup B"),
    ])
    assert {item.kind for item in items} == {"Обычный", "С учётом ролей"}
    assert len([item for item in items if item.row.tournament == "Cup A"]) == 2
    assert len([item for item in items if item.row.tournament == "Cup B"]) == 1


def forecast_at(confidence, index, *, correct=True, role="default", tournament="Cup"):
    confidence = Decimal(confidence)
    radiant_won = correct
    radiant_probability = confidence
    dire_probability = Decimal(1) - confidence
    # A 50% forecast must still have a determinable favorite to be valid.
    if confidence == Decimal("0.50"):
        dire_probability = Decimal("0.4999")
    return make_map(
        index, radiant_won=radiant_won, tournament=tournament,
        forecasts=[forecast(str(radiant_probability), str(dire_probability), role=role)],
    )


def test_confidence_band_boundaries_are_exclusive_and_use_unrounded_values():
    values = ["0.5000", "0.5499", "0.55", "0.58", "0.60", "0.65", "0.70"]
    evaluations = evaluate_maps([forecast_at(value, i) for i, value in enumerate(values)])
    counts = [row["count"] for row in _confidence_range_stats(evaluations)]
    assert counts == [2, 1, 1, 1, 1, 1]
    assert sum(counts) == len(evaluations)
    assert _confidence_band_index(Decimal("0.499999")) is None
    assert _confidence_band_index(Decimal("0.5499")) == 0
    assert _confidence_band_index(Decimal("0.55")) == 1
    assert _confidence_band_index(Decimal("0.58")) == 2
    assert _confidence_band_index(Decimal("0.60")) == 3
    assert _confidence_band_index(Decimal("0.65")) == 4
    assert _confidence_band_index(Decimal("0.70")) == 5


def test_confidence_range_rates_average_and_deviation():
    evaluations = evaluate_maps([
        forecast_at("0.55", 1, correct=True),
        forecast_at("0.56", 2, correct=False),
        forecast_at("0.57", 3, correct=True),
    ])
    band = _confidence_range_stats(evaluations)[1]
    assert band["count"] == 3
    assert band["correct"] == 2
    assert band["incorrect"] == 1
    assert band["win_rate"] == Decimal(2) / 3
    assert band["average_confidence"] == Decimal("0.56")
    assert band["deviation"] == Decimal(2) / 3 - Decimal("0.56")
    empty_band = _confidence_range_stats([])[0]
    assert empty_band["count"] == 0
    assert empty_band["win_rate"] is None


def test_thresholds_are_strict_nested_and_sample_share_is_correct():
    values = ["0.55", "0.5501", "0.58", "0.5801", "0.70", "0.7001"]
    evaluations = evaluate_maps([forecast_at(value, i) for i, value in enumerate(values)])
    rows = _confidence_threshold_stats(evaluations)
    assert [row["count"] for row in rows] == [6, 5, 3, 2, 2, 1]
    assert all(a["count"] >= b["count"] for a, b in zip(rows, rows[1:]))
    assert rows[1]["sample_share"] == Decimal(5) / 6
    assert rows[1]["average_confidence"] == sum(map(Decimal, values[1:]), Decimal(0)) / 5
    assert _confidence_threshold_stats([])[0]["sample_share"] is None


def test_confidence_analyses_split_by_prediction_type_and_tournament():
    maps = [
        forecast_at("0.60", 1, role="default", tournament="Cup A"),
        forecast_at("0.80", 2, role="role-config", tournament="Cup B"),
    ]
    evaluations = evaluate_maps(maps)
    standard = [item for item in evaluations if item.kind == "Обычный"]
    role_aware = [item for item in evaluations if item.kind == "С учётом ролей"]
    assert _confidence_threshold_stats(standard)[0]["count"] == 1
    assert _confidence_threshold_stats(role_aware)[-1]["count"] == 1
    assert _confidence_range_stats([item for item in evaluations if item.row.tournament == "Cup A"])[3]["count"] == 1
    assert _confidence_range_stats([item for item in evaluations if item.row.tournament == "Cup B"])[5]["count"] == 1


def test_workbook_contains_formatted_confidence_tables_on_each_sheet(tmp_path):
    output = tmp_path / "report.xlsx"
    maps = [
        forecast_at("0.60", 1, role="default"),
        forecast_at("0.80", 2, role="role-config"),
    ]
    create_workbook(evaluate_maps(maps), output)
    workbook = load_workbook(output)
    assert workbook.sheetnames == ["Общая статистика", "Cup"]
    for sheet_name in workbook.sheetnames:
        ws = workbook[sheet_name]
        names = {table.displayName for table in ws.tables.values()}
        assert any(name.startswith("ConfidenceBands") for name in names)
        assert any(name.startswith("ConfidenceThresholds") for name in names)
        assert ws.auto_filter.ref is None
        assert all(table.autoFilter is not None for table in ws.tables.values())
        ranges = [range_boundaries(table.ref) for table in ws.tables.values()]
        assert all(
            a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]
            for i, a in enumerate(ranges)
            for b in ranges[i + 1:]
        )
        band_table = next(table for table in ws.tables.values() if table.displayName.startswith("ConfidenceBands"))
        threshold_table = next(table for table in ws.tables.values() if table.displayName.startswith("ConfidenceThresholds"))
        assert band_table.ref.split(":")[0][1:] == threshold_table.ref.split(":")[0][1:]
        assert ws["E" + str(int(band_table.ref.split(":")[0][1:]) + 1)].number_format == "0.00%"
        assert ws["G" + str(int(band_table.ref.split(":")[0][1:]) + 1)].number_format.endswith('"п.п."')
        assert ws["P" + str(int(threshold_table.ref.split(":")[0][1:]) + 1)].number_format == "0.00%"


def test_workbook_omits_confidence_tables_without_valid_forecasts(tmp_path):
    maps = [
        forecast_at("0.60", 1, role="default"),
        make_map(2, radiant_won=None, forecasts=[forecast("0.8", "0.2", role="role-config")]),
    ]
    output = tmp_path / "partial.xlsx"
    create_workbook(evaluate_maps(maps), output)
    workbook = load_workbook(output)
    for sheet_name in workbook.sheetnames:
        names = [table.displayName for table in workbook[sheet_name].tables.values()]
        assert sum(name.startswith("ConfidenceBands") for name in names) == 1
        assert sum(name.startswith("ConfidenceThresholds") for name in names) == 1
