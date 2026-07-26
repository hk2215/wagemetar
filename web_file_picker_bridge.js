// Fletの FilePicker が Web(Pyodide Worker)環境で機能しない既知バグの回避策。
// Pythonワーカー(python-worker.js)はDOM(document)に直接アクセスできないため、
// BroadcastChannel経由でメインスレッド(このスクリプト)に画像選択を依頼し、
// 選択されたファイルのバイト列を送り返す。対になる実装は src/web_file_picker.py。
//
// このファイルは scripts/fix_web_build.py がビルド後に build/web/ へコピーし、
// index.html に <script> タグを追記する(flet build web はこのファイルの存在を
// 知らないため、毎回のビルド後処理として必須)。
(function () {
  const channel = new BroadcastChannel("flet-file-picker");

  channel.onmessage = (event) => {
    const msg = event.data;
    if (!msg || msg.type !== "pick") return;

    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.style.display = "none";
    document.body.appendChild(input);

    const cleanup = () => {
      if (input.parentNode) input.parentNode.removeChild(input);
    };

    input.onchange = () => {
      const file = input.files && input.files[0];
      cleanup();
      if (!file) {
        channel.postMessage({ type: "cancelled", requestId: msg.requestId });
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        channel.postMessage({
          type: "result",
          requestId: msg.requestId,
          name: file.name,
          data: new Uint8Array(reader.result),
        });
      };
      reader.onerror = () => {
        channel.postMessage({ type: "error", requestId: msg.requestId, message: String(reader.error) });
      };
      reader.readAsArrayBuffer(file);
    };
    // 一部ブラウザ(特に古いiOS Safari)は 'cancel' イベントに未対応な場合がある。
    // その場合、キャンセル時はメッセージが返らずPython側は待機し続ける。
    input.oncancel = () => {
      cleanup();
      channel.postMessage({ type: "cancelled", requestId: msg.requestId });
    };

    input.click();
  };
})();
