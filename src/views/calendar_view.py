"""カレンダー画面: 日別ヒートマップ、月/年集計、バイト先別内訳、
収入の壁アラート、月間目標、CSVエクスポート。

チャート専用コントロール(LineChart/PieChart等)はこのFletバージョンには
存在しないため、ProgressBar と色分けされたContainerグリッドだけで
ヒートマップ・棒グラフ相当を自作している。見た目は `theme.py` の共通デザイン
システムに統一し、セクションごとにカードで区切って情報の塊を分かりやすくしている。
"""

from __future__ import annotations

import calendar
import csv
import io
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import flet as ft

import theme
from db import Database
from formatting import format_yen
from models import WorkSession
from views.shift_import_view import build_shift_import_card

WEEKDAY_HEADER = ["月", "火", "水", "木", "金", "土", "日"]
MONTH_NAMES = [f"{m}月" for m in range(1, 13)]

# 扶養/社保の壁(円)。上から103万・106万・130万。
WALL_THRESHOLDS = [
    ("103万円の壁(所得税)", 1_030_000),
    ("106万円の壁(社会保険)", 1_060_000),
    ("130万円の壁(社会保険)", 1_300_000),
]


def _heat_color(amount: float, max_amount: float) -> str:
    if amount <= 0 or max_amount <= 0:
        return theme.HEAT_LEVELS[0]
    ratio = amount / max_amount
    if ratio < 0.25:
        return theme.HEAT_LEVELS[1]
    if ratio < 0.5:
        return theme.HEAT_LEVELS[2]
    if ratio < 0.75:
        return theme.HEAT_LEVELS[3]
    return theme.HEAT_LEVELS[4]


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _export_dir() -> Path:
    """CSV出力先。DBと同じ永続ディレクトリ配下の exports/ を使う。"""
    import db as db_module

    base = db_module.default_db_path().parent / "exports"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _section_header(icon: str, text: str) -> ft.Row:
    return ft.Row(
        [ft.Icon(icon, size=17, color=theme.PRIMARY), theme.title_text(text)],
        spacing=8,
    )


