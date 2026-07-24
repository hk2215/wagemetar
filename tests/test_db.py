"""db.py (SQLiteリポジトリ層)の単体テスト。各テストは使い捨ての ":memory:" DBを使う。"""

from datetime import date, datetime, time

import pytest

from db import Database
from models import (
    AssetCategory,
    AssetItem,
    AssetSnapshot,
    AssetSource,
    BonusType,
    RuleKind,
    ShiftPlan,
    ShiftSource,
    WageRule,
    Workplace,
)
from wage import compute_earnings, earnings_so_far, finalize_amount, is_currently_paused


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


def test_add_and_get_workplace_with_rules(db):
    wp = Workplace(name="コンビニA", base_wage=1050.0, transport_allowance=200.0)
    wp.rules.append(
        WageRule(
            workplace_id=0,  # add_workplace側で上書きされる
            kind=RuleKind.TIME_BAND,
            bonus_type=BonusType.ADD,
            amount=20.0,
            start_time=time(16, 0),
            end_time=time(18, 0),
        )
    )
    workplace_id = db.add_workplace(wp)

    fetched = db.get_workplace(workplace_id)
    assert fetched is not None
    assert fetched.name == "コンビニA"
    assert fetched.base_wage == pytest.approx(1050.0)
    assert len(fetched.rules) == 1
    assert fetched.rules[0].amount == pytest.approx(20.0)
    assert fetched.rules[0].workplace_id == workplace_id


def test_update_and_delete_workplace(db):
    wp_id = db.add_workplace(Workplace(name="旧名", base_wage=1000.0))
    wp = db.get_workplace(wp_id)
    wp.name = "新名"
    wp.base_wage = 1100.0
    db.update_workplace(wp)
    assert db.get_workplace(wp_id).name == "新名"
    assert db.get_workplace(wp_id).base_wage == pytest.approx(1100.0)

    db.delete_workplace(wp_id)
    assert db.get_workplace(wp_id) is None


def test_session_lifecycle_start_pause_resume_end(db):
    wp_id = db.add_workplace(Workplace(name="バイト先", base_wage=2000.0))
    wp = db.get_workplace(wp_id)

    start = datetime(2026, 7, 20, 10, 0)
    session = db.start_session(wp_id, start_ts=start)
    assert session.status.value == "running"

    db.pause_session(session.id, at=datetime(2026, 7, 20, 10, 30))
    active = db.get_active_session()
    assert active is not None
    assert is_currently_paused(active) is True

    db.resume_session(session.id, at=datetime(2026, 7, 20, 11, 0))
    active = db.get_active_session()
    assert is_currently_paused(active) is False

    now = datetime(2026, 7, 20, 11, 30)  # 1.5h経過、0.5h停止 => 実働1h
    amount_before_end = earnings_so_far(wp, wp.rules, active, now=now)
    assert amount_before_end == pytest.approx(2000.0)

    final_amount = finalize_amount(amount_before_end, wp)
    ended = db.end_session(session.id, gross_amount=final_amount, end_ts=now)
    assert ended.status.value == "done"
    assert ended.gross_amount == pytest.approx(2000.0)

    # 終了後は稼働中セッションが無くなる
    assert db.get_active_session() is None


def test_delete_session_removes_it_from_list(db):
    wp_id = db.add_workplace(Workplace(name="バイト先", base_wage=1000.0))
    wp = db.get_workplace(wp_id)
    start = datetime(2026, 7, 20, 10, 0)
    end = datetime(2026, 7, 20, 12, 0)
    session = db.start_session(wp_id, start_ts=start)
    amount = compute_earnings(wp, wp.rules, start, end)
    db.end_session(session.id, gross_amount=amount, end_ts=end)

    assert len(db.list_sessions(date(2026, 7, 20), date(2026, 7, 20))) == 1
    db.delete_session(session.id)
    assert db.list_sessions(date(2026, 7, 20), date(2026, 7, 20)) == []
    assert db.get_session(session.id) is None


def test_insert_session_restores_deleted_record_with_pauses(db):
    """delete_session後にUndoでinsert_sessionを使って元のセッション(pauses込み)を復元できること。"""
    wp_id = db.add_workplace(Workplace(name="バイト先", base_wage=1000.0))
    wp = db.get_workplace(wp_id)
    start = datetime(2026, 7, 20, 9, 0)
    session = db.start_session(wp_id, start_ts=start)
    db.pause_session(session.id, at=datetime(2026, 7, 20, 9, 30))
    db.resume_session(session.id, at=datetime(2026, 7, 20, 10, 0))
    end = datetime(2026, 7, 20, 11, 0)
    active = db.get_active_session()
    amount = earnings_so_far(wp, wp.rules, active, now=end)
    ended = db.end_session(session.id, gross_amount=amount, end_ts=end)

    db.delete_session(ended.id)
    assert db.get_session(ended.id) is None

    new_id = db.insert_session(ended)
    restored = db.get_session(new_id)
    assert restored is not None
    assert restored.workplace_id == wp_id
    assert restored.start_ts == start
    assert restored.end_ts == end
    assert restored.status.value == "done"
    assert restored.gross_amount == pytest.approx(ended.gross_amount)
    assert len(restored.pauses) == 1
    assert restored.pauses[0].pause_ts == datetime(2026, 7, 20, 9, 30)
    assert restored.pauses[0].resume_ts == datetime(2026, 7, 20, 10, 0)


