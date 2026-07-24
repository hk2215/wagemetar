# app — バイト時給加算アプリ（Flet / ローカル動作）

## 概要
- Flet（Flutterベースの Python 製 GUI フレームワーク）で作るスマホアプリ。
- 用途: バイトの**秒給加算タイマー**（スタート/ストップ/エンド）、稼いだ金額の**カレンダー可視化**
  （日/月/年集計・ヒートマップ）、**バイト先設定**（基本時給＋時間帯加算・深夜割増等を都度追加）、
  **シフト表の写真取込**（クラウドAIで自分の分だけ抽出しカレンダーに予定反映）、
  **資産管理**（銀行/証券のスクショAI読取+手動入力によるスナップショット履歴、総資産・増減%可視化）。
  Phase 1〜3すべて実装済み(下記「今後の実装フェーズ」参照)。
- 想定ゴール: Google Play / App Store には出さず、**自分のAndroid端末にAPKを直接インストールして使う**。
- コア機能（タイマー・カレンダー・バイト先設定）はオフラインで完結する。シフト写真/資産スクショの
  **AI読み取り機能だけ**ネット接続とAnthropic APIキーが必要（設定はカレンダー/資産タブ内で行う）。
  外部通信を行うのは `src/ai/vision.py` の1箇所のみで、セキュリティ方針は専用セクション参照。
- 開発中は PC 上でプレビュー（ブラウザ）しながら作り、最後に `flet build apk` で実機用 APK を生成する。

## 環境
- Python: **3.11.9** を使用（`python` コマンドで解決される方）。`py` コマンドは 3.14 系を指すため、このプロジェクトでは使わない。
- 仮想環境: プロジェクト直下の `.venv`（Python 3.11 で作成済み）。
  - **必ず `.venv` を有効化した状態、または `.venv` 配下の実行ファイルを直接指定して**コマンドを実行すること。グローバル環境にはインストールしない。
  - PowerShell: `.venv\Scripts\Activate.ps1`
  - Bash: `source .venv/Scripts/activate`
  - 直接パス指定（activateせず実行する場合）: `.venv\Scripts\python.exe`, `.venv\Scripts\flet.exe`
- 依存関係は `requirements.txt`（`pip freeze` 出力）で固定。`uv` は使わず、**pip + venv** のみで完結させる方針。
  - インストール: `.venv\Scripts\python.exe -m pip install -r requirements.txt`
  - Flet: 0.86.1。`flet-desktop` / `flet-web` / `flet[test]`(numpy等の重い依存込み) も導入済み。
- `pyproject.toml` は Flet CLI（`flet build` 等）がアプリのメタデータ（アプリ名・パッケージID・アイコン設定など）
  や pytest 設定（`[tool.pytest.ini_options]`）を読むために使用。README.md 内の `uv run ...` という記述は
  Flet 公式テンプレートのデフォルト案内であり、**本プロジェクトでは使わない**（pip + venv で代替）。
- **開発用ツール(Playwright)について**: 実装中のE2E動作確認のためだけに `.venv` へ playwright を
  インストールし、Chromiumバイナリを取得したことがある。これはアプリの実行時依存ではないため
  `requirements.txt` には含めていない。再度ブラウザスクリーンショットでの動作確認をしたくなったら
  `pip install playwright && playwright install chromium` で都度用意する。