def build_calendar_view(page: ft.Page, db: Database) -> tuple[ft.Control, Callable[[], None]]:
    today = date.today()
    state = {"year": today.year, "month": today.month, "selected_day": None}

    month_label = ft.Text(
        "", size=17, weight=ft.FontWeight.W_700, color=theme.TEXT_PRIMARY, text_align=ft.TextAlign.CENTER
    )
    heatmap_grid = ft.Column(spacing=4)
    selected_day_panel = ft.Column(spacing=4)
    monthly_total_value = ft.Text("", size=26, weight=ft.FontWeight.W_800, color=theme.TEXT_PRIMARY)
    workplace_breakdown_col = ft.Column(spacing=10)
    sessions_list_col = ft.Column(spacing=6)

    yearly_total_value = ft.Text("", size=22, weight=ft.FontWeight.W_800, color=theme.TEXT_PRIMARY)
    yearly_bars_col = ft.Column(spacing=8)

    wall_section_col = ft.Column(spacing=14)
    goal_field = ft.TextField(
        label="今月の目標金額(円)", keyboard_type=ft.KeyboardType.NUMBER, expand=True, **theme.field_style()
    )
    goal_progress = ft.ProgressBar(value=0, color=theme.PRIMARY, bgcolor=theme.SURFACE_ALT, bar_height=10, border_radius=6)
    goal_summary_text = ft.Text("", size=13, color=theme.TEXT_SECONDARY)
    export_status_text = ft.Text("", size=12, color=theme.TEXT_SECONDARY)

    workplaces_cache: dict[int, str] = {}

    def workplace_name(workplace_id: int) -> str:
        if workplace_id not in workplaces_cache:
            wp = db.get_workplace(workplace_id)
            workplaces_cache[workplace_id] = wp.name if wp else f"#{workplace_id}"
        return workplaces_cache[workplace_id]

    def select_day(d: date) -> None:
        state["selected_day"] = d
        render_selected_day()
        page.update()

    def render_selected_day() -> None:
        d: Optional[date] = state["selected_day"]
        selected_day_panel.controls.clear()
        if d is None:
            selected_day_panel.controls.append(theme.caption_text("日付をタップすると内訳が見られます"))
            return
        sessions = db.list_sessions(d, d)
        plans = db.list_shift_plans(d, d)
        selected_day_panel.controls.append(
            ft.Text(
                f"{d.month}月{d.day}日 ({WEEKDAY_HEADER[d.weekday()]})",
                weight=ft.FontWeight.W_700,
                size=13,
                color=theme.TEXT_PRIMARY,
            )
        )
        if not sessions and not plans:
            selected_day_panel.controls.append(theme.caption_text("記録なし"))
        for p in plans:
            wp_name = workplace_name(p.workplace_id)
            time_range = f"{p.start_time.strftime('%H:%M')}-{p.end_time.strftime('%H:%M')}"
            selected_day_panel.controls.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.EVENT_OUTLINED, size=13, color=theme.WARNING),
                        ft.Text(f"予定: {wp_name}", size=12, color=theme.TEXT_SECONDARY, expand=True),
                        ft.Text(time_range, size=12, color=theme.TEXT_SECONDARY),
                    ],
                    spacing=4,
                )
            )
        for s in sessions:
            wp_name = workplace_name(s.workplace_id)
            time_range = f"{s.start_ts.strftime('%H:%M')}-{s.end_ts.strftime('%H:%M') if s.end_ts else '--'}"
            selected_day_panel.controls.append(
                ft.Row(
                    [
                        ft.Text(wp_name, size=12, color=theme.TEXT_SECONDARY, expand=True),
                        ft.Text(time_range, size=12, color=theme.TEXT_SECONDARY),
                        ft.Text(format_yen(s.gross_amount), size=12, weight=ft.FontWeight.W_600, color=theme.PRIMARY),
                    ]
                )
            )

    def _session_row(s: WorkSession) -> ft.Row:
        wp_name = workplace_name(s.workplace_id)
        time_range = f"{s.start_ts.strftime('%H:%M')}-{s.end_ts.strftime('%H:%M') if s.end_ts else '--'}"
        return ft.Row(
            [
                ft.Text(f"{s.start_ts.month}/{s.start_ts.day}", size=12, color=theme.TEXT_SECONDARY, width=32),
                ft.Text(wp_name, size=12, color=theme.TEXT_PRIMARY, expand=True),
                ft.Text(time_range, size=12, color=theme.TEXT_SECONDARY),
                ft.Text(format_yen(s.gross_amount), size=12, weight=ft.FontWeight.W_600, color=theme.PRIMARY),
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    icon_size=16,
                    icon_color=theme.TEXT_SECONDARY,
                    tooltip="削除",
                    on_click=(lambda e, sess=s: on_delete_session(sess)),
                ),
            ],
            spacing=4,
        )

    def render_sessions_list() -> None:
        start, end = _month_bounds(state["year"], state["month"])
        sessions = db.list_sessions(start, end)
        sessions_list_col.controls.clear()
        if not sessions:
            sessions_list_col.controls.append(theme.caption_text("記録がありません"))
            return
        for s in sorted(sessions, key=lambda x: x.start_ts, reverse=True):
            sessions_list_col.controls.append(_session_row(s))

    def show_undo_snack(session: WorkSession) -> None:
        def on_undo(e) -> None:
            db.insert_session(session)
            render_heatmap()
            render_yearly()
            page.update()

        snack = ft.SnackBar(
            content=ft.Text("出勤記録を削除しました", color="#FFFFFF"),
            open=True,
            bgcolor=theme.DANGER,
            action="元に戻す",
            on_action=on_undo,
            shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM),
        )
        page.overlay.append(snack)

    def on_delete_session(session: WorkSession) -> None:
        db.delete_session(session.id)
        render_heatmap()
        render_yearly()
        show_undo_snack(session)
        page.update()

    def render_heatmap() -> None:
        year, month = state["year"], state["month"]
        month_label.value = f"{year}年 {month}月"
        start, end = _month_bounds(year, month)
        daily = db.daily_totals(start, end)
        max_amount = max(daily.values(), default=0.0)
        plan_dates = {p.plan_date for p in db.list_shift_plans(start, end)}

        cal = calendar.Calendar(firstweekday=0)
        weeks = cal.monthdatescalendar(year, month)

        heatmap_grid.controls.clear()
        header_row = ft.Row(
            [
                ft.Container(theme.caption_text(w), width=36, alignment=ft.Alignment.CENTER)
                for w in WEEKDAY_HEADER
            ],
            spacing=4,
        )
        heatmap_grid.controls.append(header_row)

        for week in weeks:
            cells = []
            for d in week:
                amount = daily.get(d, 0.0)
                in_month = d.month == month
                color = _heat_color(amount, max_amount) if in_month else theme.HEAT_LEVELS[0]
                is_today = d == today
                is_dark_cell = in_month and amount > 0 and color != theme.HEAT_LEVELS[0]
                text_color = "#FFFFFF" if is_dark_cell else theme.TEXT_SECONDARY
                cell_content: ft.Control
                if in_month and d in plan_dates:
                    dot_color = "#FFFFFF" if is_dark_cell else theme.WARNING
                    cell_content = ft.Stack(
                        [
                            ft.Container(
                                content=ft.Text(
                                    str(d.day), size=11, color=text_color, weight=ft.FontWeight.W_600 if is_today else None
                                ),
                                alignment=ft.Alignment.CENTER,
                                expand=True,
                            ),
                            ft.Container(width=5, height=5, bgcolor=dot_color, border_radius=3, bottom=3, right=3),
                        ]
                    )
                else:
                    cell_content = ft.Text(str(d.day), size=11, color=text_color, weight=ft.FontWeight.W_600 if is_today else None)
                cell = ft.Container(
                    content=cell_content,
                    width=36,
                    height=36,
                    bgcolor=color,
                    border_radius=theme.RADIUS_SM,
                    alignment=ft.Alignment.CENTER,
                    opacity=1.0 if in_month else 0.35,
                    border=ft.Border.all(1.5, theme.PRIMARY) if is_today else None,
                    on_click=(lambda e, dd=d: select_day(dd)),
                )
                cells.append(cell)
            heatmap_grid.controls.append(ft.Row(cells, spacing=4))

        monthly_total = db.monthly_total(year, month)
        monthly_total_value.value = format_yen(monthly_total)

        by_wp = db.total_by_workplace(start, end)
        workplace_breakdown_col.controls.clear()
        max_wp = max(by_wp.values(), default=0.0)
        for wp_id, amount in sorted(by_wp.items(), key=lambda kv: -kv[1]):
            ratio = (amount / max_wp) if max_wp > 0 else 0
            workplace_breakdown_col.controls.append(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(workplace_name(wp_id), size=13, color=theme.TEXT_PRIMARY, expand=True),
                                ft.Text(format_yen(amount), size=13, weight=ft.FontWeight.W_600, color=theme.TEXT_PRIMARY),
                            ]
                        ),
                        ft.ProgressBar(value=ratio, color=theme.PRIMARY, bgcolor=theme.SURFACE_ALT, bar_height=8, border_radius=4),
                    ],
                    spacing=4,
                )
            )
        if not by_wp:
            workplace_breakdown_col.controls.append(theme.caption_text("記録がありません"))

        render_selected_day()
        render_sessions_list()
        render_goal(monthly_total)

    def render_yearly() -> None:
        year = state["year"]
        yearly_total = db.yearly_total(year)
        yearly_total_value.value = format_yen(yearly_total)

        by_month = db.yearly_total_by_month(year)
        max_month = max(by_month.values(), default=0.0)
        yearly_bars_col.controls.clear()
        for m in range(1, 13):
            amount = by_month.get(m, 0.0)
            ratio = (amount / max_month) if max_month > 0 else 0
            is_current = m == state["month"]

            def jump_to_month(e, mm=m):
                state["month"] = mm
                render_heatmap()
                page.update()

            yearly_bars_col.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        MONTH_NAMES[m - 1],
                                        size=12,
                                        color=theme.PRIMARY if is_current else theme.TEXT_SECONDARY,
                                        weight=ft.FontWeight.W_700 if is_current else None,
                                        expand=True,
                                    ),
                                    ft.Text(format_yen(amount), size=12, color=theme.TEXT_PRIMARY),
                                ]
                            ),
                            ft.ProgressBar(
                                value=ratio,
                                color=theme.PRIMARY if is_current else theme.TEXT_DISABLED,
                                bgcolor=theme.SURFACE_ALT,
                                bar_height=7,
                                border_radius=4,
                            ),
                        ],
                        spacing=3,
                    ),
                    on_click=jump_to_month,
                    border_radius=theme.RADIUS_SM,
                )
            )

        render_wall_alert(yearly_total)

    def render_wall_alert(yearly_total: float) -> None:
        wall_section_col.controls.clear()
        for label, threshold in WALL_THRESHOLDS:
            ratio = min(1.0, yearly_total / threshold)
            if yearly_total >= threshold:
                color = theme.DANGER
            elif ratio >= 0.9:
                color = theme.WARNING
            else:
                color = theme.SUCCESS
            wall_section_col.controls.append(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(label, size=13, color=theme.TEXT_PRIMARY, expand=True),
                                ft.Text(f"{ratio * 100:.0f}%", size=13, weight=ft.FontWeight.W_700, color=color),
                            ]
                        ),
                        ft.ProgressBar(value=ratio, color=color, bgcolor=theme.SURFACE_ALT, bar_height=8, border_radius=4),
                        theme.caption_text(f"{format_yen(yearly_total)} / {format_yen(threshold)}"),
                    ],
                    spacing=4,
                )
            )

    def render_goal(monthly_total: float) -> None:
        goal_str = db.get_setting("monthly_goal")
        if goal_str is None:
            goal_progress.value = 0
            goal_summary_text.value = "目標未設定"
            return
        goal = float(goal_str)
        if goal_field.value in (None, ""):
            goal_field.value = goal_str
        ratio = min(1.0, monthly_total / goal) if goal > 0 else 0
        goal_progress.value = ratio
        goal_progress.color = theme.SUCCESS if monthly_total >= goal else theme.PRIMARY
        goal_summary_text.value = f"目標 {format_yen(goal)} 中 {format_yen(monthly_total)} 達成(達成率{ratio * 100:.0f}%)"

    def on_save_goal(e) -> None:
        try:
            goal = float(goal_field.value)
        except (TypeError, ValueError):
            return
        db.set_setting("monthly_goal", str(goal))
        render_heatmap()
        page.update()

    def change_month(delta: int):
        def handler(e):
            m = state["month"] + delta
            y = state["year"]
            while m < 1:
                m += 12
                y -= 1
            while m > 12:
                m -= 12
                y += 1
            state["month"], state["year"] = m, y
            render_heatmap()
            render_yearly()
            page.update()

        return handler

    def change_year(delta: int):
        def handler(e):
            state["year"] += delta
            render_heatmap()
            render_yearly()
            page.update()

        return handler

    def on_export_csv(e) -> None:
        year, month = state["year"], state["month"]
        start, end = _month_bounds(year, month)
        sessions = db.list_sessions(start, end)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["日付", "バイト先", "開始", "終了", "金額(円)"])
        for s in sessions:
            writer.writerow(
                [
                    s.start_ts.date().isoformat(),
                    workplace_name(s.workplace_id),
                    s.start_ts.strftime("%H:%M"),
                    s.end_ts.strftime("%H:%M") if s.end_ts else "",
                    round(s.gross_amount),
                ]
            )
        out_path = _export_dir() / f"earnings_{year:04d}-{month:02d}.csv"
        out_path.write_text(buf.getvalue(), encoding="utf-8-sig")  # BOM付きでExcelでも文字化けしないように
        export_status_text.value = f"出力しました: {out_path.name}"
        page.update()

    goal_field.on_submit = on_save_goal

    heatmap_card = theme.card(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, icon_color=theme.TEXT_SECONDARY, tooltip="前の月", on_click=change_month(-1)),
                        ft.Container(content=month_label, expand=True, alignment=ft.Alignment.CENTER),
                        ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, icon_color=theme.TEXT_SECONDARY, tooltip="次の月", on_click=change_month(1)),
                    ]
                ),
                heatmap_grid,
                ft.Divider(height=1, color=theme.BORDER),
                selected_day_panel,
            ],
            spacing=10,
        )
    )

    monthly_card = theme.card(
        ft.Column(
            [
                _section_header(ft.Icons.CALENDAR_VIEW_MONTH, "今月の合計"),
                monthly_total_value,
                ft.Divider(height=1, color=theme.BORDER),
                theme.caption_text("バイト先別内訳"),
                workplace_breakdown_col,
                ft.Divider(height=1, color=theme.BORDER),
                theme.caption_text("出勤記録"),
                sessions_list_col,
                ft.OutlinedButton(
                    content=ft.Row(
                        [ft.Icon(ft.Icons.FILE_DOWNLOAD_OUTLINED, size=16), ft.Text("CSV出力(今月分)", weight=ft.FontWeight.W_600)],
                        spacing=4,
                        tight=True,
                    ),
                    on_click=on_export_csv,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
                ),
                export_status_text,
            ],
            spacing=10,
        )
    )

    goal_card = theme.card(
        ft.Column(
            [
                _section_header(ft.Icons.FLAG_OUTLINED, "今月の目標"),
                ft.Row([goal_field, ft.FilledTonalButton("設定", on_click=on_save_goal, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)))], spacing=8),
                goal_progress,
                goal_summary_text,
            ],
            spacing=10,
        )
    )

    yearly_card = theme.card(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, icon_color=theme.TEXT_SECONDARY, tooltip="前の年", on_click=change_year(-1)),
                        ft.Container(
                            content=ft.Row(
                                [ft.Icon(ft.Icons.INSIGHTS, size=17, color=theme.PRIMARY), yearly_total_value],
                                spacing=8,
                                alignment=ft.MainAxisAlignment.CENTER,
                            ),
                            expand=True,
                        ),
                        ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, icon_color=theme.TEXT_SECONDARY, tooltip="次の年", on_click=change_year(1)),
                    ]
                ),
                theme.caption_text("月別内訳(タップでその月に移動)"),
                yearly_bars_col,
            ],
            spacing=10,
        )
    )

    wall_card = theme.card(
        ft.Column(
            [
                _section_header(ft.Icons.WARNING_AMBER_ROUNDED, "収入の壁アラート(年間・全バイト先合計)"),
                wall_section_col,
            ],
            spacing=10,
        )
    )

    def on_shift_saved() -> None:
        render_heatmap()
        page.update()

    shift_import_card, refresh_shift_import = build_shift_import_card(page, db, on_saved=on_shift_saved)
    shift_import_card.visible = False

    def toggle_shift_import(e) -> None:
        shift_import_card.visible = not shift_import_card.visible
        if shift_import_card.visible:
            refresh_shift_import()
        page.update()

    shift_import_toggle_row = ft.Row(
        [
            ft.FilledTonalButton(
                content=ft.Row(
                    [ft.Icon(ft.Icons.PHOTO_CAMERA_OUTLINED, size=16), ft.Text("シフト表を取り込む", weight=ft.FontWeight.W_600)],
                    spacing=4,
                    tight=True,
                ),
                on_click=toggle_shift_import,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
            )
        ],
        alignment=ft.MainAxisAlignment.END,
        # ブラウザ(Web/PWA)から直接 api.anthropic.com を呼ぶとCORSで必ず失敗するため、
        # Web実行時はこの機能自体を非表示にする(ネイティブ/デスクトップでのみ利用可能)。
        visible=not page.web,
    )

    view = ft.Column(
        controls=[heatmap_card, shift_import_toggle_row, shift_import_card, monthly_card, goal_card, yearly_card, wall_card],
        spacing=theme.SPACE_MD,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    def refresh() -> None:
        workplaces_cache.clear()
        render_heatmap()
        render_yearly()
        refresh_shift_import()
        page.update()

    render_heatmap()
    render_yearly()

    return view, refresh
