"""views/*.py と main.py が例外なく組み立てられることを検証するスモークテスト。

`curl` でのHTTP疎通確認は静的なFlutter Web資材が返るだけで、実際に
Pythonの main()/build_xxx_view() が実行されエラーが無いことまでは
保証しない(ブラウザがWebSocket接続して初めてPage側のコードが走るため)。
ここでは実際の ft.Page を使わず、必要最小限のダックタイピングPageで
各ビューを構築し、コンストラクタの引数名・enumメンバ名の誤りなどを
実行時にすぐ検出できるようにする。
"""

import os
from datetime import date, time

import flet as ft
import pytest

import db as db_module
from db import Database
from models import BonusType, RuleKind, ShiftPlan, ShiftSource, WageRule, Workplace


class FakePage:
    """Flet実行環境を使わずにビュー構築だけを検証するためのダミーPage。"""

    def __init__(self):
        self.overlay = []
        self.navigation_bar = None
        self.title = None
        self.theme_mode = None
        self.padding = None
        self.web = False

    def update(self, *controls):
        pass

    def run_task(self, handler, *args, **kwargs):
        # スモークテストでは非同期タスクを実際にスケジュールしない
        # (イベントループが無い/UIの見た目確認は flet run --web の手動確認に任せる)。
        return None

    def add(self, *controls):
        self.added_controls = list(controls)


@pytest.fixture
def db_with_sample_data():
    database = Database(":memory:")
    wp_id = database.add_workplace(
        Workplace(name="テストバイト", base_wage=1000.0, transport_allowance=200.0, night_premium_enabled=True)
    )
    database.add_wage_rule(
        WageRule(
            workplace_id=wp_id,
            kind=RuleKind.TIME_BAND,
            bonus_type=BonusType.ADD,
            amount=200.0,
            start_time=time(16, 0),
            end_time=time(18, 0),
        )
    )
    yield database
    database.close()


def test_timer_view_builds(db_with_sample_data):
    from views.timer_view import build_timer_view

    page = FakePage()
    view, refresh = build_timer_view(page, db_with_sample_data)
    assert view is not None
    refresh()


def test_workplace_view_builds(db_with_sample_data):
    from views.workplace_view import build_workplace_view

    page = FakePage()
    view, refresh = build_workplace_view(page, db_with_sample_data)
    assert view is not None
    refresh()


def test_calendar_view_builds(db_with_sample_data):
    from views.calendar_view import build_calendar_view

    page = FakePage()
    view, refresh = build_calendar_view(page, db_with_sample_data)
    assert view is not None
    refresh()


def test_calendar_view_hides_shift_import_on_web(db_with_sample_data):
    """回帰テスト: Web実行時はCORSで失敗するAI取込のボタン自体を非表示にすること。"""
    from views.calendar_view import build_calendar_view

    page = FakePage()
    page.web = True
    view, refresh = build_calendar_view(page, db_with_sample_data)
    shift_import_toggle_row = view.controls[1]
    assert shift_import_toggle_row.visible is False


def test_assets_view_hides_ai_section_on_web(db_with_sample_data):
    """回帰テスト: Web実行時はAI画像読取UIを隠し、手動入力ボタンは残ること。"""
    from views.assets_view import build_assets_view

    page = FakePage()
    page.web = True
    view, refresh = build_assets_view(page, db_with_sample_data)

    add_form_card_content = view.controls[2].content
    ai_settings_label = add_form_card_content.controls[3]
    assert ai_settings_label.visible is False

    button_row = add_form_card_content.controls[8]
    pick_image_button, manual_add_button = button_row.controls
    assert pick_image_button.visible is False
    assert manual_add_button.visible is not False  # Noneまたは明示的True


def test_assets_view_builds(db_with_sample_data):
    from views.assets_view import build_assets_view

    page = FakePage()
    view, refresh = build_assets_view(page, db_with_sample_data)
    assert view is not None
    refresh()


def test_assets_view_builds_with_existing_snapshot(db_with_sample_data):
    """回帰テスト: 既存のスナップショットがある状態でも例外なく総資産・増減・
    内訳・推移が描画できること。"""
    from datetime import datetime

    from models import AssetCategory, AssetItem, AssetSnapshot, AssetSource
    from views.assets_view import build_assets_view

    db_with_sample_data.add_asset_snapshot(
        AssetSnapshot(
            taken_at=datetime(2026, 6, 1, 9, 0),
            total_amount=1_000_000.0,
            source=AssetSource.MANUAL,
            items=[AssetItem(snapshot_id=0, category=AssetCategory.BANK, name="銀行A", amount=1_000_000.0)],
        )
    )
    db_with_sample_data.add_asset_snapshot(
        AssetSnapshot(
            taken_at=datetime.now(),
            total_amount=1_100_000.0,
            source=AssetSource.SCREENSHOT,
            items=[
                AssetItem(snapshot_id=0, category=AssetCategory.BANK, name="銀行A", amount=800_000.0),
                AssetItem(snapshot_id=0, category=AssetCategory.STOCK, name="株B", amount=300_000.0, pl=5000.0),
            ],
        )
    )

    page = FakePage()
    view, refresh = build_assets_view(page, db_with_sample_data)
    refresh()
    assert view is not None


