import { validateAudio, formatTime, characterCount } from "./core.mjs";

const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="csrf-token"]').content;
let audioFile = null;
let previewURL = null;
let recorder = null;
let recording = false;
let microphonePending = false;
let busy = false;
let modelReady = false;
let initialized = false;
let shuttingDown = false;
let closed = false;
let pendingJob = null;
let toastTimer = null;
let audioSeconds = 0;

function showError(message = "") {
  $("error").textContent = message;
  $("error").hidden = !message;
}

function toast(message) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").hidden = false;
  toastTimer = setTimeout(() => {
    $("toast").hidden = true;
  }, 3200);
}

function inputsLocked() {
  return (
    !initialized ||
    shuttingDown ||
    closed ||
    busy ||
    recording ||
    microphonePending ||
    Boolean(pendingJob)
  );
}

function refreshControls() {
  const locked = inputsLocked();
  // Stopping an active microphone must never be blocked by another state.
  $("record-button").disabled = !recording && locked;
  $("tab-record").disabled = locked;
  $("tab-file").disabled = locked;
  $("audio-file").disabled = locked;
  $("remove-audio").disabled = locked;
  $("language").disabled = locked;
  $("transcribe-button").disabled =
    !initialized ||
    shuttingDown ||
    closed ||
    busy ||
    recording ||
    microphonePending ||
    (!pendingJob && (!audioFile || !modelReady));
  $("transcribe-button").textContent =
    pendingJob && !busy
      ? "重新连接，查看进度"
      : busy
        ? "正在本机转写…"
        : "开始转写 →";
  $("exit-button").disabled = locked;
  $("transcript").readOnly = !initialized || busy || Boolean(pendingJob);
  refreshEditor();
}

function refreshEditor() {
  const text = $("transcript").value;
  $("editor-empty").hidden = text.length > 0 || busy;
  $("word-count").textContent = `${characterCount(text)} 字`;
  $("copy-button").disabled = !text.trim();
  $("export-button").disabled = !text.trim();
  $("clear-button").disabled =
    !initialized || busy || Boolean(pendingJob) || !text;
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  let response;
  try {
    response = await fetch(path, {
      ...options,
      signal: controller.signal,
      headers: { ...options.headers, "X-App-Token": token },
    });
    if (!response.headers.get("content-type")?.includes("application/json")) {
      throw new Error(
        response.status === 413
          ? "文件过大，请选择不超过 200 MB 的音频。"
          : "本地程序响应异常，请刷新页面后重试。",
      );
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "操作失败，请重试。");
    return result;
  } catch (error) {
    const failure = controller.signal.aborted
      ? new Error("本地程序响应超时，可以重新连接查看进度，或刷新页面后重试。")
      : !response
        ? new Error(
            "无法连接本地程序，请确认程序窗口仍在运行。可以重新连接查看进度，或刷新页面。",
          )
        : error;
    if (response) failure.status = response.status;
    throw failure;
  } finally {
    clearTimeout(timeout);
  }
}

function switchTab(mode) {
  if (inputsLocked()) return;
  for (const name of ["record", "file"]) {
    const selected = name === mode;
    $(`tab-${name}`).setAttribute("aria-selected", String(selected));
    $(`tab-${name}`).tabIndex = selected ? 0 : -1;
    $(`${name}-panel`).hidden = !selected;
  }
}

function selectFile(file) {
  if (inputsLocked()) return;
  const error = validateAudio(file);
  if (error) {
    showError(error);
    return;
  }
  showError();
  audioFile = file;
  $("audio-preview").pause();
  if (previewURL) URL.revokeObjectURL(previewURL);
  previewURL = URL.createObjectURL(file);
  $("audio-preview").src = previewURL;
  $("file-name").textContent = file.name;
  $("file-size").textContent =
    `${(file.size / 1024 / 1024).toFixed(2)} MB · 仅在本机处理`;
  $("selected-audio").hidden = false;
  refreshControls();
}

