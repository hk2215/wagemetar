"""ai/vision.py の単体テスト。

ネットワーク呼び出し(extract_shifts/extract_assets本体)はテストせず、AIの応答
テキストをパースする純粋関数と、送信前セキュリティバリデーションだけを検証する
(ネットワーク無しで高速に実行できる範囲に留める)。
"""

from datetime import date, time

import pytest

from ai.vision import (
    MAX_IMAGE_BYTES,
    VisionError,
    extract_assets,
    extract_shifts,
    parse_assets_response,
    parse_shifts_response,
)


def test_parse_valid_json_array():
    text = '[{"date": "2026-08-01", "start_time": "09:00", "end_time": "17:00"}]'
    shifts = parse_shifts_response(text)
    assert len(shifts) == 1
    assert shifts[0].plan_date == date(2026, 8, 1)
    assert shifts[0].start_time == time(9, 0)
    assert shifts[0].end_time == time(17, 0)


def test_parse_json_embedded_in_prose():
    """AIが説明文を付けて返してきても、JSON部分だけ抜き出せること。"""
    text = (
        "以下がシフトの抽出結果です。\n"
        '[{"date": "2026-08-02", "start_time": "10:00", "end_time": "18:00"}]\n'
        "ご確認ください。"
    )
    shifts = parse_shifts_response(text)
    assert len(shifts) == 1
    assert shifts[0].plan_date == date(2026, 8, 2)


def test_parse_empty_array_when_no_match():
    shifts = parse_shifts_response("[]")
    assert shifts == []


def test_parse_null_date_handled_gracefully():
    text = '[{"date": null, "start_time": "09:00", "end_time": "17:00"}]'
    shifts = parse_shifts_response(text)
    assert len(shifts) == 1
    assert shifts[0].plan_date is None
    assert shifts[0].start_time == time(9, 0)
    assert "?" in shifts[0].raw_label


def test_parse_invalid_time_format_becomes_none():
    text = '[{"date": "2026-08-01", "start_time": "unreadable", "end_time": "17:00"}]'
    shifts = parse_shifts_response(text)
    assert shifts[0].start_time is None
    assert shifts[0].end_time == time(17, 0)


def test_parse_no_json_raises_vision_error():
    with pytest.raises(VisionError):
        parse_shifts_response("該当する行は見つかりませんでした。")


def test_parse_malformed_json_raises_vision_error():
    with pytest.raises(VisionError):
        parse_shifts_response("[{not valid json")


def test_parse_ignores_non_dict_items():
    text = '[{"date": "2026-08-01", "start_time": "09:00", "end_time": "17:00"}, "junk", 123]'
    shifts = parse_shifts_response(text)
    assert len(shifts) == 1


async def test_extract_shifts_requires_api_key():
    """ネットワーク呼び出し前にAPIキー未設定を検出し、通信せずに例外を出すこと。"""
    with pytest.raises(VisionError, match="APIキー"):
        await extract_shifts(
            image_bytes=b"dummy",
            filename="shift.jpg",
            api_key="",
            my_name="山田太郎",
            reference_year=2026,
            reference_month=8,
        )


async def test_extract_shifts_requires_my_name():
    with pytest.raises(VisionError, match="名前"):
        await extract_shifts(
            image_bytes=b"dummy",
            filename="shift.jpg",
            api_key="sk-ant-dummy",
            my_name="",
            reference_year=2026,
            reference_month=8,
        )


# --- 資産(銀行/証券)スクリーンショット抽出 ------------------------------------


def test_parse_assets_valid_json_array():
    text = '[{"category": "bank", "name": "○○銀行", "amount": 500000, "pl": null}]'
    items = parse_assets_response(text)
    assert len(items) == 1
    assert items[0].category == "bank"
    assert items[0].name == "○○銀行"
    assert items[0].amount == 500000.0
    assert items[0].pl is None


def test_parse_assets_with_profit_loss():
    text = '[{"category": "stock", "name": "○○株式", "amount": 300000, "pl": -12345.5}]'
    items = parse_assets_response(text)
    assert items[0].pl == -12345.5


def test_parse_assets_invalid_category_falls_back_to_other():
    text = '[{"category": "crypto", "name": "謎の資産", "amount": 1000, "pl": null}]'
    items = parse_assets_response(text)
    assert items[0].category == "other"


def test_parse_assets_embedded_in_prose():
    text = (
        "以下が抽出結果です。\n"
        '[{"category": "cash", "name": "現金", "amount": 10000, "pl": null}]\n'
        "ご確認ください。"
    )
    items = parse_assets_response(text)
    assert len(items) == 1
    assert items[0].category == "cash"


def test_parse_assets_empty_array():
    assert parse_assets_response("[]") == []


def test_parse_assets_non_numeric_amount_becomes_none():
    text = '[{"category": "bank", "name": "○○銀行", "amount": "判読不能", "pl": null}]'
    items = parse_assets_response(text)
    assert items[0].amount is None


def test_parse_assets_malformed_json_raises_vision_error():
    with pytest.raises(VisionError):
        parse_assets_response("見つかりませんでした")


async def test_extract_assets_requires_api_key():
    with pytest.raises(VisionError, match="APIキー"):
        await extract_assets(image_bytes=b"dummy", filename="asset.jpg", api_key="")


# --- 送信前セキュリティバリデーション ------------------------------------------


async def test_extract_shifts_rejects_oversized_image():
    """画像サイズが上限を超える場合、通信せずに拒否すること。"""
    oversized = b"x" * (MAX_IMAGE_BYTES + 1)
    with pytest.raises(VisionError, match="サイズ"):
        await extract_shifts(
            image_bytes=oversized,
            filename="shift.jpg",
            api_key="sk-ant-dummy",
            my_name="山田太郎",
            reference_year=2026,
            reference_month=8,
        )


async def test_extract_assets_rejects_oversized_image():
    oversized = b"x" * (MAX_IMAGE_BYTES + 1)
    with pytest.raises(VisionError, match="サイズ"):
        await extract_assets(image_bytes=oversized, filename="asset.jpg", api_key="sk-ant-dummy")
