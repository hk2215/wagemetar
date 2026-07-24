"""資産管理画面: 総資産・増減%の可視化、スナップショット追加(手動+AI画像読取)。

銀行/証券の直接API連携は個人向けアプリでは非現実的なため採用しない。代わりに、
その時点の資産状況を「スナップショット」として都度記録し、時系列で比較する方式を取る
(Phase 1で設計・実装済みの `AssetSnapshot`/`AssetItem` モデルと `db.py` の関数を使う)。

## セキュリティについて(重要)
銀行/証券のスクリーンショットはシフト表よりも機微な個人情報であるため、AIへの送信前に
**必ずユーザーの明示的な同意チェックボックス**を要求する(`consent_checkbox`)。同意しない
限り「画像から読み取る」ボタンは無効化されたままにする。これは `ai/vision.py` 側の
セキュリティ対策(HTTPS強制・画像サイズ上限・APIキー非ログ出力)に加えた、UI層での
追加の安全策。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Optional

import flet as ft

import theme
from ai.vision import ExtractedAssetItem, VisionError, extract_assets
from db import Database
from formatting import format_percent_signed, format_yen, format_yen_signed
from models import AssetCategory, AssetItem, AssetSnapshot, AssetSource

CATEGORY_LABELS = {
    AssetCategory.BANK: "銀行預金",
    AssetCategory.SECURITIES: "証券口座(評価額)",
    AssetCategory.STOCK: "個別株式/投信",
    AssetCategory.CASH: "現金",
    AssetCategory.OTHER: "その他",
}


def _section_header(icon: str, text: str) -> ft.Row:
    return ft.Row([ft.Icon(icon, size=17, color=theme.PRIMARY), theme.title_text(text)], spacing=8)


def _change_row(label: str, current: float, baseline: Optional[AssetSnapshot]) -> ft.Column:
    if baseline is None or baseline.total_amount == 0:
        return ft.Column(
            [ft.Text(label, size=12, color=theme.TEXT_SECONDARY), theme.caption_text("比較データなし")],
            spacing=2,
        )
    diff = current - baseline.total_amount
    pct = diff / baseline.total_amount * 100
    color = theme.SUCCESS if diff >= 0 else theme.DANGER
    return ft.Column(
        [
            ft.Text(label, size=12, color=theme.TEXT_SECONDARY),
            ft.Row(
                [
                    ft.Text(format_yen_signed(diff), size=14, weight=ft.FontWeight.W_700, color=color),
                    ft.Text(f"({format_percent_signed(pct)})", size=12, color=color),
                ],
                spacing=6,
            ),
        ],
        spacing=2,
    )


def build_assets_view(page: ft.Page, db: Database) -> tuple[ft.Control, Callable[[], None]]:
    file_picker = ft.FilePicker()
    file_picker_attached = {"done": False}

    def ensure_file_picker_attached() -> None:
        # Fletの既知バグ(Web preview版がFilePickerを認識できない)を踏まえ、
        # 実際に使う直前まで overlay に追加しない(views/shift_import_view.py と同じ対策)。
        if not file_picker_attached["done"]:
            page.overlay.append(file_picker)
            file_picker_attached["done"] = True

    row_state: list[dict] = []  # [{category_dd, name_tf, amount_tf, pl_tf}, ...]
    used_ai = {"value": False}

    # --- 総資産・増減 ---------------------------------------------------------
    total_value_text = ft.Text("¥0", size=32, weight=ft.FontWeight.W_800, color=theme.TEXT_PRIMARY)
    no_data_text = theme.caption_text("スナップショットがまだありません")
    changes_row = ft.Row(spacing=20, wrap=True)
    breakdown_col = ft.Column(spacing=10)
    history_col = ft.Column(spacing=6)

    def render_summary() -> None:
        latest = db.latest_asset_snapshot()
        changes_row.controls.clear()
        breakdown_col.controls.clear()
        history_col.controls.clear()

        if latest is None:
            total_value_text.value = "¥0"
            no_data_text.visible = True
            return
        no_data_text.visible = False
        total_value_text.value = format_yen(latest.total_amount)

        now = latest.taken_at
        day_before = db.asset_snapshot_before(now - timedelta(days=1))
        month_before = db.asset_snapshot_before(now - timedelta(days=30))
        year_before = db.asset_snapshot_before(now - timedelta(days=365))
        changes_row.controls.extend(
            [
                _change_row("前日比", latest.total_amount, day_before),
                _change_row("前月比", latest.total_amount, month_before),
                _change_row("前年比", latest.total_amount, year_before),
            ]
        )

        totals_by_category: dict[str, float] = {}
        for item in latest.items:
            totals_by_category[item.category.value] = totals_by_category.get(item.category.value, 0.0) + item.amount
        max_amount = max(totals_by_category.values(), default=0.0)
        for cat_value, amount in sorted(totals_by_category.items(), key=lambda kv: -kv[1]):
            label = next((v for k, v in CATEGORY_LABELS.items() if k.value == cat_value), cat_value)
            ratio = (amount / max_amount) if max_amount > 0 else 0
            breakdown_col.controls.append(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(label, size=13, color=theme.TEXT_PRIMARY, expand=True),
                                ft.Text(format_yen(amount), size=13, weight=ft.FontWeight.W_600, color=theme.TEXT_PRIMARY),
                            ]
                        ),
                        ft.ProgressBar(value=ratio, color=theme.PRIMARY, bgcolor=theme.SURFACE_ALT, bar_height=8, border_radius=4),
                    ],
                    spacing=4,
                )
            )
        if not totals_by_category:
            breakdown_col.controls.append(theme.caption_text("内訳データがありません"))

        history = list(reversed(db.list_asset_snapshots()))[:12]  # 新しい順、最大12件
        max_hist = max((s.total_amount for s in history), default=0.0)
        for snap in history:
            ratio = (snap.total_amount / max_hist) if max_hist > 0 else 0
            history_col.controls.append(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(snap.taken_at.strftime("%Y-%m-%d"), size=12, color=theme.TEXT_SECONDARY, expand=True),
                                ft.Text(format_yen(snap.total_amount), size=12, color=theme.TEXT_PRIMARY),
                            ]
                        ),
                        ft.ProgressBar(value=ratio, color=theme.PRIMARY, bgcolor=theme.SURFACE_ALT, bar_height=6, border_radius=3),
                    ],
                    spacing=2,
                )
            )

    # --- 今月のまとめ(労働収入 vs 資産増減) -------------------------------------
    monthly_summary_col = ft.Column(spacing=8)

    def render_monthly_summary() -> None:
        monthly_summary_col.controls.clear()
        today = date.today()
        labor_income = db.monthly_total(today.year, today.month)
        latest = db.latest_asset_snapshot()
        month_before = db.asset_snapshot_before(datetime.combine(today, datetime.min.time()) - timedelta(days=30)) if latest else None
        asset_diff = (latest.total_amount - month_before.total_amount) if (latest and month_before) else None

        monthly_summary_col.controls.append(
            ft.Row(
                [
                    ft.Text("今月の労働収入", size=13, color=theme.TEXT_SECONDARY, expand=True),
                    ft.Text(format_yen(labor_income), size=13, weight=ft.FontWeight.W_600, color=theme.PRIMARY),
                ]
            )
        )
        if asset_diff is not None:
            color = theme.SUCCESS if asset_diff >= 0 else theme.DANGER
            monthly_summary_col.controls.append(
                ft.Row(
                    [
                        ft.Text("資産の増減(約30日)", size=13, color=theme.TEXT_SECONDARY, expand=True),
                        ft.Text(format_yen_signed(asset_diff), size=13, weight=ft.FontWeight.W_600, color=color),
                    ]
                )
            )
        else:
            monthly_summary_col.controls.append(theme.caption_text("資産の比較データがまだありません"))

    # --- スナップショット追加フォーム --------------------------------------------
    api_key_field = ft.TextField(
        label="Anthropic APIキー", password=True, can_reveal_password=True, expand=True, **theme.field_style()
    )
    save_api_key_button = ft.FilledTonalButton(
        "保存", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM))
    )
    api_key_status = ft.Text("", size=12, color=theme.SUCCESS)

    def load_api_key() -> None:
        api_key_field.value = db.get_setting("anthropic_api_key", "") or ""

    def on_save_api_key(e) -> None:
        db.set_setting("anthropic_api_key", api_key_field.value or "")
        api_key_status.value = "保存しました"
        page.update()

    save_api_key_button.on_click = on_save_api_key

    consent_checkbox = ft.Checkbox(
        label="この画像の内容を外部AI(Anthropic)に送信することに同意します",
        value=False,
    )
    rows_col = ft.Column(spacing=8)
    add_error = ft.Text("", size=13, color=theme.DANGER)
    loading_row = ft.Row(
        [ft.ProgressRing(width=18, height=18, stroke_width=2, color=theme.PRIMARY), theme.caption_text("AIが解析中です...")],
        visible=False,
        spacing=8,
    )

    def build_item_row(category: AssetCategory = AssetCategory.BANK, name: str = "", amount: str = "", pl: str = "") -> None:
        category_dd = ft.Dropdown(
            label="カテゴリ",
            options=[ft.DropdownOption(key=c.value, text=label) for c, label in CATEGORY_LABELS.items()],
            value=category.value,
            expand=True,
            **theme.field_style(),
        )
        name_tf = ft.TextField(label="名称", value=name, expand=True, **theme.field_style())
        amount_tf = ft.TextField(
            label="金額(円)", value=amount, keyboard_type=ft.KeyboardType.NUMBER, expand=True, **theme.field_style()
        )
        pl_tf = ft.TextField(
            label="損益(円・任意)", value=pl, keyboard_type=ft.KeyboardType.NUMBER, expand=True, **theme.field_style()
        )
        entry = {"category_dd": category_dd, "name_tf": name_tf, "amount_tf": amount_tf, "pl_tf": pl_tf}
        row_state.append(entry)

        def on_remove(e, entry=entry) -> None:
            idx = row_state.index(entry)
            row_state.pop(idx)
            rows_col.controls.pop(idx)
            page.update()

        rows_col.controls.append(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                category_dd,
                                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_size=18, icon_color=theme.TEXT_SECONDARY, on_click=on_remove),
                            ]
                        ),
                        name_tf,
                        ft.Row([amount_tf, pl_tf], spacing=8),
                    ],
                    spacing=6,
                ),
                padding=theme.SPACE_SM,
                bgcolor=theme.SURFACE_ALT,
                border_radius=theme.RADIUS_SM,
            )
        )

    def on_add_manual_row(e) -> None:
        build_item_row()
        page.update()

    async def on_pick_image(e) -> None:
        if not consent_checkbox.value:
            add_error.value = "画像を送信するには、上の同意チェックボックスにチェックしてください"
            page.update()
            return
        add_error.value = ""
        page.update()

        ensure_file_picker_attached()
        files = await file_picker.pick_files(
            dialog_title="資産のスクリーンショットを選択",
            file_type=ft.FilePickerFileType.IMAGE,
            with_data=True,
        )
        if not files:
            return
        picked = files[0]
        if not picked.bytes:
            add_error.value = "画像データを読み込めませんでした"
            page.update()
            return

        api_key = db.get_setting("anthropic_api_key", "") or ""
        loading_row.visible = True
        page.update()
        try:
            extracted: list[ExtractedAssetItem] = await extract_assets(picked.bytes, picked.name, api_key)
        except VisionError as ex:
            add_error.value = str(ex)
            loading_row.visible = False
            page.update()
            return
        loading_row.visible = False

        if not extracted:
            add_error.value = "資産項目が見つかりませんでした"
        else:
            used_ai["value"] = True
            for item in extracted:
                build_item_row(
                    category=AssetCategory(item.category),
                    name=item.name,
                    amount=str(item.amount) if item.amount is not None else "",
                    pl=str(item.pl) if item.pl is not None else "",
                )
        page.update()

    def on_save_snapshot(e) -> None:
        add_error.value = ""
        items: list[AssetItem] = []
        for entry in row_state:
            try:
                amount = float(entry["amount_tf"].value)
            except (TypeError, ValueError):
                continue
            name = (entry["name_tf"].value or "").strip()
            if not name:
                continue
            pl_raw = entry["pl_tf"].value
            pl_value: Optional[float]
            try:
                pl_value = float(pl_raw) if pl_raw else None
            except ValueError:
                pl_value = None
            items.append(
                AssetItem(
                    snapshot_id=0,
                    category=AssetCategory(entry["category_dd"].value),
                    name=name,
                    amount=amount,
                    pl=pl_value,
                )
            )

        if not items:
            add_error.value = "有効な項目がありません(名称・金額を入力してください)"
            page.update()
            return

        total = sum(i.amount for i in items)
        snapshot = AssetSnapshot(
            taken_at=datetime.now(),
            total_amount=total,
            source=AssetSource.SCREENSHOT if used_ai["value"] else AssetSource.MANUAL,
            items=items,
        )
        db.add_asset_snapshot(snapshot)

        row_state.clear()
        rows_col.controls.clear()
        used_ai["value"] = False
        consent_checkbox.value = False
        add_error.value = ""
        add_error.color = theme.SUCCESS
        add_error.value = f"スナップショットを保存しました({format_yen(total)})"
        render_summary()
        render_monthly_summary()
        page.update()

    add_form_visible = {"value": False}

    def toggle_add_form(e) -> None:
        add_form_visible["value"] = not add_form_visible["value"]
        add_form_card.visible = add_form_visible["value"]
        page.update()

    # ブラウザ(Web/PWA)から直接 api.anthropic.com を呼ぶとCORSで必ず失敗するため、
    # Web実行時はAI画像読取に関する部分だけを非表示にし、手動入力のみ使えるようにする。
    is_web = page.web
    ai_section_visible = not is_web

    ai_settings_label = theme.caption_text("AI設定")
    ai_settings_label.visible = ai_section_visible
    api_key_status.visible = ai_section_visible

    add_form_card = theme.card(
        ft.Column(
            [
                _section_header(ft.Icons.ADD_CHART, "スナップショットを追加"),
                theme.caption_text(
                    "Web版では画像からの読み取りはご利用いただけません。手動で入力してください。"
                    if is_web
                    else "手動入力、または銀行/証券アプリのスクリーンショットをAIで読み取って追加できます。"
                ),
                ft.Divider(height=1, color=theme.BORDER, visible=ai_section_visible),
                ai_settings_label,
                ft.Row([api_key_field, save_api_key_button], spacing=8, visible=ai_section_visible),
                api_key_status,
                ft.Divider(height=1, color=theme.BORDER, visible=ai_section_visible),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [ft.Icon(ft.Icons.SHIELD_OUTLINED, size=15, color=theme.WARNING), theme.caption_text("送信前の同意が必要です", theme.WARNING)],
                                spacing=6,
                            ),
                            consent_checkbox,
                        ],
                        spacing=4,
                    ),
                    padding=theme.SPACE_SM,
                    bgcolor=theme.WARNING_SOFT,
                    border_radius=theme.RADIUS_SM,
                    visible=ai_section_visible,
                ),
                ft.Row(
                    [
                        ft.FilledTonalButton(
                            content=ft.Row(
                                [ft.Icon(ft.Icons.PHOTO_CAMERA_OUTLINED, size=16), ft.Text("画像から読み取る", weight=ft.FontWeight.W_600)],
                                spacing=4,
                                tight=True,
                            ),
                            on_click=on_pick_image,
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
                            visible=ai_section_visible,
                        ),
                        ft.OutlinedButton(
                            content=ft.Row(
                                [ft.Icon(ft.Icons.ADD, size=16), ft.Text("手動で項目を追加", weight=ft.FontWeight.W_600)],
                                spacing=4,
                                tight=True,
                            ),
                            on_click=on_add_manual_row,
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                loading_row,
                add_error,
                rows_col,
                ft.FilledButton(
                    content=ft.Row(
                        [ft.Icon(ft.Icons.SAVE_OUTLINED, size=16), ft.Text("スナップショットを保存", weight=ft.FontWeight.W_600)],
                        spacing=4,
                        tight=True,
                    ),
                    on_click=on_save_snapshot,
                    style=ft.ButtonStyle(bgcolor=theme.PRIMARY, shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
                ),
            ],
            spacing=10,
        )
    )
    add_form_card.visible = False

    summary_card = theme.card(
        ft.Column(
            [
                _section_header(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, "総資産"),
                total_value_text,
                no_data_text,
                changes_row,
            ],
            spacing=8,
        )
    )

    monthly_card = theme.card(
        ft.Column([_section_header(ft.Icons.SUMMARIZE_OUTLINED, "今月のまとめ"), monthly_summary_col], spacing=8)
    )

    breakdown_card = theme.card(
        ft.Column([_section_header(ft.Icons.PIE_CHART_OUTLINE, "カテゴリ別内訳(最新)"), breakdown_col], spacing=10)
    )

    history_card = theme.card(
        ft.Column([_section_header(ft.Icons.SHOW_CHART, "推移(最新12件)"), history_col], spacing=8)
    )

    toggle_row = ft.Row(
        [
            ft.FilledTonalButton(
                content=ft.Row(
                    [ft.Icon(ft.Icons.ADD, size=16), ft.Text("スナップショットを追加", weight=ft.FontWeight.W_600)],
                    spacing=4,
                    tight=True,
                ),
                on_click=toggle_add_form,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_SM)),
            )
        ],
        alignment=ft.MainAxisAlignment.END,
    )

    view = ft.Column(
        controls=[summary_card, toggle_row, add_form_card, monthly_card, breakdown_card, history_card],
        spacing=theme.SPACE_MD,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    def refresh() -> None:
        load_api_key()
        render_summary()
        render_monthly_summary()
        page.update()

    load_api_key()
    render_summary()
    render_monthly_summary()

    return view, refresh
