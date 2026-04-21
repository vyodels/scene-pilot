from __future__ import annotations

from recruit_agent.db.base import UnixTimestamp


def test_unix_timestamp_process_result_value_accepts_epoch_int() -> None:
    column = UnixTimestamp()

    value = column.process_result_value(1_713_202_800, None)

    assert value == 1_713_202_800


def test_unix_timestamp_process_result_value_accepts_iso_datetime_string() -> None:
    column = UnixTimestamp()

    value = column.process_result_value("2026-04-16 16:48:41.419759", None)

    assert value == 1776358121