## ディレクトリ構成
```
app/
├── .venv/                  # 仮想環境（Git管理外）
├── src/
│   ├── main.py              # エントリーポイント。NavigationBarで3画面を切り替えるシェル
│   ├── models.py             # dataclass定義(Workplace, WageRule, WorkSession, ShiftPlan, AssetSnapshot等)
│   ├── wage.py                # 時給計算エンジン(純粋関数。最重要・要テスト維持)
│   ├── db.py                   # SQLiteスキーマ+リポジトリ関数一式
│   ├── formatting.py            # 金額/時間の表示フォーマットヘルパー
│   ├── theme.py                  # 共通デザインシステム(色・余白・角丸・カード/バッジのヘルパー)
│   ├── ai/
│   │   └── vision.py              # クラウドAI(Anthropic Messages API)。シフト表/資産画像の構造化抽出
│   ├── views/
│   │   ├── timer_view.py         # タイマー画面(スタート/ストップ/エンド+ライブ円カウンター)
│   │   ├── workplace_view.py     # バイト先設定画面(CRUD+加算ルール追加)
│   │   ├── calendar_view.py      # カレンダー画面(ヒートマップ+集計+壁アラート+CSV出力+シフト予定表示)
│   │   ├── shift_import_view.py  # シフト取込カード(画像選択→AI解析→確認編集→保存。calendar_viewに埋込)
│   │   └── assets_view.py        # 資産画面(総資産・増減%・カテゴリ内訳・推移+スナップショット追加)
│   └── assets/                 # アイコン等の静的リソース(紛らわしいが views/assets_view.py の
│                                  「資産」機能とは無関係。Fletの慣習的なディレクトリ名)
├── tests/
│   ├── test_wage.py          # wage.py の単体テスト(境界またぎ・深夜割増・休憩控除等)
│   ├── test_db.py             # db.py の単体テスト(CRUD・集計クエリ)
│   ├── test_vision.py          # ai/vision.py のAI応答パース・セキュリティバリデーションの単体テスト
│   ├── test_views_smoke.py     # views/*.py と main.py が例外なく組み立てられるかの検証
│   └── test_main.py            # Flet公式スキャフォールドの統合テスト(重い。下記「テスト」参照)
├── pyproject.toml            # Fletアプリのメタデータ・ビルド設定・pytest設定
├── requirements.txt           # pip install -r 用の依存関係固定ファイル
├── README.md                   # Flet公式テンプレートが生成した実行/ビルド手順
└── CLAUDE.md                    # このファイル
```

## データモデル / 時給計算の設計（重要な前提）
- **秒給は"時刻ベースで都度計算"**: 単純な毎秒カウンタはスマホのスリープ/バックグラウンドで狂うため、
  `WorkSession.start_ts` を保存し、経過は「今の時刻 − start_ts − 一時停止(pause)時間」から都度計算する
  (`wage.earnings_so_far`)。アプリ再起動・タブ切替後も正確に復元される。
- **時給は"時刻の関数"として区間積分**: `wage.compute_earnings` が、時間帯加算・曜日加算・深夜割増の
  境界(開始/終了時刻や日付が変わる瞬間)で区間を分割し、それぞれの実効時給(`wage.effective_rate`)を
  掛けて積算する。例えば17:30開始→18:00の時間帯加算をまたぐケースも正確。
- **一時停止(pause)は正確な実時間で除外**: `WorkSession.pauses` (`SessionPause`のリスト)に記録された
  実際の停止区間を、積分対象の時間から取り除いてから計算する(`break_minutes`による概算按分とは別経路)。
- **深夜割増**は `Workplace.night_premium_enabled=True` で 22:00-翌5:00 に自動で+25%適用。ただし
  `WageRule(kind=NIGHT_PREMIUM)` を明示的に追加した場合はそちらが優先され、自動デフォルトは無効になる。
- データは SQLite (`src/db.py`) に保存。保存先は環境変数 `FLET_APP_STORAGE_DATA`
  (`flet run` / ビルド後アプリが自動設定する端末内永続ディレクトリ) を優先し、無ければ開発用に
  `<プロジェクト>/data/app.db` にフォールバックする(このフォールバック用 `data/` は `.gitignore` 済み)。
- `flet run` 経由で開発中は、実際の保存先は `src/.flet/storage/data/app.db`
  ([tool.flet.app] path="src" のため .flet/ が src 配下に作られる。こちらも `.gitignore` 済み)。

## 画面構成 (`main.py`)
- `NavigationBar` で「タイマー」「カレンダー」「バイト先」「資産」の4画面を切り替える。
- **4画面は起動時に一度だけ構築し、タブ切替では `body.content` を差し替えるだけ**にしている
  (タブ切替のたびに作り直すと、タイマー画面のバックグラウンド更新タスク`ticking_loop`が多重に走るため)。
- 各 `build_xxx_view(page, db)` は `(Control, refresh)` のタプルを返す。`refresh()` はそのタブが
  表示される瞬間に呼び、最新のDB状態(バイト先一覧、稼働中セッションの有無等)をUIに反映する。