def test_calendar_view_renders_shift_plan_indicator_and_detail(db_with_sample_data):
    """回帰テスト: 今日の日付にシフト予定(ShiftPlan)があっても例外なく描画でき、
    ヒートマップのドット表示・日別詳細パネルの「予定」表示コードパスが動くこと。
    """
    from views.calendar_view import build_calendar_view

    wp = db_with_sample_data.list_workplaces()[0]
    today = date.today()
    db_with_sample_data.add_shift_plan(
        ShiftPlan(
            workplace_id=wp.id,
            plan_date=today,
            start_time=time(9, 0),
            end_time=time(17, 0),
            source=ShiftSource.AI,
            confirmed=True,
        )
    )

    page = FakePage()
    view, refresh = build_calendar_view(page, db_with_sample_data)
    refresh()

    # heatmap_card(Container) -> Column -> [nav row, heatmap_grid, Divider, selected_day_panel]
    heatmap_card_column = view.controls[0].content
    heatmap_grid = heatmap_card_column.controls[1]
    selected_day_panel = heatmap_card_column.controls[3]

    today_cell = None
    for week_row in heatmap_grid.controls[1:]:  # [0]は曜日ヘッダー行
        for cell in week_row.controls:
            if cell.opacity == 1.0 and isinstance(cell.content, ft.Stack):
                day_text = cell.content.controls[0].content
                if day_text.value == str(today.day):
                    today_cell = cell
                    break
        if today_cell:
            break

    assert today_cell is not None, "予定がある日はStack(ドット付き)で描画されているはず"
    today_cell.on_click(None)  # ハンドラは e を使わないため None で呼び出せる

    detail_text = "\n".join(
        c.value for c in selected_day_panel.controls if hasattr(c, "value")
    )
    assert "予定" in detail_text or any(
        "予定" in str(getattr(sub, "value", ""))
        for c in selected_day_panel.controls
        if hasattr(c, "controls")
        for sub in c.controls
    )


def test_format_rule_label_handles_missing_time_gracefully():
    """TIME_BANDルールにstart_time/end_timeが無くても例外にならないこと(回帰テスト)。"""
    from views.workplace_view import format_rule_label

    rule = WageRule(
        workplace_id=1,
        kind=RuleKind.TIME_BAND,
        bonus_type=BonusType.ADD,
        amount=200.0,
    )
    assert "?" in format_rule_label(rule)


def test_timer_view_refresh_restores_paused_session(db_with_sample_data):
    """回帰テスト: 既に一時停止中のセッションがDBにある状態でビューを構築し、
    refresh()を呼ぶとUIがそれを復元すること。

    これを怠ると、ブラウザ再接続やアプリ再起動の直後に稼働中/一時停止中の
    セッションがあっても idle 表示のままになってしまう(実際に起きた不具合)。
    """
    from views.timer_view import build_timer_view

    wp = db_with_sample_data.list_workplaces()[0]
    session = db_with_sample_data.start_session(wp.id)
    db_with_sample_data.pause_session(session.id)

    page = FakePage()
    view, refresh = build_timer_view(page, db_with_sample_data)
    refresh()

    # status_badge の文言はティック(バックグラウンドタスク)側でしか更新されない
    # ため、ここでは refresh() が同期的に更新するボタン状態で復元を確認する。
    # view.controls = [workplace_dropdown, earnings_card, buttons_row, transport_row, last_result_banner]
    button_row = view.controls[2]
    start_button = button_row.controls[0]
    pause_button = button_row.controls[1]
    workplace_dropdown = view.controls[0]
    assert start_button.disabled is True
    assert pause_button.disabled is False
    assert pause_button.content.controls[1].value == "再開"
    assert workplace_dropdown.value == str(wp.id)


async def test_main_restores_active_session_on_initial_load(tmp_path, monkeypatch):
    """回帰テスト: main()がタブ切替なしの初期表示でも稼働中セッションを復元すること。

    以前は on_nav_change 経由でしか refresh が呼ばれず、起動直後(タブ未切替)は
    稼働中/一時停止中のセッションがあっても idle 表示のままになる不具合があった。
    """
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))
    db_module._db_singleton = None

    import main as main_module

    db = db_module.get_db()
    wp_id = db.add_workplace(Workplace(name="バイト", base_wage=1000.0))
    db.start_session(wp_id)

    page = FakePage()
    await main_module.main(page)

    safe_area = page.added_controls[0]
    timer_view = safe_area.content.content  # SafeArea -> body Container -> timer_control
    start_button = timer_view.controls[2].controls[0]
    workplace_dropdown = timer_view.controls[0]
    assert start_button.disabled is True  # 稼働中セッションがあればスタートは押せない
    assert workplace_dropdown.value == str(wp_id)


async def test_main_wires_everything_together(tmp_path, monkeypatch):
    """main.py の main(page) が例外なく最後まで実行できることを確認する。"""
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))
    db_module._db_singleton = None  # 前のテストのシングルトンが残らないようにする

    import main as main_module

    page = FakePage()
    await main_module.main(page)

    assert page.navigation_bar is not None
    assert len(page.navigation_bar.destinations) == 4
