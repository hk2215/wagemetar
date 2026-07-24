"""`flet build web --no-cdn` 実行後に必ず走らせる後処理スクリプト。

このFletバージョン(0.86.1)の `flet build web` には、完全オフライン運用を狙う
このプロジェクトにとって致命的な既知バグが複数ある(調査で確認済み):

1. `--no-cdn` を指定しても、生成される `build/web/index.html` 内の
   `flet.pyodideUrl` が `https://cdn.jsdelivr.net/...` のCDN URLのまま出力される
   (`flet_web/patch_index.py` の `no_cdn` 分岐はコードとしては正しいが、
   `flet build web` はこの関数を経由せず別のテンプレート機構でindex.htmlを
   生成しており、そちらには `--no-cdn` が正しく伝播していない)。
   ローカルの `build/web/pyodide/` 自体は正しく生成されているため、
   URLだけを `/pyodide/pyodide.mjs` に書き換えれば解決する。

2. `flet` パッケージ自体(および `repath`/`httpx`/`msgpack`/`six` の各wheel)が
   Emscriptenターゲットの `app.zip` にも `~/.flet/cache/pyodide/<version>/` にも
   バンドルされない。ランタイム(`python-worker.js`)は展開後のカレントディレクトリに
   `requirements.txt` があれば `micropip.install()` を呼ぶ設計だが、
   `flet build web` はこのファイルをapp.zipに含めない(`src/requirements.txt` を
   このプロジェクトに追加済みで、これで解決)。加えて `flet` は
   `~/.flet/cache/pyodide/<pyodide_version>/pyodide-lock.json` に一切登録が
   無いため、micropip はPyPI(ネットワーク)に頼ろうとして完全オフラインで失敗する。
   このスクリプトは、あらかじめ用意した wheel ファイル一式を `build/web/pyodide/`
   に配置し、`pyodide-lock.json` に `flet`/`repath` のエントリを追加する
   (`httpx`/`msgpack`/`six` は元々 Pyodide 公式配布に含まれるパッケージ名として
   ロックファイルに載っているが、実体のwheelファイルが `--no-cdn` では
   同梱されないため、これも併せて配置する)。

wheel本体は初回のみこのマシンのグローバルキャッシル
(`~/.flet/cache/pyodide/<version>/`)にダウンロードして保存し、以後の
`flet build web` 実行でもそこから複製されるようにしている
(`WHEEL_CACHE_DIR` 配下、`--refresh-wheels` を付けない限り再ダウンロードしない)。

使い方: `flet build web --no-cdn ...` の直後に
`python scripts/fix_web_build.py` を実行する。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_WEB = PROJECT_ROOT / "build" / "web"
PYODIDE_VERSION = "314.0.2"
CDN_BASE = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full"

# (package name, wheel filename, pip spec or None, micropip "depends" list)
#
# httpx/msgpack/six are official Pyodide-distributed packages: their
# pyodide-lock.json entries (and sha256) already exist and MUST be fetched
# from the Pyodide CDN mirror byte-for-byte (verified: PyPI's own "six" wheel
# has a different sha256 than Pyodide's redistributed copy, so a plain `pip
# download` would fail micropip's integrity check).
#
# flet/repath are NOT Pyodide packages at all — there is no CDN mirror copy,
# so these are fetched from PyPI via `pip download` instead, and we compute
# our own sha256 for the brand-new lock entries we add for them.
REQUIRED_WHEELS = [
    ("msgpack", "msgpack-1.1.2-cp314-cp314-pyemscripten_2026_0_wasm32.whl", "cdn", None, None),
    ("httpx", "httpx-0.28.1-py3-none-any.whl", "cdn", None, None),
    ("six", "six-1.17.0-py2.py3-none-any.whl", "cdn", None, None),
    ("flet", "flet-0.86.1-py3-none-any.whl", "pypi", "flet==0.86.1", ["repath", "msgpack"]),
    ("repath", "repath-0.9.0-py3-none-any.whl", "pypi", "repath==0.9.0", ["six"]),
]

WHEEL_CACHE_DIR = PROJECT_ROOT / ".web_build_wheel_cache"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _ensure_wheel_cached(filename: str, source: str, pip_spec: str | None) -> Path:
    cached = WHEEL_CACHE_DIR / filename
    if cached.exists():
        return cached
    WHEEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if source == "cdn":
        url = f"{CDN_BASE}/{filename}"
        print(f"Downloading {url}")
        urllib.request.urlretrieve(url, cached)
    else:
        print(f"pip download {pip_spec}")
        subprocess.run(
            [
                sys.executable, "-m", "pip", "download", pip_spec,
                "--no-deps", "-d", str(WHEEL_CACHE_DIR),
            ],
            check=True,
        )
        if not cached.exists():
            raise RuntimeError(f"pip download did not produce expected file {filename}")
    return cached


def fix_index_html() -> None:
    index_path = BUILD_WEB / "index.html"
    text = index_path.read_text(encoding="utf-8")
    marker = 'pyodideUrl: "'
    start = text.index(marker) + len(marker)
    end = text.index('"', start)
    current_url = text[start:end]
    # A leading-slash path ("/pyodide/pyodide.mjs") only resolves correctly
    # when the site is served from the domain root; GitHub Pages project
    # sites are served under a subpath (e.g. /wagemetar/), which would break
    # it. python-worker.js runs as a module worker, so a relative specifier
    # here resolves against *its own* script URL (which already lives under
    # the same base path) — "./pyodide/pyodide.mjs" works at any base path.
    # (A bare "pyodide/pyodide.mjs", with no "./" prefix, is invalid too:
    # ES module resolution treats it as a bare specifier, not a relative
    # URL, and fails with "Failed to resolve module specifier".)
    local_url = "./pyodide/pyodide.mjs"
    if current_url == local_url:
        print("index.html: pyodideUrl already local, skipping")
        return
    text = text[:start] + local_url + text[end:]

    # Same class of bug: canvasKitBaseUrl is emitted as "/canvaskit/" (root-
    # absolute), which ignores `<base href>` and breaks under a GitHub Pages
    # project-site subpath (e.g. /wagemetar/). Unlike pyodideUrl this one is
    # consumed via fetch()/URL, not a bare `import()` specifier, so a plain
    # relative path (no "./" needed) resolves correctly against the page's
    # base href.
    text = text.replace('canvasKitBaseUrl: "/canvaskit/"', 'canvasKitBaseUrl: "canvaskit/"')

    index_path.write_text(text, encoding="utf-8")
    print(f"index.html: pyodideUrl {current_url!r} -> {local_url!r}; canvasKitBaseUrl -> relative")


def fix_pyodide_packages() -> None:
    pyodide_dir = BUILD_WEB / "pyodide"
    lock_path = pyodide_dir / "pyodide-lock.json"
    with lock_path.open(encoding="utf-8") as f:
        lock = json.load(f)

    for name, filename, source, pip_spec, depends in REQUIRED_WHEELS:
        dest = pyodide_dir / filename
        if not dest.exists():
            shutil.copy2(_ensure_wheel_cached(filename, source, pip_spec), dest)
            print(f"pyodide/: added {filename}")

        if name not in lock["packages"]:
            version = pip_spec.split("==")[1] if pip_spec else None
            lock["packages"][name] = {
                "name": name,
                "version": version,
                "file_name": filename,
                "install_dir": "site",
                "sha256": _sha256(dest),
                "package_type": "package",
                "imports": [name],
                "depends": depends or [],
                "unvendored_tests": False,
            }
            print(f"pyodide-lock.json: added entry for {name}")

    with lock_path.open("w", encoding="utf-8") as f:
        json.dump(lock, f)


def add_requirements_to_app_zip() -> None:
    """app.zip に requirements.txt が無ければ src/requirements.txt を追加する。

    通常は `src/requirements.txt` をリポジトリに置いておけば `flet build web`
    がそのまま拾ってapp.zipに含めてくれるはずだが、素の `flet build web`
    (このスクリプトを書いた時点のバージョン)がapp.zip生成時に
    `src/`直下の非`.py`ファイルを取りこぼす場合の保険として、無ければここで
    直接追記する。
    """
    import zipfile

    app_zip = BUILD_WEB / "assets" / "app" / "app.zip"
    with zipfile.ZipFile(app_zip) as zf:
        already_present = "requirements.txt" in zf.namelist()
    if already_present:
        print("app.zip: requirements.txt already present, skipping")
        return
    with zipfile.ZipFile(app_zip, "a") as zf:
        zf.write(PROJECT_ROOT / "src" / "requirements.txt", "requirements.txt")
    print("app.zip: injected requirements.txt")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    fix_index_html()
    fix_pyodide_packages()
    add_requirements_to_app_zip()
    print("Done. build/web is now fully offline-capable.")


if __name__ == "__main__":
    main()
