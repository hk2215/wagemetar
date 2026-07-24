"""アプリ全体で共有するデザインシステム。

スマホアプリとして「シンプル・わかりやすい・安っぽくない」見た目にするため、
色・余白・角丸をここに一元化し、各画面はこれらの定数だけを使って組み立てる
(場当たり的な色コードをviews側に散らばらせない)。

配色方針:
- 落ち着いたティール(緑がかった青)を基調色にする(お金・成長のイメージに合い、
  派手すぎない)。Material3の `color_scheme_seed` に渡すと、ボタンやスイッチ等の
  標準コンポーネントは自動で調和した配色になる。
- ページ全体はごくわずかにグレーがかった背景(SURFACE_DIM)の上に、白いカード
  (SURFACE)を浮かせることで、影を多用せずに階層感を出す。
- ダークモードは意図的に無効化している(page.theme_mode=LIGHT固定)。カード色を
  固定値で持っているため、システムがダークモードだと配色が破綻するのを避けるため。
  将来的にダークモード対応が必要になったら、ここの定数をライト/ダーク両対応の
  関数に変更すること。
"""

from __future__ import annotations

import flet as ft

# --- フォント -------------------------------------------------------------
# Web(Pyodide)ビルドはCanvasKitがGoogle Fonts CDNから日本語グリフを動的取得する
# ため、オフライン(機内モード等)では文字化けする(実機検証で確認済み)。
# `src/assets/fonts/` に同梱したNoto Sans JPを明示的なアプリフォントとして登録し、
# ネットワーク無しでも常に正しく日本語が表示されるようにする。
FONT_FAMILY = "NotoSansJP"
FONT_ASSET_PATH = "fonts/NotoSansJP-Regular.ttf"  # assetsディレクトリからの相対パス

# --- 基調色 -------------------------------------------------------------
SEED_COLOR = "#00897B"  # ティール600。落ち着いていて安っぽく見えない
PRIMARY = "#00695C"  # 主要アクション・強調テキストに使う濃いめのティール
PRIMARY_SOFT = "#E0F2F1"  # PRIMARYの薄い背景版(チップ・選択状態などに)

# --- ニュートラル ---------------------------------------------------------
SURFACE_DIM = "#F3F5F6"  # ページ全体の背景(白カードを浮かせるための下地)
SURFACE = "#FFFFFF"  # カードの背景
SURFACE_ALT = "#FAFAFA"  # カードの中でさらに一段沈める領域
BORDER = "#E3E6E8"  # 薄い罫線・区切り
TEXT_PRIMARY = "#1A1D1E"
TEXT_SECONDARY = "#6B7280"
TEXT_DISABLED = "#B0B6BB"

# --- セマンティックカラー ---------------------------------------------------
SUCCESS = "#2E7D32"
SUCCESS_SOFT = "#E8F5E9"
WARNING = "#EF6C00"
WARNING_SOFT = "#FFF3E0"
DANGER = "#C62828"
DANGER_SOFT = "#FDECEA"
NEUTRAL_SOFT = "#EEF0F2"  # 待機中などニュートラルな状態のバッジ背景

# --- ヒートマップ(基調色の濃淡で統一。GitHub風の緑ではなくアプリの色に合わせる) --
HEAT_LEVELS = ["#EDEFF0", "#B2DFDB", "#4DB6AC", "#00897B", "#00594F"]

# --- 余白・角丸スケール ----------------------------------------------------
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 32

RADIUS_SM = 10
RADIUS_MD = 16
RADIUS_LG = 22

# --- タイポグラフィのヘルパー -----------------------------------------------


def title_text(value: str) -> ft.Text:
    """画面内の小見出し(セクション見出し)。"""
    return ft.Text(value, size=15, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)


def caption_text(value: str, color: str = TEXT_SECONDARY) -> ft.Text:
    """補足・ラベル用の小さいテキスト。"""
    return ft.Text(value, size=12, color=color)


def build_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=SEED_COLOR,
        use_material3=True,
        visual_density=ft.VisualDensity.COMFORTABLE,
        font_family=FONT_FAMILY,
    )


def card(
    content: ft.Control,
    padding: int = SPACE_MD,
    bgcolor: str = SURFACE,
    radius: int = RADIUS_MD,
) -> ft.Container:
    """影を持つ角丸カード。画面内のセクションはこれで包んで統一感を出す。"""
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=bgcolor,
        border_radius=radius,
        shadow=ft.BoxShadow(
            blur_radius=12,
            spread_radius=0,
            color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK),
            offset=ft.Offset(0, 2),
        ),
    )


def field_style() -> dict:
    """TextField/Dropdown/DatePicker等の入力欄に共通で使うスタイル。

    アウトライン(枠線)だけの素っ気ない見た目ではなく、薄い塗りつぶし背景の
    "filled" スタイルに統一する(Material3の標準的な入力欄デザイン)。
    """
    return dict(
        filled=True,
        fill_color=SURFACE_ALT,
        border_radius=RADIUS_SM,
        border_color=BORDER,
        focused_border_color=PRIMARY,
    )


def badge(text: str, fg: str, bg: str) -> ft.Container:
    """ピル型のステータスバッジ(稼働中・待機中など)。"""
    return ft.Container(
        content=ft.Text(text, size=12, weight=ft.FontWeight.W_600, color=fg),
        padding=ft.Padding(12, 5, 12, 5),
        bgcolor=bg,
        border_radius=100,
    )
