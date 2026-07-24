"""クラウドAIによる画像の構造化抽出(シフト表・資産スクリーンショット)。

このアプリで唯一ネットワーク通信を行うモジュール(オフライン原則の唯一の例外)。
既定では Anthropic の Messages API を httpx で直接呼び出す(SDK不使用・軽量)。

設計上の注意:
- AIの読み取り結果は「候補」に過ぎない。呼び出し側(views/shift_import_view.py,
  views/assets_view.py)は必ず人間が内容を確認・修正できる画面を経由してから
  保存すること(誤読をそのまま保存しない human-in-the-loop)。
- APIキーはこのモジュールの引数として渡すだけで、ここでは保存しない
  (永続化は db.py の settings テーブル側の責務)。
- 画像バイト列はこのモジュール内・呼び出し元のどちらでもディスクに書き出さない
  (メモリ上でAPI呼び出しに使うだけで捨てる)。

## セキュリティ方針(外部通信を行う唯一の箇所であるため特に厳格にする)
- 通信先は Anthropic の固定HTTPSエンドポイントのみ。呼び出し時に必ずスキームが
  `https://` であることを検証してから送信する(将来の改変でうっかり平文HTTPに
  ならないようにするための自己防衛的なガード)。
- `httpx.AsyncClient` は `verify=True` を明示指定し、TLS証明書検証を無効化する
  変更が入っても目立つようにしている(デフォルト値だが明示することが意図)。
- 送信前に画像サイズの上限(`MAX_IMAGE_BYTES`)を検証し、想定外に大きいデータや
  誤って選択したファイルをそのまま送らないようにする。
- APIキーはログや例外メッセージに出力しない。HTTPエラー時のレスポンス本文は
  一部のみ(300文字)を例外メッセージに含めるが、これはAnthropic側のエラー説明
  であり、リクエストヘッダ(APIキー等)がここに含まれることはない。
- 資産(銀行/証券)のスクリーンショットはシフト表よりも機微な情報のため、
  呼び出し側(assets_view.py)で送信前にユーザーの明示的な同意を必須としている。
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import date, time
from typing import Optional

import httpx

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-5"

# 送信する画像の上限サイズ(8MB)。上限を超える場合は誤操作/想定外データの可能性が
# 高いため、送信せずにエラーとする。
MAX_IMAGE_BYTES = 8 * 1024 * 1024

_EXTENSION_TO_MEDIA_TYPE = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


class VisionError(Exception):
    """AI抽出に失敗した際の例外。メッセージはそのままUIに表示できる想定。"""


@dataclass
class ExtractedShift:
    """AIが抽出したシフト候補1件。人間の確認・修正を経てから保存される。"""

    plan_date: Optional[date]
    start_time: Optional[time]
    end_time: Optional[time]
    raw_label: str  # 確認画面での表示用(日付/時刻がNoneの場合でも元の文字列が分かるように)


@dataclass
class ExtractedAssetItem:
    """AIが抽出した資産項目候補1件。人間の確認・修正を経てから保存される。"""

    category: str  # models.AssetCategory の value と対応(bank/securities/stock/cash/other)
    name: str
    amount: Optional[float]
    pl: Optional[float]
    raw_label: str


def _media_type_for(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return _EXTENSION_TO_MEDIA_TYPE.get(ext, "image/jpeg")


def _validate_request_security(image_bytes: bytes) -> None:
    """送信前のセキュリティ関連バリデーション(HTTPS強制・画像サイズ上限)。"""
    if not ANTHROPIC_API_URL.startswith("https://"):
        # 通常到達しないはずのガード。将来的な改変でエンドポイントが平文HTTPに
        # なってしまうことを防ぐための自己防衛的なチェック。
        raise VisionError("内部エラー: APIエンドポイントがHTTPSではありません")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise VisionError(
            f"画像サイズが大きすぎます({len(image_bytes) / 1024 / 1024:.1f}MB)。"
            f"{MAX_IMAGE_BYTES // 1024 // 1024}MB以下の画像を選択してください。"
        )


async def _call_anthropic_vision(
    image_bytes: bytes,
    filename: str,
    api_key: str,
    prompt: str,
    model: str,
    timeout: float,
) -> str:
    """Anthropic Messages APIを呼び出し、テキスト応答を返す(共通処理)。"""
    _validate_request_security(image_bytes)

    payload = {
        "model": model,
        "max_tokens": 2000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _media_type_for(filename),
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
            resp = await client.post(ANTHROPIC_API_URL, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise VisionError(f"通信エラーが発生しました: {e}") from e

    if resp.status_code == 401:
        raise VisionError("APIキーが正しくありません(401 Unauthorized)")
    if resp.status_code != 200:
        raise VisionError(f"APIエラーが発生しました(HTTP {resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    return "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )


def _extract_json_array(text: str) -> list:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise VisionError(f"AIの応答をJSONとして解釈できませんでした: {text[:200]!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise VisionError(f"AIの応答のJSON解析に失敗しました: {e}") from e


# ---------------------------------------------------------------------------
# シフト表の抽出
# ---------------------------------------------------------------------------


def _build_shift_prompt(my_name: str, reference_year: int, reference_month: int) -> str:
    return (
        f"これは{reference_year}年{reference_month}月のアルバイトのシフト表(勤務予定表)の"
        "画像です。\n"
        f"「{my_name}」という人物の行を探してください(敬称の有無、カタカナ/漢字/ひらがなの"
        "表記ゆれ、フルネームか名字のみか等の違いは許容してください)。\n"
        "見つかった場合、その人物の勤務予定(日付・開始時刻・終了時刻)をすべて抽出してください。\n"
        "出力は説明文などを一切含めず、次の形式のJSON配列だけを返してください:\n"
        '[{"date": "YYYY-MM-DD", "start_time": "HH:MM", "end_time": "HH:MM"}, ...]\n'
        "年が画像内に明記されていない場合は上記の年を使ってください。"
        "日付や時刻がどうしても判読できない項目は、その値だけ null にしてください。"
        "該当する人物の行が見つからない場合は空配列 [] を返してください。"
    )


async def extract_shifts(
    image_bytes: bytes,
    filename: str,
    api_key: str,
    my_name: str,
    reference_year: int,
    reference_month: int,
    model: str = DEFAULT_MODEL,
    timeout: float = 60.0,
) -> list[ExtractedShift]:
    """シフト表画像から、my_nameに該当する行だけを抽出する。

    Raises:
        VisionError: APIキー未設定・通信エラー・APIエラー・応答の解析失敗など。
    """
    if not api_key:
        raise VisionError("APIキーが設定されていません(下の「AI設定」から入力してください)")
    if not my_name:
        raise VisionError("「自分の名前」が設定されていません(下の「AI設定」から入力してください)")

    text = await _call_anthropic_vision(
        image_bytes, filename, api_key, _build_shift_prompt(my_name, reference_year, reference_month), model, timeout
    )
    return parse_shifts_response(text)


def parse_shifts_response(text: str) -> list[ExtractedShift]:
    """AIのテキスト応答からシフト候補のリストを取り出す(純粋関数・テスト容易)。"""
    raw_items = _extract_json_array(text)

    shifts: list[ExtractedShift] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        plan_date = _safe_date(item.get("date"))
        start_time = _safe_time(item.get("start_time"))
        end_time = _safe_time(item.get("end_time"))
        raw_label = f"{item.get('date') or '?'} {item.get('start_time') or '?'}-{item.get('end_time') or '?'}"
        shifts.append(
            ExtractedShift(plan_date=plan_date, start_time=start_time, end_time=end_time, raw_label=raw_label)
        )
    return shifts


# ---------------------------------------------------------------------------
# 資産(銀行/証券)スクリーンショットの抽出
# ---------------------------------------------------------------------------

_VALID_ASSET_CATEGORIES = {"bank", "securities", "stock", "cash", "other"}


def _build_asset_prompt() -> str:
    return (
        "これは銀行口座や証券口座の残高・資産一覧のスクリーンショットです。\n"
        "表示されている資産項目(銀行預金、証券口座の評価額、個別株式の銘柄、現金等)を"
        "すべて抽出してください。\n"
        "出力は説明文などを一切含めず、次の形式のJSON配列だけを返してください:\n"
        '[{"category": "bank", "name": "○○銀行", "amount": 123456, "pl": null}, ...]\n'
        'category は "bank"(銀行預金) / "securities"(証券口座全体の評価額) / '
        '"stock"(個別株式・投資信託等の銘柄) / "cash"(現金) / "other"(その他) '
        "のいずれかにしてください。\n"
        "amount は円換算した金額(数値のみ、カンマや通貨記号は含めない)。"
        "pl は含み損益が画像に表示されていればその金額(円、マイナスは負の数値)、"
        "無ければ null にしてください。\n"
        "該当する項目が見つからない場合は空配列 [] を返してください。"
    )


async def extract_assets(
    image_bytes: bytes,
    filename: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout: float = 60.0,
) -> list[ExtractedAssetItem]:
    """銀行/証券のスクリーンショットから資産項目を抽出する。

    Raises:
        VisionError: APIキー未設定・通信エラー・APIエラー・応答の解析失敗など。
    """
    if not api_key:
        raise VisionError("APIキーが設定されていません(下の「AI設定」から入力してください)")

    text = await _call_anthropic_vision(image_bytes, filename, api_key, _build_asset_prompt(), model, timeout)
    return parse_assets_response(text)


def parse_assets_response(text: str) -> list[ExtractedAssetItem]:
    """AIのテキスト応答から資産項目候補のリストを取り出す(純粋関数・テスト容易)。"""
    raw_items = _extract_json_array(text)

    items: list[ExtractedAssetItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        category = item.get("category") if item.get("category") in _VALID_ASSET_CATEGORIES else "other"
        name = str(item.get("name") or "?")
        amount = _safe_float(item.get("amount"))
        pl = _safe_float(item.get("pl"))
        raw_label = f"{name} {item.get('amount') if item.get('amount') is not None else '?'}"
        items.append(ExtractedAssetItem(category=category, name=name, amount=amount, pl=pl, raw_label=raw_label))
    return items


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _safe_time(value) -> Optional[time]:
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        return None
