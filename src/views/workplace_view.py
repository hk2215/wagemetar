"""バイト先設定画面: 基本時給・交通費・締め日/給料日・深夜割増ON/OFFのCRUDと、
時間帯加算/曜日加算ルールを都度追加できるUI。

ダイアログ(AlertDialog)は使わず、ExpansionTileで各バイト先を折りたたみ表示し、
その中にインラインの編集フォーム・ルール追加フォームを置く方針(実装がシンプルで
挙動も把握しやすいため)。見た目は `theme.py` の共通デザインシステムに統一している。
"""

from __future__ import annotations

from datetime import time
from typing import Callable

import flet as ft

import theme
from db import Database
from models import BonusType, RuleKind, WageRule, Workplace

WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]

KIND_LABELS = {
    RuleKind.TIME_BAND: "時間帯加算",
    RuleKind.WEEKDAY: "曜日加算",
    RuleKind.NIGHT_PREMIUM: "深夜割増(カスタム)",
}
BONUS_LABELS = {
    BonusType.ADD: "円/時 加算",
    BonusType.MULTIPLY: "倍率",
}
KIND_ICONS = {
    RuleKind.TIME_BAND: ft.Icons.SCHEDULE,
    RuleKind.WEEKDAY: ft.Icons.EVENT_REPEAT,
    RuleKind.NIGHT_PREMIUM: ft.Icons.NIGHTLIGHT_ROUND,
}


def format_rule_label(rule: WageRule) -> str:
    """ルール一覧に表示する短い説明文。"""
    bonus = f"+{rule.amount:.0f}円/時" if rule.bonus_type == BonusType.ADD else f"×{rule.amount:.2f}"
    if rule.kind == RuleKind.TIME_BAND:
        day = f"({WEEKDAY_LABELS[rule.day_of_week]})" if rule.day_of_week is not None else "(毎日)"
        start_s = rule.start_time.strftime("%H:%M") if rule.start_time else "?"
        end_s = rule.end_time.strftime("%H:%M") if rule.end_time else "?"
        return f"{start_s}-{end_s}{day} ・ {bonus}"
    if rule.kind == RuleKind.WEEKDAY:
        day = WEEKDAY_LABELS[rule.day_of_week] if rule.day_of_week is not None else "?"
        return f"{day}曜日(終日) ・ {bonus}"
    if rule.kind == RuleKind.NIGHT_PREMIUM:
        s = rule.start_time.strftime("%H:%M") if rule.start_time else "22:00"
        e = rule.end_time.strftime("%H:%M") if rule.end_time else "05:00"
        return f"{s}-{e} ・ {bonus}"
    return "?"


def _field_row(fields: list[ft.Control]) -> ft.Row:
    """入力欄を並べる行。各フィールドはexpand=Trueで等幅に揃える(wrap=Trueは使わない)。"""
    return ft.Row(fields, spacing=theme.SPACE_SM)


