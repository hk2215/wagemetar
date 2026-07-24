# app — バイト時給加算アプリ（Flet / ローカル動作）

## 概要
- Flet（FlutterベースのPython製GUIフレームワーク）で作るスマホアプリ。4機能=**秒給加算タイマー**
  (スタート/ストップ/エンド)、**カレンダー可視化**(日/月/年集計・ヒートマップ・収入の壁アラート・
  月間目標・CSV出力)、**バイト先設定**(基本時給+時間帯/曜日加算・深夜割増・交通費・締め日/給料日)、
  **資産管理**(スクショAI読取+手動入力のスナップショット履歴・総資産/増減%)。Phase 1〜3すべて実装済み。
- **配信の現況**: 主経路は **iPhone PWA** — GitHub Pages にデプロイ済み(https://hk2215.github.io/wagemetar/)。
  `flet build apk` で Android実機APK も生成可能(ストア非公開)。詳細は [docs/web-build.md](docs/web-build.md)。
- **オフライン**: コア(タイマー/カレンダー/バイト先/資産手動入力)はローカルではオフライン完結。ただし
  **実機iPhoneのオフライン起動は動かず妥協済み**(オンラインなら動作)。APKはオフライン動作可。
- **費用は全て無料**。外部通信は `src/ai/vision.py` の1箇所(Anthropic API)のみで、シフト写真/資産スクショの
  **AI読取だけ**ネット接続とAPIキーが必要(従量課金は自分のキー分のみ)。セキュリティ方針は専用節参照。
- 開発は PC上でプレビュー(ブラウザ)しながら作る。

## 環境
- Python **3.11.9**(`python` で解決する方。`py` は3.14系なので使わない)。
- 仮想環境 `.venv`(直下・Git管理外)。**必ず有効化 or `.venv`配下の実行ファイルを直接指定**して実行し、
  グローバルには入れない。有効化: PS `.venv\Scripts\Activate.ps1` / Bash `source .venv/Scripts/activate`。
  直接指定: `.venv\Scripts\python.exe`, `.venv\Scripts\flet.exe`。
- 依存は `requirements.txt`(pip freeze)で固定。**pip + venv のみ**(uv不使用。README内の `uv run` は
  公式テンプレの案内で本プロジェクトでは使わない)。導入: `.venv\Scripts\python.exe -m pip install -r requirements.txt`。
- Flet **0.86.1**。`flet-desktop`/`flet-web`/`flet[test]`(numpy等の重い依存込み)も導入済み。
- `pyproject.toml` は Flet CLI がメタデータ(アプリ名/パッケージID/アイコン)と pytest設定を読むのに使う。
- **Playwright** はアプリの実行時依存ではなく E2E確認用。必要時に `pip install playwright && playwright install chromium`。

## ディレクトリ構成
```
app/
├── src/
│   ├── main.py            # エントリ。NavigationBarで4画面を切替えるシェル
│   ├── models.py          # dataclass(Workplace, WageRule, WorkSession, ShiftPlan, AssetSnapshot等)
│   ├── wage.py            # 時給計算エンジン(純粋関数。最重要・要テスト維持)
│   ├── db.py              # SQLiteスキーマ+リポジトリ関数一式
│   ├── formatting.py      # 金額/時間の表示フォーマットヘルパー
│   ├── theme.py           # 共通デザインシステム(色・余白・角丸・カード/バッジ)
│   ├── web_persistence.py # Web(Pyodide)時のみ有効なIndexedDB永続化。ネイティブ時はno-op
│   ├── ai/vision.py       # クラウドAI(Anthropic Messages API)。唯一のネットワーク通信
│   └── views/
│       ├── timer_view.py         # タイマー画面(+ライブ円カウンター/ticking_loop)
│       ├── workplace_view.py     # バイト先設定(CRUD+加算ルール追加)
│       ├── calendar_view.py      # カレンダー(ヒートマップ+集計+壁アラート+CSV+シフト予定)
│       ├── shift_import_view.py  # シフト取込カード(calendar_viewに埋込)
│       └── assets_view.py        # 資産(総資産・増減%・内訳・推移+スナップショット追加)
├── src/assets/            # アイコン等の静的リソース(views/assets_view.pyの資産機能とは無関係。Flet慣習名)
├── scripts/fix_web_build.py  # Webビルド後処理(docs/web-build.md参照)
├── tests/                 # test_wage/test_db/test_vision/test_views_smoke/test_web_persistence, test_main(重い)
├── docs/web-build.md      # iPhone/Webビルドの詳細(既知バグ・fix手順・デプロイ)
└── pyproject.toml / requirements.txt / README.md / CLAUDE.md
```

## データモデル / 時給計算（重要な前提）
- **秒給は時刻ベースで都度計算**: 毎秒カウンタはスリープ/バックグラウンドで狂うため、`WorkSession.start_ts` を
  保存し「今の時刻 − start_ts − 一時停止時間」から都度算出(`wage.earnings_so_far`)。再起動/タブ切替後も正確。
- **時給は時刻の関数として区間積分**: `wage.compute_earnings` が時間帯/曜日加算・深夜割増の境界で区間分割し、
  各区間の実効時給(`wage.effective_rate`)を積算(17:30開始→18:00の境界またぎも正確)。
- **一時停止(pause)は実時間で除外**: `WorkSession.pauses`(`SessionPause`リスト)の停止区間を積分から除く
  (`break_minutes` の概算按分とは別経路)。
- **深夜割増**: `Workplace.night_premium_enabled=True` で22:00-翌5:00に自動+25%。ただし
  `WageRule(kind=NIGHT_PREMIUM)` を明示追加した場合はそちらが優先され自動デフォルトは無効。
- **保存先**: SQLite(`src/db.py`)。環境変数 `FLET_APP_STORAGE_DATA`(端末内永続dir)優先、無ければ
  `<プロジェクト>/data/app.db`(`.gitignore`済)。`flet run`開発時は `src/.flet/storage/data/app.db`
  (`[tool.flet.app] path="src"` のため。`.gitignore`済)。

## 画面構成 (`main.py`)
- `NavigationBar` で「タイマー/カレンダー/バイト先/資産」の4画面を切替。
- **4画面は起動時に一度だけ構築し、切替では `body.content` を差し替えるだけ**(毎回作り直すとタイマーの
  `ticking_loop` が多重に走るため)。各 `build_xxx_view(page, db)` は `(Control, refresh)` を返し、`refresh()` は
  表示の瞬間に呼んで最新DB状態をUIへ反映。
- **重要**: 初期表示(タイマー)は `on_nav_change` を経由しないため `main()` 末尾で明示的に `refresh_timer()` を
  呼ぶ。忘れると稼働中/一時停止中セッションがあっても起動直後 idle 表示になる(修正済。回帰テスト
  `tests/test_views_smoke.py::test_main_restores_active_session_on_initial_load`)。

## デザインシステム (`theme.py`)
- 色・余白・角丸を `theme.py` に一元化。各画面は場当たりな色コードを書かずこの定数/ヘルパーだけ使う。
- **配色**: ティール(`SEED_COLOR="#00897B"`)基調を `ft.Theme(color_scheme_seed=...)` に渡しMaterial3標準
  コンポーネントを自動調和。薄グレー背景(`SURFACE_DIM`)に白カード(`SURFACE`)を影付きで浮かせ階層感を出す。
  ヒートマップも基調色の濃淡(`HEAT_LEVELS`)。
- **ダークモードは意図的に無効**(`page.theme_mode=LIGHT` 固定。カード色を固定hexで持つため破綻回避。将来対応
  時は `theme.py` 定数をライト/ダーク両対応の関数化)。
- **共通ヘルパー**: `theme.card()`/`theme.badge()`/`theme.field_style()`/`theme.title_text()`/`theme.caption_text()`。
  新要素はまずこれで表現できるか検討し、無ければ `theme.py` に追加。
- **AppBar**: `main.py` の `page.appbar` にタイトル表示。各 `views/*.py` は見出しTextを重複配置しない
  (切替時に `app_bar.title.value` を書換え)。
- **罠**: ボタン中身をRow(アイコン+テキスト)にした場合、アイコン差替えは `Icon` のフィールド名が `name` では
  なく **`icon`**(`pause_button.content.controls[0].icon = ft.Icons.PLAY_ARROW`)。

## Phase 2 シフト取込 / Phase 3 資産管理
- **シフト取込**(`ai/vision.py` + `views/shift_import_view.py`): カレンダー右上ボタンで折りたたみカードが開く
  (`build_shift_import_card`、`calendar_view.py`に埋込)。`FilePicker`で画像選択(`with_data=True`)→
  `ai.vision.extract_shifts()`が「自分の名前」の行だけJSON抽出→**必ず編集フォームで表示**し確認/修正後に
  `shift_plans` へ保存(human-in-the-loop、保存時 `confirmed=True`)。純粋関数 `parse_shifts_response()` と通信を行う
  `extract_shifts()` を分離し、単体テストは前者のみ対象。カレンダーはシフト予定日にドット(`ft.Stack`)を重ね、
  詳細パネルに「予定: バイト先名 開始-終了」を実績と分けて表示。
- **FilePicker赤帯バグ(Flet 0.86.1)**: `flet run --web` プレビューは `FilePicker` を認識できず画面に赤い
  "Unknown control: FilePicker" 帯が出る(flet issue #6040等)。`page.overlay` に存在するだけで発生。
  **回避**: 実際に「写真を選択」が押される時まで `page.overlay` に追加しない(`ensure_file_picker_attached()` を
  shift_import/assets両方に実装済)。写真選択自体の動作は `flet run --web` では未検証、実機ビルドで要確認。
- **資産管理**(`views/assets_view.py`): 銀行/証券の直接API連携は個人向けに非現実的なため不採用。**ある時点の
  資産を「スナップショット」記録し時系列比較**(`models.AssetSnapshot`/`AssetItem`, `db.py` の
  `add_asset_snapshot`/`list_asset_snapshots`/`latest_asset_snapshot`/`asset_snapshot_before`)。タブ構成=総資産
  (前日/前月/前年比の増減額/率)・今月のまとめ(労働収入 vs 資産の約30日増減)・カテゴリ内訳・推移(直近12件)・
  追加(折りたたみ)。**手動入力とAI画像読取を同じ編集可能な行リスト(`row_state`)に統合**し保存前に自由に編集/
  削除、合計は都度合算。AI読取は `ai.vision.extract_assets()`(bank/securities/stock/cash/other・名称・金額・損益)。
- **AI設定**(Anthropic APIキー・自分の名前)は SQLite `settings` テーブルに保存(`anthropic_api_key`/`my_name`。
  APIキーはシフト取込と資産で共有)。

## 外部通信のセキュリティ方針（ユーザー明示要望・要保持）
外部通信は `src/ai/vision.py` の1箇所(Anthropic Messages API)のみ。機微情報(シフト表・銀行/証券スクショ)を
送りうるため以下を徹底:
- **HTTPS固定**: エンドポイントは `https://api.anthropic.com/...` のみ。呼出時にスキームが `https://` であることを
  実行時検証するガード `_validate_request_security`(将来の改変で平文HTTPになったら気付ける)。
- **TLS検証明示**: `httpx.AsyncClient(verify=True, ...)`(デフォルト値だが意図明示で将来の緩和を防ぐ)。
- **画像サイズ上限**: `MAX_IMAGE_BYTES`(8MB)超は送信前に拒否。
- **APIキー非ログ**: ヘッダにのみ使用、ログ/例外に一切含めない(HTTPエラー時にレスポンス本文300字を例外に含めるが
  Anthropic側の説明でありヘッダは含まれない)。
- **画像はディスクに永続化しない**: メモリ上に一時保持のみ(shift_import/assets どちらも書き出さない)。
- **資産スクショは追加の同意ステップ**: `assets_view.py` は「外部AIに送信することに同意します」チェックボックスを
  入れない限り「画像から読み取る」が機能せず、未同意なら通信(FilePicker起動含む)自体を行わない。シフト表は相対的に
  機微度が低いためこの同意は無し。
- **APIキー平文保存のトレードオフ**: このFletバージョンに Secure Storage 相当が無い(`flet/controls/services/` 確認済)。
  そのため他設定と同じく SQLite `settings` に平文保存(端末のセキュリティと同保護レベル、他データと同等)。強化する
  なら将来 Android Keystore 連携のネイティブプラグインを検討(現状のFlet標準では不可)。

## Flet 0.86 系のAPIの注意点（旧チュートリアルと異なる部分）
- イベントハンドラは同期/非同期どちらも可。実行後は自動で画面更新されるので基本 `page.update()` 不要(本プロジェクトは
  明示呼びで分かりやすさ優先の箇所あり)。
- **バックグラウンドで動き続けるタスク**(タイマー毎秒更新等)は `page.run_task(async_handler)` で投げっぱなしに。
  クリックハンドラ内で無限ループを直接 `await` すると他イベントをブロックするため避ける(`timer_view.py::ticking_loop`)。
- KVストレージは `page.client_storage` 非推奨(非同期 `SharedPreferences` に置換)。同期で扱いたいので SQLite
  `settings`(`db.get_setting`/`db.set_setting`)で代替。
- **チャート専用コントロール(LineChart/PieChart/BarChart)は存在しない**。ヒートマップ/棒グラフは `ProgressBar` と
  色付き `Container` グリッドの自作。
- `AlertDialog` は使わず `ExpansionTile` のインライン展開フォーム(`workplace_view.py`)+ `SnackBar` で済ませる。
- `ElevatedButton` は0.80.0で非推奨(1.0で削除予定)→ **`ft.Button` を使う**。
- **`ft.Row(..., wrap=True)` に単独の `expand=True` 子を入れるとレイアウトが灰色空白ボックスに壊れる**(実機確認済)。
  単一 `expand=True` 要素だけのRowに `wrap=True` を付けない(既存コードは回避済)。

## コマンド / テスト / ビルド（すべて `.venv` 有効化して実行）
- プレビュー: `flet run --web src/main.py`(ブラウザ・ホットリロード) / `flet run src/main.py`(デスクトップ窓) /
  `flet run --android src/main.py`(実機)。`flet devices` / `flet doctor` で診断。
- **ユニットテスト**(高速・ネット不要): `.venv\Scripts\python.exe -m pytest tests/ -v`。
  - `test_wage.py`(境界またぎ・深夜割増・休憩控除・pause精度) — **金額計算に関わる変更をしたら必ずここに追加**。
  - `test_db.py`(CRUD・集計。`Database(":memory:")`)、`test_vision.py`(AI応答パース+送信前ガード。実通信は対象外)、
    `test_views_smoke.py`(ダックタイピング `FakePage` で `build_xxx_view()`/`main()` を組立検証)、
    `test_web_persistence.py`(ネイティブ時のno-op検証)。
  - `pyproject.toml` の `addopts="--ignore=tests/test_main.py"` で重い統合テストは既定で除外。`test_main.py` は
    `flet.testing` の `flet_app` フィクスチャで実機同等ホストを起動(初回はFlutter SDK自動DL。雛形のままなので節目で使う)。
- **見た目確認**: `flet run --web` + ブラウザ操作が最確実(curlのHTTP疎通だけでは検出できないレイアウト崩壊を過去に
  Playwrightのスクショで発見= `wrap=True`+`expand=True` バグ)。
- **APKビルド**(実機用・ストア非公開): `flet build apk -v`。初回は Flutter SDK/Android SDK/JDK17 を自動DL(数GB)。
  生成物 `build/apk/*.apk` を実機に転送し「提供元不明のアプリ」許可でインストール。デバッグ用鍵で自動署名(同じ端末で
  繰返すなら `--...-key-store` で署名鍵固定するとデータ引継ぎしやすい)。APKはSQLiteが端末内永続dirに保存されるため
  **AI読取以外はオフライン動作**。
- **Webビルド/iPhone配信**: 手順・既知バグ・デプロイは [docs/web-build.md](docs/web-build.md) 参照
  (`flet build web --no-cdn --base-url wagemetar ...` → `python scripts/fix_web_build.py` が必須)。

## 実装フェーズ（すべて実装済み）
- **Phase 1**: タイマー(秒給/一時停止/エンド)、バイト先設定、カレンダー(ヒートマップ・月/年集計・バイト先別内訳・
  収入の壁アラート103/106/130万・月間目標・CSV出力)。
- **Phase 2**: シフト表の写真取込(AIで自分の分だけ抽出→確認画面で修正→カレンダーに予定反映)。`ai/vision.py` に隔離。
- **Phase 3**: 資産管理(スクショAI読取+手動入力を統合した編集リストでスナップショット記録)。
- **配信(iPhone PWA)**: GitHub Pages にデプロイ完了。実機オフラインは不可で妥協(オンライン利用は可)。詳細は
  [docs/web-build.md](docs/web-build.md)。
