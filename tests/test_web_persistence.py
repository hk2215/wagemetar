"""web_persistence.py の単体テスト。

ネイティブ(CPython)実行環境では `is_pyodide()` が常に False を返し、
全ての関数が安全な no-op になることを保証する
(この安全網が無いと、通常のデスクトップ/pytest実行でも誤って
`pyodide_js` 等の存在しないモジュールをimportしようとして壊れる)。
実際のPyodide環境(IDBFSマウント・syncfs)はブラウザが無いと再現できないため、
実機/ブラウザでの検証(Playwright)で別途確認する。
"""

import web_persistence


def test_is_pyodide_false_on_native():
    assert web_persistence.is_pyodide() is False


async def test_setup_and_pull_is_noop_on_native():
    # pyodide_js 等が存在しない環境でも例外を出さずに即座に戻ること。
    await web_persistence.setup_and_pull()


def test_mark_dirty_is_noop_on_native():
    web_persistence.mark_dirty()
    assert web_persistence._dirty is False


async def test_flush_now_is_noop_on_native():
    await web_persistence.flush_now()


async def test_autosave_loop_returns_immediately_on_native():
    # Pyodideでなければ即座にreturnする(無限ループに入らない)ことを保証する。
    # ハングした場合はテスト自体がタイムアウトして失敗する。
    await web_persistence.autosave_loop(interval_seconds=0.01)