def build_workplace_view(page: ft.Page, db: Database) -> tuple[ft.Control, Callable[[], None]]:
    list_column = ft.Column(spacing=theme.SPACE_MD)

    # --- 新規バイト先追加フォーム ------------------------------------------------
    new_name = ft.TextField(label="バイト先名", expand=True, **theme.field_style())
    new_base_wage = ft.TextField(
        label="基本時給(円)", keyboard_type=ft.KeyboardType.NUMBER, expand=True, **theme.field_style()
    )
    new_transport = ft.TextField(
        label="交通費(円/回)", keyboard_type=ft.KeyboardType.NUMBER, value="0", expand=True, **theme.field_style()
    )
    new_cutoff = ft.TextField(
        label="締め日(1-31)", keyboard_type=ft.KeyboardType.NUMBER, value="31", expand=True, **theme.field_style()
    )
    new_payday = ft.TextField(
        label="給料日(1-31)", keyboard_type=ft.KeyboardType.NUMBER, value="25", expand=True, **theme.field_style()
    )
    new_night = ft.Switch(label="深夜割増(22:00-翌5:00 +25%)を自動適用", value=False, active_color=theme.PRIMARY)
    add_error = ft.Text("", color=theme.DANGER, size=13)

    add_form = theme.card(
        ft.Column(
            [
                ft.Row(
                    [ft.Icon(ft.Icons.ADD_BUSINESS, color=theme.PRIMARY, size=20), theme.title_text("新しいバイト先を追加")],
                    spacing=8,
                ),
                new_name,
                _field_row([new_base_wage, new_transport]),
                _field_row([new_cutoff, new_payday]),
                new_night,
                add_error,
                ft.Row(
                    [
                        ft.FilledButton(
                            content=ft.Row(
                                [ft.Icon(ft.Icons.ADD, size=16), ft.Text("追加", weight=ft.FontWeight.W_600)],
                                spacing=4,
                                tight=True,
                            ),
                            style=ft.ButtonStyle(bgcolor=theme.PRIMARY, shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
                        ),
                        ft.TextButton("閉じる"),
                    ],
                    spacing=8,
                ),
            ],
            spacing=12,
        ),
        bgcolor=theme.SURFACE,
    )
    add_form.visible = False

    def toggle_add_form(e) -> None:
        add_form.visible = not add_form.visible
        page.update()

    add_form.content.controls[-1].controls[1].on_click = toggle_add_form

    def do_add_workplace(e) -> None:
        add_error.value = ""
        if not new_name.value or not new_name.value.strip():
            add_error.value = "バイト先名を入力してください"
            page.update()
            return
        try:
            base_wage = float(new_base_wage.value)
            transport = float(new_transport.value or 0)
            cutoff = int(new_cutoff.value or 31)
            payday = int(new_payday.value or 25)
        except (TypeError, ValueError):
            add_error.value = "数値の入力が正しくありません"
            page.update()
            return

        wp = Workplace(
            name=new_name.value.strip(),
            base_wage=base_wage,
            transport_allowance=transport,
            pay_cutoff_day=cutoff,
            payday=payday,
            night_premium_enabled=new_night.value,
        )
        db.add_workplace(wp)
        new_name.value = ""
        new_base_wage.value = ""
        new_transport.value = "0"
        new_cutoff.value = "31"
        new_payday.value = "25"
        new_night.value = False
        add_form.visible = False
        rebuild_list()
        page.update()

    add_form.content.controls[-1].controls[0].on_click = do_add_workplace

    # --- 既存バイト先の1件分のUIを組み立てる -------------------------------------

    def build_rule_row(rule: WageRule) -> ft.Container:
        def on_delete(e, rule_id=rule.id):
            db.delete_wage_rule(rule_id)
            rebuild_list()
            page.update()

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(KIND_ICONS.get(rule.kind, ft.Icons.RULE), size=16, color=theme.PRIMARY),
                    ft.Text(format_rule_label(rule), size=13, color=theme.TEXT_PRIMARY, expand=True),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE, icon_color=theme.TEXT_SECONDARY, icon_size=18, on_click=on_delete
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
            ),
            padding=ft.Padding(theme.SPACE_SM, 2, theme.SPACE_XS, 2),
            bgcolor=theme.SURFACE_ALT,
            border_radius=theme.RADIUS_SM,
        )

    def build_add_rule_form(workplace: Workplace) -> ft.Container:
        kind_dd = ft.Dropdown(
            label="種別",
            options=[ft.DropdownOption(key=k.value, text=v) for k, v in KIND_LABELS.items()],
            value=RuleKind.TIME_BAND.value,
            expand=True,
            **theme.field_style(),
        )
        bonus_dd = ft.Dropdown(
            label="適用方法",
            options=[ft.DropdownOption(key=k.value, text=v) for k, v in BONUS_LABELS.items()],
            value=BonusType.ADD.value,
            expand=True,
            **theme.field_style(),
        )
        amount_tf = ft.TextField(
            label="金額 or 倍率", keyboard_type=ft.KeyboardType.NUMBER, expand=True, **theme.field_style()
        )
        start_tf = ft.TextField(label="開始 HH:MM", value="16:00", expand=True, **theme.field_style())
        end_tf = ft.TextField(label="終了 HH:MM", value="18:00", expand=True, **theme.field_style())
        day_dd = ft.Dropdown(
            label="曜日",
            options=[ft.DropdownOption(key="any", text="毎日")]
            + [ft.DropdownOption(key=str(i), text=f"{w}曜日") for i, w in enumerate(WEEKDAY_LABELS)],
            value="any",
            expand=True,
            **theme.field_style(),
        )
        rule_error = ft.Text("", color=theme.DANGER, size=12)

        def on_kind_change(e) -> None:
            is_time_band = kind_dd.value == RuleKind.TIME_BAND.value
            is_night = kind_dd.value == RuleKind.NIGHT_PREMIUM.value
            start_tf.visible = is_time_band or is_night
            end_tf.visible = is_time_band or is_night
            day_dd.visible = is_time_band or kind_dd.value == RuleKind.WEEKDAY.value
            page.update()

        kind_dd.on_select = on_kind_change

        def on_add_rule(e) -> None:
            rule_error.value = ""
            try:
                amount = float(amount_tf.value)
            except (TypeError, ValueError):
                rule_error.value = "金額/倍率が正しくありません"
                page.update()
                return

            kind = RuleKind(kind_dd.value)
            day_of_week = None if day_dd.value == "any" else int(day_dd.value)
            start_t: time | None = None
            end_t: time | None = None
            if kind in (RuleKind.TIME_BAND, RuleKind.NIGHT_PREMIUM):
                try:
                    start_t = time.fromisoformat(start_tf.value)
                    end_t = time.fromisoformat(end_tf.value)
                except ValueError:
                    rule_error.value = "時刻は HH:MM の形式で入力してください"
                    page.update()
                    return
            if kind == RuleKind.WEEKDAY and day_of_week is None:
                rule_error.value = "曜日加算には曜日の指定が必要です"
                page.update()
                return

            rule = WageRule(
                workplace_id=workplace.id,
                kind=kind,
                bonus_type=BonusType(bonus_dd.value),
                amount=amount,
                start_time=start_t,
                end_time=end_t,
                day_of_week=day_of_week,
            )
            db.add_wage_rule(rule)
            amount_tf.value = ""
            rebuild_list()
            page.update()

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=15, color=theme.TEXT_SECONDARY), theme.caption_text("加算ルールを追加", theme.TEXT_SECONDARY)],
                        spacing=6,
                    ),
                    kind_dd,
                    _field_row([day_dd, bonus_dd]),
                    _field_row([start_tf, end_tf]),
                    amount_tf,
                    rule_error,
                    ft.FilledTonalButton(
                        content=ft.Row(
                            [ft.Icon(ft.Icons.ADD, size=16), ft.Text("ルールを追加", weight=ft.FontWeight.W_600)],
                            spacing=4,
                            tight=True,
                        ),
                        on_click=on_add_rule,
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
                    ),
                ],
                spacing=8,
            ),
            padding=theme.SPACE_SM,
            bgcolor=theme.SURFACE_DIM,
            border_radius=theme.RADIUS_SM,
        )

    def build_edit_form(workplace: Workplace) -> ft.Container:
        name_tf = ft.TextField(label="バイト先名", value=workplace.name, expand=True, **theme.field_style())
        base_wage_tf = ft.TextField(
            label="基本時給(円)",
            value=str(workplace.base_wage),
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
            **theme.field_style(),
        )
        transport_tf = ft.TextField(
            label="交通費(円/回)",
            value=str(workplace.transport_allowance),
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
            **theme.field_style(),
        )
        cutoff_tf = ft.TextField(
            label="締め日",
            value=str(workplace.pay_cutoff_day),
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
            **theme.field_style(),
        )
        payday_tf = ft.TextField(
            label="給料日",
            value=str(workplace.payday),
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
            **theme.field_style(),
        )
        night_sw = ft.Switch(
            label="深夜割増(22:00-翌5:00 +25%)自動適用", value=workplace.night_premium_enabled, active_color=theme.PRIMARY
        )
        edit_error = ft.Text("", color=theme.DANGER, size=13)

        def on_save(e) -> None:
            try:
                workplace.name = name_tf.value.strip() or workplace.name
                workplace.base_wage = float(base_wage_tf.value)
                workplace.transport_allowance = float(transport_tf.value or 0)
                workplace.pay_cutoff_day = int(cutoff_tf.value or 31)
                workplace.payday = int(payday_tf.value or 25)
                workplace.night_premium_enabled = night_sw.value
            except (TypeError, ValueError):
                edit_error.value = "数値の入力が正しくありません"
                page.update()
                return
            db.update_workplace(workplace)
            rebuild_list()
            page.update()

        def on_delete(e) -> None:
            db.delete_workplace(workplace.id)
            rebuild_list()
            page.update()

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [ft.Icon(ft.Icons.EDIT_OUTLINED, size=15, color=theme.TEXT_SECONDARY), theme.caption_text("基本情報を編集", theme.TEXT_SECONDARY)],
                        spacing=6,
                    ),
                    name_tf,
                    _field_row([base_wage_tf, transport_tf]),
                    _field_row([cutoff_tf, payday_tf]),
                    night_sw,
                    edit_error,
                    ft.Row(
                        [
                            ft.FilledButton(
                                content=ft.Row(
                                    [ft.Icon(ft.Icons.SAVE_OUTLINED, size=16), ft.Text("保存", weight=ft.FontWeight.W_600)],
                                    spacing=4,
                                    tight=True,
                                ),
                                on_click=on_save,
                                style=ft.ButtonStyle(bgcolor=theme.PRIMARY, shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
                            ),
                            ft.OutlinedButton(
                                content=ft.Row(
                                    [ft.Icon(ft.Icons.DELETE_OUTLINE, size=16, color=theme.DANGER), ft.Text("削除", color=theme.DANGER, weight=ft.FontWeight.W_600)],
                                    spacing=4,
                                    tight=True,
                                ),
                                on_click=on_delete,
                                style=ft.ButtonStyle(
                                    side=ft.BorderSide(1, theme.DANGER),
                                    shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM),
                                ),
                            ),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=10,
            ),
            padding=theme.SPACE_SM,
        )

    def build_workplace_tile(workplace: Workplace) -> ft.Card:
        rule_rows = [build_rule_row(r) for r in workplace.rules]
        subtitle_parts = [f"¥{workplace.base_wage:.0f}/時"]
        if workplace.transport_allowance:
            subtitle_parts.append(f"交通費¥{workplace.transport_allowance:.0f}")
        if workplace.night_premium_enabled:
            subtitle_parts.append("深夜割増")
        subtitle_parts.append(f"締め{workplace.pay_cutoff_day}日・給料日{workplace.payday}日")

        tile = ft.ExpansionTile(
            title=ft.Text(workplace.name, weight=ft.FontWeight.W_600, color=theme.TEXT_PRIMARY),
            subtitle=ft.Text(" ・ ".join(subtitle_parts), size=12, color=theme.TEXT_SECONDARY),
            leading=ft.CircleAvatar(
                content=ft.Icon(ft.Icons.STOREFRONT, color=theme.PRIMARY, size=20),
                bgcolor=theme.PRIMARY_SOFT,
                radius=20,
            ),
            bgcolor=theme.SURFACE,
            collapsed_bgcolor=theme.SURFACE,
            shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_MD),
            collapsed_shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_MD),
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            theme.caption_text("加算ルール一覧"),
                            *(rule_rows if rule_rows else [theme.caption_text("まだルールがありません")]),
                        ],
                        spacing=6,
                    ),
                    padding=ft.Padding(theme.SPACE_MD, theme.SPACE_XS, theme.SPACE_MD, theme.SPACE_SM),
                ),
                ft.Container(
                    content=build_add_rule_form(workplace),
                    padding=ft.Padding(theme.SPACE_MD, 0, theme.SPACE_MD, theme.SPACE_SM),
                ),
                ft.Divider(height=1, color=theme.BORDER),
                build_edit_form(workplace),
            ],
        )
        return ft.Container(
            content=tile,
            bgcolor=theme.SURFACE,
            border_radius=theme.RADIUS_MD,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            shadow=ft.BoxShadow(
                blur_radius=12, spread_radius=0, color=ft.Colors.with_opacity(0.06, ft.Colors.BLACK), offset=ft.Offset(0, 2)
            ),
        )

    def rebuild_list() -> None:
        workplaces = db.list_workplaces()
        if not workplaces:
            list_column.controls = [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.STOREFRONT, size=36, color=theme.TEXT_DISABLED),
                            ft.Text("バイト先がまだ登録されていません", color=theme.TEXT_SECONDARY, size=13),
                            theme.caption_text("上の「+ 追加」から登録してください"),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=6,
                    ),
                    alignment=ft.Alignment.CENTER,
                    padding=theme.SPACE_XL,
                )
            ]
        else:
            list_column.controls = [build_workplace_tile(w) for w in workplaces]

    def refresh() -> None:
        rebuild_list()
        page.update()

    rebuild_list()

    view = ft.Column(
        controls=[
            ft.Row(
                [
                    ft.FilledTonalButton(
                        content=ft.Row(
                            [ft.Icon(ft.Icons.ADD, size=16), ft.Text("バイト先を追加", weight=ft.FontWeight.W_600)],
                            spacing=4,
                            tight=True,
                        ),
                        on_click=toggle_add_form,
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
                    ),
                ],
                alignment=ft.MainAxisAlignment.END,
            ),
            add_form,
            list_column,
        ],
        spacing=theme.SPACE_MD,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    return view, refresh
