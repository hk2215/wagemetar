"""SQLiteによる永続化層。

- 保存先は環境変数 `FLET_APP_STORAGE_DATA` (flet run / ビルド後アプリが自動設定する
  端末内の永続ディレクトリ) を優先し、無ければ開発用に `<プロジェクト>/data/app.db`
  にフォールバックする。
- 日時は ISO 8601 文字列として保存し、読み出し時に `datetime.fromisoformat` 等で
  Python の型に戻す。真偽値は 0/1 の INTEGER。
- Flet の UI 層はこのモジュールの関数だけを呼び、生SQLを書かないようにする。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional

import web_persistence
from models import (
    AssetCategory,
    AssetItem,
    AssetSnapshot,
    AssetSource,
    BonusType,
    RuleKind,
    SessionPause,
    SessionStatus,
    ShiftPlan,
    ShiftSource,
    WageRule,
    Workplace,
    WorkSession,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS workplaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    base_wage REAL NOT NULL,
    transport_allowance REAL NOT NULL DEFAULT 0,
    pay_cutoff_day INTEGER NOT NULL DEFAULT 31,
    payday INTEGER NOT NULL DEFAULT 25,
    night_premium_enabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS wage_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workplace_id INTEGER NOT NULL REFERENCES workplaces(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    bonus_type TEXT NOT NULL,
    amount REAL NOT NULL,
    start_time TEXT,
    end_time TEXT,
    day_of_week INTEGER,
    label TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS work_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workplace_id INTEGER NOT NULL REFERENCES workplaces(id) ON DELETE CASCADE,
    start_ts TEXT NOT NULL,
    end_ts TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    gross_amount REAL NOT NULL DEFAULT 0,
    transport_included INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS session_pauses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES work_sessions(id) ON DELETE CASCADE,
    pause_ts TEXT NOT NULL,
    resume_ts TEXT
);

CREATE TABLE IF NOT EXISTS shift_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workplace_id INTEGER NOT NULL REFERENCES workplaces(id) ON DELETE CASCADE,
    plan_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    confirmed INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS asset_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at TEXT NOT NULL,
    total_amount REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS asset_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES asset_snapshots(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    amount REAL NOT NULL,
    pl REAL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def default_db_path() -> Path:
    """DBファイルの保存先を決定する。

    - Web(Pyodide)実行時: `web_persistence` がマウントする IDBFS 配下
      (`/idbfs_data/app.db`) を使う。IDBFSマウント外に置くとリロードで消えるため、
      必ずこのマウントポイント配下に置くこと(`web_persistence.setup_and_pull()` を
      DB接続前に呼んでおくのが呼び出し側の責務)。
    - それ以外(ネイティブ/デスクトップ): `flet run` / ビルド済みアプリでは
      FLET_APP_STORAGE_DATA が常に設定される。未設定(このモジュール単体のテスト
      実行など)の場合はプロジェクト直下の `data/app.db` にフォールバックする。
    """
    if web_persistence.is_pyodide():
        base = Path(web_persistence.MOUNT_DIR)
        base.mkdir(parents=True, exist_ok=True)
        return base / "app.db"

    data_dir = os.environ.get("FLET_APP_STORAGE_DATA")
    if data_dir:
        base = Path(data_dir)
    else:
        base = Path(__file__).resolve().parent.parent / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base / "app.db"


def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _d(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _t(value: Optional[str]) -> Optional[time]:
    return time.fromisoformat(value) if value else None


class Database:
    """SQLite接続とリポジトリ関数一式。

    テストでは `Database(":memory:")` で使い捨てのDBを作れる。
    アプリ本体は `get_db()` が返すプロセス内シングルトンを使う。
    """

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._commit()

    def close(self) -> None:
        self._conn.close()

    def _commit(self) -> None:
        """`self._conn.commit()` の代わりに全書込みメソッドから呼ぶ。

        Web(Pyodide)実行時は、変更があったことを `web_persistence` に伝える
        (`autosave_loop` が一定間隔でIndexedDBへ書き出す)。ネイティブ実行時は
        通常のcommitのみでno-op。
        """
        self._conn.commit()
        web_persistence.mark_dirty()

    # ------------------------------------------------------------------
    # Workplace
    # ------------------------------------------------------------------

    def add_workplace(self, wp: Workplace) -> int:
        cur = self._conn.execute(
            """INSERT INTO workplaces
               (name, base_wage, transport_allowance, pay_cutoff_day, payday,
                night_premium_enabled)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                wp.name,
                wp.base_wage,
                wp.transport_allowance,
                wp.pay_cutoff_day,
                wp.payday,
                int(wp.night_premium_enabled),
            ),
        )
        self._commit()
        workplace_id = cur.lastrowid
        for rule in wp.rules:
            rule.workplace_id = workplace_id
            self.add_wage_rule(rule)
        return workplace_id

    def update_workplace(self, wp: Workplace) -> None:
        if wp.id is None:
            raise ValueError("update_workplace には id が必要です")
        self._conn.execute(
            """UPDATE workplaces SET name=?, base_wage=?, transport_allowance=?,
               pay_cutoff_day=?, payday=?, night_premium_enabled=? WHERE id=?""",
            (
                wp.name,
                wp.base_wage,
                wp.transport_allowance,
                wp.pay_cutoff_day,
                wp.payday,
                int(wp.night_premium_enabled),
                wp.id,
            ),
        )
        self._commit()

    def delete_workplace(self, workplace_id: int) -> None:
        self._conn.execute("DELETE FROM workplaces WHERE id=?", (workplace_id,))
        self._commit()

    def _row_to_workplace(self, row: sqlite3.Row) -> Workplace:
        return Workplace(
            id=row["id"],
            name=row["name"],
            base_wage=row["base_wage"],
            transport_allowance=row["transport_allowance"],
            pay_cutoff_day=row["pay_cutoff_day"],
            payday=row["payday"],
            night_premium_enabled=bool(row["night_premium_enabled"]),
            rules=self.list_wage_rules(row["id"]),
        )

    def get_workplace(self, workplace_id: int) -> Optional[Workplace]:
        row = self._conn.execute(
            "SELECT * FROM workplaces WHERE id=?", (workplace_id,)
        ).fetchone()
        return self._row_to_workplace(row) if row else None

    def list_workplaces(self) -> list[Workplace]:
        rows = self._conn.execute("SELECT * FROM workplaces ORDER BY id").fetchall()
        return [self._row_to_workplace(r) for r in rows]

    # ------------------------------------------------------------------
    # WageRule
    # ------------------------------------------------------------------

    def add_wage_rule(self, rule: WageRule) -> int:
        cur = self._conn.execute(
            """INSERT INTO wage_rules
               (workplace_id, kind, bonus_type, amount, start_time, end_time,
                day_of_week, label)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.workplace_id,
                rule.kind.value,
                rule.bonus_type.value,
                rule.amount,
                rule.start_time.isoformat() if rule.start_time else None,
                rule.end_time.isoformat() if rule.end_time else None,
                rule.day_of_week,
                rule.label,
            ),
        )
        self._commit()
        return cur.lastrowid

    def delete_wage_rule(self, rule_id: int) -> None:
        self._conn.execute("DELETE FROM wage_rules WHERE id=?", (rule_id,))
        self._commit()

    def list_wage_rules(self, workplace_id: int) -> list[WageRule]:
        rows = self._conn.execute(
            "SELECT * FROM wage_rules WHERE workplace_id=? ORDER BY id", (workplace_id,)
        ).fetchall()
        return [
            WageRule(
                id=r["id"],
                workplace_id=r["workplace_id"],
                kind=RuleKind(r["kind"]),
                bonus_type=BonusType(r["bonus_type"]),
                amount=r["amount"],
                start_time=_t(r["start_time"]),
                end_time=_t(r["end_time"]),
                day_of_week=r["day_of_week"],
                label=r["label"] or "",
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # WorkSession / SessionPause
    # ------------------------------------------------------------------

    def start_session(self, workplace_id: int, start_ts: Optional[datetime] = None) -> WorkSession:
        start_ts = start_ts or datetime.now()
        cur = self._conn.execute(
            """INSERT INTO work_sessions
               (workplace_id, start_ts, status, gross_amount, transport_included)
               VALUES (?, ?, 'running', 0, 1)""",
            (workplace_id, start_ts.isoformat()),
        )
        self._commit()
        return WorkSession(
            id=cur.lastrowid,
            workplace_id=workplace_id,
            start_ts=start_ts,
            status=SessionStatus.RUNNING,
        )

    def pause_session(self, session_id: int, at: Optional[datetime] = None) -> None:
        at = at or datetime.now()
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"session {session_id} が見つかりません")
        if session.status == SessionStatus.DONE:
            raise ValueError("終了済みセッションは一時停止できません")
        from wage import is_currently_paused  # 循環import回避のため遅延import

        if is_currently_paused(session):
            return  # 既に停止中なら何もしない
        self._conn.execute(
            "INSERT INTO session_pauses (session_id, pause_ts, resume_ts) VALUES (?, ?, NULL)",
            (session_id, at.isoformat()),
        )
        self._conn.execute(
            "UPDATE work_sessions SET status='paused' WHERE id=?", (session_id,)
        )
        self._commit()

    def resume_session(self, session_id: int, at: Optional[datetime] = None) -> None:
        at = at or datetime.now()
        row = self._conn.execute(
            """SELECT id FROM session_pauses WHERE session_id=? AND resume_ts IS NULL
               ORDER BY id DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
        if row is None:
            return  # 停止中ではない
        self._conn.execute(
            "UPDATE session_pauses SET resume_ts=? WHERE id=?", (at.isoformat(), row["id"])
        )
        self._conn.execute(
            "UPDATE work_sessions SET status='running' WHERE id=?", (session_id,)
        )
        self._commit()

    def end_session(
        self,
        session_id: int,
        gross_amount: float,
        end_ts: Optional[datetime] = None,
        transport_included: bool = True,
    ) -> WorkSession:
        """セッションを確定する。金額(gross_amount)は呼び出し側(wage.py)で計算済みのものを渡す。

        一時停止中のまま終了した場合は、最後のpauseをend_tsで自動的にresumeする
        (そうしないと停止時間が計算に含まれ続けてしまうため)。
        """
        end_ts = end_ts or datetime.now()
        self.resume_session(session_id, at=end_ts)  # 停止中なら自動resume
        self._conn.execute(
            """UPDATE work_sessions
               SET end_ts=?, status='done', gross_amount=?, transport_included=?
               WHERE id=?""",
            (end_ts.isoformat(), gross_amount, int(transport_included), session_id),
        )
        self._commit()
        session = self.get_session(session_id)
        assert session is not None
        return session

    def _row_to_session(self, row: sqlite3.Row) -> WorkSession:
        pauses = self._conn.execute(
            "SELECT * FROM session_pauses WHERE session_id=? ORDER BY id", (row["id"],)
        ).fetchall()
        return WorkSession(
            id=row["id"],
            workplace_id=row["workplace_id"],
            start_ts=_dt(row["start_ts"]),
            end_ts=_dt(row["end_ts"]),
            status=SessionStatus(row["status"]),
            gross_amount=row["gross_amount"],
            transport_included=bool(row["transport_included"]),
            pauses=[
                SessionPause(
                    id=p["id"],
                    session_id=p["session_id"],
                    pause_ts=_dt(p["pause_ts"]),
                    resume_ts=_dt(p["resume_ts"]),
                )
                for p in pauses
            ],
        )

    def get_session(self, session_id: int) -> Optional[WorkSession]:
        row = self._conn.execute(
            "SELECT * FROM work_sessions WHERE id=?", (session_id,)
        ).fetchone()
        return self._row_to_session(row) if row else None

    def get_active_session(self, workplace_id: Optional[int] = None) -> Optional[WorkSession]:
        """稼働中(running/paused)のセッションを1件返す(基本的にアプリ全体で同時に1つ)。"""
        if workplace_id is not None:
            row = self._conn.execute(
                """SELECT * FROM work_sessions WHERE workplace_id=? AND status!='done'
                   ORDER BY id DESC LIMIT 1""",
                (workplace_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM work_sessions WHERE status!='done' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(
        self,
        start_date: date,
        end_date: date,
        workplace_id: Optional[int] = None,
        done_only: bool = True,
    ) -> list[WorkSession]:
        """[start_date, end_date] (両端含む) に開始したセッション一覧。日付はstart_ts基準。"""
        query = "SELECT * FROM work_sessions WHERE date(start_ts) BETWEEN ? AND ?"
        params: list = [start_date.isoformat(), end_date.isoformat()]
        if workplace_id is not None:
            query += " AND workplace_id=?"
            params.append(workplace_id)
        if done_only:
            query += " AND status='done'"
        query += " ORDER BY start_ts"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_session(r) for r in rows]

    def delete_session(self, session_id: int) -> None:
        """出勤記録を削除する。session_pauses は ON DELETE CASCADE で連動削除される。"""
        self._conn.execute("DELETE FROM work_sessions WHERE id=?", (session_id,))
        self._commit()

    def insert_session(self, session: WorkSession) -> int:
        """既存の WorkSession(pauses込み)をそのまま挿入し直す。delete_session の取消(Undo)用。"""
        cur = self._conn.execute(
            """INSERT INTO work_sessions
               (workplace_id, start_ts, end_ts, status, gross_amount, transport_included)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session.workplace_id,
                session.start_ts.isoformat(),
                session.end_ts.isoformat() if session.end_ts else None,
                session.status.value,
                session.gross_amount,
                int(session.transport_included),
            ),
        )
        new_id = cur.lastrowid
        for p in session.pauses:
            self._conn.execute(
                "INSERT INTO session_pauses (session_id, pause_ts, resume_ts) VALUES (?, ?, ?)",
                (new_id, p.pause_ts.isoformat(), p.resume_ts.isoformat() if p.resume_ts else None),
            )
        self._commit()
        return new_id

    # ------------------------------------------------------------------
    # 集計(カレンダー・ヒートマップ・壁アラート用)
    # ------------------------------------------------------------------

    def daily_totals(self, start_date: date, end_date: date, workplace_id: Optional[int] = None) -> dict[date, float]:
        """日付ごとの合計金額(start_ts の日付に集計)。"""
        query = (
            "SELECT date(start_ts) AS d, SUM(gross_amount) AS total "
            "FROM work_sessions WHERE status='done' AND date(start_ts) BETWEEN ? AND ?"
        )
        params: list = [start_date.isoformat(), end_date.isoformat()]
        if workplace_id is not None:
            query += " AND workplace_id=?"
            params.append(workplace_id)
        query += " GROUP BY d"
        rows = self._conn.execute(query, params).fetchall()
        return {date.fromisoformat(r["d"]): r["total"] for r in rows}

    def monthly_total(self, year: int, month: int, workplace_id: Optional[int] = None) -> float:
        query = (
            "SELECT SUM(gross_amount) AS total FROM work_sessions "
            "WHERE status='done' AND strftime('%Y-%m', start_ts) = ?"
        )
        params: list = [f"{year:04d}-{month:02d}"]
        if workplace_id is not None:
            query += " AND workplace_id=?"
            params.append(workplace_id)
        row = self._conn.execute(query, params).fetchone()
        return row["total"] or 0.0

    def yearly_total(self, year: int, workplace_id: Optional[int] = None) -> float:
        query = (
            "SELECT SUM(gross_amount) AS total FROM work_sessions "
            "WHERE status='done' AND strftime('%Y', start_ts) = ?"
        )
        params: list = [f"{year:04d}"]
        if workplace_id is not None:
            query += " AND workplace_id=?"
            params.append(workplace_id)
        row = self._conn.execute(query, params).fetchone()
        return row["total"] or 0.0

    def yearly_total_by_month(self, year: int, workplace_id: Optional[int] = None) -> dict[int, float]:
        query = (
            "SELECT strftime('%m', start_ts) AS m, SUM(gross_amount) AS total "
            "FROM work_sessions WHERE status='done' AND strftime('%Y', start_ts) = ?"
        )
        params: list = [f"{year:04d}"]
        if workplace_id is not None:
            query += " AND workplace_id=?"
            params.append(workplace_id)
        query += " GROUP BY m"
        rows = self._conn.execute(query, params).fetchall()
        return {int(r["m"]): r["total"] for r in rows}

    def total_by_workplace(self, start_date: date, end_date: date) -> dict[int, float]:
        rows = self._conn.execute(
            """SELECT workplace_id, SUM(gross_amount) AS total FROM work_sessions
               WHERE status='done' AND date(start_ts) BETWEEN ? AND ?
               GROUP BY workplace_id""",
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        return {r["workplace_id"]: r["total"] for r in rows}

    # ------------------------------------------------------------------
    # ShiftPlan
    # ------------------------------------------------------------------

    def add_shift_plan(self, plan: ShiftPlan) -> int:
        cur = self._conn.execute(
            """INSERT INTO shift_plans
               (workplace_id, plan_date, start_time, end_time, source, confirmed)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                plan.workplace_id,
                plan.plan_date.isoformat(),
                plan.start_time.isoformat(),
                plan.end_time.isoformat(),
                plan.source.value,
                int(plan.confirmed),
            ),
        )
        self._commit()
        return cur.lastrowid

    def update_shift_plan(self, plan: ShiftPlan) -> None:
        if plan.id is None:
            raise ValueError("update_shift_plan には id が必要です")
        self._conn.execute(
            """UPDATE shift_plans SET workplace_id=?, plan_date=?, start_time=?,
               end_time=?, source=?, confirmed=? WHERE id=?""",
            (
                plan.workplace_id,
                plan.plan_date.isoformat(),
                plan.start_time.isoformat(),
                plan.end_time.isoformat(),
                plan.source.value,
                int(plan.confirmed),
                plan.id,
            ),
        )
        self._commit()

    def delete_shift_plan(self, plan_id: int) -> None:
        self._conn.execute("DELETE FROM shift_plans WHERE id=?", (plan_id,))
        self._commit()

    def list_shift_plans(
        self, start_date: date, end_date: date, workplace_id: Optional[int] = None
    ) -> list[ShiftPlan]:
        query = "SELECT * FROM shift_plans WHERE plan_date BETWEEN ? AND ?"
        params: list = [start_date.isoformat(), end_date.isoformat()]
        if workplace_id is not None:
            query += " AND workplace_id=?"
            params.append(workplace_id)
        query += " ORDER BY plan_date, start_time"
        rows = self._conn.execute(query, params).fetchall()
        return [
            ShiftPlan(
                id=r["id"],
                workplace_id=r["workplace_id"],
                plan_date=_d(r["plan_date"]),
                start_time=_t(r["start_time"]),
                end_time=_t(r["end_time"]),
                source=ShiftSource(r["source"]),
                confirmed=bool(r["confirmed"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # AssetSnapshot / AssetItem
    # ------------------------------------------------------------------

    def add_asset_snapshot(self, snapshot: AssetSnapshot) -> int:
        cur = self._conn.execute(
            "INSERT INTO asset_snapshots (taken_at, total_amount, source) VALUES (?, ?, ?)",
            (snapshot.taken_at.isoformat(), snapshot.total_amount, snapshot.source.value),
        )
        snapshot_id = cur.lastrowid
        for item in snapshot.items:
            self._conn.execute(
                """INSERT INTO asset_items (snapshot_id, category, name, amount, pl)
                   VALUES (?, ?, ?, ?, ?)""",
                (snapshot_id, item.category.value, item.name, item.amount, item.pl),
            )
        self._commit()
        return snapshot_id

    def _row_to_snapshot(self, row: sqlite3.Row) -> AssetSnapshot:
        items = self._conn.execute(
            "SELECT * FROM asset_items WHERE snapshot_id=? ORDER BY id", (row["id"],)
        ).fetchall()
        return AssetSnapshot(
            id=row["id"],
            taken_at=_dt(row["taken_at"]),
            total_amount=row["total_amount"],
            source=AssetSource(row["source"]),
            items=[
                AssetItem(
                    id=i["id"],
                    snapshot_id=i["snapshot_id"],
                    category=AssetCategory(i["category"]),
                    name=i["name"],
                    amount=i["amount"],
                    pl=i["pl"],
                )
                for i in items
            ],
        )

    def list_asset_snapshots(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> list[AssetSnapshot]:
        query = "SELECT * FROM asset_snapshots"
        params: list = []
        if start_date and end_date:
            query += " WHERE date(taken_at) BETWEEN ? AND ?"
            params = [start_date.isoformat(), end_date.isoformat()]
        query += " ORDER BY taken_at"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def latest_asset_snapshot(self) -> Optional[AssetSnapshot]:
        row = self._conn.execute(
            "SELECT * FROM asset_snapshots ORDER BY taken_at DESC LIMIT 1"
        ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def asset_snapshot_before(self, when: datetime) -> Optional[AssetSnapshot]:
        """指定時刻より前の直近スナップショット(増減%計算の基準に使う)。"""
        row = self._conn.execute(
            "SELECT * FROM asset_snapshots WHERE taken_at <= ? ORDER BY taken_at DESC LIMIT 1",
            (when.isoformat(),),
        ).fetchone()
        return self._row_to_snapshot(row) if row else None

    # ------------------------------------------------------------------
    # Settings (簡易KVストア: 月間目標・壁アラート閾値・APIキー等)
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._commit()


_db_singleton: Optional[Database] = None


def get_db() -> Database:
    """アプリ本体用のプロセス内シングルトン。"""
    global _db_singleton
    if _db_singleton is None:
        _db_singleton = Database(default_db_path())
    return _db_singleton