- **重要**: 初期表示(タイマー画面)は `on_nav_change` を経由しないため、`main()` の最後で明示的に
  `refresh_timer()` を呼んでいる。これを忘れると、稼働中/一時停止中のセッションがあってもアプリ起動
  直後は idle 表示のままになるバグになる(実際に発生し、修正済み。回帰テストは
  `tests/test_views_smoke.py::test_main_restores_active_session_on_initial_load` を参照)。

## デザインシステム (`theme.py`)
- スマホアプリとして「シンプル・わかりやすい・安っぽくない」見た目にするため、色・余白・角丸を
  `theme.py` に一元化している。各画面は場当たり的な色コードを直接書かず、この定数/ヘルパーだけを使う。
- **配色**: 落ち着いたティール(`SEED_COLOR = "#00897B"`)を基調色にし、`ft.Theme(color_scheme_seed=...)`
  でMaterial3の標準コンポーネント(ボタン・スイッチ・NavigationBar等)を自動で調和させている。
  ページ全体はごく薄いグレー背景(`SURFACE_DIM`)の上に白いカード(`SURFACE`)を影付きで浮かせることで、
  影を多用せずに階層感を出す方針。ヒートマップもGitHub風の緑ではなく基調色の濃淡(`HEAT_LEVELS`)に統一。
- **ダークモードは意図的に無効化**(`page.theme_mode = ft.ThemeMode.LIGHT` 固定)。カード等の色を
  固定の hex 値で持っているため、システムがダークモードだとコントラストが破綻するのを避けるため。
  将来ダークモード対応が必要になったら `theme.py` の定数をライト/ダーク両対応の関数に変更すること。
- **共通ヘルパー**: `theme.card(content)`(影付き角丸カード)、`theme.badge(text, fg, bg)`(ピル型の
  ステータスバッジ)、`theme.field_style()`(TextField/Dropdown用の"filled"スタイルkwargs一式)、
  `theme.title_text()`/`theme.caption_text()`(見出し・補足テキストの統一)。新しい画面や要素を
  追加するときはまずこれらで表現できないか検討し、無ければ `theme.py` に定数/ヘルパーを追加する。
- **AppBar**: `main.py` で `page.appbar` に画面タイトルを表示し、各 `views/*.py` 側では見出しの
  `Text` を重複して置かない(タブ切替時に `app_bar.title.value` を書き換える)。
- 実装時に踏んだ罠: ボタンの中身をRow(アイコン+テキスト)にした場合、アイコンを差し替えるときは
  `Icon` コントロールのフィールド名が `name` ではなく **`icon`** であることに注意
  (`pause_button.content.controls[0].icon = ft.Icons.PLAY_ARROW` のように書く)。

## シフト表の写真取込 (Phase 2: `src/ai/vision.py`, `src/views/shift_import_view.py`)
- カレンダー画面右上の「シフト表を取り込む」ボタンで、折りたたみ式のカードが開く
  (`views/shift_import_view.py::build_shift_import_card`。`calendar_view.py`に埋め込み)。
- **AI設定**(Anthropic APIキー・自分の名前)はこのカード内に常設。値は`db.py`の`settings`
  テーブルに保存する(`anthropic_api_key`, `my_name`キー。Phase1のSQLite設定KVをそのまま流用)。
- 流れ: `FilePicker`で画像選択(`with_data=True`でバイト列を直接取得) →
  `ai.vision.extract_shifts()`がAnthropic Messages APIをhttpxで直接呼び出し、
  「自分の名前」に該当する行だけをJSON配列で抽出 → 結果は**必ず編集可能なフォームとして表示**し、
  日付/開始/終了をユーザーが確認・修正してから「シフトを保存」で`shift_plans`テーブルに保存する
  (human-in-the-loop。保存時点で`ShiftPlan.confirmed=True`固定。編集フォームを経由すること自体が
  確認を兼ねる設計)。
- `ai/vision.py`はプロジェクト内で**唯一ネットワーク通信を行うモジュール**。純粋関数
  `parse_shifts_response()`(AI応答テキストからJSON抽出)とネットワーク呼び出しを行う
  `extract_shifts()`を分離しており、単体テスト(`tests/test_vision.py`)は前者だけを対象にしている。
