def status_from_series_score(
    current_status: str,
    series_format: str | None,
    team_one_wins: int,
    team_two_wins: int,
) -> str:
    if current_status == "completed":
        return current_status

    best_of = {"BO1": 1, "BO3": 3, "BO5": 5}.get(series_format)
    if best_of is None:
        return current_status

    wins_required = best_of // 2 + 1
    if max(team_one_wins, team_two_wins) >= wins_required:
        return "completed"
    return current_status
