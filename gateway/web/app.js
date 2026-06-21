const state = {
  samples: [],
  markers: [],
  chartMarks: [],
  latest: null,
  running: false,
  status: "idle",
  currentLabel: "",
  chartWindow: 40,
  maxChartSamples: 2600,
  firstDeviceMs: null,
  batteryStartMv: null,
  batteryLastMv: null,
  prediction: null,
  processRunning: false,
  deviceBusy: false,
};

const els = {
  catId: document.getElementById("catId"),
  rate: document.getElementById("rate"),
  device: document.getElementById("device"),
  saveMode: document.getElementById("saveMode"),
  startBtn: document.getElementById("startBtn"),
  stopBtn: document.getElementById("stopBtn"),
  behaviorButtons: document.querySelectorAll("[data-label]"),
  cancelLabelBtn: document.getElementById("cancelLabelBtn"),
  currentLabel: document.getElementById("currentLabel"),
  statusDot: document.getElementById("statusDot"),
  statusText: document.getElementById("statusText"),
  samples: document.getElementById("samples"),
  duration: document.getElementById("duration"),
  observedRate: document.getElementById("observedRate"),
  battery: document.getElementById("battery"),
  predictionLabel: document.getElementById("predictionLabel"),
  predictionScore: document.getElementById("predictionScore"),
  predictionTop: document.getElementById("predictionTop"),
  outputPath: document.getElementById("outputPath"),
  markerList: document.getElementById("markerList"),
  logs: document.getElementById("logs"),
  chart: document.getElementById("chart"),
  deviceButtons: document.querySelectorAll("[data-device-action]"),
  deviceStatus: document.getElementById("deviceStatus"),
  deviceOutput: document.getElementById("deviceOutput"),
  deviceProgress: document.getElementById("deviceProgress"),
  deviceProgressTitle: document.getElementById("deviceProgressTitle"),
  deviceProgressPercent: document.getElementById("deviceProgressPercent"),
  deviceProgressFill: document.getElementById("deviceProgressFill"),
  deviceProgressMessage: document.getElementById("deviceProgressMessage"),
  firmwareDownload: document.getElementById("firmwareDownload"),
  firmwareInfo: document.getElementById("firmwareInfo"),
  processButtons: document.querySelectorAll("[data-process]"),
  processStatus: document.getElementById("processStatus"),
  processOutput: document.getElementById("processOutput"),
};

const labelNames = {
  rest: "休息",
  parkour: "跑酷",
  walk: "走动",
  play: "玩耍",
  groom: "舔毛",
  eat: "进食",
};

function addLog(message) {
  const line = document.createElement("div");
  line.className = "log-line";
  line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
  els.logs.prepend(line);
  while (els.logs.children.length > 120) els.logs.lastChild.remove();
}

