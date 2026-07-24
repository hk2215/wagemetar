# iPhone向け Web(Pyodide PWA)ビルドの詳細

CLAUDE.md から分離した「たまにしか要らない深い詳細」。Webビルド/再デプロイ時に読む。
概要と方針は CLAUDE.md の「iPhone向け配信」節を参照。

- **ライブURL**: https://hk2215.github.io/wagemetar/ (GitHub Pages, gh-pagesブランチ)
- **リポジトリ**: https://github.com/hk2215/wagemetar (main=ソース, gh-pages=ビルド成果物)
- **費用**: 全て無料(GitHub Pagesは静的配信・課金なし)。AI読取のみ自分のAnthropic APIキーで従量。

## 方式の背景
iPhoneにはMac無しでネイティブアプリを配布できない。かつ「PCを毎回起動するのは面倒」
「お金をかけたくない」という制約から、**PC非依存・無料・(狙いは)オフライン動作**を満たす方式として
Pyodide(CPythonをWebAssemblyにコンパイルしたランタイム)でアプリ全体をブラウザ内で動かす静的サイトを
ビルドし、無料の静的ホスティング(GitHub Pages)に置いて iPhone Safari の「ホーム画面に追加」で使う。
タイマー・カレンダー・バイト先設定・資産の手動入力はコアはオフライン動作可能。シフト写真/資産スクショの
AI読取はブラウザ直叩きだとCORSで失敗するため `page.web` 時はUIごと非表示(`calendar_view.py`/
`assets_view.py` の `page.web` 分岐)。

## ビルド/デプロイ手順
```
flet build web -v --no-cdn --base-url wagemetar --pwa-theme-color "#00897B" --pwa-background-color "#F3F5F6" --yes
python scripts/fix_web_build.py
```
1つ目のコマンドだけでは**完全にはオフライン化されない**(下記の既知バグ)。必ず2つ目の
`fix_web_build.py` を実行してから配布・検証すること。`--base-url wagemetar` は GitHub Pages の
プロジェクトサイトがサブパス(`/wagemetar/`)配信になるため必須。

デプロイ(gh-pagesブランチへ):
- `git worktree` で orphan `gh-pages` ブランチを別ディレクトリに用意し、`build/web/` の中身をコピー。
- `.nojekyll`(Jekyll処理を無効化。`_` 始まりファイル等を素通しさせる)を置く。
- `.gitattributes` に `* -text`(CRLF変換を全ファイルで無効化。wasm等バイナリ破損防止)。
- コミットして push → GitHub の Settings > Pages で Source=Deploy from a branch, Branch=gh-pages /(root)。
- push は成果物が約80MBあり、このClaude環境からは不安定。実機端末から `git push` するのが確実。

## `flet build web --no-cdn` の既知バグ3件と対応 (Flet 0.86.1で確認・要再検証)
`flet build web` は「依存を事前同梱してオフラインで動く」と謳うが、実際には以下3つの独立バグで
**素のまま使うとオフラインで確実に壊れる**。`scripts/fix_web_build.py` がビルド後に機械的に修正する
(ビルドのたびに実行する前提)。

1. **`index.html` の `pyodideUrl` が `--no-cdn` を無視してCDN URLのまま出力される**:
   `flet_web/patch_index.py` の `patch_index_html()` 自体は `no_cdn` 分岐を正しく実装しているが、
   `flet build web` はこの関数を経由しない別テンプレート機構で `index.html` を生成しており、
   そちらに `--no-cdn` が伝播していない。ローカルの `build/web/pyodide/` 自体は(バグ2を除けば)
   正しく生成されるので、URL文字列を書き換えれば直る。
   - **サブパス対応**: ルート直下配信なら `"/pyodide/pyodide.mjs"` でよいが、GitHub Pages の
     サブパス(`/wagemetar/`)では壊れる。`python-worker.js` はモジュールワーカーとして動くため、
     相対指定 `"./pyodide/pyodide.mjs"` にすると自身のスクリプトURL基準で解決され、任意のbase pathで動く
     (`"pyodide/..."` のように `./` 無しの裸指定はESモジュール解決で bare specifier 扱いになり失敗する)。

