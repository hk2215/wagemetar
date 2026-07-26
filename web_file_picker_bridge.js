// Fletの FilePicker が Web(Pyodide Worker)環境で機能しない既知バグの回避策。
//
// 単純に BroadcastChannel 経由で受け取ったメッセージから input.click() を呼ぶだけでは
// iOS Safari で動かない(実機確認済み・症状: タップしても何も起きない)。Safariは
// 「ファイル選択ダイアログを開く操作は、ユーザーの実際のタップと完全に同期して
// 呼び出されなければならない」という制約(transient user activation)を厳格に課しており、
// Flet(Flutter)のボタン→Dart→Python(python-worker.js、別スレッド)→
// BroadcastChannel(非同期)→ここ、という経路はこの間に非同期処理を挟むため、
// Safariに「ユーザー操作から切り離された」とみなされ input.click() が黙って無視される。
//
// 対策: Fletのボタンは「準備完了」の通知(BroadcastChannel)を送るだけにし、実際に
// ファイル選択ダイアログを開く操作は、この画面に浮かぶ**本物のHTML `<label>`**
// (`<input type="file">` に紐づく)をユーザーが直接タップすることで行う。
// label→input の関連付けはブラウザネイティブの機構であり、JavaScriptから
// click()を呼ぶ必要すら無いため、間に何も挟まらず完全に同期する。
//
// 対になる実装は src/web_file_picker.py。
(function () {
  const channel = new BroadcastChannel("flet-file-picker");
  let currentRequestId = null;

  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/*";
  input.id = "flet-file-picker-input";
  input.style.position = "fixed";
  input.style.left = "-9999px";
  document.body.appendChild(input);

  const overlay = document.createElement("div");
  overlay.style.cssText =
    "position:fixed;inset:0;z-index:99999;display:none;" +
    "align-items:flex-end;justify-content:center;" +
    "background:rgba(0,0,0,0.45);";

  const label = document.createElement("label");
  label.htmlFor = "flet-file-picker-input";
  label.style.cssText =
    "margin:24px;padding:16px 28px;border-radius:999px;" +
    "background:#00897B;color:#fff;font-size:16px;font-weight:600;" +
    "box-shadow:0 4px 16px rgba(0,0,0,0.3);cursor:pointer;" +
    "font-family:sans-serif;";

  const cancelBtn = document.createElement("div");
  cancelBtn.textContent = "キャンセル";
  cancelBtn.style.cssText =
    "position:absolute;top:24px;right:24px;color:#fff;font-size:14px;" +
    "padding:8px 12px;cursor:pointer;font-family:sans-serif;";

  overlay.appendChild(label);
  overlay.appendChild(cancelBtn);
  document.body.appendChild(overlay);

  function hideOverlay() {
    overlay.style.display = "none";
  }

  function finish(payload) {
    if (!currentRequestId) return;
    hideOverlay();
    channel.postMessage(Object.assign({ requestId: currentRequestId }, payload));
    currentRequestId = null;
  }

  cancelBtn.onclick = () => finish({ type: "cancelled" });
  overlay.onclick = (e) => {
    if (e.target === overlay) finish({ type: "cancelled" });
  };

  input.onchange = () => {
    const file = input.files && input.files[0];
    hideOverlay();
    if (!file) {
      finish({ type: "cancelled" });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => finish({ type: "result", name: file.name, data: new Uint8Array(reader.result) });
    reader.onerror = () => finish({ type: "error", message: String(reader.error) });
    reader.readAsArrayBuffer(file);
  };
  // 一部ブラウザ(古いiOS Safari等)は 'cancel' イベントに未対応な場合がある。
  // その場合、キャンセル時はオーバーレイの「キャンセル」ボタンで手動で閉じる必要がある。
  input.oncancel = () => finish({ type: "cancelled" });

  channel.onmessage = (event) => {
    const msg = event.data;
    if (!msg || msg.type !== "pick") return;
    currentRequestId = msg.requestId;
    input.value = ""; // 同じファイルを連続選択してもchangeが発火するようにリセット
    label.textContent = "📷 " + (msg.label || "タップして写真を選択");
    overlay.style.display = "flex";
  };
})();