async function postJson(url, payload = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function applyState(next) {
  state.running = Boolean(next.running);
  state.status = next.status || "idle";
  if (typeof next.processing === "boolean") state.processRunning = next.processing;
  if (typeof next.device_busy === "boolean") state.deviceBusy = next.device_busy;
  els.statusText.textContent = state.status;
  els.statusDot.className = "status-dot";
  if (state.status === "recording") els.statusDot.classList.add("recording");
  if (state.status === "error") els.statusDot.classList.add("error");

  els.samples.textContent = String(next.samples || 0);
  els.duration.textContent = `${(next.duration_s || 0).toFixed(1)}s`;
  els.observedRate.textContent = `${(next.observed_rate_hz || 0).toFixed(1)}Hz`;
  renderBattery(next.battery_mv);
  els.outputPath.textContent = next.output_path || "未开始采集";
  if (!state.running && next.save_mode) els.saveMode.value = next.save_mode;
  state.currentLabel = next.current_label || next.label || "";
  renderCurrentLabel(state.currentLabel);

  els.startBtn.disabled = state.running || state.processRunning || state.deviceBusy;
  els.stopBtn.disabled = !state.running;
  els.saveMode.disabled = state.running || state.processRunning || state.deviceBusy;
  updateBehaviorButtons(state.currentLabel);
  updateDeviceButtons();
  updateProcessButtons();

  if (Array.isArray(next.markers)) {
    state.markers = next.markers;
    renderMarkers();
  }

  if (next.prediction) renderPrediction(next.prediction);
}

function renderMarkers() {
  els.markerList.innerHTML = "";
  const items = [...state.markers].reverse();
  for (const item of items.slice(0, 12)) {
    const div = document.createElement("div");
    div.className = "marker-item";
    const title = labelEventTitle(item);
    div.innerHTML = `<strong>${escapeHtml(title)}</strong><br>${escapeHtml(item.marker_time_iso || "")}`;
    els.markerList.appendChild(div);
  }
}

function labelEventTitle(item) {
  if (item.action === "label_start") return `开始 ${labelDisplayName(item.label || "")}`;
  if (item.action === "label_end") return "结束标记";
  return item.marker || "mark";
}

function renderCurrentLabel(label) {
  els.currentLabel.textContent = label ? labelDisplayName(label) : "未标记";
  els.currentLabel.className = label ? "active-label" : "";
}

function updateBehaviorButtons(activeLabel) {
  els.behaviorButtons.forEach((button) => {
    const isActive = Boolean(activeLabel) && button.dataset.label === activeLabel;
    button.disabled = !state.running;
    button.classList.toggle("active", isActive);
    button.classList.toggle("primary", isActive);
  });
  updateCancelLabelButton(activeLabel);
}

function updateCancelLabelButton(activeLabel = state.currentLabel) {
  els.cancelLabelBtn.disabled = !state.running || !activeLabel;
}

function renderPrediction(prediction) {
  state.prediction = prediction;
  els.predictionTop.innerHTML = "";
  const currentBox = els.predictionLabel.closest(".prediction-current");
  currentBox.className = "prediction-current";

  if (!prediction || !prediction.enabled) {
    els.predictionLabel.textContent = "未启用";
    els.predictionScore.textContent = prediction?.message || "未加载模型";
    return;
  }

  if (!prediction.ready) {
    els.predictionLabel.textContent = "未就绪";
    els.predictionScore.textContent = prediction.message || "等待窗口数据";
    return;
  }

  if (prediction.stability) currentBox.classList.add(`prediction-${prediction.stability}`);
  els.predictionLabel.textContent = prediction.label_zh || labelDisplayName(prediction.label || "");
  const stability = prediction.stability_zh || "观察中";
  const stableScore = Math.round((prediction.confidence || 0) * 100);
  const rawLabel = prediction.raw_label && prediction.raw_label !== prediction.label
    ? ` · 原始 ${labelDisplayName(prediction.raw_label)}`
    : "";
  els.predictionScore.textContent = `${stability} · 稳定度 ${stableScore}% · ${Number(prediction.window_s || 0).toFixed(1)}s${rawLabel}`;

  const topItems = Array.isArray(prediction.top)
    ? prediction.top.filter((item) => !item.label || Object.prototype.hasOwnProperty.call(labelNames, item.label))
    : [];
  for (const item of topItems) {
    const row = document.createElement("div");
    row.className = "prediction-row";
    const score = Math.max(0, Math.min(1, Number(item.score || 0)));
    row.innerHTML = `
      <span>${escapeHtml(item.label_zh || labelDisplayName(item.label || ""))}</span>
      <span class="prediction-bar"><span class="prediction-fill" style="width:${score * 100}%"></span></span>
      <span>${Math.round(score * 100)}%</span>
    `;
    els.predictionTop.appendChild(row);
  }
}

function updateProcessButtons() {
  els.processButtons.forEach((button) => {
    button.disabled = state.running || state.processRunning || state.deviceBusy;
  });
}

function updateDeviceButtons() {
  els.deviceButtons.forEach((button) => {
    button.disabled = state.running || state.processRunning || state.deviceBusy;
  });
}

function renderProcessResult(result) {
  state.processRunning = false;
  updateProcessButtons();
  updateDeviceButtons();
  const status = result.ok ? "完成" : "失败";
  els.processStatus.textContent = `${status} · ${new Date().toLocaleTimeString()}`;

  const lines = [];
  if (Array.isArray(result.summary) && result.summary.length) {
    lines.push({ text: "摘要", important: false });
    for (const line of result.summary) {
      lines.push({ text: line, important: isImportantProcessLine(line) });
    }
    lines.push({ text: "", important: false });
  }

  for (const step of result.results || []) {
    lines.push({ text: `== ${step.title} (${step.script}) ==`, important: false });
    lines.push({
      text: `returncode=${step.returncode} duration=${Number(step.duration_s || 0).toFixed(2)}s`,
      important: Number(step.returncode) !== 0,
    });
    if (step.stdout) {
      lines.push({ text: "", important: false });
      lines.push({ text: step.stdout, important: false });
    }
    if (step.stderr) {
      lines.push({ text: "", important: false });
      lines.push({ text: "stderr:", important: true });
      lines.push({ text: step.stderr, important: true });
    }
    lines.push({ text: "", important: false });
  }

  const body = lines.map(renderProcessLine).join("\n").trim();
  els.processOutput.innerHTML = body || "没有输出。";
}

function isImportantProcessLine(line) {
  return [
    "准确率",
    "解析错误",
    "时间间隔异常",
    "序号跳变",
    "待补采",
    "失败",
  ].some((keyword) => String(line).includes(keyword));
}

function renderProcessLine(line) {
  const text = escapeHtml(line.text);
  if (!line.important) return text;
  return `<span class="process-key">${text}</span>`;
}

function renderDeviceResult(result) {
  state.deviceBusy = false;
  updateDeviceButtons();
  updateProcessButtons();
  const isOtaWaiting = result.ok && result.action === "ota";
  const isFlash = ["flash", "flash_fast", "flash_safe"].includes(result.action);
  const isDfuReboot = result.action === "reboot_dfu";
  const status = isOtaWaiting ? "等待刷写" : (result.ok ? "完成" : "失败");
  els.deviceStatus.textContent = `${status} · ${deviceActionName(result.action)} · ${new Date().toLocaleTimeString()}`;
  renderDeviceProgress({
    action: result.action,
    percent: 100,
    message: isOtaWaiting
      ? "开发板闪灯时是 OTA/bootloader 等待状态"
      : (result.ok
        ? (isFlash || isDfuReboot ? "已确认设备重新广播" : "设备操作完成")
        : (result.error || "设备操作失败")),
    state: isOtaWaiting ? "waiting" : (result.ok ? "done" : "error"),
  });

  const lines = [];
  if (Array.isArray(result.summary) && result.summary.length) {
    lines.push({ text: "摘要", important: false });
    for (const line of result.summary) {
      lines.push({ text: line, important: isImportantDeviceLine(line) });
    }
    lines.push({ text: "", important: false });
  }

  if (result.error) {
    lines.push({ text: `错误：${result.error}`, important: true });
    lines.push({ text: "", important: false });
  }

  if (Array.isArray(result.lines) && result.lines.length) {
    lines.push({ text: "设备原始返回", important: false });
    for (const line of result.lines) {
      lines.push({ text: line, important: line.startsWith("ERR") });
    }
  }

  const body = lines.map(renderDeviceLine).join("\n").trim();
  els.deviceOutput.innerHTML = body || "没有输出。";
}

function isImportantDeviceLine(line) {
  return [
    "失败",
    "错误",
    "注意",
    "OTA",
    "DFU",
    "固件",
    "模式",
    "电池",
    "发射功率",
    "缓存",
    "保存文件",
    "丢弃",
  ].some((keyword) => String(line).includes(keyword));
}

function renderDeviceLine(line) {
  const text = escapeHtml(line.text);
  if (!line.important) return text;
  return `<span class="device-key">${text}</span>`;
}

function renderDeviceProgress(progress) {
  if (!els.deviceProgress) return;
  const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)));
  els.deviceProgress.classList.remove("hidden", "error", "done");
  els.deviceProgress.classList.remove("waiting");
  if (progress.state === "error") els.deviceProgress.classList.add("error");
  if (progress.state === "done") els.deviceProgress.classList.add("done");
  if (progress.state === "waiting") els.deviceProgress.classList.add("waiting");
  els.deviceProgressTitle.textContent = progress.action_zh || deviceActionName(progress.action);
  els.deviceProgressPercent.textContent = `${Math.round(percent)}%`;
  els.deviceProgressFill.style.width = `${percent}%`;
  els.deviceProgressMessage.textContent = progress.message || "处理中";
}