async function toggleRecording() {
  if (recording) {
    if (recorder?.state === "recording") recorder.stop();
    return;
  }
  if (inputsLocked()) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    showError(
      "此浏览器不支持录音，请使用近期版本的 Edge 或 Chrome；也可以导入音频文件。",
    );
    return;
  }
  showError();
  microphonePending = true;
  refreshControls();
  let stream;
  let localRecorder;
  let recordingTimer;
  let released = false;
  const chunks = [];
  const isCurrent = () => !released && recorder === localRecorder;
  const release = () => {
    if (released) return;
    released = true;
    if (localRecorder) {
      localRecorder.ondataavailable = null;
      localRecorder.onstop = null;
      localRecorder.onerror = null;
    }
    chunks.length = 0;
    stream?.getTracks().forEach((track) => track.stop());
    clearInterval(recordingTimer);
    if (recorder === localRecorder) {
      recorder = null;
      finishRecording();
    }
  };
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
      video: false,
    });
    const mimeType = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ].find((type) => MediaRecorder.isTypeSupported(type));
    localRecorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream);
    recorder = localRecorder;
    let size = 0;
    const started = Date.now();
    const actualType = localRecorder.mimeType || "audio/webm";
    localRecorder.ondataavailable = (event) => {
      if (!isCurrent()) return;
      if (event.data.size) {
        chunks.push(event.data);
        size += event.data.size;
      }
      if (size > 200 * 1024 * 1024 && localRecorder.state === "recording")
        localRecorder.stop();
    };
    localRecorder.onerror = () => {
      if (!isCurrent()) return;
      showError("录音发生错误，请检查麦克风连接后重试。");
      // Stopping the tracks also ends capture; detached callbacks cannot publish partial audio.
      release();
    };
    localRecorder.onstop = () => {
      if (!isCurrent()) return;
      let file;
      try {
        const extension = actualType.includes("mp4")
          ? "m4a"
          : actualType.includes("ogg")
            ? "ogg"
            : "webm";
        const blob = new Blob(chunks, { type: actualType });
        const stamp = new Date()
          .toISOString()
          .slice(0, 19)
          .replace(/[T:]/g, "-");
        file = new File([blob], `麦克风录音-${stamp}.${extension}`, {
          type: actualType,
        });
      } finally {
        release();
      }
      selectFile(file);
      $("record-hint").textContent = "录音已准备好，可试听后开始转写";
    };
    localRecorder.start(1000);
    recording = true;
    $("record-label").textContent = "停止录音";
    $("record-button").classList.add("recording");
    $("record-visual").classList.add("is-recording");
    $("record-hint").textContent = "正在录音，清晰自然地说话即可";
    $("record-timer").textContent = "00:00";
    recordingTimer = setInterval(() => {
      if (!isCurrent()) return;
      const seconds = (Date.now() - started) / 1000;
      $("record-timer").textContent = formatTime(seconds);
      if (seconds >= 3600 && localRecorder.state === "recording")
        localRecorder.stop();
    }, 250);
  } catch (error) {
    release();
    const messages = {
      NotAllowedError:
        "麦克风权限未开启。请在浏览器地址栏的网站权限中允许使用麦克风，再试一次。",
      NotFoundError: "没有找到麦克风，请连接麦克风，或改用“导入音频”。",
      NotReadableError:
        "无法读取麦克风，可能被其他程序占用。请关闭其他录音程序后重试。",
    };
    showError(
      messages[error.name] || "无法开始录音，请检查麦克风和浏览器设置。",
    );
  } finally {
    microphonePending = false;
    refreshControls();
  }
}

function finishRecording() {
  recording = false;
  $("record-label").textContent = "重新录音";
  $("record-button").classList.remove("recording");
  $("record-visual").classList.remove("is-recording");
  refreshControls();
}

