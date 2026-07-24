"""wage.py (時給計算エンジン)の単体テスト。

`src` を import path に含める前提。pyproject.toml の [tool.flet.app] path="src" と
揃え、pytest 実行時は conftest.py で src をパスに追加する。
"""

from datetime import datetime

import pytest

from models import BonusType, RuleKind, WageRule, Workplace, WorkSession, SessionPause
from wage import (
    compute_earnings,
    earnings_so_far,
    effective_rate,
    finalize_amount,
    is_currently_paused,
)


def make_workplace(**kwargs) -> Workplace:
    defaults = dict(name="テストバイト", base_wage=1000.0)
    defaults.update(kwargs)
    return Workplace(**defaults)


def test_base_wage_only_no_rules():
    wp = make_workplace(base_wage=1000.0)
    start = datetime(2026, 7, 20, 10, 0)  # 2026-07-20 は月曜日
    end = datetime(2026, 7, 20, 11, 0)
    assert compute_earnings(wp, [], start, end) == pytest.approx(1000.0)


def test_effective_rate_plain():
    wp = make_workplace(base_wage=1200.0)
    dt = datetime(2026, 7, 20, 12, 0)
    assert effective_rate(wp, [], dt) == pytest.approx(1200.0)


def test_time_band_add_rule_crossing_boundary():
    """17:00-19:00の勤務で、16:00-18:00に+200円のルールがまたがるケース。

    17:00-18:00: 1000+200=1200円/時 の1時間
    18:00-19:00: 1000円/時 の1時間
    合計 2200円
    """
    wp = make_workplace(base_wage=1000.0)
    rule = WageRule(
        workplace_id=1,
        kind=RuleKind.TIME_BAND,
        bonus_type=BonusType.ADD,
        amount=200.0,
        start_time=datetime(2026, 7, 20, 16, 0).time(),
        end_time=datetime(2026, 7, 20, 18, 0).time(),
    )
    start = datetime(2026, 7, 20, 17, 0)
    end = datetime(2026, 7, 20, 19, 0)
    assert compute_earnings(wp, [rule], start, end) == pytest.approx(2200.0)


def test_time_band_rule_respects_day_of_week():
    """day_of_week指定のルールは、その曜日以外には適用されない。"""
    wp = make_workplace(base_wage=1000.0)
    # 2026-07-20 は月曜(weekday=0)。ルールは火曜(weekday=1)限定のため不発。
    rule = WageRule(
        workplace_id=1,
        kind=RuleKind.TIME_BAND,
        bonus_type=BonusType.ADD,
        amount=500.0,
        start_time=datetime(2026, 7, 20, 16, 0).time(),
        end_time=datetime(2026, 7, 20, 18, 0).time(),
        day_of_week=1,
    )
    start = datetime(2026, 7, 20, 16, 0)
    end = datetime(2026, 7, 20, 17, 0)
    assert compute_earnings(wp, [rule], start, end) == pytest.approx(1000.0)


def test_weekday_multiply_rule_whole_day():
    """土曜(weekday=5)は全日1.5倍、というルール。"""
    wp = make_workplace(base_wage=1000.0)
    rule = WageRule(
        workplace_id=1,
        kind=RuleKind.WEEKDAY,
        bonus_type=BonusType.MULTIPLY,
        amount=1.5,
        day_of_week=5,
    )
    # 2026-07-25 は土曜日
    start = datetime(2026, 7, 25, 10, 0)
    end = datetime(2026, 7, 25, 12, 0)
    assert compute_earnings(wp, [rule], start, end) == pytest.approx(3000.0)


def test_night_premium_default_crossing_midnight():
    """深夜割増(22:00-翌5:00, +25%)が完全に含まれるケース。"""
    wp = make_workplace(base_wage=1000.0, night_premium_enabled=True)
    start = datetime(2026, 7, 20, 23, 0)
    end = datetime(2026, 7, 21, 1, 0)  # 2時間、すべて深夜帯
    assert compute_earnings(wp, [], start, end) == pytest.approx(1000.0 * 1.25 * 2)


def test_night_premium_partial_overlap():
    """21:00-23:00の勤務。21-22時は通常、22-23時は深夜割増。"""
    wp = make_workplace(base_wage=1000.0, night_premium_enabled=True)
    start = datetime(2026, 7, 20, 21, 0)
    end = datetime(2026, 7, 20, 23, 0)
    expected = 1000.0 * 1 + 1000.0 * 1.25 * 1
    assert compute_earnings(wp, [], start, end) == pytest.approx(expected)