async function runDeviceAction(action) {
  if (action === "clear") {
    const confirmed = window.confirm("确定清空设备本地缓存？请先确认已经拉取并保存。");
    if (!confirmed) return;
  }
  if (action === "ota") {
    const confirmed = window.confirm("进入 OTA 后设备会断开当前连接，并等待固件刷写。确定继续？");
    if (!confirmed) return;
  }
  if (action === "flash" || action === "flash_fast" || action === "flash_safe") {
    const mode = action === "flash_fast" ? "快速模式" : (action === "flash_safe" ? "慢速可靠模式，耗时更久" : "推荐模式");
    const confirmed = window.confirm(`将由电脑通过 BLE 直接刷写 firmware.zip（${mode}）。过程中不要断电，也不要关闭网页服务。确定继续？`);
    if (!confirmed) return;
  }
  if (action === "reboot_dfu") {
    const confirmed = window.confirm("只在设备已经停留在 DFU/bootloader 时使用。后端会发送重启命令并等待 CatSense-V0 重新广播。确定继续？");
    if (!confirmed) return;
  }

  state.deviceBusy = true;
  updateDeviceButtons();
  updateProcessButtons();
  const label = deviceActionName(action);
  els.deviceStatus.textContent = `运行中：${label}`;
  els.deviceOutput.textContent = "连接设备中...";
  renderDeviceProgress({ action, action_zh: label, percent: 1, message: "准备连接设备", state: "running" });
  addLog(`设备操作开始：${label}`);

  try {
    const result = await postJson("/api/device", {
      action,
      cat_id: els.catId.value,
      device: els.device.value,
      scan_timeout: 30,
      connect_retries: 2,
    });
    renderDeviceResult(result);
    addLog(`设备操作${result.ok ? "完成" : "失败"}：${label}`);
    const stateRes = await fetch("/api/state");
    applyState(await stateRes.json());
  } catch (err) {
    renderDeviceResult({
      action,
      ok: false,
      summary: [`失败：${err.message}`],
      lines: [],
      samples: 0,
      output_path: "",
      error: err.message,
    });
    addLog(`Error: ${err.message}`);
  } finally {
    state.deviceBusy = false;
    updateDeviceButtons();
    updateProcessButtons();
  }
}