2. **`flet` パッケージ本体と依存(`repath`/`httpx`/`msgpack`/`six`)がオフラインで解決できない**:
   Pyodideランタイムはapp.zip展開後のカレントに `requirements.txt` があれば `micropip.install()` で
   追加パッケージを入れる設計だが、`flet build web` はこのファイルをapp.zipに含めない。加えて
   `httpx`/`msgpack`/`six` は Pyodide公式配布のパッケージ名として `pyodide-lock.json` に載っているが
   `--no-cdn` では実体wheelが同梱されず、`flet`/`repath` に至っては Pyodide公式配布に**存在すらしない**
   (通常のPyPI専用)。結果、オフラインでは micropip が PyPI 到達を試みて失敗する。
   - 対応: `src/requirements.txt`(`flet>=0.86.1` / `httpx>=0.28.1`)をリポジトリに追加済み
     (このファイルは `flet build web` のapp.zipに自動同梱される。ネイティブビルドの依存解決は引き続き
     `pyproject.toml` 側が使われるため無視される)。
   - `flet`/`repath` の wheel は `pip download <pkg>==<version> --no-deps` でPyPIから、
     `httpx`/`msgpack`/`six` は同一バイトが必要なため**必ず** Pyodide CDN
     (`https://cdn.jsdelivr.net/pyodide/v<version>/full/<file>`)から取得し、`build/web/pyodide/` に
     配置した上で `pyodide-lock.json` に `flet`/`repath` のエントリ(name/file_name/sha256/depends等)を
     追加する必要がある(PyPI版と同名でもPyodide版はsha256が異なる場合があり、既存の
     `httpx`/`msgpack`/`six` エントリの検証に失敗する。実際に `six` で確認)。
   - `scripts/fix_web_build.py` がこの一連を自動化し、取得wheelは `.web_build_wheel_cache/`
     (`.gitignore`済み)と `~/.flet/cache/pyodide/<version>/` の両方にキャッシュ→2回目以降はネット不要。

3. **`canvasKitBaseUrl` がサブパスで壊れる**: `index.html` に `"/canvaskit/"`(ルート絶対)で出力され、
   `<base href>` を無視するためサブパス配信で404。相対 `"canvaskit/"` に書き換えて解決
   (fetch/URL解決なのでbase href基準で正しく解決される)。

- **Pyodideバージョン更新時**: `314.0.2` が変わったら `scripts/fix_web_build.py` 内の `PYODIDE_VERSION`・
  各wheelのファイル名・sha256 を再取得し直すこと。

## `web_persistence.py` の既知の罠: IDBFSコールバックの `jsnull`
Web(Pyodide)実行時のデータ永続化は `src/web_persistence.py` が IndexedDB(IDBFS)へ syncfs する。
`FS.syncfs(populate, callback)` は Node.js流の `callback(err)` 規約に従い、**成功時も `null` を渡す**
(失敗時 `undefined` ではなく `null` という区別)。Pyodide は JSの `null` を Pythonの `None` ではなく、
`undefined` と区別するための falsy な `pyodide.ffi.jsnull` センチネルに変換する。そのため
`if err is not None:` で判定すると成功時も誤ってエラー扱いになる(実際に発生・修正済み)。
**`if err:` の真偽値判定を使うこと**(`jsnull` は falsy)。

## 日本語フォントの同梱
CanvasKit(Flet Webのレンダラー)は日本語グリフを Google Fonts CDN から動的取得する設計のため、
オフラインでは文字化けする(Playwright検証で確認)。`src/assets/fonts/NotoSansJP-Regular.ttf`
(google/fonts の `NotoSansJP[wght].ttf`)を `theme.FONT_FAMILY` / `page.fonts` で明示登録し、
常にローカルから読ませることで解決。

## 検証手順と結果
- 手順: `flet serve build/web -p <port>` でローカル配信し、Playwright で localhost(またはサブパス)以外の
  通信を全ブロックした状態でロード→バイト先登録→タイマー開始→リロード、を確認する。
  Playwright はヘッドレスで `--enable-unsafe-swiftshader` 必須(無いと描画が不安定になりピンク/青の矢印。
  実機Safariはハードウェアレンダリングのため影響しない)。実機は都度使えないためこの方法が確実。
- 結果(ローカル/CI相当): 外部通信ゼロ・日本語表示崩れなし・リロード後もタイマーが時刻ベースで正しく
  経過(稼働中/金額/経過時間が復元)を確認。クリーンな `build/` 削除→再ビルド→`fix_web_build.py` でも
  再現。GitHub Pages のサブパス配信・公開URLでも同様に確認済み。
- **実機の結末**: iPhone実機での**オフライン起動は動かず、ユーザーが妥協**(オンラインなら動作)。
  原因の深掘りは未実施(実機のSafariコンソールログ等が取れれば追える)。オンライン利用前提なら実用可。
