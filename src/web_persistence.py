"""Web(Pyodide)実行時のみ有効なデータ永続化ヘルパー。

`flet build web`/`flet publish` で生成した静的サイトは、ブラウザ内で Pyodide
(CPythonをWebAssemblyにコンパイルしたランタイム) 上で動く。Pyodide の既定の
ファイルシステム(MEMFS)はメモリ上にしか存在せず、**ページをリロードすると
消える**(実機検証で確認済み: バイト先登録やタイマーの記録がリロードで消失した)。

これを避けるため、DBファイルを置くディレクトリに IndexedDB 裏付けの IDBFS を
マウントし、
- 起動時: IndexedDB → メモリへ読み込む(pull, `populate=True`)
- 変更があったとき: メモリ → IndexedDB へ書き出す(push, `populate=False`)
という同期(syncfs)を行う。

ネイティブ(デスクトップ/Android APK)実行時やサーバーサイドの `flet run --web`
(Pyodideではなく通常のCPythonがサーバー側で動く)では、この処理はすべて
no-op になる(`is_pyodide()` が False を返すため)。判定には Flet 公式の
`flet.utils.is_pyodide()` と同じロジック(`sys.platform == "emscripten"`)を使う。
"""

from __future__ import annotations

import asyncio
import sys

MOUNT_DIR = "/idbfs_data"

_dirty = False
_initialized = False


def is_pyodide() -> bool:
    """Pyodide(ブラウザ内WebAssembly)で実行中かどうか。"""
    return sys.platform == "emscripten"


async def _syncfs(populate: bool) -> None:
    """Emscripten の `FS.syncfs` をPythonの awaitable としてラップする。

    Args:
        populate: True なら IndexedDB→メモリ(起動時のpull)、
            False ならメモリ→IndexedDB(変更時のpush)。
    """
    import pyodide_js as pjs
    from pyodide.ffi import create_once_callable

    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()

    def _callback(err=None):
        # Node.js流のコールバック規約(callback(err))に従い、FS.syncfsは成功時も
        # JSの`null`を渡してくる。PyodideはJSのnullをPythonのNoneではなく
        # falsyな`pyodide.ffi.jsnull`センチネルに変換する(undefinedとnullを
        # 区別するため)ので、`err is not None`ではなく真偽値で判定する必要がある。
        if err:
            if not fut.done():
                fut.set_exception(RuntimeError(f"IDBFS sync failed: {err}"))
        else:
            if not fut.done():
                fut.set_result(None)

    pjs.FS.syncfs(populate, create_once_callable(_callback))
    await fut


async def setup_and_pull() -> None:
    """アプリ起動時に1度だけ呼ぶ: IDBFSをマウントし、既存データを読み込む。

    DB接続を開く**前**に完了させること(先にDBファイルを新規作成してしまうと、
    IndexedDB側の既存データで上書き/混同される恐れがあるため)。
    """
    global _initialized
    if not is_pyodide() or _initialized:
        return

    import js
    import pyodide_js as pjs
    from pyodide.ffi import to_js

    pjs.FS.mkdirTree(MOUNT_DIR)
    empty_opts = to_js({}, dict_converter=js.Object.fromEntries)
    pjs.FS.mount(pjs.FS.filesystems.IDBFS, empty_opts, MOUNT_DIR)
    await _syncfs(populate=True)
    _initialized = True


def mark_dirty() -> None:
    """DBに変更があったことを記録する(次回の自動保存でIndexedDBへ書き出される)。"""
    global _dirty
    if is_pyodide():
        _dirty = True


async def autosave_loop(interval_seconds: float = 3.0) -> None:
    """Web実行時のみ: `mark_dirty()` 以降、一定間隔でIndexedDBへ書き出し続ける。

    `page.run_task()` で"投げっぱなし"にして使う想定(タイマーのticking_loopと同じ
    パターン)。ネイティブ実行時は即座に戻り何もしない。
    """
    if not is_pyodide():
        return
    global _dirty
    while True:
        await asyncio.sleep(interval_seconds)
        if _dirty:
            _dirty = False
            await _syncfs(populate=False)


async def flush_now() -> None:
    """即座にIndexedDBへ書き出す(セッション確定直後など、間を置きたくない場面用)。"""
    if is_pyodide():
        await _syncfs(populate=False)
