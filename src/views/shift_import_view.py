"""シフト取込カード: カレンダー画面に埋め込む折りたたみ式のUI。

画像選択 → クラウドAI(ai/vision.py)で解析 → 確認・編集フォーム → 保存(shift_plans)、
という一連の流れを1つのカードにまとめている。

human-in-the-loop の原則: AIの抽出結果は必ずこの画面上の編集可能なフォームを経由してから
保存する。ユーザーが内容を確認・修正した上で保存ボタンを押すことそのものが「確認」を兼ねる
ため、保存時は常に `ShiftPlan.confirmed=True` とする。
"""

from __future__ import annotations

from datetime import date, time
from typing import Callable, Optional

import flet as ft

import theme
from ai.vision import ExtractedShift, VisionError, extract_shifts
from db import Database
from models import ShiftPlan, ShiftSource


def build_shift_import_card(
    page: ft.Page, db: Database, on_saved: Callable[[], None]
) -> tuple[ft.Control, Callable[[], None]]:
    file_picker = ft.FilePicker()
    file_picker_attached = {"done": False}

    def ensure_file_picker_attached() -> None:
        """FilePickerを実際に使う直前まで page.overlay に追加しない。

        `flet run --web` のプレビュークライアントは FilePicker を認識できず
        "Unknown control: FilePicker" という赤い帯を表示してしまう既知の不具合が
        ある(flet-dev/flet issue #6040 等)。起動時に無条件でoverlayへ追加すると
        アプリ全体・全タブでこの帯が常時表示されてしまうため、実際に「写真を選択」
        ボタンが押されるまで追加を遅らせ、影響をシフト取込機能の利用時だけに限定する。
        (なお `flet build apk` 等の正式ビルドではFilePickerは問題なく動作する見込み。
        この問題はプレビュー専用クライアントの制限)。
        """
        if not file_picker_attached["done"]:
            page.overlay.append(file_picker)
            file_picker_attached["done"] = True

    pending_image: dict = {"bytes": None, "filename": None}
    row_state: list[dict] = []  # [{shift, date_tf, start_tf, end_tf}, ...]

    # --- AI設定(APIキー・自分の名前) -------------------------------------------
    api_key_field = ft.TextField(
        label="Anthropic APIキー", password=True, can_reveal_password=True, expand=True, **theme.field_style()
    )
    my_name_field = ft.TextField(label="自分の名前(シフト表の表記に合わせる)", expand=True, **theme.field_style())
    settings_status = ft.Text("", size=12, color=theme.SUCCESS)

    def load_settings() -> None:
        api_key_field.value = db.get_setting("anthropic_api_key", "") or ""
        my_name_field.value = db.get_setting("my_name", "") or ""

    def on_save_settings(e) -> None:
        db.set_setting("anthropic_api_key", api_key_field.value or "")
        db.set_setting("my_name", my_name_field.value or "")
        settings_status.value = "設定を保存しました"
        page.update()

    # --- バイト先選択 -------------------------------------------------------
    workplace_dd = ft.Dropdown(label="バイト先", options=[], expand=True, **theme.field_style())

    def reload_workplaces() -> None:
        workplaces = db.list_workplaces()
        workplace_dd.options = [ft.DropdownOption(key=str(w.id), text=w.name) for w in workplaces]
        if workplaces and workplace_dd.value is None:
            workplace_dd.value = str(workplaces[0].id)

    # --- 画像選択・プレビュー・解析 ----------------------------------------------
    preview_image = ft.Image(src="", visible=False, height=160, fit=ft.BoxFit.CONTAIN, border_radius=theme.RADIUS_SM)
    loading_ring = ft.ProgressRing(visible=False, width=18, height=18, stroke_width=2, color=theme.PRIMARY)
    loading_row = ft.Row([loading_ring, theme.caption_text("AIが解析中です...")], visible=False, spacing=8)
    status_text = ft.Text("", size=13, color=theme.DANGER)
    result_rows_col = ft.Column(spacing=8)
    save_button = ft.FilledButton(
        content=ft.Row(
            [ft.Icon(ft.Icons.SAVE_OUTLINED, size=16), ft.Text("シフトを保存", weight=ft.FontWeight.W_600)],
            spacing=4,
            tight=True,
        ),
        disabled=True,
        style=ft.ButtonStyle(bgcolor=theme.PRIMARY, shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
    )

    def set_loading(is_loading: bool) -> None:
        loading_row.visible = is_loading
        page.update()

    def render_result_rows() -> None:
        result_rows_col.controls.clear()
        row_state.clear()
        for shift in pending_shifts:
            date_tf = ft.TextField(
                label="日付(YYYY-MM-DD)",
                value=shift.plan_date.isoformat() if shift.plan_date else "",
                expand=True,
                **theme.field_style(),
            )
            start_tf = ft.TextField(
                label="開始 HH:MM",
                value=shift.start_time.strftime("%H:%M") if shift.start_time else "",
                expand=True,
                **theme.field_style(),
            )
            end_tf = ft.TextField(
                label="終了 HH:MM",
                value=shift.end_time.strftime("%H:%M") if shift.end_time else "",
                expand=True,
                **theme.field_style(),
            )
            entry = {"date_tf": date_tf, "start_tf": start_tf, "end_tf": end_tf}
            row_state.append(entry)

            def on_remove_row(e, entry=entry):
                idx = row_state.index(entry)
                row_state.pop(idx)
                result_rows_col.controls.pop(idx)
                save_button.disabled = len(row_state) == 0
                page.update()

            result_rows_col.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(f"候補: {shift.raw_label}", size=11, color=theme.TEXT_SECONDARY, expand=True),
                                    ft.IconButton(
                                        icon=ft.Icons.DELETE_OUTLINE,
                                        icon_size=16,
                                        icon_color=theme.TEXT_SECONDARY,
                                        on_click=on_remove_row,
                                        tooltip="この候補を除外",
                                    ),
                                ]
                            ),
                            date_tf,
                            ft.Row([start_tf, end_tf], spacing=8),
                        ],
                        spacing=6,
                    ),
                    padding=theme.SPACE_SM,
                    bgcolor=theme.SURFACE_ALT,
                    border_radius=theme.RADIUS_SM,
                )
            )
        save_button.disabled = len(row_state) == 0
        page.update()

    pending_shifts: list[ExtractedShift] = []

    async def run_extraction() -> None:
        nonlocal pending_shifts
        api_key = db.get_setting("anthropic_api_key", "") or ""
        my_name = db.get_setting("my_name", "") or ""
        status_text.value = ""
        set_loading(True)
        today = date.today()
        try:
            pending_shifts = await extract_shifts(
                pending_image["bytes"],
                pending_image["filename"],
                api_key,
                my_name,
                reference_year=today.year,
                reference_month=today.month,
            )
        except VisionError as ex:
            status_text.value = str(ex)
            pending_shifts = []
        set_loading(False)
        if not pending_shifts and not status_text.value:
            status_text.value = "該当するシフトが見つかりませんでした(画像や名前の設定をご確認ください)"
        render_result_rows()
        page.update()

    async def on_pick_image(e) -> None:
        status_text.value = ""
        result_rows_col.controls.clear()
        row_state.clear()
        save_button.disabled = True
        ensure_file_picker_attached()
        page.update()

        files = await file_picker.pick_files(
            dialog_title="シフト表の写真を選択",
            file_type=ft.FilePickerFileType.IMAGE,
            with_data=True,
        )
        if not files:
            return
        picked = files[0]
        if not picked.bytes:
            status_text.value = "画像データを読み込めませんでした"
            page.update()
            return
        pending_image["bytes"] = picked.bytes
        pending_image["filename"] = picked.name
        preview_image.src = picked.bytes
        preview_image.visible = True
        page.update()
        await run_extraction()

    def on_save_all(e) -> None:
        if workplace_dd.value is None:
            status_text.value = "バイト先を選択してください"
            page.update()
            return
        workplace_id = int(workplace_dd.value)
        saved = 0
        skipped = 0
        for entry in list(row_state):
            plan_date = _safe_parse_date(entry["date_tf"].value)
            start_t = _safe_parse_time(entry["start_tf"].value)
            end_t = _safe_parse_time(entry["end_tf"].value)
            if plan_date is None or start_t is None or end_t is None:
                skipped += 1
                continue
            db.add_shift_plan(
                ShiftPlan(
                    workplace_id=workplace_id,
                    plan_date=plan_date,
                    start_time=start_t,
                    end_time=end_t,
                    source=ShiftSource.AI,
                    confirmed=True,
                )
            )
            saved += 1

        if skipped:
            status_text.value = f"{saved}件を保存しました({skipped}件は日付/時刻が不正のためスキップ)"
            status_text.color = theme.WARNING
        else:
            status_text.value = f"{saved}件のシフトを保存しました"
            status_text.color = theme.SUCCESS
        result_rows_col.controls.clear()
        row_state.clear()
        pending_shifts.clear()
        preview_image.visible = False
        save_button.disabled = True
        page.update()
        on_saved()

    save_settings_button = ft.FilledTonalButton(
        "保存",
        on_click=on_save_settings,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
    )
    pick_image_button = ft.FilledTonalButton(
        content=ft.Row(
            [ft.Icon(ft.Icons.PHOTO_CAMERA_OUTLINED, size=16), ft.Text("シフト表の写真を選択", weight=ft.FontWeight.W_600)],
            spacing=4,
            tight=True,
        ),
        on_click=on_pick_image,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
    )
    save_button.on_click = on_save_all

    load_settings()
    reload_workplaces()

    card = theme.card(
        ft.Column(
            [
                ft.Row(
                    [ft.Icon(ft.Icons.PHOTO_CAMERA_OUTLINED, size=17, color=theme.PRIMARY), theme.title_text("シフト表を取り込む")],
                    spacing=8,
                ),
                theme.caption_text(
                    "写真からAIが自分のシフトだけを読み取ります。保存前に必ず内容を確認・修正してください。"
                ),
                ft.Divider(height=1, color=theme.BORDER),
                theme.caption_text("AI設定"),
                api_key_field,
                ft.Row([my_name_field, save_settings_button], spacing=8),
                settings_status,
                ft.Divider(height=1, color=theme.BORDER),
                workplace_dd,
                pick_image_button,
                preview_image,
                loading_row,
                status_text,
                result_rows_col,
                save_button,
            ],
            spacing=10,
        )
    )

    def refresh() -> None:
        reload_workplaces()

    return card, refresh


def _safe_parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _safe_parse_time(value: Optional[str]) -> Optional[time]:
    if not value:
        return None
    try:
        return time.fromisoformat(value.strip())
    except ValueError:
        return None