function deviceActionName(action) {
  return {
    status: "读取状态",
    collect: "采集模式",
    daily: "日常模式",
    ota: "进入 OTA",
    flash: "刷写固件",
    flash_fast: "快速刷写",
    flash_safe: "慢速刷写",
    reboot_dfu: "重启 DFU",
    upload: "拉取缓存",
    clear: "清空缓存",
  }[action] || action || "设备操作";
}

async function loadFirmwareInfo() {
  if (!els.firmwareDownload) return;
  try {
    const res = await fetch("/api/firmware");
    const info = await res.json();
    if (!info.exists) {
      els.firmwareDownload.classList.add("disabled");
      els.firmwareDownload.removeAttribute("href");
      els.firmwareDownload.setAttribute("aria-disabled", "true");
      els.firmwareDownload.title = "未找到 firmware.zip，请先编译固件";
      if (els.firmwareInfo) els.firmwareInfo.textContent = "未找到 firmware.zip，请先编译固件。";
      return;
    }

    const sizeKb = Math.round(Number(info.size_bytes || 0) / 1024);
    els.firmwareDownload.classList.remove("disabled");
    els.firmwareDownload.href = "/firmware/latest.zip";
    els.firmwareDownload.removeAttribute("aria-disabled");
    els.firmwareDownload.title = `固件包 ${sizeKb}KB · ${info.modified_iso || ""}`;
    if (els.firmwareInfo) els.firmwareInfo.textContent = `固件包 ${sizeKb}KB · ${info.modified_iso || ""}`;
  } catch (err) {
    els.firmwareDownload.classList.add("disabled");
    els.firmwareDownload.removeAttribute("href");
    els.firmwareDownload.setAttribute("aria-disabled", "true");
    els.firmwareDownload.title = "无法读取固件包信息";
    if (els.firmwareInfo) els.firmwareInfo.textContent = "无法读取固件包信息。";
  }
}

