"""formatting.py (表示フォーマットヘルパー) の単体テスト。"""

import pytest

from formatting import format_rate_triplet, format_yen


def test_format_rate_triplet_splits_hourly_into_minute_and_second():
    hourly, per_min, per_sec = format_rate_triplet(1200.0)
    assert hourly == format_yen(1200.0)
    assert per_min == "¥20.0"
    assert per_sec == "¥0.33"


def test_format_rate_triplet_handles_zero():
    hourly, per_min, per_sec = format_rate_triplet(0.0)
    assert hourly == "¥0"
    assert per_min == "¥0.0"
    assert per_sec == "¥0.00"