- カレンダー画面には、シフト予定がある日にヒートマップセル内へ小さいドット(`ft.Stack`で重ね描画)を
  表示し、日付タップ時の詳細パネルにも「予定: バイト先名 開始-終了」を実績と分けて表示する。

### FilePickerの既知の不具合(Flet 0.86.1)と回避策
- **`flet run --web`のプレビュークライアントは `FilePicker` を認識できず、
  画面全体に赤い "Unknown control: FilePicker" という帯が出る既知のバグがある**
  (flet-dev/flet issue #6040, #6250 等。0.80系以降で継続中)。`flet build apk`等の正式ビルドでは
  Flutter側のfile_pickerプラグインが実際にコンパイルされるため問題ない見込み(未検証)。
  デスクトップ実行(`flet run`、`--web`無し)でも発生しない可能性が高い。
- この不具合は「`FilePicker`が`page.overlay`に存在するだけ」で発生し、タイミングをずらしても
  (`page.update()`を挟んで少し待っても)解消しない。
- **回避策**: `FilePicker`を**実際に「写真を選択」ボタンが押された時点まで`page.overlay`に
  追加しない**(`shift_import_view.py`と`assets_view.py`の両方に同じ`ensure_file_picker_attached()`
  パターンを実装済み)。これによりアプリ起動時や他のタブ・カードを開いただけの状態ではこの赤帯は
  出ず、実際に写真選択を試みた場合にのみ影響が限定される。**`flet run --web`でのプレビュー中は、
  写真選択そのものはまだ動作確認できていない**(この既知バグのため)。実機ビルド後に改めて確認すること。

## 資産管理 (Phase 3: `src/views/assets_view.py`)
- 銀行/証券口座への直接API連携は個人向けアプリでは非現実的なため採用していない
  (認証・審査が必要な法人向け契約が前提となるため)。代わりに、**ある時点の資産状況を
  「スナップショット」として都度記録し、時系列で比較する方式**を取る
  (`models.AssetSnapshot`/`AssetItem`, `db.py`の`add_asset_snapshot`/`list_asset_snapshots`/
  `latest_asset_snapshot`/`asset_snapshot_before`。データモデル自体はPhase1から用意済み)。
- 資産タブの構成: 総資産(前日/前月/前年比の増減額・増減率)、今月のまとめ(今月の労働収入 vs
  資産の約30日増減の比較)、カテゴリ別内訳(最新スナップショット)、推移(直近12件)、
  スナップショット追加(折りたたみ式)。
- スナップショット追加は**手動入力とAI画像読取を同じ編集可能な行リストに統合**している:
  手動で「+ 項目を追加」した行も、AIが画像から抽出した行も同じ`row_state`に並び、
  保存前にどちらも自由に編集・削除できる。合計金額は行の金額を都度合算して算出する。
- AI画像読取は`ai.vision.extract_assets()`(Anthropic Messages API)を使い、
  カテゴリ(bank/securities/stock/cash/other)・名称・金額・損益をJSON配列で抽出する。
  シフト表と同じくAPIキーは`db.py`の`settings`テーブル(`anthropic_api_key`キーをシフト取込と
  共有)に保存。

## 外部通信のセキュリティ方針(重要・ユーザーからの明示的な要望)
アプリ内で外部と通信するのは `src/ai/vision.py` の1箇所(Anthropic Messages API呼び出し)のみ。
シフト表・銀行/証券のスクリーンショットという機微な情報を送信しうるため、以下を徹底している。

- **HTTPS強制**: エンドポイントは固定の `https://api.anthropic.com/...` のみ。呼び出し時に
  スキームが`https://`であることを実行時検証するガード(`_validate_request_security`)を入れ、
  将来の改変で誤って平文HTTPになった場合に気付けるようにしている。
- **TLS証明書検証**: `httpx.AsyncClient(verify=True, ...)` を明示指定(デフォルト値だが、
  意図を明確にし将来の変更で緩められることを防ぐため明示している)。
- **画像サイズ上限**: `MAX_IMAGE_BYTES`(8MB)を超える画像は送信前に拒否する
  (誤操作や想定外の巨大データをそのまま送らない)。
- **APIキーの非ログ出力**: APIキーはリクエストヘッダにのみ使用し、ログや例外メッセージには
  一切含めない。HTTPエラー時にレスポンス本文の一部(300文字)を例外メッセージに含めるが、
  これはAnthropic側のエラー説明であり、送信したヘッダ情報が含まれることはない。
- **画像はディスクに永続化しない**: 選択した画像バイト列はAPI呼び出しのために一時的に
  メモリ上に保持するだけで、`shift_import_view.py`/`assets_view.py`のどちらもディスクに
  書き出さない(処理が終われば破棄される)。
- **資産(銀行/証券)スクショはシフト表より機微なため追加の同意ステップを設けている**:
  `assets_view.py`では「この画像の内容を外部AI(Anthropic)に送信することに同意します」
  というチェックボックスに明示的にチェックしない限り「画像から読み取る」ボタンが機能せず、
  同意していない場合はネットワーク通信(FilePickerの起動含む)そのものが行われない。
  シフト表(`shift_import_view.py`)は相対的に機微度が低いためこの同意ステップは設けていない。
- **APIキーの保存場所についてのトレードオフ**: このFletバージョンには「Secure Storage」
  (Android Keystore等に裏付けられた安全な保存領域)に相当するサービスが存在しない
  (`flet/controls/services/`配下を確認済み)。そのため、APIキーは他の設定と同じくSQLiteの
  `settings`テーブルに平文で保存している。これは端末自体のセキュリティ(画面ロック等)と
  同じ保護レベルであり、アプリの他のデータ(勤怠・資産額)と同等の扱い。より強固にしたい
  場合は、将来的にAndroidのKeystoreと連携するネイティブプラグインの追加を検討すること
  (現状のFletの標準機能では実現不可)。

## Flet 0.86 系のAPIで気をつけている点(旧バージョンのチュートリアルと異なる部分)
- イベントハンドラは同期/非同期どちらも書ける(`def on_click(e): ...` でも `async def on_click(e): ...`
  でも良い)。イベントハンドラ実行後は自動的に画面が更新されるため、ハンドラ内では基本 `page.update()`
  は不要だが、本プロジェクトでは明示的に呼んで分かりやすさを優先している箇所がある。
- **バックグラウンドで動き続けるタスク**(タイマーの毎秒更新など、イベントハンドラの外側で動くもの)は
  `page.run_task(async_handler)` で"投げっぱなし"にする。クリックハンドラの中で無限ループを直接
  `await` すると他のイベント処理をブロックしうるため避けること(`views/timer_view.py` の
  `ticking_loop` を参照)。
- 設定・APIキー等のKVストレージは、旧来の `page.client_storage` は非推奨(`SharedPreferences`
  serviceに置き換わり、しかも非同期API)。本プロジェクトでは同期的に扱いたいため、SQLiteの
  `settings` テーブル(`db.get_setting`/`db.set_setting`)で代替している。
- **チャート専用コントロール(LineChart/PieChart/BarChart)はこのバージョンに存在しない**。
  `calendar_view.py` のヒートマップ・棒グラフはすべて `ProgressBar` と色付き `Container` グリッドの
  自作で実現している。
- ダイアログ(`AlertDialog`)は使わず、`ExpansionTile` によるインライン展開フォーム(`workplace_view.py`)
  と `SnackBar`(簡易メッセージ)だけで済ませている。実装がシンプルで挙動も把握しやすいため。
- `ElevatedButton` は 0.80.0 で非推奨(1.0で削除予定)。**`ft.Button` を使うこと**。
- **`ft.Row(..., wrap=True)` に `expand=True` を持つ子を1つだけ入れると、レイアウトが壊れて灰色の
  空白ボックスになる不具合を実機で確認済み**(`Wrap`と`Expanded`相当の実装が非互換と推測される)。
  単一の`expand=True`要素だけを持つRowには `wrap=True` を付けないこと。既存コードはこの回避策済み。

## よく使うコマンド（すべて `.venv` を有効化した上で実行）
- ブラウザでプレビュー（ホットリロード付き）: `flet run --web src/main.py`
- デスクトップ窓でプレビュー: `flet run src/main.py`
- Android実機/エミュレータで直接プレビュー: `flet run --android src/main.py`（要: 実機のUSBデバッグ or エミュレータ）
- 接続デバイス確認: `flet devices`
- 環境診断（Flutter/Android SDK/JDKの状態確認）: `flet doctor`

## テスト
- **日常のユニットテスト**(高速・ネット不要): `.venv\Scripts\python.exe -m pytest tests/ -v`
  - `test_wage.py`: 時給計算エンジンの単体テスト(境界またぎ・深夜割増・休憩控除・一時停止の精度等)。
    **金額計算に関わる変更をしたら必ずここにテストケースを追加すること**。
  - `test_db.py`: SQLiteリポジトリ層の単体テスト(CRUD・集計クエリ)。使い捨ての `Database(":memory:")` を使う。
  - `test_vision.py`: `ai/vision.py`のAI応答パース(`parse_shifts_response`/`parse_assets_response`)と、
    送信前セキュリティバリデーション(APIキー未設定・画像サイズ上限超過を通信前に拒否すること)の
    単体テスト。実際のネットワーク呼び出し(`extract_shifts`/`extract_assets`本体の通信部分)は
    テスト対象外(ガード節のみテスト)。
  - `test_views_smoke.py`: `build_xxx_view()` / `main()` が実際のFlet実行環境無しで例外なく組み立てられる
    ことを確認するスモークテスト。ダックタイピングの `FakePage` を使い、コンストラクタの引数名や
    enumメンバ名の間違いをすぐ検出できる(ブラウザ経由の見た目確認とは別の安全網)。
  - `pyproject.toml` の `addopts = "--ignore=tests/test_main.py"` により、下記の重い統合テストは
    デフォルトでは実行されない。
- **`test_main.py`(重い統合テスト)**: Flet公式スキャフォールドが生成した、`flet.testing` の
  `flet_app` フィクスチャ経由で実機同等のFlutterテストホストを起動するテスト。初回はFlutter SDK等の
  自動ダウンロードが走りうる。**現状は雛形のカウンターアプリ用のテストのままなので、実際のmain.py
  (NavigationBar+3画面)に合わせて書き直すか、Phase完了時の節目でのみ `flet test` を使う想定**。
- **見た目の実機確認(ブラウザ)**: `flet run --web` でサーバーを起動し、ブラウザで実際に操作して確認する
  のが最も確実(過去に `curl` でのHTTP疎通確認だけでは検出できないレイアウト崩壊バグを、実際に
  Playwrightでスクリーンショットを撮って発見したことがある — 上記の `wrap=True`+`expand=True` の
  不具合)。Playwrightは常設の依存ではないため、必要な時に `pip install playwright && playwright
  install chromium` してから使う。

## Android APK ビルド（実機インストール用、ストア非公開）
```
flet build apk -v
```
- 初回実行時、Flutter SDK / Android SDK / JDK17 が未導入なら自動ダウンロード・インストールされる（ネットワーク接続とディスク容量が必要）。数GB規模のダウンロードになるため、初回は時間がかかる。
- 生成物は `build/apk/` 配下に `.apk` が出力される。これを実機に転送し、「提供元不明のアプリ」を許可してインストールすれば、ストアを経由せず自分の端末だけで使える。
- ストア配布はしないため、正式な署名鍵（アップロードキーストア）は必須ではないが、Flet はデバッグ用鍵で自動署名する。長期的に同じ端末で `flet build apk` を繰り返す場合は署名鍵を固定しておくと再インストール時にデータが引き継がれやすい（必要になったら `flet build apk --help` で `--...-key-store` 系オプションを確認する）。
- ビルド後のAPKは、SQLiteが端末内の永続ディレクトリに保存されるため**ネットワーク接続なしで
  タイマー・バイト先設定・カレンダー・資産管理が動作する**。Phase 2/3のクラウドAI画像読み取り
  (シフト表・資産スクショ)だけはこの限りでない(ネット接続とAPIキーが必要)。

## iPhoneでのオフライン利用: 静的Pyodide PWA化 (`flet build web`)
iPhoneにはMac無しでネイティブアプリを配布できない。かつ「PCを毎回起動するのは面倒」
「お金をかけたくない」という制約があるため、**PC非依存・無料・オフライン動作**を満たす
唯一の方式として、Pyodide(CPythonをWebAssemblyにコンパイルしたランタイム)でアプリ全体を
ブラウザ内で動かす静的サイトをビルドし、無料の静的ホスティング(GitHub Pages等)に置いて
iPhone Safariから「ホーム画面に追加」して使う方式を採用した。タイマー・カレンダー・
バイト先設定・資産の手動入力は完全オフラインで動く。シフト写真/資産スクショのAI読取は
ブラウザ直叩きだとCORSで失敗するため`page.web`時はUIごと非表示にしている
(`calendar_view.py`/`assets_view.py`の`page.web`分岐)。

### ビルド手順
```
flet build web -v --no-cdn --pwa-theme-color "#00897B" --pwa-background-color "#F3F5F6" --yes
python scripts/fix_web_build.py
```
1つ目のコマンドだけでは**完全にはオフライン化されない**(下記の既知バグ参照)。
必ず2つ目の`fix_web_build.py`を実行してから配布・実機確認すること。
検証は `flet serve build/web -p 8765` でローカル配信し、Playwrightでネットワークを
localhost以外ブロックした状態でロード・操作・リロードを行うのが確実(実機は都度使えないため)。

### `flet build web --no-cdn` の既知バグと対応 (Flet 0.86.1で確認・要再検証)
調査の結果、このバージョンの`flet build web`は「依存を事前同梱してオフラインで動く」と
謳っているにもかかわらず、実際には2つの独立したバグで**素のまま使うとオフラインで
確実に壊れる**ことが判明した。`scripts/fix_web_build.py`はこれをビルド後に機械的に
修正する後処理スクリプト(ビルドのたびに実行する前提)。

1. **`index.html`の`pyodideUrl`が`--no-cdn`を無視してCDN URLのまま出力される**:
   `flet_web/patch_index.py`の`patch_index_html()`関数のコード自体は`no_cdn`分岐を
   正しく実装しているが、`flet build web`はこの関数を経由しない別のテンプレート機構で
   `index.html`を生成しており、そちらに`--no-cdn`が伝播していない。ローカルの
   `build/web/pyodide/`自体は(この後述のバグを除けば)正しく生成されるので、
   URL文字列だけを`"/pyodide/pyodide.mjs"`に書き換えれば直る。
2. **`flet`パッケージ自体(と依存の`repath`/`httpx`/`msgpack`/`six`)がオフラインでは
   解決できない**: Pyodideランタイムはアプリのapp.zipを展開したカレントディレクトリに
   `requirements.txt`があれば`micropip.install()`で追加パッケージを入れる設計だが、
   `flet build web`はこのファイルをapp.zipに含めない。加えて`httpx`/`msgpack`/`six`は
   Pyodide公式配布のパッケージ名として`pyodide-lock.json`に載ってはいるものの、
   `--no-cdn`では実体のwheelファイルが同梱されず、`flet`/`repath`に至っては
   Pyodide公式配布に**存在すらしない**(通常のPyPI専用パッケージ)ため、オフラインでは
   micropipがPyPIへの到達を試みて必ず失敗する。
   - 対応: `src/requirements.txt`(`flet>=0.86.1`・`httpx>=0.28.1`)をリポジトリに追加
     済み(このファイルは`flet build web`のapp.zipには自動的に含まれる。ネイティブ
     ビルドの依存解決は引き続き`pyproject.toml`側が使われるため無視される)。
   - `flet`/`repath`のwheelは`pip download <pkg>==<version> --no-deps`でPyPIから、
     `httpx`/`msgpack`/`six`は同一バイトが必要なため**必ず**Pyodide CDN
     (`https://cdn.jsdelivr.net/pyodide/v<version>/full/<file>`)から取得し、
     `build/web/pyodide/`に配置した上で`pyodide-lock.json`に`flet`/`repath`の
     エントリ(name/file_name/sha256/depends等)を追加する必要がある
     (PyPI版と同名でもPyodide版はsha256が異なることがあり、既存の
     `httpx`/`msgpack`/`six`エントリの検証に失敗する。これは実際に`six`で確認した)。
     `scripts/fix_web_build.py`がこの一連の処理を自動化し、取得したwheelは
     `.web_build_wheel_cache/`(`.gitignore`済み)と`~/.flet/cache/pyodide/<version>/`
     の両方にキャッシュするため、2回目以降の実行はネットワーク不要。
   - Pyodideのバージョン(`314.0.2`)が変わったら`scripts/fix_web_build.py`内の
     `PYODIDE_VERSION`・各wheelのファイル名・sha256を再取得し直すこと。

### `web_persistence.py` の既知の罠: IDBFSコールバックの`jsnull`
`FS.syncfs(populate, callback)`はNode.js流の`callback(err)`規約に従い、**成功時も
`null`を渡してくる**(失敗時は`undefined`ではなく`null`、という違いを明示するため)。
Pyodideは JSの`null`をPythonの`None`に変換せず、`undefined`と区別するための
falsyな`pyodide.ffi.jsnull`センチネルに変換する。そのため`if err is not None:`で
判定すると成功時も誤ってエラー扱いになる(実際に発生し、修正済み)。**`if err:`のような
真偽値判定を使うこと**(`jsnull`はfalsy)。

### 日本語フォントの同梱
CanvasKit(Flet Webのレンダラー)は日本語グリフをGoogle Fonts CDNから動的取得する設計
のため、オフラインでは文字化けする(実機相当のPlaywright検証で確認済み)。
`src/assets/fonts/NotoSansJP-Regular.ttf`(google/fontsの`NotoSansJP[wght].ttf`)を
`theme.FONT_FAMILY`/`page.fonts`で明示登録し、常にローカルから読ませることで解決した。

### 検証状況
- Playwright(`--enable-unsafe-swiftshader`必須。無いとヘッドレスで描画が不安定になり
  ピンク/青の矢印が出る。実機Safariはハードウェアレンダリングのため影響しない見込み)で
  localhost以外への通信をすべてブロックした状態でロード→バイト先登録→タイマー開始→
  リロード、まで確認し、外部通信ゼロ・日本語表示崩れなし・リロード後もタイマーが
  時刻ベースで正しく経過(`稼働中`/金額/経過時間が復元)することを確認済み。
  クリーンな`build/`削除→再ビルド→`fix_web_build.py`でも同じ結果を再現済み。
- **未検証**: 実機iPhone Safariでの動作(ホーム画面追加・機内モードでの起動)。
  無料静的ホスティング(GitHub Pages想定)への配置もまだ。

## 今後の実装フェーズ（段階リリース。詳細は元の計画を参照）
- **Phase 1（実装済み）**: タイマー(秒給・一時停止・エンド)、バイト先設定(基本時給・
  時間帯加算・曜日加算・深夜割増・交通費・締め日/給料日)、カレンダー(ヒートマップ・月/年集計・
  バイト先別内訳・収入の壁アラート103/106/130万・月間目標・CSV出力)。
- **Phase 2（実装済み）**: シフト表の写真取り込み(クラウドAIで自分の分だけ抽出→
  確認画面で人が修正→カレンダーに予定として反映)。`src/ai/vision.py`にAI呼び出しを隔離。
- **Phase 3（実装済み・本コミット時点）**: 資産管理(銀行/証券のスクショAI読取+手動入力を
  統合した編集リストでスナップショットを記録。総資産・前日/前月/前年の増減額・増減率、
  カテゴリ別内訳、推移、今月の労働収入との比較)。個人向けの直接API連携は非現実的なため
  不採用。資産スクショはシフト表より機微なため送信前の明示的同意チェックボックスを追加。
- Phase 2/3共通で、`flet run --web`でのFilePicker動作は既知バグ未検証(上記セクション参照)。
  **実機ビルドでの動作確認が今後最優先の課題**。
- 各Phase完了時に `flet build apk -v` で実機APKを生成し、実機で(可能なら機内モードで)動作確認する。
  特にPhase2/3の写真取込(FilePicker)は実機ビルドでの動作確認が必須(プレビューでは未検証のため)。