def test_night_premium_disabled_by_default():
    wp = make_workplace(base_wage=1000.0, night_premium_enabled=False)
    start = datetime(2026, 7, 20, 23, 0)
    end = datetime(2026, 7, 21, 1, 0)
    assert compute_earnings(wp, [], start, end) == pytest.approx(2000.0)


def test_explicit_night_rule_overrides_auto_default():
    """明示的なNIGHT_PREMIUMルールがあれば、night_premium_enabledの自動デフォルトは使われない。"""
    wp = make_workplace(base_wage=1000.0, night_premium_enabled=True)
    custom_rule = WageRule(
        workplace_id=1,
        kind=RuleKind.NIGHT_PREMIUM,
        bonus_type=BonusType.ADD,
        amount=100.0,  # 倍率でなく固定+100円/時のカスタム深夜手当
        start_time=datetime(2026, 7, 20, 22, 0).time(),
        end_time=datetime(2026, 7, 21, 5, 0).time(),
    )
    start = datetime(2026, 7, 20, 23, 0)
    end = datetime(2026, 7, 21, 1, 0)
    # 自動+25%ではなく、明示ルールの+100円/時のみが適用される
    assert compute_earnings(wp, [custom_rule], start, end) == pytest.approx(1100.0 * 2)


def test_break_minutes_proportional_deduction():
    """休憩30分(概算按分)を差し引くと、実働按分で金額が減る。"""
    wp = make_workplace(base_wage=1000.0)
    start = datetime(2026, 7, 20, 10, 0)
    end = datetime(2026, 7, 20, 12, 0)  # 2時間のうち30分休憩
    earnings = compute_earnings(wp, [], start, end, break_minutes=30)
    # 総額(休憩無視)2000円 * (1.5h/2h) = 1500円
    assert earnings == pytest.approx(1500.0)


def test_earnings_so_far_with_pause_precise():
    """一時停止(pause)は正確な実時間で差し引かれる(概算ではない)。"""
    wp = make_workplace(base_wage=2000.0)  # 秒給計算しやすいよう時給2000円
    session = WorkSession(
        workplace_id=1,
        start_ts=datetime(2026, 7, 20, 10, 0),
        id=1,
    )
    session.pauses.append(
        SessionPause(
            session_id=1,
            pause_ts=datetime(2026, 7, 20, 10, 30),
            resume_ts=datetime(2026, 7, 20, 11, 0),
        )
    )
    now = datetime(2026, 7, 20, 11, 30)  # 経過1.5h、うち0.5h停止 => 実働1h
    assert earnings_so_far(wp, [], session, now=now) == pytest.approx(2000.0)


def test_earnings_so_far_currently_paused_excludes_ongoing_pause():
    """resume_tsがまだ無い(＝現在停止中)場合、nowまでを停止として扱う。"""
    wp = make_workplace(base_wage=1000.0)
    session = WorkSession(
        workplace_id=1,
        start_ts=datetime(2026, 7, 20, 9, 0),
        id=1,
    )
    session.pauses.append(
        SessionPause(
            session_id=1,
            pause_ts=datetime(2026, 7, 20, 9, 30),
            resume_ts=None,
        )
    )
    now = datetime(2026, 7, 20, 10, 0)  # 9:00-9:30稼働(0.5h)、9:30-10:00停止中
    assert earnings_so_far(wp, [], session, now=now) == pytest.approx(500.0)
    assert is_currently_paused(session) is True


def test_finalize_amount_adds_transport():
    wp = make_workplace(base_wage=1000.0, transport_allowance=300.0)
    assert finalize_amount(1000.0, wp, include_transport=True) == pytest.approx(1300.0)
    assert finalize_amount(1000.0, wp, include_transport=False) == pytest.approx(1000.0)


def test_zero_or_negative_duration_returns_zero():
    wp = make_workplace(base_wage=1000.0)
    start = datetime(2026, 7, 20, 10, 0)
    assert compute_earnings(wp, [], start, start) == 0.0
    assert compute_earnings(wp, [], start, start.replace(hour=9)) == 0.0