async function runProcess(action) {
  state.processRunning = true;
  updateProcessButtons();
  updateDeviceButtons();
  const label = processActionName(action);
  els.processStatus.textContent = `运行中：${label}`;
  els.processOutput.textContent = "处理中...";
  addLog(`数据处理开始：${label}`);

  try {
    const result = await postJson("/api/process", { action });
    renderProcessResult(result);
    addLog(`数据处理${result.ok ? "完成" : "失败"}：${label}`);
    const stateRes = await fetch("/api/state");
    applyState(await stateRes.json());
  } finally {
    state.processRunning = false;
    updateProcessButtons();
    updateDeviceButtons();
  }
}

function processActionName(action) {
  return {
    report: "检查数据",
    build: "构建数据",
    train: "训练模型",
    evaluate: "Session 评估",
    all: "一键全部",
  }[action] || action;
}

function labelDisplayName(label) {
  return labelNames[label] || label;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#039;",
  }[ch]));
}

function resetChart() {
  state.samples = [];
  state.markers = [];
  state.chartMarks = [];
  state.latest = null;
  state.currentLabel = "";
  state.firstDeviceMs = null;
  state.batteryStartMv = null;
  state.batteryLastMv = null;
  state.prediction = null;
  renderBattery(null);
  renderPrediction({ enabled: true, ready: false, message: "等待窗口数据", top: [] });
  renderCurrentLabel("");
  updateBehaviorButtons("");
}

function addSample(sample) {
  if (state.firstDeviceMs === null) state.firstDeviceMs = sample.device_ms;
  sample.elapsed_s = Math.max(0, (sample.device_ms - state.firstDeviceMs) / 1000);
  state.samples.push(sample);
  if (sample.marker) {
    const mark = {
      marker: sample.marker,
      marker_time_iso: sample.marker_time_iso,
      label: sample.label || "",
      elapsed_s: sample.elapsed_s,
    };
    state.chartMarks.push(mark);
  }
  const overflow = state.samples.length - state.maxChartSamples;
  if (overflow > 0) state.samples.splice(0, overflow);
  state.latest = sample;
  state.currentLabel = sample.label || "";
  renderBattery(sample.battery_mv);
  renderCurrentLabel(state.currentLabel);

  const minMarkT = Math.max(0, sample.elapsed_s - state.chartWindow);
  while (state.chartMarks.length && state.chartMarks[0].elapsed_s < minMarkT) {
    state.chartMarks.shift();
  }
}

function renderBattery(mv) {
  if (!mv || mv <= 0) {
    els.battery.textContent = "--";
    return;
  }

  if (state.batteryStartMv === null) state.batteryStartMv = mv;
  state.batteryLastMv = mv;

  const delta = mv - state.batteryStartMv;
  const deltaText = delta === 0 ? "" : ` · ${delta > 0 ? "+" : ""}${delta}mV`;
  els.battery.textContent = `${mv}mV · ~${estimateBatteryPercent(mv)}%${deltaText}`;
}

