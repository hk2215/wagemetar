"""時給計算エンジン。

このモジュールは Flet にも SQLite にも依存しない「純粋関数」だけで構成する。
理由: 金額計算はアプリの中で最も間違えてはいけない部分なので、UIやDBの都合から
切り離してテストしやすい形に保つ。

## 設計の要点

- 実効時給は「ある瞬間(datetime)」に対して決まる関数として定義する
  (`effective_rate`)。基本時給に対し、時間帯加算・曜日加算・深夜割増を
  ADD(円/時を加算)または MULTIPLY(倍率を掛ける)で適用する。
- ADDは全て合算してから基本時給に足し、MULTIPLYは全て掛け合わせる
  (`rate = (base + sum(add)) * product(multiply)`)。
- ある区間[start, end)の金額は、時給が変化する境界(時間帯の開始/終了・
  日付が変わる瞬間・深夜割増の開始/終了)で区切り、区間ごとに一定の実効時給を
  適用して積算する(`compute_earnings`)。これにより「17:30開始→18:00の
  時間帯加算をまたぐ」ようなケースも正確に計算できる。
- 深夜割増(22:00〜翌5:00)のように日をまたぐ区間は、`start_time > end_time`
  であれば「日をまたぐ」とみなして扱う。
- 稼働中セッションのライブ金額(`earnings_so_far`)は、記録済みの一時停止
  (pause)区間を実時間で正確に差し引いてから積算する。`break_minutes`による
  概算控除(`compute_earnings`の引数)とは別の、より正確な経路。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from models import BonusType, RuleKind, WageRule, Workplace, WorkSession

# 深夜割増のデフォルト時間帯 (労働基準法の深夜割増と同じ 22:00-翌5:00)
DEFAULT_NIGHT_START = time(22, 0)
DEFAULT_NIGHT_END = time(5, 0)
DEFAULT_NIGHT_MULTIPLIER = 1.25


def _night_rule_window(rule: Optional[WageRule]) -> tuple[time, time]:
    """深夜割増ルールの開始/終了時刻。ルール未指定ならデフォルト値。"""
    if rule is None:
        return DEFAULT_NIGHT_START, DEFAULT_NIGHT_END
    return (
        rule.start_time or DEFAULT_NIGHT_START,
        rule.end_time or DEFAULT_NIGHT_END,
    )


def _in_time_window(t: time, start: time, end: time) -> bool:
    """時刻tが[start, end)に含まれるか。start > endなら日をまたぐ区間として扱う。"""
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def effective_rate(workplace: Workplace, rules: Iterable[WageRule], dt: datetime) -> float:
    """ある瞬間(dt)における実効時給(円/時)を返す。

    Args:
        workplace: 対象のバイト先(base_wage, night_premium_enabledを使用)。
        rules: そのバイト先に紐づく WageRule の一覧
            (呼び出し側で workplace_id によるフィルタ済みであること)。
        dt: 評価したい時刻。

    Returns:
        円/時 の実効時給。
    """
    t = dt.time()
    weekday = dt.weekday()  # 0=月曜 ... 6=日曜

    add_total = 0.0
    mult_total = 1.0
    has_explicit_night_rule = False

    for rule in rules:
        matched = False

        if rule.kind == RuleKind.TIME_BAND:
            if rule.start_time is None or rule.end_time is None:
                continue
            day_ok = rule.day_of_week is None or rule.day_of_week == weekday
            matched = day_ok and _in_time_window(t, rule.start_time, rule.end_time)

        elif rule.kind == RuleKind.WEEKDAY:
            matched = rule.day_of_week == weekday

        elif rule.kind == RuleKind.NIGHT_PREMIUM:
            has_explicit_night_rule = True
            start, end = _night_rule_window(rule)
            matched = _in_time_window(t, start, end)

        if matched:
            if rule.bonus_type == BonusType.ADD:
                add_total += rule.amount
            else:
                mult_total *= rule.amount

    # ルール一覧に明示的な深夜割増ルールが無い場合のみ、
    # workplace.night_premium_enabled による自動デフォルト(+25%)を適用する。
    if workplace.night_premium_enabled and not has_explicit_night_rule:
        if _in_time_window(t, DEFAULT_NIGHT_START, DEFAULT_NIGHT_END):
            mult_total *= DEFAULT_NIGHT_MULTIPLIER

    return (workplace.base_wage + add_total) * mult_total


def _time_band_boundaries(
    rules: Iterable[WageRule], day: date
) -> list[datetime]:
    """その日における time_band ルールの開始/終了の境界時刻(datetime)一覧。"""
    points: list[datetime] = []
    weekday = day.weekday()
    for rule in rules:
        if rule.kind != RuleKind.TIME_BAND:
            continue
        if rule.start_time is None or rule.end_time is None:
            continue
        if rule.day_of_week is not None and rule.day_of_week != weekday:
            continue
        points.append(datetime.combine(day, rule.start_time))
        points.append(datetime.combine(day, rule.end_time))
    return points


def _night_boundaries(
    workplace: Workplace, rules: Iterable[WageRule], day: date
) -> list[datetime]:
    """dayを起点とする深夜割増区間の境界(開始・終了のdatetime)一覧。

    深夜割増は「day 22:00 〜 day+1 05:00」のように日をまたぐ1本の区間として
    dayごとに1つ生成する(自動デフォルト分 + 明示ルール分)。
    """
    night_rules = [r for r in rules if r.kind == RuleKind.NIGHT_PREMIUM]
    windows: list[tuple[time, time]] = [_night_rule_window(r) for r in night_rules]
    if workplace.night_premium_enabled and not night_rules:
        windows.append((DEFAULT_NIGHT_START, DEFAULT_NIGHT_END))

    points: list[datetime] = []
    for start_t, end_t in windows:
        start_dt = datetime.combine(day, start_t)
        end_dt = datetime.combine(day, end_t)
        if end_t <= start_t:
            end_dt += timedelta(days=1)
        points.append(start_dt)
        points.append(end_dt)
    return points


def _boundary_points(
    workplace: Workplace, rules: list[WageRule], start: datetime, end: datetime
) -> list[datetime]:
    """[start, end] の間で実効時給が変化しうる境界点を昇順・重複無しで返す。"""
    points: set[datetime] = {start, end}

    # 深夜割増は日をまたぐので、start前日から end当日まで走査する。
    day = start.date() - timedelta(days=1)
    last_day = end.date()
    while day <= last_day:
        for p in _time_band_boundaries(rules, day):
            if start < p < end:
                points.add(p)
        for p in _night_boundaries(workplace, rules, day):
            if start < p < end:
                points.add(p)
        # 日付が変わる瞬間(曜日別ルールの境界)も区切る。
        midnight = datetime.combine(day, time.min)
        if start < midnight < end:
            points.add(midnight)
        day += timedelta(days=1)

    return sorted(points)


def compute_earnings(
    workplace: Workplace,
    rules: list[WageRule],
    start: datetime,
    end: datetime,
    break_minutes: float = 0,
) -> float:
    """[start, end) の勤務に対する金額(交通費を除く)を計算する。

    break_minutes を指定した場合、正確な休憩時刻が分からない前提で
    「実働時間 / 総時間」の比率で按分控除する(概算)。正確な休憩時刻が
    分かる場合は `earnings_so_far` 側の一時停止(pause)処理を使うこと。

    Returns:
        円単位の金額(丸めなし)。呼び出し側で表示・保存時に丸めること。
    """
    if end <= start:
        return 0.0

    points = _boundary_points(workplace, rules, start, end)
    total = 0.0
    for p1, p2 in zip(points, points[1:]):
        duration_hours = (p2 - p1).total_seconds() / 3600
        midpoint = p1 + (p2 - p1) / 2
        total += effective_rate(workplace, rules, midpoint) * duration_hours

    if break_minutes > 0:
        total_hours = (end - start).total_seconds() / 3600
        if total_hours > 0:
            worked_ratio = max(0.0, (total_hours - break_minutes / 60) / total_hours)
            total *= worked_ratio

    return total


def _subtract_pauses(
    start: datetime,
    end: datetime,
    pauses: list,
    now: datetime,
) -> list[tuple[datetime, datetime]]:
    """[start, end] から pauses の実時間区間を取り除いた「稼働中」の区間一覧。"""
    active: list[tuple[datetime, datetime]] = [(start, end)]
    for pause in pauses:
        p_start = max(pause.pause_ts, start)
        p_end = min(pause.resume_ts or now, end)
        if p_end <= p_start:
            continue
        new_active: list[tuple[datetime, datetime]] = []
        for a, b in active:
            if p_end <= a or p_start >= b:
                new_active.append((a, b))
                continue
            if p_start > a:
                new_active.append((a, p_start))
            if p_end < b:
                new_active.append((p_end, b))
        active = new_active
    return active


def earnings_so_far(
    workplace: Workplace,
    rules: list[WageRule],
    session: WorkSession,
    now: Optional[datetime] = None,
) -> float:
    """稼働中(または終了済み)セッションの、現時点までの金額(交通費除く)。

    session.pauses に記録された正確な一時停止区間を差し引いてから積算するため、
    `compute_earnings` の break_minutes 概算より正確。
    """
    now = now or datetime.now()
    end = min(session.end_ts or now, now)
    if end <= session.start_ts:
        return 0.0
    active_ranges = _subtract_pauses(session.start_ts, end, session.pauses, now)
    return sum(
        compute_earnings(workplace, rules, a, b) for a, b in active_ranges
    )


def is_currently_paused(session: WorkSession) -> bool:
    """セッションが現在一時停止中かどうか(最後のpauseが未resumeなら停止中)。"""
    if not session.pauses:
        return False
    return session.pauses[-1].resume_ts is None


def finalize_amount(
    base_earnings: float, workplace: Workplace, include_transport: bool = True
) -> float:
    """確定金額 = 稼働分の金額 + (含めるなら)交通費。"""
    return base_earnings + (workplace.transport_allowance if include_transport else 0.0)
