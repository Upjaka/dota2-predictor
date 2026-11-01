import logging
import re
from datetime import datetime

from app.core.logging import ContextFilter, UTCFormatter, cycle_id_var


def test_log_timestamp_has_milliseconds_and_utc_suffix():
    formatter = UTCFormatter("%(asctime)s")
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)

    timestamp = formatter.format(record)

    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", timestamp)
    assert datetime.fromisoformat(timestamp.replace("Z", "+00:00")).utcoffset().total_seconds() == 0


def test_context_filter_adds_current_correlation_ids():
    token = cycle_id_var.set("cycle-test")
    try:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
        ContextFilter().filter(record)
        assert record.component == "backend"
        assert record.cycle_id == "cycle-test"
        assert record.request_id is None
        assert record.task_id is None
    finally:
        cycle_id_var.reset(token)