function updateJob(job) {
  $("progress-panel").hidden = false;
  $("progress").value = job.progress || 0;
  $("progress-value").textContent = `${job.progress || 0}%`;
  const stages = {
    queued: "等待处理",
    decoding: "读取音频",
    analyzing: "检测语音",
    loading: "加载本地模型",
    transcribing: "正在识别",
    completed: "转写完成",
    failed: "转写失败",
  };
  $("stage").textContent = stages[job.stage] || "准备中";
  $("transcript").value = job.text || "";
  audioSeconds = job.duration || 0;
  $("audio-duration").textContent = audioSeconds
    ? `音频时长 ${formatTime(audioSeconds)} · 请及时导出`
    : "结果仅在本次程序运行期间保留";
  refreshEditor();
}

async function pollJob(id) {
  pendingJob = id;
  busy = true;
  showError();
  $("result-status").textContent = "正在转写";
  $("result-status").classList.remove("done");
  refreshControls();
  try {
    const job = await api(`/api/transcriptions/${encodeURIComponent(id)}`);
    updateJob(job);
    if (job.state === "completed" || job.state === "failed") {
      pendingJob = null;
      busy = false;
      if (job.state === "failed") {
        $("result-status").textContent = "转写未完成";
        showError(job.error || "转写失败，请检查音频后重试。");
      } else {
        $("result-status").textContent = job.text?.trim()
          ? "转写完成"
          : "未检测到语音";
        $("result-status").classList.add("done");
        if (!job.text?.trim())
          showError("未检测到清晰语音。请试听音频，确认音量合适且包含说话声。");
        else toast("转写完成，可编辑并导出文字");
      }
      refreshControls();
      return;
    }
    setTimeout(() => pollJob(id), 900);
  } catch (error) {
    busy = false;
    const terminal = error.status === 404 || error.status === 403;
    if (terminal) pendingJob = null;
    $("result-status").textContent = terminal ? "任务不可用" : "连接中断";
    showError(
      terminal
        ? "转写任务已失效或无法访问。请刷新页面检查本地程序，或重新选择音频。"
        : error.message,
    );
    refreshControls();
  }
}

async function startTranscription() {
  if (
    !initialized ||
    shuttingDown ||
    closed ||
    busy ||
    recording ||
    microphonePending
  )
    return;
  if (pendingJob) {
    await pollJob(pendingJob);
    return;
  }
  if (!audioFile || !modelReady) return;
  if (
    $("transcript").value.trim() &&
    !confirm(
      "新的转写会替换当前文字。请确认已复制或导出需要保留的内容。继续吗？",
    )
  )
    return;
  showError();
  busy = true;
  $("audio-preview").pause();
  $("result-status").textContent = "正在读取音频";
  refreshControls();
  try {
    const data = new FormData();
    data.append("audio", audioFile, audioFile.name);
    data.append("language", $("language").value);
    const job = await api("/api/transcriptions", {
      method: "POST",
      body: data,
    });
    await pollJob(job.id);
  } catch (error) {
    busy = false;
    $("result-status").textContent = "等待重试";
    showError(error.message);
    refreshControls();
  }
}