function estimateBatteryPercent(mv) {
  const curve = [
    [3200, 0],
    [3500, 10],
    [3700, 30],
    [3800, 50],
    [3900, 68],
    [4000, 80],
    [4100, 92],
    [4200, 100],
  ];

  if (mv <= curve[0][0]) return curve[0][1];
  for (let i = 1; i < curve.length; i += 1) {
    const [hiMv, hiPct] = curve[i];
    const [loMv, loPct] = curve[i - 1];
    if (mv <= hiMv) {
      const ratio = (mv - loMv) / (hiMv - loMv);
      return Math.round(loPct + ratio * (hiPct - loPct));
    }
  }
  return 100;
}

let lastChartDrawMs = 0;

function drawChart(timestamp = 0) {
  if (timestamp - lastChartDrawMs < 50) {
    requestAnimationFrame(drawChart);
    return;
  }
  lastChartDrawMs = timestamp;

  const canvas = els.chart;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = Math.floor(rect.width * dpr);
  const height = Math.floor(rect.height * dpr);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const pad = { left: 48, right: 14, top: 16, bottom: 28 };
  const plotW = rect.width - pad.left - pad.right;
  const plotH = rect.height - pad.top - pad.bottom;

  ctx.fillStyle = "#fbfcfd";
  ctx.fillRect(0, 0, rect.width, rect.height);

  const latestT = state.samples.at(-1)?.elapsed_s ?? state.chartWindow;
  const minT = Math.max(0, latestT - state.chartWindow);
  let firstVisible = 0;
  while (firstVisible < state.samples.length && state.samples[firstVisible].elapsed_s < minT) {
    firstVisible += 1;
  }
  const visible = state.samples.slice(firstVisible);
  const maxAbs = Math.max(1200, ...visible.flatMap((s) => [Math.abs(s.ax_mg), Math.abs(s.ay_mg), Math.abs(s.az_mg)]));
  const yLimit = Math.min(8000, Math.ceil(maxAbs / 500) * 500);

  function xOf(t) {
    return pad.left + ((t - minT) / Math.max(1, state.chartWindow)) * plotW;
  }
  function yOf(v) {
    return pad.top + ((yLimit - v) / (2 * yLimit)) * plotH;
  }

  ctx.strokeStyle = "#d9e0e4";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (plotH * i) / 4;
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + plotW, y);
  }
  for (let i = 0; i <= 4; i += 1) {
    const x = pad.left + (plotW * i) / 4;
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + plotH);
  }
  ctx.stroke();

  ctx.strokeStyle = "#9aa8af";
  ctx.beginPath();
  ctx.moveTo(pad.left, yOf(0));
  ctx.lineTo(pad.left + plotW, yOf(0));
  ctx.stroke();

  ctx.fillStyle = "#64727a";
  ctx.font = "12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillText(`${yLimit}`, 8, yOf(yLimit) + 4);
  ctx.fillText("0", 28, yOf(0) + 4);
  ctx.fillText(`${-yLimit}`, 4, yOf(-yLimit) + 4);
  ctx.fillText(`${Math.round(minT)}s`, pad.left, rect.height - 8);
  ctx.fillText(`${Math.round(latestT)}s`, pad.left + plotW - 34, rect.height - 8);

  for (const mark of state.chartMarks) {
    if (typeof mark.elapsed_s !== "number") continue;
    if (mark.elapsed_s < minT) continue;
    const x = xOf(mark.elapsed_s);
    ctx.strokeStyle = "rgba(11,111,133,0.45)";
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + plotH);
    ctx.stroke();
  }

  drawLine(ctx, visible, "ax_mg", "#c33d3d", xOf, yOf);
  drawLine(ctx, visible, "ay_mg", "#2267b8", xOf, yOf);
  drawLine(ctx, visible, "az_mg", "#2f8f46", xOf, yOf);

  requestAnimationFrame(drawChart);
}

