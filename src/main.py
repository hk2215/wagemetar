"""バイト時給加算アプリ エントリーポイント。

Phase 1: タイマー(スタート/ストップ/エンド) + バイト先設定 + カレンダー(集計・壁アラート・
CSV出力)。3画面は起動時に一度だけ構築し、NavigationBarの切り替えでは
`body.content` を差し替えるだけにする(タブ切替のたびに作り直すと、タイマー画面の
バックグラウンド更新タスクが多重に走ってしまうのを避けるため)。

見た目は `theme.py` の共通デザインシステムに統一している。ダークモードは
意図的に無効化(page.theme_mode=LIGHT固定)している(詳細はtheme.py参照)。

Web(Pyodide)実行時のデータ永続化について: Pyodideの既定ファイルシステムは
メモリ上にしかなくページリロードで消えるため(実機検証で確認済み)、
`web_persistence` モジュールで IndexedDB(IDBFS) への保存/復元を行う。
`main` を async def にしているのはこの初期化(`setup_and_pull`)を
DB接続より前に確実に完了させるため。ネイティブ実行時はすべて no-op。
"""

import flet as ft

import theme
import web_persistence
from db import get_db
from views.assets_view import build_assets_view
from views.calendar_view import build_calendar_view
from views.timer_view import build_timer_view
from views.workplace_view import build_workplace_view

TAB_TITLES = ["タイマー", "カレンダー", "バイト先設定", "資産"]


async def main(page: ft.Page) -> None:
    page.title = "バイト時給トラッカー"
    page.fonts = {theme.FONT_FAMILY: theme.FONT_ASSET_PATH}
    page.theme = theme.build_theme()
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = theme.SURFACE_DIM
    page.padding = ft.Padding(16, 12, 16, 0)

    # IDBFSのマウント+IndexedDBからの復元(pull)は、DBファイルを開く前に完了させる
    # 必要がある(先に空のDBファイルが作られてしまうと復元データと混同するため)。
    await web_persistence.setup_and_pull()

    db = get_db()

    timer_control, refresh_timer = build_timer_view(page, db)
    workplace_control, refresh_workplace = build_workplace_view(page, db)
    calendar_control, refresh_calendar = build_calendar_view(page, db)
    assets_control, refresh_assets = build_assets_view(page, db)

    views = [timer_control, calendar_control, workplace_control, assets_control]
    refreshers = [refresh_timer, refresh_calendar, refresh_workplace, refresh_assets]

    body = ft.Container(content=views[0], expand=True)

    app_bar = ft.AppBar(
        title=ft.Text(TAB_TITLES[0], weight=ft.FontWeight.BOLD, color=theme.TEXT_PRIMARY),
        center_title=False,
        bgcolor=theme.SURFACE_DIM,
        elevation=0,
    )

    def on_nav_change(e: ft.Event[ft.NavigationBar]) -> None:
        index = e.control.selected_index
        body.content = views[index]
        app_bar.title.value = TAB_TITLES[index]
        refreshers[index]()
        page.update()

    nav_bar = ft.NavigationBar(
        selected_index=0,
        on_change=on_nav_change,
        bgcolor=theme.SURFACE,
        indicator_color=theme.PRIMARY_SOFT,
        elevation=3,
        shadow_color=ft.Colors.with_opacity(0.10, ft.Colors.BLACK),
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.TIMER_OUTLINED, selected_icon=ft.Icons.TIMER, label="タイマー"),
            ft.NavigationBarDestination(
                icon=ft.Icons.CALENDAR_MONTH_OUTLINED, selected_icon=ft.Icons.CALENDAR_MONTH, label="カレンダー"
            ),
            ft.NavigationBarDestination(icon=ft.Icons.WORK_OUTLINE, selected_icon=ft.Icons.WORK, label="バイト先"),
            ft.NavigationBarDestination(
                icon=ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
                selected_icon=ft.Icons.ACCOUNT_BALANCE_WALLET,
                label="資産",
            ),
        ],
    )
    page.navigation_bar = nav_bar
    page.appbar = app_bar

    page.add(ft.SafeArea(expand=True, content=body))

    # 初期表示(タイマー画面)は on_nav_change を経由しないため、ここで明示的に
    # refresh を呼ぶ。これを忘れると、稼働中/一時停止中のセッションがあっても
    # ブラウザ再接続やアプリ再起動の直後は反映されない(idle表示のまま)バグになる。
    refresh_timer()

    # Web(Pyodide)実行時のみ: 変更があったDBを定期的にIndexedDBへ書き出す。
    # ネイティブ実行時は即座に戻るno-opなので無条件で呼んでよい。
    page.run_task(web_persistence.autosave_loop)


if __name__ == "__main__":
    ft.run(main)
