"""画面表示用のフォーマットヘルパー。UIから共通で使う小さな関数だけを置く。"""

from __future__ import annotations


def format_yen(amount: float) -> str:
    """金額を "¥1,234" の形式にフォーマットする(四捨五入して整数円表示)。"""
    return f"¥{round(amount):,}"


def format_yen_signed(amount: float) -> str:
    """増減額を "+¥1,234" / "-¥1,234" の形式で表示する。"""
    sign = "+" if amount >= 0 else "-"
    return f"{sign}¥{abs(round(amount)):,}"


def format_percent_signed(pct: float) -> str:
    """増減率を "+12.3%" / "-4.5%" の形式で表示する。"""
    sign = "+" if pct >= 0 else "-"
    return f"{sign}{abs(pct):.1f}%"


def format_hms(total_seconds: float) -> str:
    """経過秒数を "HH:MM:SS" 形式にフォーマットする。"""
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_rate_triplet(hourly: float) -> tuple[str, str, str]:
    """実効時給(円/時)から (時給, 分給, 秒給) の表示文字列を返す。

    分給・秒給は端数が大きいため小数表示にする(整数丸めだと秒給が常に¥0/¥1になり無意味なため)。
    """
    return (format_yen(hourly), f"¥{hourly / 60:.1f}", f"¥{hourly / 3600:.2f}")