function drawLine(ctx, samples, field, color, xOf, yOf) {
  if (samples.length < 2) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  samples.forEach((s, idx) => {
    const x = xOf(s.elapsed_s);
    const y = yOf(s[field]);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

async function startRecording() {
  resetChart();
  addLog("Start requested.");
  await postJson("/api/start", {
    cat_id: els.catId.value,
    rate: Number(els.rate.value),
    device: els.device.value,
    save_mode: els.saveMode.value,
    connect_retries: 5,
  });
}

async function stopRecording() {
  addLog("Stop requested.");
  await postJson("/api/stop");
}

async function setBehaviorLabel(label) {
  const item = await postJson("/api/label", { label });
  state.currentLabel = item.label || "";
  renderCurrentLabel(state.currentLabel);
  updateBehaviorButtons(state.currentLabel);
  addLog(label ? `开始标记：${labelDisplayName(label)}` : "结束标记。");
  return item;
}

async function toggleBehaviorLabel(label) {
  if (state.currentLabel === label) {
    await setBehaviorLabel("");
    return;
  }
  await setBehaviorLabel(label);
}

async function cancelBehaviorLabel() {
  if (!state.currentLabel) return;
  await setBehaviorLabel("");
}

function connectEvents() {
  const events = new EventSource("/events");
  events.addEventListener("state", (event) => applyState(JSON.parse(event.data)));
  events.addEventListener("sample", (event) => addSample(JSON.parse(event.data)));
  events.addEventListener("prediction", (event) => renderPrediction(JSON.parse(event.data)));
  events.addEventListener("process", (event) => renderProcessResult(JSON.parse(event.data)));
  events.addEventListener("device", (event) => renderDeviceResult(JSON.parse(event.data)));
  events.addEventListener("device_progress", (event) => renderDeviceProgress(JSON.parse(event.data)));
  events.addEventListener("mark", (event) => {
    const item = JSON.parse(event.data);
    addLog(`Marker queued: ${item.marker}`);
  });
  events.addEventListener("log", (event) => addLog(JSON.parse(event.data).message));
  events.addEventListener("warning", (event) => addLog(`Warning: ${JSON.parse(event.data).message}`));
  events.addEventListener("error", (event) => addLog(`Error: ${JSON.parse(event.data).message}`));
  events.onerror = () => addLog("Event stream reconnecting...");
}

els.startBtn.addEventListener("click", () => startRecording().catch((err) => addLog(`Error: ${err.message}`)));
els.stopBtn.addEventListener("click", () => stopRecording().catch((err) => addLog(`Error: ${err.message}`)));
els.behaviorButtons.forEach((button) => {
  button.addEventListener("click", () => toggleBehaviorLabel(button.dataset.label).catch((err) => addLog(`Error: ${err.message}`)));
});
els.cancelLabelBtn.addEventListener("click", () => cancelBehaviorLabel().catch((err) => addLog(`Error: ${err.message}`)));
if (els.firmwareDownload) {
  els.firmwareDownload.addEventListener("click", (event) => {
    if (els.firmwareDownload.classList.contains("disabled") || !els.firmwareDownload.getAttribute("href")) {
      event.preventDefault();
    }
  });
}
els.deviceButtons.forEach((button) => {
  button.addEventListener("click", () => {
    runDeviceAction(button.dataset.deviceAction).catch((err) => {
      renderDeviceResult({
        action: button.dataset.deviceAction,
        ok: false,
        summary: [`失败：${err.message}`],
        lines: [],
        samples: 0,
        output_path: "",
        error: err.message,
      });
      addLog(`Error: ${err.message}`);
    });
  });
});
els.processButtons.forEach((button) => {
  button.addEventListener("click", () => {
    runProcess(button.dataset.process).catch((err) => {
      els.processStatus.textContent = "失败";
      els.processOutput.textContent = err.message;
      addLog(`Error: ${err.message}`);
    });
  });
});

fetch("/api/state").then((res) => res.json()).then(applyState).catch(() => {});
loadFirmwareInfo();
connectEvents();
drawChart();