def test_end_session_while_paused_auto_resumes(db):
    """一時停止中にエンドしても、停止時間が正しく除外されること。"""
    wp_id = db.add_workplace(Workplace(name="バイト先", base_wage=1000.0))
    wp = db.get_workplace(wp_id)
    start = datetime(2026, 7, 20, 9, 0)
    session = db.start_session(wp_id, start_ts=start)
    db.pause_session(session.id, at=datetime(2026, 7, 20, 9, 30))
    # 一時停止したまま10:00にエンド(合計1h経過、うち0.5h稼働)
    end_ts = datetime(2026, 7, 20, 10, 0)
    active = db.get_active_session()
    amount = earnings_so_far(wp, wp.rules, active, now=end_ts)
    ended = db.end_session(session.id, gross_amount=amount, end_ts=end_ts)
    assert ended.gross_amount == pytest.approx(500.0)
    assert ended.pauses[-1].resume_ts == end_ts


def test_daily_monthly_yearly_totals(db):
    wp_id = db.add_workplace(Workplace(name="バイト先", base_wage=1000.0))
    wp = db.get_workplace(wp_id)

    def add_done_session(start, end):
        s = db.start_session(wp_id, start_ts=start)
        amount = compute_earnings(wp, wp.rules, start, end)
        db.end_session(s.id, gross_amount=amount, end_ts=end)

    add_done_session(datetime(2026, 7, 1, 10, 0), datetime(2026, 7, 1, 12, 0))  # 2000
    add_done_session(datetime(2026, 7, 15, 10, 0), datetime(2026, 7, 15, 13, 0))  # 3000
    add_done_session(datetime(2026, 8, 1, 10, 0), datetime(2026, 8, 1, 11, 0))  # 1000

    totals = db.daily_totals(date(2026, 7, 1), date(2026, 7, 31))
    assert totals[date(2026, 7, 1)] == pytest.approx(2000.0)
    assert totals[date(2026, 7, 15)] == pytest.approx(3000.0)

    assert db.monthly_total(2026, 7) == pytest.approx(5000.0)
    assert db.monthly_total(2026, 8) == pytest.approx(1000.0)
    assert db.yearly_total(2026) == pytest.approx(6000.0)

    by_month = db.yearly_total_by_month(2026)
    assert by_month[7] == pytest.approx(5000.0)
    assert by_month[8] == pytest.approx(1000.0)


def test_shift_plan_crud(db):
    wp_id = db.add_workplace(Workplace(name="バイト先", base_wage=1000.0))
    plan = ShiftPlan(
        workplace_id=wp_id,
        plan_date=date(2026, 8, 1),
        start_time=time(9, 0),
        end_time=time(17, 0),
        source=ShiftSource.AI,
        confirmed=False,
    )
    plan_id = db.add_shift_plan(plan)
    plans = db.list_shift_plans(date(2026, 8, 1), date(2026, 8, 1))
    assert len(plans) == 1
    assert plans[0].confirmed is False

    plans[0].confirmed = True
    db.update_shift_plan(plans[0])
    assert db.list_shift_plans(date(2026, 8, 1), date(2026, 8, 1))[0].confirmed is True

    db.delete_shift_plan(plan_id)
    assert db.list_shift_plans(date(2026, 8, 1), date(2026, 8, 1)) == []


def test_asset_snapshot_and_percentage_change(db):
    snap1 = AssetSnapshot(
        taken_at=datetime(2026, 7, 1, 9, 0),
        total_amount=1_000_000.0,
        source=AssetSource.MANUAL,
        items=[
            AssetItem(snapshot_id=0, category=AssetCategory.BANK, name="銀行A", amount=800_000.0),
            AssetItem(snapshot_id=0, category=AssetCategory.STOCK, name="株B", amount=200_000.0, pl=5000.0),
        ],
    )
    snap2 = AssetSnapshot(
        taken_at=datetime(2026, 7, 8, 9, 0),
        total_amount=1_100_000.0,
        source=AssetSource.SCREENSHOT,
    )
    db.add_asset_snapshot(snap1)
    db.add_asset_snapshot(snap2)

    latest = db.latest_asset_snapshot()
    assert latest.total_amount == pytest.approx(1_100_000.0)

    baseline = db.asset_snapshot_before(datetime(2026, 7, 5, 0, 0))
    assert baseline.total_amount == pytest.approx(1_000_000.0)
    assert len(baseline.items) == 2

    pct_change = (latest.total_amount - baseline.total_amount) / baseline.total_amount * 100
    assert pct_change == pytest.approx(10.0)


def test_settings_kv_store(db):
    assert db.get_setting("monthly_goal") is None
    db.set_setting("monthly_goal", "80000")
    assert db.get_setting("monthly_goal") == "80000"
    db.set_setting("monthly_goal", "90000")  # 上書き
    assert db.get_setting("monthly_goal") == "90000"