$("tab-record").addEventListener("click", () => switchTab("record"));
$("tab-file").addEventListener("click", () => switchTab("file"));
for (const name of ["record", "file"]) {
  $(`tab-${name}`).addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const other = name === "record" ? "file" : "record";
      if (!$(`tab-${other}`).disabled) {
        switchTab(other);
        $(`tab-${other}`).focus();
      }
    }
  });
}
$("audio-file").addEventListener("change", (event) => {
  if (event.target.files.length) selectFile(event.target.files[0]);
  event.target.value = "";
});
$("dropzone").addEventListener("dragover", (event) => {
  event.preventDefault();
  if (!inputsLocked()) $("dropzone").classList.add("dragging");
});
$("dropzone").addEventListener("dragleave", () =>
  $("dropzone").classList.remove("dragging"),
);
$("dropzone").addEventListener("drop", (event) => {
  event.preventDefault();
  $("dropzone").classList.remove("dragging");
  if (inputsLocked()) return;
  if (event.dataTransfer.files.length > 1) {
    showError("一次只能转写一个音频文件，请逐个选择。");
    return;
  }
  if (event.dataTransfer.files.length) selectFile(event.dataTransfer.files[0]);
});
$("record-button").addEventListener("click", toggleRecording);
$("transcribe-button").addEventListener("click", startTranscription);
$("remove-audio").addEventListener("click", () => {
  if (inputsLocked()) return;
  $("audio-preview").pause();
  $("audio-preview").removeAttribute("src");
  $("audio-preview").load();
  if (previewURL) URL.revokeObjectURL(previewURL);
  previewURL = null;
  audioFile = null;
  $("selected-audio").hidden = true;
  showError();
  refreshControls();
});
$("transcript").addEventListener("input", refreshEditor);
$("clear-button").addEventListener("click", () => {
  if (!initialized || busy || pendingJob) return;
  if (!confirm("清空后无法恢复，确定已保存需要的文字吗？")) return;
  $("transcript").value = "";
  $("result-status").textContent = "文字已清空";
  $("result-status").classList.remove("done");
  refreshEditor();
});
$("copy-button").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("transcript").value);
    toast("文字已复制");
  } catch {
    $("transcript").focus();
    $("transcript").select();
    toast("已选中文字，请按 Ctrl+C 复制");
  }
});
$("export-button").addEventListener("click", () => {
  const content = new Blob(
    ["\ufeff", $("transcript").value.replace(/\r?\n/g, "\r\n")],
    { type: "text/plain;charset=utf-8" },
  );
  const url = URL.createObjectURL(content);
  const link = document.createElement("a");
  link.href = url;
  link.download = `听写-${new Date().toISOString().slice(0, 10)}.txt`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  toast("已发起 TXT 下载，请在浏览器下载列表中查看");
});
$("help-button").addEventListener("click", () => $("help-dialog").showModal());
$("close-help").addEventListener("click", () => $("help-dialog").close());
$("exit-button").addEventListener("click", async () => {
  if (inputsLocked()) return;
  if (!confirm("退出后本次文字不会保留。请先导出需要的内容。确定退出吗？"))
    return;
  shuttingDown = true;
  refreshControls();
  try {
    await api("/api/shutdown", { method: "POST" });
    closed = true;
    modelReady = false;
    $("model-status").textContent = "程序已退出，双击 EXE 可再次打开";
    $("model-dot").classList.add("error");
    toast("已退出本地程序，可以关闭此页面");
  } catch (error) {
    showError(error.message);
  } finally {
    shuttingDown = false;
    refreshControls();
  }
});
window.addEventListener("beforeunload", (event) => {
  if (
    recording ||
    microphonePending ||
    busy ||
    pendingJob ||
    $("transcript").value.trim()
  ) {
    event.preventDefault();
    event.returnValue = "";
  }
});

async function initialize() {
  refreshControls();
  try {
    const info = await api("/api/info");
    modelReady = info.model_ready;
    $("model-status").textContent = modelReady
      ? `${info.model} · 离线模型已就绪`
      : "本地模型不完整";
    if (!modelReady) {
      $("model-dot").classList.add("error");
      showError("没有找到完整的离线模型。请完整解压离线包，不要只复制 EXE。");
    }
    if (info.job) {
      if (["queued", "running"].includes(info.job.state)) {
        // pollJob establishes the job lock synchronously, before initialization unlocks.
        const polling = pollJob(info.job.id);
        initialized = true;
        await polling;
        return;
      }
      updateJob(info.job);
      $("result-status").textContent =
        info.job.state === "completed" ? "已恢复本次转写" : "上次转写未完成";
      if (info.job.state === "failed") showError(info.job.error);
    }
    initialized = true;
  } catch (error) {
    $("model-status").textContent = "本地程序连接失败";
    $("model-dot").classList.add("error");
    showError(error.message);
  } finally {
    refreshControls();
  }
}
initialize();
