"""アプリ全体で使うデータモデル(dataclass)。

Flet や SQLite に依存しない純粋なデータ構造だけを置く。
DBの行(sqlite3.Row / tuple)からの変換は db.py 側の責務。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Optional


class RuleKind(str, Enum):
    """賃金ルールの種別。"""

    TIME_BAND = "time_band"  # 時間帯加算 (例: 16:00-18:00 は +20円/時)
    WEEKDAY = "weekday"  # 曜日別加算 (例: 土日は +50円/時)
    NIGHT_PREMIUM = "night_premium"  # 深夜割増 (22:00-翌5:00)


class BonusType(str, Enum):
    """加算の適用方法。"""

    ADD = "add"  # 基本時給に加算 (円/時)
    MULTIPLY = "multiply"  # 基本時給に倍率を掛ける (例: 1.25倍)


class SessionStatus(str, Enum):
    """勤務セッションの状態。"""

    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"


class ShiftSource(str, Enum):
    """シフト予定の登録元。"""

    MANUAL = "manual"
    AI = "ai"


class AssetSource(str, Enum):
    """資産スナップショットの登録元。"""

    MANUAL = "manual"
    SCREENSHOT = "screenshot"


class AssetCategory(str, Enum):
    """資産項目のカテゴリ。"""

    BANK = "bank"
    SECURITIES = "securities"
    STOCK = "stock"
    CASH = "cash"
    OTHER = "other"


@dataclass
class WageRule:
    """バイト先ごとに都度追加できる賃金加算ルール。

    time_band: day_of_week=None なら毎日、指定すればその曜日のみ(0=月,...,6=日)。
    night_premium: start_time/end_time は無視され、固定で 22:00-翌5:00 に適用。
    """

    workplace_id: int
    kind: RuleKind
    bonus_type: BonusType
    amount: float  # ADDなら円/時、MULTIPLYなら倍率(例1.25)
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    day_of_week: Optional[int] = None  # 0=月曜 ... 6=日曜。Noneは曜日指定なし
    label: str = ""
    id: Optional[int] = None


@dataclass
class Workplace:
    """バイト先。"""

    name: str
    base_wage: float  # 基本時給(円)
    transport_allowance: float = 0.0  # 出勤1回あたりの交通費(円)
    pay_cutoff_day: int = 31  # 締め日(1-31, 31は月末扱い)
    payday: int = 25  # 給料日(1-31, 31は月末扱い)
    night_premium_enabled: bool = False  # 22-5時に法定+25%を自動適用するか
    id: Optional[int] = None
    rules: list[WageRule] = field(default_factory=list)


@dataclass
class SessionPause:
    """勤務セッション中の一時停止区間。"""

    session_id: int
    pause_ts: datetime
    resume_ts: Optional[datetime] = None
    id: Optional[int] = None


@dataclass
class WorkSession:
    """1回の勤務(スタート〜エンド)。"""

    workplace_id: int
    start_ts: datetime
    end_ts: Optional[datetime] = None
    status: SessionStatus = SessionStatus.RUNNING
    gross_amount: float = 0.0  # 確定時に計算して保存する金額(交通費込み)
    transport_included: bool = True
    id: Optional[int] = None
    pauses: list[SessionPause] = field(default_factory=list)

    def total_break_seconds(self, now: Optional[datetime] = None) -> float:
        """休止(一時停止)の合計秒数。resumeしていない停止は now までを計上。"""
        total = 0.0
        for p in self.pauses:
            end = p.resume_ts or now or datetime.now()
            total += max(0.0, (end - p.pause_ts).total_seconds())
        return total


@dataclass
class ShiftPlan:
    """シフト予定(写真取込 or 手動)。"""

    workplace_id: int
    plan_date: date
    start_time: time
    end_time: time
    source: ShiftSource = ShiftSource.MANUAL
    confirmed: bool = True
    id: Optional[int] = None


@dataclass
class AssetItem:
    """資産スナップショットの内訳1件。"""

    snapshot_id: int
    category: AssetCategory
    name: str
    amount: float
    pl: Optional[float] = None  # 損益(証券/株式のみ想定、無ければNone)
    id: Optional[int] = None


@dataclass
class AssetSnapshot:
    """ある時点での総資産スナップショット。"""

    taken_at: datetime
    total_amount: float
    source: AssetSource = AssetSource.MANUAL
    id: Optional[int] = None
    items: list[AssetItem] = field(default_factory=list)
