"""タイマー画面: スタート/ストップ(一時停止)/エンド + ライブ円カウンター。

設計メモ:
- `page.run_task` でティック用の非同期タスクを"投げっぱなし"にし、スタートボタンの
  クリックハンドラ自体はすぐ終了させる。クリックハンドラの中で無限ループを
  `await` してしまうと、その間ほかのイベント(ストップ/エンドのクリック)が
  処理できなくなる恐れがあるため。
- 秒給は毎秒その場でカウントするのではなく、`wage.earnings_so_far` で
  「開始時刻からの経過」を都度計算し直す。こうすることで、アプリがスリープ
  などで一瞬止まっても金額がズレない。
- 時間帯加算などが今まさに発動しているかどうかを `wage.effective_rate` で
  判定し、発動中は色を変えてフィードバックする。
- 見た目は `theme.py` の共通デザインシステムに合わせている。3つの操作ボタンは
  同じRow内で `expand=True` を使い等幅に揃える(`wrap=True`は使わない。
  wrap+expandの組み合わせはこのFletバージョンでレイアウトが壊れる既知の不具合)。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable, Optional

import flet as ft

import theme
from db import Database
from formatting import format_hms, format_yen
from models import WorkSession
from wage import earnings_so_far, effective_rate, finalize_amount, is_currently_paused


def show_snack(page: ft.Page, message: str, error: bool = False) -> None:
    """簡易メッセージ表示。ダイアログより軽量なSnackBarで代替する。"""
    snack = ft.SnackBar(
        content=ft.Text(message, color="#FFFFFF"),
        open=True,
        bgcolor=theme.DANGER if error else theme.PRIMARY,
        shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM),
    )
    page.overlay.append(snack)
    page.update()


def build_timer_view(page: ft.Page, db: Database) -> tuple[ft.Control, Callable[[], None]]:
    """タイマー画面のControlと、タブ表示のたびに呼ぶrefresh関数を返す。"""

    state: dict = {
        "workplace": None,
        "session": None,  # type: Optional[WorkSession]
        "active": False,  # ticking_loopの継続フラグ
    }

    workplace_dropdown = ft.Dropdown(
        label="バイト先",
        options=[],
        expand=True,
        **theme.field_style(),
    )
    amount_text = ft.Text("¥0", size=52, weight=ft.FontWeight.W_800, color=theme.TEXT_PRIMARY)
    elapsed_text = ft.Row(
        [ft.Icon(ft.Icons.SCHEDULE, size=15, color=theme.TEXT_SECONDARY), theme.caption_text("00:00:00")],
        spacing=4,
        alignment=ft.MainAxisAlignment.CENTER,
    )
    status_badge = theme.badge("待機中", theme.TEXT_SECONDARY, theme.NEUTRAL_SOFT)
    transport_switch = ft.Switch(value=True, active_color=theme.PRIMARY)

    start_button = ft.FilledButton(
        content=ft.Row(
            [ft.Icon(ft.Icons.PLAY_ARROW, size=18), ft.Text("スタート", weight=ft.FontWeight.W_600)],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=4,
            tight=True,
        ),
        expand=True,
        height=52,
        style=ft.ButtonStyle(
            bgcolor=theme.PRIMARY,
            shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM),
        ),
    )
    pause_button = ft.FilledTonalButton(
        content=ft.Row(
            [ft.Icon(ft.Icons.PAUSE, size=18), ft.Text("一時停止", weight=ft.FontWeight.W_600)],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=4,
            tight=True,
        ),
        expand=True,
        height=52,
        disabled=True,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
    )
    end_button = ft.OutlinedButton(
        content=ft.Row(
            [ft.Icon(ft.Icons.STOP, size=18, color=theme.DANGER), ft.Text("エンド", weight=ft.FontWeight.W_600, color=theme.DANGER)],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=4,
            tight=True,
        ),
        expand=True,
        height=52,
        disabled=True,
        style=ft.ButtonStyle(
            side=ft.BorderSide(1, theme.DANGER),
            shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM),
        ),
    )
    last_result_banner = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=theme.SUCCESS), ft.Text("", size=13, color=theme.SUCCESS)],
            spacing=6,
        ),
        padding=ft.Padding(12, 10, 12, 10),
        bgcolor=theme.SUCCESS_SOFT,
        border_radius=theme.RADIUS_SM,
        visible=False,
    )

    def set_last_result(message: str) -> None:
        if message:
            last_result_banner.content.controls[1].value = message
            last_result_banner.visible = True
        else:
            last_result_banner.visible = False

    def reload_workplaces(select_id: Optional[int] = None) -> None:
        workplaces = db.list_workplaces()
        workplace_dropdown.options = [
            ft.DropdownOption(key=str(w.id), text=f"{w.name} ・ ¥{w.base_wage:.0f}/時")
            for w in workplaces
        ]
        if select_id is not None:
            workplace_dropdown.value = str(select_id)
        elif workplaces and workplace_dropdown.value is None:
            workplace_dropdown.value = str(workplaces[0].id)

    def set_idle_ui() -> None:
        start_button.disabled = False
        pause_button.disabled = True
        end_button.disabled = True
        workplace_dropdown.disabled = False
        transport_switch.disabled = False
        pause_button.content.controls[0].icon = ft.Icons.PAUSE
        pause_button.content.controls[1].value = "一時停止"
        status_badge.content.value = "待機中"
        status_badge.bgcolor = theme.NEUTRAL_SOFT
        status_badge.content.color = theme.TEXT_SECONDARY
        amount_text.value = "¥0"
        elapsed_text.controls[1].value = "00:00:00"

    def set_running_ui() -> None:
        start_button.disabled = True
        pause_button.disabled = False
        end_button.disabled = False
        workplace_dropdown.disabled = True
        transport_switch.disabled = True

    async def ticking_loop() -> None:
        while state["active"] and state["session"] is not None:
            session: WorkSession = state["session"]
            wp = state["workplace"]
            now = datetime.now()
            amount = earnings_so_far(wp, wp.rules, session, now=now)
            elapsed = (now - session.start_ts).total_seconds() - session.total_break_seconds(now)
            amount_text.value = format_yen(amount)
            elapsed_text.controls[1].value = format_hms(elapsed)

            paused = is_currently_paused(session)
            if paused:
                status_badge.content.value = "一時停止中"
                status_badge.bgcolor = theme.NEUTRAL_SOFT
                status_badge.content.color = theme.TEXT_SECONDARY
            else:
                rate_now = effective_rate(wp, wp.rules, now)
                if rate_now > wp.base_wage:
                    status_badge.content.value = f"⚡ 加算中 ・ ¥{rate_now:.0f}/時"
                    status_badge.bgcolor = theme.WARNING_SOFT
                    status_badge.content.color = theme.WARNING
                else:
                    status_badge.content.value = "稼働中"
                    status_badge.bgcolor = theme.SUCCESS_SOFT
                    status_badge.content.color = theme.SUCCESS
            page.update()
            await asyncio.sleep(1)

    async def on_start(e) -> None:
        if workplace_dropdown.value is None:
            show_snack(page, "先に「バイト先」タブでバイト先を登録してください", error=True)
            return
        workplace = db.get_workplace(int(workplace_dropdown.value))
        if workplace is None:
            show_snack(page, "バイト先が見つかりません", error=True)
            return
        existing = db.get_active_session()
        if existing is not None:
            show_snack(page, "既に稼働中のセッションがあります", error=True)
            return

        state["workplace"] = workplace
        state["session"] = db.start_session(workplace.id)
        state["active"] = True
        set_last_result("")
        set_running_ui()
        page.update()
        page.run_task(ticking_loop)

    async def on_pause_resume(e) -> None:
        session = state["session"]
        if session is None:
            return
        if is_currently_paused(session):
            db.resume_session(session.id)
            pause_button.content.controls[0].icon = ft.Icons.PAUSE
            pause_button.content.controls[1].value = "一時停止"
        else:
            db.pause_session(session.id)
            pause_button.content.controls[0].icon = ft.Icons.PLAY_ARROW
            pause_button.content.controls[1].value = "再開"
        state["session"] = db.get_session(session.id)
        page.update()

    async def on_end(e) -> None:
        session = state["session"]
        workplace = state["workplace"]
        if session is None or workplace is None:
            return
        state["active"] = False
        now = datetime.now()
        base_amount = earnings_so_far(workplace, workplace.rules, session, now=now)
        final_amount = finalize_amount(
            base_amount, workplace, include_transport=transport_switch.value
        )
        db.end_session(
            session.id,
            gross_amount=final_amount,
            end_ts=now,
            transport_included=transport_switch.value,
        )
        state["session"] = None
        state["workplace"] = None
        set_last_result(f"直前の勤務: {format_yen(final_amount)} を記録しました")
        set_idle_ui()
        page.update()

    start_button.on_click = on_start
    pause_button.on_click = on_pause_resume
    end_button.on_click = on_end

    def refresh() -> None:
        """タブ表示のたびに呼ぶ: バイト先一覧の再読込 & 稼働中セッションの復帰。"""
        reload_workplaces(
            select_id=int(workplace_dropdown.value) if workplace_dropdown.value else None
        )
        active = db.get_active_session()
        if active is not None and state["session"] is None:
            # アプリ再起動やタブ切替後の復帰: 稼働中セッションをUIに反映する。
            state["workplace"] = db.get_workplace(active.workplace_id)
            state["session"] = active
            state["active"] = True
            workplace_dropdown.value = str(active.workplace_id)
            set_running_ui()
            if is_currently_paused(active):
                pause_button.content.controls[0].icon = ft.Icons.PLAY_ARROW
                pause_button.content.controls[1].value = "再開"
            page.update()
            page.run_task(ticking_loop)
        page.update()

    earnings_card = theme.card(
        ft.Column(
            [
                status_badge,
                amount_text,
                elapsed_text,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        ),
        padding=theme.SPACE_LG,
    )
    earnings_card.alignment = ft.Alignment.CENTER

    transport_row = theme.card(
        ft.Row(
            [
                ft.Icon(ft.Icons.DIRECTIONS_BUS, size=18, color=theme.TEXT_SECONDARY),
                ft.Text("交通費を含める", size=14, color=theme.TEXT_PRIMARY, expand=True),
                transport_switch,
            ],
            alignment=ft.MainAxisAlignment.START,
        ),
        padding=ft.Padding(theme.SPACE_MD, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM),
    )

    view = ft.Column(
        controls=[
            workplace_dropdown,
            earnings_card,
            ft.Row([start_button, pause_button, end_button], spacing=10),
            transport_row,
            last_result_banner,
        ],
        spacing=theme.SPACE_MD,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    reload_workplaces()
    return view, refresh
