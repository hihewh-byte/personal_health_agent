window.pdfParsing = false;
(function () {
  var COLORS = { steps: '#2ecc71', hrv: '#3498db', sleep: '#9b59b6', rhr: '#e67e22' };
  var chat = document.getElementById('chat-stream');
  var chatStatusBar = document.getElementById('chat-status-bar');
  var chatStatusText = document.getElementById('chat-status-text');
  var phaBuild = document.getElementById('pha-build');
  var modelSelect = document.getElementById('model-select');
  var modelHint = document.getElementById('model-hint');
  var sendBtn = document.getElementById('send');
  var q = document.getElementById('q');
  var userIdInput = document.getElementById('user-id');
  var trendsPre = document.getElementById('trends-pre');
  var refreshTrends = document.getElementById('refresh-trends');
  var trendsEmpty = document.getElementById('trends-empty');
  var dynamicChartsGrid = document.getElementById('dynamic-charts-grid');
  var metricTrendPicker = document.getElementById('metric-trend-picker');
  var metricCatalog = [];
  var metricsPayload = null;
  var selectedMetricIds = new Set(['steps', 'rhr', 'activity_kcal']);
  var DEFAULT_METRIC_PICKS = ['steps', 'rhr', 'activity_kcal'];
  var CHART_MAX_RAW_POINTS = 800;
  var CHART_TARGET_POINTS = 300;
  var ALERTS_CACHE_KEY = 'pha_v213_alerts_cache_v1';
  var goldenTagsEl = document.getElementById('golden-metric-tags');
  var groupedMetricsEl = document.getElementById('grouped-metrics-list');
  var metricSearchBar = document.getElementById('metric-search-bar');
  var moreMetricsSummary = document.getElementById('more-metrics-summary');
  var aiDoctorBtn = document.getElementById('ai-doctor-review-btn');
  var DYNAMIC_CHART_COLORS = [
    '#2ecc71', '#3498db', '#9b59b6', '#e67e22', '#1abc9c', '#e74c3c',
    '#f39c12', '#16a085', '#8e44ad', '#2980b9', '#d35400', '#27ae60'
  ];
  window.phaCharts = window.phaCharts || {};
  var zipFiles = [];
  var pdfFiles = [];
  var connBadge = document.getElementById('conn-badge');
  var dbBadge = document.getElementById('db-badge');
  var dbStatusText = document.getElementById('db-status-text');
  var PDF_MODEL_OVERRIDE_KEY = 'pha_pdf_model_override_v214';
  var pdfModelOverrideSelect = document.getElementById('pdf-model-override-selector');
  var dataDrawerCheckbox = document.getElementById('data-drawer');
  var visionState = { vision_available: false, medical_text_available: false };
  var activeModelLabel = document.getElementById('active-model-label');
  var parseToast = document.getElementById('parse-toast');
  var parseToastText = document.getElementById('parse-toast-text');
  var chatAttachFile = document.getElementById('chat-attach-file');
  var chatAttachLabel = document.getElementById('chat-attach-label');
  var pendingChatAttachment = null;
  var pendingAttachMeta = null;
  var pendingAttachBundle = null;
  var attachParseInFlight = false;
  var lastChatIngestPayload = null;
  var lastChatUserMessageId = null;
  var pinnedTemporalStatus = '';
  var auditPanelShownThisTurn = false;

  if (typeof marked !== 'undefined') {
    marked.setOptions({ breaks: true, gfm: true });
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function renderMarkdown(text) {
    if (typeof marked !== 'undefined') return marked.parse(text || '');
    return '<p>' + esc(text) + '</p>';
  }

  function showChatStatus(msg, opts) {
    if (!chatStatusBar || !chatStatusText) return;
    var text = (msg || '').trim() || '处理中…';
    chatStatusBar.classList.remove('hidden');
    chatStatusText.textContent = text;
    if (opts && opts.pin) pinnedTemporalStatus = text;
    if (chat) chat.scrollTop = chat.scrollHeight;
  }
  function hideChatStatus() {
    if (chatStatusBar) chatStatusBar.classList.add('hidden');
  }

  function handleChatSseEvent(ev) {
    if (!ev) return;
    var typ = String(ev.event || ev.type || '').toLowerCase();
    if (!typ && ev.message && !ev.delta && !ev.answer) typ = 'status';
      if (typ === 'status' || typ === 'info') {
        var m = ev.message || ev.status || ev.info || '';
        if (ev.code === 'background_too_long') {
          showToast(m || '生活背景内容过长，已跳过落库。', 'error');
        }
      if (/已合并|定账\s+\d+\s+行/.test(m)) {
        showToast(m, 'success');
      }
      if (ev.is_temporal_dynamic || ev.slow_path_stage || /勾兑|时间轴|动态提取|深度审阅|WASO|SQLite/.test(m)) {
        showChatStatus(m, { pin: true });
      } else if (pinnedTemporalStatus) {
        showChatStatus(pinnedTemporalStatus);
      } else {
        showChatStatus(m);
      }
      if (ev.open_data_drawer && dataDrawerCheckbox) dataDrawerCheckbox.checked = true;
      if (ev.session_id) currentChatSessionId = ev.session_id;
      return;
    }
    if (typ === 'delta') {
      if (pinnedTemporalStatus) showChatStatus(pinnedTemporalStatus);
      appendStreamingAssistantDelta(ev.delta || '');
      return;
    }
    if (typ === 'audit') {
      if (!auditPanelShownThisTurn) {
        appendDataPipelineAuditPanel(ev.data_pipeline_audit || ev, ev.warning_banner || ev.markdown);
        auditPanelShownThisTurn = true;
      }
      return;
    }
    if (typ === 'attach_error') {
      showChatStatus('📎 附件解析失败：' + (ev.message || ev.code || 'unknown'), { pin: true });
      loadHealthAssets();
      return;
    }
    if (typ === 'done') {
      pinnedTemporalStatus = '';
      hideChatStatus();
      if (ev.session_id) currentChatSessionId = ev.session_id;
      var ans = ev.answer || {};
      var ingestOptsDone = null;
      if (ev.ingest_payload && ev.user_message_id) {
        ingestOptsDone = {
          ingest_payload: ev.ingest_payload,
          user_message_id: ev.user_message_id,
          ingest_status: ev.ingest_status || '',
          ingest_metrics_stored: ev.ingest_metrics_stored
        };
      }
      if (streamingAssistantBubble) {
        finalizeStreamingAssistantBubble(
          ans.answer_text || streamingMarkdownBuf,
          ans.evidence_items,
          ans.model_reply_raw || streamingMarkdownBuf,
          ingestOptsDone
        );
      } else {
        appendAssistantWithEvidence(
          ans.answer_text || streamingMarkdownBuf,
          ans.evidence_items,
          ans.model_reply_raw || streamingMarkdownBuf,
          ingestOptsDone
        );
      }
      if (ev.data_pipeline_audit && !auditPanelShownThisTurn) {
        appendDataPipelineAuditPanel(ev.data_pipeline_audit);
        auditPanelShownThisTurn = true;
      }
      streamingAssistantBubble = null;
      streamingMarkdownBuf = '';
      loadChatSessions();
      loadTrends();
      loadHealthAssets();
      return;
    }
    if (typ === 'error') {
      throw new Error(ev.message || '对话失败');
    }
  }

  function appendDataPipelineAuditPanel(audit, fallbackMarkdown) {
    var md = (audit && audit.markdown) || fallbackMarkdown || '';
    if (!md) return;
    var warn = (audit && audit.warning_banner) || '';
    var inner = (warn ? '<p class="pha-audit-warn">' + esc(warn) + '</p>' : '') + renderMarkdown(md);
    if (!chat) return;
    var row = document.createElement('div');
    row.className = 'pha-chat-row pha-chat-row--assistant';
    var shell = document.createElement('div');
    shell.className = 'pha-chat-audit-wrap';
    shell.innerHTML = '<div class="pha-audit-panel"><strong>🔬 数据流水线审计</strong>' + inner + '</div>';
    row.appendChild(shell);
    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
  }

  function appendChat(html, role) {
    if (!chat) return null;
    var isUser = role === 'user';
    var wrap = document.createElement('div');
    wrap.className = 'pha-chat-row ' + (isUser ? 'pha-chat-row--user' : 'pha-chat-row--assistant');
    var bubble = document.createElement('div');
    bubble.className = 'pha-chat-bubble ' + (isUser ? 'pha-chat-bubble--user' : 'pha-chat-bubble--assistant');
    if (isUser) {
      bubble.textContent = html;
    } else {
      bubble.classList.add('prose-pha');
      bubble.innerHTML = html;
    }
    wrap.appendChild(bubble);
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return wrap;
  }

  /** Post-audit answer_text is authoritative; model_reply_raw only for 【依据索引】 parse. */
  function resolveAssistantBubble(text, raw) {
    var body = String(text || '').trim();
    var verbatim = String(raw || '').trim();
    var parsed = parseEvidence(verbatim || body);
    return { display: body || parsed.display || verbatim, ids: parsed.ids };
  }

  function finalizeStreamingAssistantBubble(text, items, raw, ingestOpts) {
    if (!streamingAssistantBubble) return;
    var resolved = resolveAssistantBubble(text, raw);
    var bubble = streamingAssistantBubble.querySelector('.pha-chat-bubble');
    if (bubble) bubble.innerHTML = renderMarkdown(resolved.display || '');
    if (shouldShowIngestConfirm(ingestOpts)) {
      attachIngestButton(streamingAssistantBubble, ingestOpts.ingest_payload, ingestOpts.user_message_id);
    }
    if (resolved.ids.length && items && items.length && bubble) {
      var pills = document.createElement('div');
      pills.className = 'mt-2 flex flex-wrap gap-1';
      var map = {};
      items.forEach(function (it) { if (it.ref_id) map[it.ref_id] = it.title || it.ref_id; });
      resolved.ids.forEach(function (id) {
        var b = document.createElement('button');
        b.className = 'rounded border border-gray-600 px-2 py-0.5 text-xs text-slate-300 hover:border-blue-500/50';
        b.textContent = id;
        b.title = map[id] || id;
        pills.appendChild(b);
      });
      bubble.appendChild(pills);
    }
    if (chat) chat.scrollTop = chat.scrollHeight;
  }

  function appendError(res, detail) {
    var html = '<div class="text-red-400 font-semibold">请求失败</div><div class="text-sm text-slate-400">HTTP ' + esc(res.status) + '</div><pre class="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded border border-gray-700 bg-black/30 p-2 text-xs">' + esc(detail) + '</pre>';
    appendChat(html, 'assistant');
  }

  function errorDetailMessage(detail) {
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object') {
      return detail.message || JSON.stringify(detail);
    }
    return String(detail);
  }

  async function readHttpErrorDetail(res) {
    var detail = res.statusText || ('HTTP ' + res.status);
    var detailObj = null;
    try {
      var ct = (res.headers && res.headers.get('content-type')) || '';
      if (ct.indexOf('application/json') !== -1) {
        var j = await res.json();
        if (typeof j.detail === 'string') detail = j.detail;
        else if (j.detail && typeof j.detail === 'object') {
          detailObj = j.detail;
          detail = errorDetailMessage(j.detail);
        } else if (j.detail) detail = JSON.stringify(j.detail);
      } else {
        var t = await res.text();
        if (t) detail = t;
      }
    } catch (e) { detail += ' | ' + e; }
    return { status: res.status, detail: detail, detailObj: detailObj };
  }

  function selectDefaultModel(models) {
    if (!models || !models.length || !modelSelect) return;
    var nonVision = models.filter(function (m) {
      var low = m.toLowerCase();
      return low.indexOf('vision') < 0 && low.indexOf('llava') < 0;
    });
    var pick = (nonVision.length ? nonVision : models)[0];
    modelSelect.value = pick;
  }

  function getPdfModelOverride() {
    var raw = '';
    if (pdfModelOverrideSelect) raw = pdfModelOverrideSelect.value || '';
    if (!raw) {
      try { raw = localStorage.getItem(PDF_MODEL_OVERRIDE_KEY) || '__auto__'; } catch (e) { raw = '__auto__'; }
    }
    if (raw === '__auto__' || raw === 'auto' || raw === '') return '';
    return raw;
  }

  function persistPdfModelOverride(val) {
    try { localStorage.setItem(PDF_MODEL_OVERRIDE_KEY, val || '__auto__'); } catch (e) { /* ignore */ }
  }

  var PDF_TEXT_MODELS_CACHE_KEY = 'pha_pdf_text_models_cache_v214';

  function renderPdfModelOverrideOptions(models, autoModel) {
    if (!pdfModelOverrideSelect) return;
    var stored = '__auto__';
    try { stored = localStorage.getItem(PDF_MODEL_OVERRIDE_KEY) || '__auto__'; } catch (e) { /* ignore */ }
    var rootOpts = [
      { v: '__auto__', t: '智能选择 (Auto-Detect)' },
      { v: 'FALLBACK_TO_HEURISTIC', t: '纯规则提取 (Heuristic)' }
    ];
    pdfModelOverrideSelect.innerHTML = '';
    rootOpts.forEach(function (o) {
      var el = document.createElement('option');
      el.value = o.v;
      el.textContent = o.t;
      pdfModelOverrideSelect.appendChild(el);
    });
    (models || []).forEach(function (name) {
      var opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      pdfModelOverrideSelect.appendChild(opt);
    });
    pdfModelOverrideSelect.value = stored;
    if (!pdfModelOverrideSelect.value) pdfModelOverrideSelect.value = '__auto__';
    if (stored === '__auto__' && autoModel) {
      var hint = document.getElementById('vision-status');
      if (hint && !window.pdfParsing) {
        hint.textContent = 'PDF 智能解析将使用: ' + autoModel;
      }
    }
  }

  async function loadPdfTextModels(forceRefresh) {
    if (!pdfModelOverrideSelect) return;
    if (!forceRefresh) {
      try {
        var cachedRaw = sessionStorage.getItem(PDF_TEXT_MODELS_CACHE_KEY);
        if (cachedRaw) {
          var cached = JSON.parse(cachedRaw);
          if (cached && Array.isArray(cached.models)) {
            renderPdfModelOverrideOptions(cached.models, cached.auto_model || null);
            return;
          }
        }
      } catch (e) { /* ignore corrupt cache */ }
    }
    renderPdfModelOverrideOptions([], null);
    try {
      var res = await fetch('/llm/pdf-text-models');
      if (res.ok) {
        var data = await res.json();
        try {
          sessionStorage.setItem(
            PDF_TEXT_MODELS_CACHE_KEY,
            JSON.stringify({ models: data.models || [], auto_model: data.auto_model || null }),
          );
        } catch (e) { /* quota */ }
        renderPdfModelOverrideOptions(data.models || [], data.auto_model || null);
      }
    } catch (e) { /* offline — root options only */ }
  }

  function isDataImportPanelOpen() {
    return !!(dataDrawerCheckbox && dataDrawerCheckbox.checked);
  }

  function closeDataImportPanel() {
    if (dataDrawerCheckbox) dataDrawerCheckbox.checked = false;
  }

  async function refreshVisionStatus() {
    try {
      var res = await fetch('/llm/vision-status');
      if (!res.ok) return;
      visionState = await res.json();
      updatePdfSubmitState();
      if (reportFile && reportFile.files && reportFile.files[0]) {
        updateDrawerVisionHint(reportFile.files[0]);
      }
    } catch (e) { /* ignore */ }
  }


  function showParseToast(message, kind) {
    if (!parseToast || !parseToastText) return;
    var alertEl = parseToast.querySelector('.alert');
    if (alertEl) {
      alertEl.className = 'rounded-xl border px-4 py-3 shadow-lg max-w-md text-sm ' + (
        kind === 'error' ? 'border-red-500/50 bg-red-950/80 text-red-100' : kind === 'info' ? 'border-blue-500/40 bg-slate-900/90 text-slate-100' : 'border-emerald-500/40 bg-emerald-950/70 text-emerald-100'
      );
    }
    parseToastText.textContent = message;
    parseToast.classList.remove('hidden');
    setTimeout(function () { parseToast.classList.add('hidden'); }, 8000);
  }

  function showToast(message, kind) {
    showParseToast(message, kind !== undefined ? kind : 'info');
  }

  function openErrorDebugModal(title, snippet) {
    var modal = document.getElementById('error-debug-modal');
    var pre = document.getElementById('error-debug-pre');
    var tit = document.getElementById('error-debug-title');
    if (tit) tit.textContent = title || '调试输出';
    if (pre) pre.textContent = (snippet && String(snippet)) || '(无片段)';
    if (modal) modal.showModal();
  }

  function maybeShowParseErrorModal(res, parsed) {
    if (!res || !parsed) return;
    if (res.status !== 422 && res.status !== 500) return;
    var snip = '';
    if (parsed.detailObj && typeof parsed.detailObj.raw_snippet === 'string') {
      snip = parsed.detailObj.raw_snippet;
    } else if (parsed.detailObj) {
      try { snip = JSON.stringify(parsed.detailObj, null, 2); } catch (e) { snip = String(parsed.detailObj); }
    }
    if (!snip) snip = typeof parsed.detail === 'string' ? parsed.detail : '';
    openErrorDebugModal('HTTP ' + res.status + ' · 解析/服务错误', snip.slice(0, 12000));
  }


  function setPdfParsing(loading) {
    window.pdfParsing = !!loading;
    if (!pdfSubmit) return;
    if (loading) {
      pdfSubmit.disabled = true;
      pdfSubmit.classList.add('loading');
      pdfSubmit.textContent = '解析中…';
    } else {
      pdfSubmit.classList.remove('loading');
      updatePdfSubmitState();
    }
  }

  function isMedicalUploadFile(file) {
    if (!file) return false;
    var n = (file.name || '').toLowerCase();
    var t = (file.type || '').toLowerCase();
    if (t.indexOf('pdf') >= 0) return true;
    if (t.indexOf('image/') === 0) return true;
    return /\.(pdf|jpe?g|png|webp|gif|bmp|tiff?)$/i.test(n);
  }

  function updatePdfSubmitState() {
    if (window.pdfParsing || !pdfSubmit) return;
    if (!pdfFiles.length) {
      pdfSubmit.disabled = false;
      pdfSubmit.textContent = '手动重新上传';
      return;
    }
    pdfSubmit.disabled = false;
    pdfSubmit.textContent = '手动重新上传 (' + pdfFiles.length + ')';
  }

  function renderMedicalAlertItems(items, count) {
    var modal = document.getElementById('medical-alerts-modal');
    var list = document.getElementById('medical-alerts-list');
    var summary = document.getElementById('medical-alerts-summary');
    if (!modal || !list || !summary) return;
    var n = count != null ? count : (items ? items.length : 0);
    summary.textContent = '共 ' + n + ' 项异常指标';
    list.innerHTML = '';
    if (!items || !items.length) {
      list.innerHTML = '<p class="opacity-60 py-4">暂无异常记录</p>';
      modal.showModal();
      return;
    }
    items.forEach(function (it) {
      var row = document.createElement('div');
      row.className = 'p-3 rounded-lg bg-[#161B22] border border-gray-700 hover:border-blue-500/40 transition-colors';
      var label = it.name_zh || it.metric_name || it.metric_code;
      var val = it.value != null ? it.value : '—';
      var unit = it.unit ? ' ' + it.unit : '';
      row.innerHTML =
        '<div class="font-semibold text-slate-100">' + esc(label) + ' <span class="text-amber-400">(' + esc(it.metric_code || '') + ')</span></div>' +
        '<div class="mt-1">报告日 ' + esc(it.report_date) + ' · 值 <span class="font-mono">' + esc(val) + esc(unit) + '</span></div>' +
        '<div class="text-xs opacity-70 mt-1">参考 ' + esc(it.reference_range || '—') + '</div>';
      list.appendChild(row);
    });
    modal.showModal();
  }

  async function openMedicalAlertsModal() {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    var modal = document.getElementById('medical-alerts-modal');
    var list = document.getElementById('medical-alerts-list');
    var summary = document.getElementById('medical-alerts-summary');
    if (!modal || !list || !summary) return;
    summary.textContent = '加载中…';
    list.innerHTML = '';
    modal.showModal();
    try {
      var res = await fetch('/dashboard/medical-alerts?user_id=' + encodeURIComponent(uid));
      if (!res.ok) throw new Error((await readHttpErrorDetail(res)).detail);
      var data = await res.json();
      renderMedicalAlertItems(data.items || [], data.count);
    } catch (e) {
      summary.textContent = String(e.message || e);
    }
  }
  function labelsFromPoints(pts) { return (pts || []).map(function (p) { return p.label; }); }
  function valuesFromPoints(pts) {
    return (pts || []).map(function (p) { return p.value == null ? null : p.value; });
  }

  function downsamplePoints(pts, maxRaw, target) {
    var arr = pts || [];
    var cap = maxRaw == null ? CHART_MAX_RAW_POINTS : maxRaw;
    var goal = target == null ? CHART_TARGET_POINTS : target;
    if (arr.length <= cap) return arr;
    var step = Math.max(1, Math.ceil(arr.length / goal));
    var out = [];
    for (var i = 0; i < arr.length; i += step) out.push(arr[i]);
    var last = arr[arr.length - 1];
    if (out.length && out[out.length - 1] !== last) out.push(last);
    return out;
  }

  function dedupeMetricIds(ids) {
    var seen = {};
    var out = [];
    (ids || []).forEach(function (id) {
      var k = String(id || '').trim().toLowerCase();
      if (!k || seen[k]) return;
      seen[k] = true;
      out.push(String(id).trim());
    });
    return out;
  }

  function ensureTrendsChartsPanelVisible() {
    var panel = document.getElementById('trends-charts-panel');
    if (panel) panel.classList.remove('hidden');
    if (dynamicChartsGrid) dynamicChartsGrid.classList.remove('hidden');
  }

  function updateDrawerVisionHint(file) {
    var vs = document.getElementById('vision-status');
    if (!vs || !file) return;
    var name = (file.name || '').toLowerCase();
    if (/\.(png|jpe?g|webp|gif|bmp)$/i.test(name)) {
      var vm = (visionState && visionState.model) ? visionState.model : 'llama3.2-vision:11b';
      vs.textContent = '图片视觉解析将使用: ' + vm;
      return;
    }
    if (/\.pdf$/i.test(name)) {
      var sel = pdfModelOverrideSelect && pdfModelOverrideSelect.value;
      if (sel === '__auto__') vs.textContent = 'PDF 文本解析：智能选择本地最大文本模型';
      else if (sel === 'FALLBACK_TO_HEURISTIC') vs.textContent = 'PDF 解析：纯规则提取（不调用 LLM）';
      else if (sel) vs.textContent = 'PDF 智能解析将使用: ' + sel;
    }
  }

  var chartColors = { grid: 'rgba(55,65,81,0.45)', tick: '#94a3b8' };

  function chartCommonOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: chartColors.tick, boxWidth: 12 } },
        tooltip: {
          backgroundColor: 'rgba(15,23,42,.95)',
          titleColor: '#e2e8f0',
          bodyColor: '#cbd5e1',
          borderColor: 'rgba(59,130,246,.35)',
          borderWidth: 1
        }
      },
      scales: {
        x: {
          ticks: { color: chartColors.tick, maxRotation: 35 },
          grid: { color: chartColors.grid }
        },
        y: {
          ticks: { color: chartColors.tick },
          grid: { color: chartColors.grid }
        }
      }
    };
  }

  function destroyCharts() {
    Object.keys(window.phaCharts || {}).forEach(function (k) {
      var c = window.phaCharts[k];
      if (c && typeof c.destroy === 'function') {
        c.destroy();
        delete window.phaCharts[k];
      }
    });
  }

  function destroyDynamicCharts() {
    destroyCharts();
    if (dynamicChartsGrid) dynamicChartsGrid.innerHTML = '';
  }

  function metricChartColor(metricId, idx) {
    var s = String(metricId || '');
    var h = 0;
    for (var i = 0; i < s.length; i++) h = ((h << 5) - h) + s.charCodeAt(i);
    return DYNAMIC_CHART_COLORS[(Math.abs(h) + idx) % DYNAMIC_CHART_COLORS.length];
  }

  function catalogLabel(metricId) {
    var hit = metricCatalog.find(function (m) { return m.id === metricId; });
    if (!hit) return metricId;
    var u = hit.unit ? ' (' + hit.unit + ')' : '';
    return (hit.label || hit.id) + u;
  }

  function loadAlertsCache() {
    try {
      var raw = localStorage.getItem(ALERTS_CACHE_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) { return null; }
  }

  function saveAlertsCache(data, uid) {
    try {
      localStorage.setItem(ALERTS_CACHE_KEY, JSON.stringify({
        user_id: uid,
        count: data.count || 0,
        items: data.items || [],
        ts: Date.now()
      }));
    } catch (e) { /* ignore */ }
  }

  function applyAlertsCacheToHero() {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    var cached = loadAlertsCache();
    var el = document.getElementById('stat-medical');
    if (!el) return;
    if (cached && cached.user_id === uid && cached.count != null) {
      el.textContent = String(cached.count);
    }
    if (aiDoctorBtn) {
      if (cached && cached.user_id === uid) {
        aiDoctorBtn.textContent = '✓ AI 医生已审阅 · 点击重新审阅';
        aiDoctorBtn.className = 'done';
      } else {
        aiDoctorBtn.textContent = '⚙️ AI 医生离线静默中 / 点击重新审阅';
        aiDoctorBtn.className = '';
      }
    }
  }

  function getSelectedMetricIds() {
    return dedupeMetricIds(Array.from(selectedMetricIds));
  }

  function toggleMetricId(id, on) {
    if (!id) return;
    if (on) selectedMetricIds.add(id); else selectedMetricIds.delete(id);
    renderDynamicMetricCharts();
  }

  var UI_TAG_BLACKLIST = [
    '作为乘客', '失眠是指', '中度症状', '评估者', '流水号',
    '病人号', '体 检 号', '吸烟指数', '戒烟', '年龄:', '总审日期', '□', '机构:'
  ];

  function ensureDefaultTrendMetrics() {
    DEFAULT_METRIC_PICKS.forEach(function (id) { selectedMetricIds.add(id); });
    selectedMetricIds.add('activity_kcal');
  }

  function isUiPollutedMetricTag(m) {
    var label = String((m && (m.label || m.id)) || '').trim();
    var mid = String((m && m.id) || '').trim();
    if (!label && !mid) return true;
    if (label.length > 12 || mid.length > 12) return true;
    for (var i = 0; i < UI_TAG_BLACKLIST.length; i++) {
      if (label.indexOf(UI_TAG_BLACKLIST[i]) >= 0 || mid.indexOf(UI_TAG_BLACKLIST[i]) >= 0) return true;
    }
    return false;
  }

  function makeMetricTag(m, opts) {
    opts = opts || {};
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pha-metric-tag' + (selectedMetricIds.has(m.id) ? ' on' : '');
    btn.dataset.metricId = m.id;
    var label = m.label || m.id;
    var hint = m.hint ? '<span class="hint">' + esc(m.hint) + '</span>' : '';
    btn.innerHTML = esc(label) + hint;
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      var nowOn = !selectedMetricIds.has(m.id);
      if (nowOn) selectedMetricIds.add(m.id); else selectedMetricIds.delete(m.id);
      btn.classList.toggle('on', nowOn);
      renderDynamicMetricCharts();
    });
    return btn;
  }

  function renderGoldenTags(golden) {
    if (!goldenTagsEl) return;
    goldenTagsEl.innerHTML = '';
    (golden || []).forEach(function (m) {
      if (m.default && !selectedMetricIds.size) selectedMetricIds.add(m.id);
      goldenTagsEl.appendChild(makeMetricTag(m));
    });
  }

  function renderGroupedMetrics(groups, filter) {
    if (!groupedMetricsEl) return;
    var q = (filter || '').trim().toLowerCase();
    groupedMetricsEl.innerHTML = '';
    (groups || []).forEach(function (g) {
      var visible = (g.metrics || []).filter(function (m) {
        if (isUiPollutedMetricTag(m)) return false;
        if (!q) return true;
        var blob = ((m.label || '') + ' ' + (m.id || '')).toLowerCase();
        return blob.indexOf(q) >= 0;
      });
      if (!visible.length) return;
      var sec = document.createElement('div');
      sec.className = 'pha-metric-group';
      sec.innerHTML = '<h4>' + esc(g.label || g.id) + '</h4><div class="pha-metric-group-tags"></div>';
      var host = sec.querySelector('.pha-metric-group-tags');
      visible.forEach(function (m) {
        var tag = makeMetricTag(m);
        if (q) tag.classList.add('match');
        host.appendChild(tag);
      });
      groupedMetricsEl.appendChild(sec);
    });
    if (moreMetricsSummary && metricsPayload) {
      var extra = metricsPayload.medical_count || 0;
      moreMetricsSummary.textContent = '展开更多健康指标报告 (查看全量 ' + extra + '+ 项体检与长尾体征)';
    }
  }

  async function loadMetricCatalog() {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    try {
      var res = await fetch('/api/v1/available_metrics?user_id=' + encodeURIComponent(uid));
      if (!res.ok) throw new Error((await readHttpErrorDetail(res)).detail);
      metricsPayload = await res.json();
      metricCatalog = metricsPayload.metrics || [];
      renderGoldenTags(metricsPayload.golden || []);
      renderGroupedMetrics(metricsPayload.groups || [], metricSearchBar ? metricSearchBar.value : '');
      ensureDefaultTrendMetrics();
      if (!selectedMetricIds.size) {
        (metricsPayload.golden || []).forEach(function (m) {
          if (m.default) selectedMetricIds.add(m.id);
        });
      }
      await renderDynamicMetricCharts();
    } catch (e) {
      if (goldenTagsEl) goldenTagsEl.innerHTML = '<span class="text-slate-500 text-xs">指标目录加载失败</span>';
    }
  }

  function runAiDoctorReview(background) {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    if (aiDoctorBtn) {
      aiDoctorBtn.textContent = '🧠 AI 医生深度审阅中…';
      aiDoctorBtn.className = 'running';
    }
    var streamUrl = '/dashboard/medical-alerts/stream?user_id=' + encodeURIComponent(uid) + '&refresh=1';
    var finished = function (data, err) {
      if (err) {
        if (aiDoctorBtn) { aiDoctorBtn.textContent = '⚠️ 审阅失败 · 点击重试'; aiDoctorBtn.className = ''; }
        return;
      }
      saveAlertsCache(data, uid);
      applyAlertsCacheToHero();
      if (!background) {
        renderMedicalAlertItems(data.items || [], data.count);
      }
    };
    if (typeof EventSource !== 'undefined') {
      var es = new EventSource(streamUrl);
      es.onmessage = function (ev) {
        try {
          var p = JSON.parse(ev.data);
          if (p.event === 'done' || p.items) { es.close(); finished(p); }
        } catch (e) { es.close(); finished(null, e); }
      };
      es.onerror = function () {
        es.close();
        fetch('/dashboard/medical-alerts?user_id=' + encodeURIComponent(uid) + '&refresh=1')
          .then(function (r) { return r.json(); }).then(finished)
          .catch(function (e) { finished(null, e); });
      };
      return;
    }
    fetch('/dashboard/medical-alerts?user_id=' + encodeURIComponent(uid) + '&refresh=1')
      .then(function (r) { return r.json(); }).then(function (d) { finished(d); })
      .catch(function (e) { finished(null, e); });
  }

  async function renderDynamicMetricCharts() {
    if (!dynamicChartsGrid) return;
    ensureTrendsChartsPanelVisible();
    var selected = getSelectedMetricIds();
    if (!selected.length) {
      destroyDynamicCharts();
      if (trendsEmpty) trendsEmpty.classList.remove('hidden');
      return;
    }
    var uid = (userIdInput.value || 'default').trim() || 'default';
    destroyDynamicCharts();
    if (trendsEmpty) trendsEmpty.classList.add('hidden');
    try {
      var qs = '/api/v1/metric-trends?user_id=' + encodeURIComponent(uid)
        + '&metrics=' + encodeURIComponent(selected.join(','));
      var res = await fetch(qs);
      if (!res.ok) throw new Error((await readHttpErrorDetail(res)).detail);
      var data = await res.json();
      var series = data.series || {};
      var anyData = false;
      var rendered = {};
      selected.forEach(function (mid, idx) {
        var key = String(mid || '').trim().toLowerCase();
        if (!key || rendered[key]) return;
        rendered[key] = true;
        var block = series[mid] || series[key] || {};
        var rawPts = block.points || [];
        var pts = downsamplePoints(rawPts);
        if (pts.length) anyData = true;
        var box = document.createElement('div');
        box.className = 'pha-chart-box';
        var title = document.createElement('p');
        title.textContent = catalogLabel(mid);
        var sub = document.createElement('p');
        sub.className = 'sub';
        sub.textContent = rawPts.length > pts.length
          ? pts.length + ' 点（由 ' + rawPts.length + ' 降采样）'
          : (pts.length ? pts.length + ' 个数据点' : '暂无历史数据');
        var host = document.createElement('div');
        host.className = 'chart-canvas-host';
        var canvas = document.createElement('canvas');
        var chartId = 'dyn-chart-' + key.replace(/[^a-zA-Z0-9]/g, '_');
        canvas.id = chartId;
        host.appendChild(canvas);
        box.appendChild(title);
        box.appendChild(sub);
        box.appendChild(host);
        dynamicChartsGrid.appendChild(box);
        if (!pts.length || typeof Chart === 'undefined') return;
        var color = metricChartColor(mid, idx);
        var isSteps = String(mid).toLowerCase() === 'steps';
        initChartJs(chartId, {
          type: isSteps ? 'bar' : 'line',
          data: {
            labels: labelsFromPoints(pts),
            datasets: [{
              label: catalogLabel(mid),
              data: valuesFromPoints(pts),
              borderColor: color,
              backgroundColor: isSteps ? color + 'cc' : color + '26',
              fill: !isSteps,
              tension: 0.35,
              pointRadius: pts.length > 60 ? 0 : 3
            }]
          },
          options: chartCommonOptions()
        });
      });
      if (!anyData) {
        var onlyActivity = selected.length === 1 && String(selected[0]).toLowerCase() === 'activity_kcal';
        if (onlyActivity && trendsEmpty) {
          trendsEmpty.textContent = '无活动消耗数据，请先导入 Apple Health';
        }
        trendsEmpty.classList.remove('hidden');
      }
    } catch (e) {
      trendsEmpty.classList.remove('hidden');
      dynamicChartsGrid.innerHTML = '<p class="sub" style="padding:0.5rem;color:#f87171">' + esc(String(e.message || e)) + '</p>';
    }
  }

  function initChartJs(id, config) {
    var el = document.getElementById(id);
    if (!el || typeof Chart === 'undefined') return null;
    if (window.phaCharts[id]) {
      window.phaCharts[id].destroy();
      delete window.phaCharts[id];
    }
    var ctx = el.getContext('2d');
    var chart = new Chart(ctx, config);
    window.phaCharts[id] = chart;
    return chart;
  }

  function flashHeroStats() {
    ['today-steps', 'avg-hrv', 'sleep-duration', 'stat-medical'].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.classList.add('animate-pulse', 'text-blue-400');
      setTimeout(function () {
        el.classList.remove('animate-pulse', 'text-blue-400');
      }, 1400);
    });
  }

  var healthAssetsCache = [];

  function formatAssetSourceTag(kind) {
    var k = String(kind || 'pdf').toLowerCase();
    if (k === 'chat_ingest') return '[聊天归仓]';
    if (k === 'event_drawer') return '[事件归仓]';
    if (k === 'screenshot') return '[截图解析]';
    if (k === 'scan') return '[扫描解析]';
    return '[PDF解析]';
  }

  function formatAssetMetricsPreview(raw) {
    if (raw == null || raw === '' || raw === '—') return '';
    if (typeof raw === 'object') {
      try { return JSON.stringify(raw, null, 2); } catch (e) { return String(raw); }
    }
    return String(raw).trim();
  }

  function truncatePreviewTooltip(text, maxLen) {
    var t = String(text || '');
    if (t.length <= maxLen) return t;
    return t.slice(0, maxLen) + '…';
  }

  function animateAssetRowsExit(rows, done) {
    var list = Array.isArray(rows) ? rows : [rows];
    list = list.filter(Boolean);
    if (!list.length) {
      if (done) done();
      return;
    }
    list.forEach(function (row) { row.classList.add('pha-asset-row-exit'); });
    setTimeout(function () {
      list.forEach(function (row) {
        if (row.parentNode) row.parentNode.removeChild(row);
      });
      if (done) done();
    }, 300);
  }

  function buildHealthAssetRow(it, index) {
    var wrap = document.createElement('div');
    wrap.className = 'pha-asset-row';
    if (index != null) wrap.style.animationDelay = String(index * 45) + 'ms';

    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'pha-asset-cb';
    cb.dataset.assetId = String(it.id);
    cb.dataset.reportDate = it.report_date || '';
    cb.addEventListener('click', function (e) { e.stopPropagation(); });

    var card = document.createElement('div');
    card.className = 'pha-asset-card';

    var head = document.createElement('div');
    head.className = 'pha-asset-card-head';

    var dateEl = document.createElement('span');
    dateEl.className = 'pha-asset-date';
    dateEl.textContent = '📅 ' + (it.report_date || '—');

    var fileEl = document.createElement('span');
    fileEl.className = 'pha-asset-filename';
    fileEl.textContent = '📄 ' + (it.source_filename || '—');

    var tagEl = document.createElement('span');
    tagEl.className = 'pha-asset-source-tag';
    tagEl.textContent = formatAssetSourceTag(it.source_kind);

    head.appendChild(dateEl);
    head.appendChild(fileEl);
    head.appendChild(tagEl);
    card.appendChild(head);

    var row2 = document.createElement('div');
    row2.className = 'pha-asset-card-row2';

    var previewText = formatAssetMetricsPreview(it.metrics_preview);
    if (previewText) {
      fileEl.title = truncatePreviewTooltip(previewText, 140);
      var details = document.createElement('details');
      details.className = 'pha-asset-details';
      var summary = document.createElement('summary');
      summary.textContent = '点击查看指标预览';
      var pre = document.createElement('pre');
      pre.className = 'pha-asset-preview-body';
      pre.textContent = previewText;
      details.appendChild(summary);
      details.appendChild(pre);
      details.addEventListener('click', function (e) { e.stopPropagation(); });
      row2.appendChild(details);
    }

    if (!it.legacy) {
      var jsonLink = document.createElement('button');
      jsonLink.type = 'button';
      jsonLink.className = 'pha-asset-json-link';
      jsonLink.textContent = '📋 原始 JSON';
      jsonLink.addEventListener('click', function (e) {
        e.stopPropagation();
        openAssetJsonModal(it.id);
      });
      row2.appendChild(jsonLink);
    }

    if (row2.childNodes.length) {
      card.appendChild(row2);
    }

    var delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'pha-asset-del-btn';
    delBtn.textContent = '🗑️ 删除';
    delBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (!confirm('彻底删除该日体检数据与关联文件？不可恢复。')) return;
      delBtn.disabled = true;
      deleteHealthAssetsBatch([String(it.id)], [it.report_date || '']).then(function () {
        showToast('已连根拔起删除', 'success');
        animateAssetRowsExit(wrap, function () {
          loadHealthAssets({ animateIn: true });
          loadTrends();
          flashHeroStats();
        });
      }).catch(function (err) {
        showToast(String(err), 'error');
        delBtn.disabled = false;
      });
    });

    wrap.appendChild(cb);
    wrap.appendChild(card);
    wrap.appendChild(delBtn);
    return wrap;
  }

  async function deleteHealthAssetsBatch(assetIds, reportDates) {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    var res = await fetch('/api/assets/delete-batch', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: uid,
        asset_ids: assetIds || [],
        report_dates: reportDates || []
      })
    });
    if (!res.ok) {
      var err = await readHttpErrorDetail(res);
      throw new Error(err.detail || '删除失败');
    }
    return res.json();
  }

  async function loadHealthAssets(opts) {
    opts = opts || {};
    var list = document.getElementById('health-assets-list');
    var toolbar = document.getElementById('health-assets-toolbar');
    var selectAll = document.getElementById('health-assets-select-all');
    if (!list) return;
    list.classList.remove('pha-assets-list-in');
    var uid = (userIdInput.value || 'default').trim() || 'default';
    try {
      var res = await fetch('/dashboard/health-assets?user_id=' + encodeURIComponent(uid));
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var data = await res.json();
      healthAssetsCache = data.items || [];
      list.innerHTML = '';
      list.className = 'pha-assets-list';
      if (toolbar) toolbar.classList.toggle('hidden', !healthAssetsCache.length);
      if (selectAll) selectAll.checked = false;
      if (!healthAssetsCache.length) {
        list.innerHTML = '<p class="opacity-50 text-xs py-2">暂无归档；上传 PDF 或截图后将显示于此</p>';
        return;
      }
      healthAssetsCache.forEach(function (it, idx) {
        list.appendChild(buildHealthAssetRow(it, idx));
      });
      if (opts.animateIn) {
        requestAnimationFrame(function () {
          list.classList.add('pha-assets-list-in');
          setTimeout(function () { list.classList.remove('pha-assets-list-in'); }, 500);
        });
      }
    } catch (e) {
      list.innerHTML = '<p class="text-red-400 text-xs">' + esc(String(e.message || e)) + '</p>';
    }
  }

  (function bindHealthAssetsToolbar() {
    var selectAll = document.getElementById('health-assets-select-all');
    var batchBtn = document.getElementById('health-assets-delete-batch');
    if (selectAll) {
      selectAll.addEventListener('change', function () {
        document.querySelectorAll('.pha-asset-cb').forEach(function (cb) {
          cb.checked = selectAll.checked;
        });
      });
    }
    if (batchBtn) {
      batchBtn.addEventListener('click', function () {
        var ids = [];
        var dates = [];
        document.querySelectorAll('.pha-asset-cb:checked').forEach(function (cb) {
          if (cb.dataset.assetId) ids.push(cb.dataset.assetId);
          if (cb.dataset.reportDate) dates.push(cb.dataset.reportDate);
        });
        if (!ids.length && !dates.length) {
          showToast('请先勾选要删除的资产', 'error');
          return;
        }
        if (!confirm('将物理删除选中附件并清空对应 SQLite 指标/叙事，确定？')) return;
        batchBtn.disabled = true;
        var checkedRows = [];
        document.querySelectorAll('.pha-asset-cb:checked').forEach(function (cb) {
          var row = cb.closest('.pha-asset-row');
          if (row) checkedRows.push(row);
        });
        deleteHealthAssetsBatch(ids, dates).then(function (r) {
          showToast('已删除 ' + (r.report_dates || []).length + ' 个体检日资产', 'success');
          animateAssetRowsExit(checkedRows, function () {
            loadHealthAssets({ animateIn: true });
            loadTrends();
            flashHeroStats();
          });
        }).catch(function (e) {
          showToast(String(e), 'error');
        }).finally(function () { batchBtn.disabled = false; });
      });
    }
  })();

  async function openAssetJsonModal(assetId) {
    var modal = document.getElementById('asset-json-modal');
    var pre = document.getElementById('asset-json-pre');
    var meta = document.getElementById('asset-json-meta');
    if (!modal || !pre) return;
    var uid = (userIdInput.value || 'default').trim() || 'default';
    pre.textContent = '加载中…';
    meta.textContent = '';
    modal.showModal();
    try {
      var res = await fetch(
        '/dashboard/health-assets/' + encodeURIComponent(assetId) + '?user_id=' + encodeURIComponent(uid)
      );
      if (!res.ok) throw new Error((await readHttpErrorDetail(res)).detail);
      var data = await res.json();
      meta.textContent = [
        data.report_date,
        data.source_filename,
        data.vision_model ? 'Vision: ' + data.vision_model : ''
      ].filter(Boolean).join(' · ');
      pre.textContent = JSON.stringify(data.vision_raw != null ? data.vision_raw : data, null, 2);
    } catch (e) {
      pre.textContent = String(e.message || e);
    }
  }

  var syncStatusLabel = document.getElementById('sync-status-label');
  var syncLastTime = document.getElementById('sync-last-time');
  var syncCountsLine = document.getElementById('sync-counts-line');
  var syncStatusMessage = document.getElementById('sync-status-message');
  var syncJobProgress = document.getElementById('sync-job-progress');
  var medicalPdfProgress = document.getElementById('medical-pdf-progress');

  function formatSyncTime(iso) {
    if (!iso) return '—';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso).slice(0, 19);
      return d.toLocaleString('zh-CN', { hour12: false });
    } catch (e) { return String(iso).slice(0, 19); }
  }

  async function loadSyncStatus() {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    try {
      var res = await fetch('/dashboard/sync-status?user_id=' + encodeURIComponent(uid));
      if (!res.ok) return;
      var d = await res.json();
      if (syncStatusLabel) {
        syncStatusLabel.textContent = d.status_label || d.status || '—';
        var badge = 'rounded-md border border-gray-600 bg-[#0D1117] px-2 py-0.5 text-xs text-slate-300';
        if (d.status === 'parsing' || d.status === 'running') badge = 'rounded-md border border-amber-600/50 bg-amber-950/40 px-2 py-0.5 text-xs text-amber-200';
        else if (d.status === 'complete') badge = 'rounded-md border border-emerald-600/50 bg-emerald-950/30 px-2 py-0.5 text-xs text-emerald-200';
        else if (d.status === 'failed') badge = 'rounded-md border border-red-600/50 bg-red-950/40 px-2 py-0.5 text-xs text-red-200';
        syncStatusLabel.className = badge;
      }
      if (syncLastTime) {
        syncLastTime.textContent = formatSyncTime(d.last_record_time || d.last_sync_at);
      }
      if (syncCountsLine && d.counts) {
        syncCountsLine.textContent =
          '睡眠 ' + (d.counts.sleep_segments || 0).toLocaleString() + ' 条 · ' +
          '运动(步数) ' + (d.counts.steps_samples || 0).toLocaleString() + ' 条 · ' +
          '锻炼会话 ' + (d.counts.workout_sessions || 0).toLocaleString() + ' 条 · ' +
          '日聚合 ' + (d.counts.daily_days || 0).toLocaleString() + ' 天';
      }
      if (syncStatusMessage) {
        var msg = d.message || '';
        if (d.workout_backfill_needed) {
          msg = (msg ? msg + ' · ' : '') + '锻炼数据未入库：请选择 export.zip 与「锻炼 (HKWorkout)」模块后增量同步';
        }
        syncStatusMessage.textContent = msg;
      }
      if (syncJobProgress) {
        if (d.status === 'parsing' && d.percent > 0) {
          syncJobProgress.classList.remove('hidden');
          syncJobProgress.value = Math.min(100, d.percent);
        } else if (d.status === 'complete') {
          syncJobProgress.classList.remove('hidden');
          syncJobProgress.value = 100;
        } else if (d.status !== 'parsing') {
          syncJobProgress.classList.add('hidden');
        }
      }
    } catch (e) { /* ignore */ }
  }

  async function loadHeroStats() {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    try {
      var res = await fetch('/dashboard/hero-stats?user_id=' + encodeURIComponent(uid));
      if (!res.ok) return;
      var d = await res.json();
      var elSteps = document.getElementById('today-steps');
      var elHrv = document.getElementById('avg-hrv');
      var elSleep = document.getElementById('sleep-duration');
      if (elSteps) elSteps.textContent = d.today_steps != null ? Number(d.today_steps).toLocaleString() : '—';
      if (elHrv) elHrv.textContent = d.avg_hrv_7d != null ? d.avg_hrv_7d : '—';
      if (elSleep) elSleep.textContent = d.avg_sleep_7d != null ? d.avg_sleep_7d : '—';
      var elMed = document.getElementById('stat-medical');
      if (elMed) elMed.textContent = d.medical_alerts != null ? d.medical_alerts : '—';
      if (d.db_samples != null) {
        dbStatusText.textContent = (d.db_samples / 1e6 >= 1 ? (d.db_samples / 1e6).toFixed(1) + 'M' : d.db_samples.toLocaleString()) + ' 行';
        dbBadge.className = 'inline-flex items-center gap-1 rounded-md border border-emerald-600/40 bg-emerald-950/20 px-2 py-1 text-xs text-emerald-200';
      }
      if (d.db_max_timestamp) {
        dbBadge.title = '最新: ' + d.db_max_timestamp.slice(0, 10);
      }
    } catch (e) { /* ignore */ }
  }

  async function loadHealth() {
    try {
      var res = await fetch('/health');
      if (!res.ok) return;
      var data = await res.json();
      phaBuild.textContent = data.pha_build || '';
    } catch (e) { phaBuild.textContent = 'offline'; }
  }

  async function loadModels() {
    modelHint.textContent = '探测模型…';
    connBadge.className = 'inline-flex items-center gap-1 rounded-md border border-amber-600/50 bg-amber-950/30 px-2 py-1 text-xs text-amber-200';
    connBadge.innerHTML = '<span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-amber-400 border-t-transparent mr-1 align-middle"></span> 连接中';
    modelSelect.innerHTML = '';
    try {
      var res = await fetch('/llm/models');
      if (!res.ok) throw new Error((await readHttpErrorDetail(res)).detail);
      var data = await res.json();
      var models = data.models || [];
      if (!models.length) throw new Error('未检测到 Ollama 模型');
      models.forEach(function (m) {
        var o = document.createElement('option');
        o.value = m; o.textContent = m;
        modelSelect.appendChild(o);
      });
      selectDefaultModel(models);
      lastLoadedModel = modelSelect.value || '';
      updateActiveModelLabel();
      modelHint.textContent = '已连接 · 默认 ' + (modelSelect.value || '（自动）');
      connBadge.className = 'inline-flex items-center gap-1 rounded-md border border-emerald-600/40 bg-emerald-950/20 px-2 py-1 text-xs text-emerald-200';
      connBadge.textContent = 'Ollama 在线';
      sendBtn.disabled = false;
    } catch (e) {
      modelHint.textContent = String(e.message || e);
      connBadge.className = 'inline-flex items-center gap-1 rounded-md border border-red-600/50 bg-red-950/30 px-2 py-1 text-xs text-red-200';
      connBadge.textContent = '未连接';
      sendBtn.disabled = true;
    }
  }

  async function loadTrends() {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    trendsPre.textContent = '加载中…';
    try {
      var res = await fetch('/user/context?user_id=' + encodeURIComponent(uid));
      if (!res.ok) throw new Error((await readHttpErrorDetail(res)).detail);
      var data = await res.json();
      trendsPre.textContent = typeof data.compressed_wearable_trends === 'string' ? data.compressed_wearable_trends : JSON.stringify(data, null, 2);
      ensureTrendsChartsPanelVisible();
      ensureDefaultTrendMetrics();
      await loadMetricCatalog();
      await renderDynamicMetricCharts();
      await loadHeroStats();
    } catch (e) {
      trendsPre.textContent = String(e);
      destroyDynamicCharts();
      if (trendsEmpty) trendsEmpty.classList.remove('hidden');
    }
  }

  document.querySelectorAll('[data-trends-tab]').forEach(function (tab) {
    tab.addEventListener('click', function () {
      try {
        var t = tab.getAttribute('data-trends-tab');
        document.querySelectorAll('[data-trends-tab]').forEach(function (x) {
          var on = x === tab;
          x.className = 'tab-trends rounded-md px-3 py-1.5 text-xs ' + (
            on ? 'bg-blue-600/30 text-blue-200' : 'text-slate-400 hover:text-slate-200'
          );
        });
        var chartsPanel = document.getElementById('trends-charts-panel');
        var rawPanel = document.getElementById('trends-raw-panel');
        if (chartsPanel) chartsPanel.classList.toggle('hidden', t !== 'charts');
        if (rawPanel) rawPanel.classList.toggle('hidden', t !== 'raw');
        if (t === 'charts' && typeof renderDynamicMetricCharts === 'function') {
          renderDynamicMetricCharts().catch(function () { /* chart not ready */ });
        }
      } catch (err) {
        console.warn('trends tab switch failed', err);
      }
    });
  });
  function parseEvidence(raw) {
    var re = /【依据索引】\s*([^\n\r]+)\s*$/;
    var m = (raw || '').match(re);
    if (!m) return { display: String(raw || '').trim(), ids: [] };
    return { display: raw.slice(0, m.index).trim(), ids: m[1].split(',').map(function (s) { return s.trim(); }).filter(Boolean) };
  }

  function shouldShowIngestConfirm(ingestOpts) {
    if (!ingestOpts || !ingestOpts.ingest_payload) return false;
    var st = (ingestOpts.ingest_status || '').trim();
    return st === 'manual_required' || st === 'auto_partial';
  }

  function attachIngestButton(wrap, ingestPayload, userMessageId) {
    if (!wrap || !ingestPayload) return;
    var tracks = splitTracksFromPageData({
      metrics_preview: ingestPayload.metrics || [],
      extraction: {
        results: (ingestPayload.metrics || []).map(function (m) {
          return {
            item: m.item || m.metric_name,
            value: m.value_text || String(m.value != null ? m.value : ''),
            unit: m.unit,
            ref: m.ref || m.reference_range,
            is_abnormal: !!m.is_abnormal
          };
        }),
        narratives: (ingestPayload.narratives || []).map(function (n) {
          return { category: n.category, content: n.content, summary: n.summary };
        })
      }
    });
    if (!tracks.metrics.length && !tracks.narratives.length) return;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pha-ingest-gold-btn';
    btn.textContent = '保存到健康档案';
    btn.addEventListener('click', function () {
      ingestChatPayload(userMessageId, ingestPayload, tracks, btn);
    });
    wrap.style.flexDirection = 'column';
    wrap.style.alignItems = 'flex-start';
    wrap.appendChild(btn);
  }

  async function ingestChatPayload(userMessageId, ingestPayload, tracks, btn) {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    if (btn) { btn.disabled = true; btn.textContent = '归仓中…'; }
    try {
      var res = await fetch('/api/chat/messages/' + encodeURIComponent(userMessageId) + '/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: uid,
          report_date: ingestPayload.report_date || new Date().toISOString().slice(0, 10),
          hospital: ingestPayload.hospital || '',
          metrics: tracks.metrics,
          narratives: tracks.narratives
        })
      });
      if (!res.ok) {
        var err = await readHttpErrorDetail(res);
        showToast(err.detail || '归仓失败', 'error');
        if (btn) { btn.disabled = false; btn.textContent = '保存到健康档案'; }
        return;
      }
      var data = await res.json();
      showToast('已归仓：指标 ' + (data.metrics_stored || 0) + ' · 叙事 ' + (data.narratives_stored || 0), 'success');
      if (btn) { btn.textContent = '✓ 已归仓'; btn.disabled = true; }
      loadTrends();
    } catch (e) {
      showToast(String(e), 'error');
      if (btn) { btn.disabled = false; btn.textContent = '📥 识别结果一键归仓（存入 SQLite 趋势表）'; }
    }
  }

  function appendAssistantWithEvidence(text, items, raw, ingestOpts) {
    var resolved = resolveAssistantBubble(text, raw);
    var body = renderMarkdown(resolved.display || '');
    var wrap = appendChat(body, 'assistant');
    if (shouldShowIngestConfirm(ingestOpts)) {
      attachIngestButton(wrap, ingestOpts.ingest_payload, ingestOpts.user_message_id);
    }
    if (resolved.ids.length && items && items.length) {
      var pills = document.createElement('div');
      pills.className = 'mt-2 flex flex-wrap gap-1';
      var map = {};
      items.forEach(function (it) { if (it.ref_id) map[it.ref_id] = it.title || it.ref_id; });
      resolved.ids.forEach(function (id) {
        var b = document.createElement('button');
        b.className = 'rounded border border-gray-600 px-2 py-0.5 text-xs text-slate-300 hover:border-blue-500/50';
        b.textContent = id;
        b.title = map[id] || id;
        pills.appendChild(b);
      });
      wrap.querySelector('.pha-chat-bubble').appendChild(pills);
    }
  }


  /* Zip import */
  var dropZip = document.getElementById('drop-zone-zip');
  var zipInput = document.getElementById('zip-file');
  var importSubmit = document.getElementById('import-submit');
  var syncModuleSelect = document.getElementById('sync-module-select');
  var syncModuleSubmit = document.getElementById('sync-module-submit');
  var syncModuleHint = document.getElementById('sync-module-hint');
  var uploadProgress = document.getElementById('upload-progress');
  var uploadStatus = document.getElementById('upload-status');
  var importFilename = document.getElementById('import-filename');

  function setZipList(files) {
    zipFiles = Array.from(files || []).filter(function (f) { return f.name.toLowerCase().endsWith('.zip'); });
    if (importFilename) {
      importFilename.textContent = zipFiles.length ? zipFiles.map(function (f) { return f.name; }).join(', ') : '';
    }
    var hasZip = zipFiles.length > 0;
    if (importSubmit) importSubmit.disabled = !hasZip;
    updateSyncModuleSubmitState();
  }

  function updateSyncModuleSubmitState() {
    if (!syncModuleSubmit) return;
    var mod = syncModuleSelect ? (syncModuleSelect.value || '').trim() : '';
    syncModuleSubmit.disabled = !(zipFiles.length > 0 && mod);
  }

  async function loadSyncModules() {
    if (!syncModuleSelect) return;
    try {
      var res = await fetch('/data/sync-modules');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var data = await res.json();
      var mods = data.modules || [];
      syncModuleSelect.innerHTML = '';
      if (!mods.length) {
        syncModuleSelect.innerHTML = '<option value="">（无已注册模块）</option>';
        updateSyncModuleSubmitState();
        return;
      }
      var placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = '选择增量同步模块…';
      syncModuleSelect.appendChild(placeholder);
      mods.forEach(function (m) {
        var opt = document.createElement('option');
        opt.value = m.module_id || '';
        opt.textContent = m.display_zh || m.module_id || 'module';
        if (m.requires_zip) opt.dataset.requiresZip = '1';
        syncModuleSelect.appendChild(opt);
      });
      if (mods.length === 1 && mods[0].module_id) {
        syncModuleSelect.value = mods[0].module_id;
      }
      updateSyncModuleSubmitState();
    } catch (e) {
      syncModuleSelect.innerHTML = '<option value="">模块列表加载失败</option>';
      updateSyncModuleSubmitState();
    }
  }

  if (syncModuleSelect) {
    syncModuleSelect.addEventListener('change', updateSyncModuleSubmitState);
  }
  if (dropZip && zipInput) {
    dropZip.addEventListener('click', function (e) {
      if (e.target === zipInput) return;
      zipInput.click();
    });
    zipInput.addEventListener('change', function () { setZipList(zipInput.files); });
    dropZip.addEventListener('dragover', function (e) { e.preventDefault(); dropZip.classList.add('border-primary'); });
    dropZip.addEventListener('dragleave', function () { dropZip.classList.remove('border-primary'); });
    dropZip.addEventListener('drop', function (e) {
      e.preventDefault(); dropZip.classList.remove('border-primary');
      if (e.dataTransfer && e.dataTransfer.files) setZipList(e.dataTransfer.files);
    });
  }

  function pollImportJob(jobId) {
    var t = setInterval(async function () {
      try {
        var res = await fetch('/data/import/status/' + encodeURIComponent(jobId));
        if (!res.ok) return;
        var st = await res.json();
        if (uploadStatus) uploadStatus.textContent = st.message || st.status;
        if (uploadProgress && st.percent != null) {
          uploadProgress.classList.remove('hidden');
          uploadProgress.value = Math.min(100, st.percent);
        }
        await loadSyncStatus();
        if (st.status === 'complete') {
          clearInterval(t);
          if (uploadProgress) uploadProgress.value = 100;
          if (importSubmit) importSubmit.disabled = false;
          showParseToast('✅ Apple Health 同步完成', 'success');
          await Promise.all([loadTrends(), loadSyncStatus()]);
        } else if (st.status === 'failed') {
          clearInterval(t);
          if (uploadStatus) uploadStatus.classList.add('text-error');
          if (importSubmit) importSubmit.disabled = false;
          showParseToast('❌ 导入失败：' + (st.message || st.error || ''), 'error');
          await loadSyncStatus();
        }
      } catch (e) {
        clearInterval(t);
        showToast('❌ 导入状态轮询失败：' + (e.message || String(e)), 'error');
      }
    }, 2000);
  }

  function uploadOneZip(f, uid, idx, total) {
    return new Promise(function (resolve, reject) {
      var fd = new FormData();
      fd.append('file', f, f.name);
      fd.append('user_id', uid);
      if (uploadStatus) uploadStatus.textContent = '上传 ' + f.name + ' (' + (idx + 1) + '/' + total + ')…';
      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/data/upload');
      xhr.upload.onprogress = function (e) {
        if (uploadProgress && e.lengthComputable) uploadProgress.value = Math.min(30, (e.loaded / e.total) * 30);
      };
      xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText || '{}')); } catch (e) { resolve({}); }
        } else reject(new Error('HTTP ' + xhr.status));
      };
      xhr.onerror = function () { reject(new Error('网络错误')); };
      xhr.send(fd);
    });
  }

  function uploadSyncModuleZip(f, uid, moduleId) {
    return new Promise(function (resolve, reject) {
      var mid = (moduleId || '').trim();
      if (!mid) return reject(new Error('未选择同步模块'));
      var fd = new FormData();
      fd.append('file', f, f.name);
      fd.append('user_id', uid);
      fd.append('clear_existing', 'false');
      if (uploadStatus) uploadStatus.textContent = '增量同步 ' + mid + '：' + f.name + '…';
      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/data/sync-module/' + encodeURIComponent(mid));
      xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText || '{}')); } catch (e) { resolve({}); }
        } else reject(new Error('HTTP ' + xhr.status));
      };
      xhr.onerror = function () { reject(new Error('网络错误')); };
      xhr.send(fd);
    });
  }

  if (syncModuleSubmit) syncModuleSubmit.addEventListener('click', async function () {
    if (!zipFiles.length) return;
    var mod = syncModuleSelect ? (syncModuleSelect.value || '').trim() : '';
    if (!mod) return;
    var uid = (userIdInput.value || 'default').trim() || 'default';
    syncModuleSubmit.disabled = true;
    if (importSubmit) importSubmit.disabled = true;
    if (uploadProgress) uploadProgress.classList.remove('hidden');
    try {
      var rep = await uploadSyncModuleZip(zipFiles[0], uid, mod);
      if (rep.job_id) pollImportJob(rep.job_id);
      else showParseToast('模块同步已提交', 'success');
      await loadSyncStatus();
    } catch (e) {
      showToast('模块同步失败：' + (e.message || String(e)), 'error');
    } finally {
      updateSyncModuleSubmitState();
      if (importSubmit) importSubmit.disabled = !zipFiles.length;
    }
  });

  if (importSubmit) importSubmit.addEventListener('click', async function () {
    if (!zipFiles.length) return;
    var uid = (userIdInput.value || 'default').trim() || 'default';
    if (uploadProgress) uploadProgress.classList.remove('hidden');
    importSubmit.disabled = true;
    await loadSyncStatus();
    try {
      for (var i = 0; i < zipFiles.length; i++) {
        var rep = await uploadOneZip(zipFiles[i], uid, i, zipFiles.length);
        if (rep.job_id) {
          await new Promise(function (resolve) {
            var t = setInterval(async function () {
              try {
                var res = await fetch('/data/import/status/' + encodeURIComponent(rep.job_id));
                if (!res.ok) return;
                var st = await res.json();
                if (uploadStatus) uploadStatus.textContent = st.message || st.status;
                if (uploadProgress && st.percent != null) uploadProgress.value = Math.min(100, st.percent);
                await loadSyncStatus();
                if (st.status === 'complete') {
                  clearInterval(t);
                  showParseToast('✅ Apple Health 同步完成', 'success');
                  resolve();
                } else if (st.status === 'failed') {
                  clearInterval(t);
                  showParseToast('❌ 导入失败：' + (st.message || st.error || ''), 'error');
                  resolve();
                }
              } catch (e) { clearInterval(t); resolve(); }
            }, 2000);
          });
        }
      }
      if (uploadProgress) uploadProgress.value = 100;
      await Promise.all([loadTrends(), loadSyncStatus()]);
    } catch (e) {
      if (uploadStatus) uploadStatus.textContent = String(e.message || e);
      showParseToast('❌ 上传失败：' + (e.message || e), 'error');
    } finally {
      if (importSubmit) importSubmit.disabled = false;
    }
  });

  var factoryResetBtn = document.getElementById('factory-reset-btn');
  var factoryResetStatus = document.getElementById('factory-reset-status');
  if (factoryResetBtn) {
    factoryResetBtn.addEventListener('click', async function () {
      var uid = (userIdInput.value || 'default').trim() || 'default';
      if (!window.confirm('将永久删除 ' + uid + ' 的全部可穿戴与体检数据。确定继续？')) return;
      factoryResetBtn.disabled = true;
      if (factoryResetStatus) factoryResetStatus.textContent = '正在清空…';
      try {
        var res = await fetch(
          '/data/factory-reset?user_id=' + encodeURIComponent(uid) + '&confirm=true',
          { method: 'POST' }
        );
        if (!res.ok) throw new Error((await readHttpErrorDetail(res)).detail);
        var data = await res.json();
        if (factoryResetStatus) factoryResetStatus.textContent = data.message || '已清空';
        showParseToast('✅ ' + (data.message || '数据已清空'), 'success');
        await Promise.all([loadSyncStatus(), loadHeroStats(), loadTrends(), loadHealthAssets()]);
      } catch (e) {
        if (factoryResetStatus) factoryResetStatus.textContent = String(e.message || e);
        showParseToast('❌ 清空失败：' + (e.message || e), 'error');
      } finally {
        factoryResetBtn.disabled = false;
      }
    });
  }

  var recomputeBtn = document.getElementById('recompute-integrity-btn');
  var recomputeStatus = document.getElementById('recompute-integrity-status');
  if (recomputeBtn) {
    recomputeBtn.addEventListener('click', async function () {
      var uid = (userIdInput.value || 'default').trim() || 'default';
      recomputeBtn.disabled = true;
      if (recomputeStatus) recomputeStatus.textContent = '正在去重并重算睡眠并集…';
      try {
        var res = await fetch(
          '/data/recompute-integrity?user_id=' + encodeURIComponent(uid),
          { method: 'POST' }
        );
        if (!res.ok) throw new Error((await readHttpErrorDetail(res)).detail);
        var data = await res.json();
        if (recomputeStatus) recomputeStatus.textContent = data.message || '重算完成';
        showParseToast(data.message || '数据完整性重算完成');
        flashHeroStats();
        await Promise.all([loadHeroStats(), loadTrends(), loadHealthAssets()]);
      } catch (e) {
        if (recomputeStatus) recomputeStatus.textContent = String(e.message || e);
      } finally {
        recomputeBtn.disabled = false;
      }
    });
  }

  /* Events + unified medical parse */
  var pendingEventParse = { metrics: [], vision_model: '', source_filename: '' };
  var eventDate = document.getElementById('event-date');
  var visionParseProgress = document.getElementById('vision-parse-progress');
  var visionPageLedgerWrap = document.getElementById('vision-page-ledger-wrap');
  var visionPageLedger = document.getElementById('vision-page-ledger');
  var visionPageLedgerHint = document.getElementById('vision-page-ledger-hint');
  var eventPagePreview = document.getElementById('event-page-preview');
  var eventAlignHint = document.getElementById('event-align-hint');
  var eventMetricsBody = document.getElementById('event-metrics-body');
  var eventMetricsPageLabel = document.getElementById('event-metrics-page-label');
  var eventMetricsEmpty = document.getElementById('event-metrics-empty');
  var eventMetricsTableWrap = document.getElementById('event-metrics-table-wrap');
  var eventAbnormalHint = document.getElementById('event-abnormal-hint');
  var eventMetricsAddRow = document.getElementById('event-metrics-add-row');
  var eventNarrativesList = document.getElementById('event-narratives-list');
  var eventNarrativesLabel = document.getElementById('event-narratives-label');
  var eventNarrativesEmpty = document.getElementById('event-narratives-empty');
  var eventNarrativesAdd = document.getElementById('event-narratives-add');
  var eventHospitalInput = document.getElementById('event-hospital');
  var pageLedger = [];
  var activeLedgerPageIndex = 0;

  var NARRATIVE_TEXT_HINTS = [
    '超声', '所见', '提示', '建议', '结论', '诊断', '心电图', '病史', '综述', '总检', '检查', '描述', '意见'
  ];

  function ledgerMetricCount(entry) {
    return (entry && entry.metrics) ? entry.metrics.length : 0;
  }

  function ledgerNarrativeCount(entry) {
    return (entry && entry.narratives) ? entry.narratives.length : 0;
  }

  function ledgerPageCapturedCount(entry) {
    if (!entry) return 0;
    return ledgerMetricCount(entry) + ledgerNarrativeCount(entry);
  }

  function ledgerAlignmentGap(entry) {
    if (!entry || entry.total_detected_rows == null) return 0;
    var captured = ledgerPageCapturedCount(entry);
    return Math.max(0, entry.total_detected_rows - captured);
  }

  function isPlausibleNumericMetric(row) {
    var item = (row.item || row.metric_name || '').trim();
    var valRaw = row.value_text != null && row.value_text !== '' ? String(row.value_text) : String(row.value != null ? row.value : '');
    var unit = (row.unit || '').trim();
    var ref = (row.ref || row.reference_range || '').trim();
    if (!item) return false;
    var i;
    for (i = 0; i < NARRATIVE_TEXT_HINTS.length; i++) {
      if (item.indexOf(NARRATIVE_TEXT_HINTS[i]) >= 0 && !unit && !ref && valRaw.length > 6) return false;
    }
    if (item.length > 32 && !unit && !ref) return false;
    if (valRaw.length > 48) return false;
    var num = parseFloat(valRaw.replace(/,/g, ''));
    if (!isNaN(num) && num >= 1900 && num <= 2100 && !unit && !ref) return false;
    if (isNaN(num) && valRaw.length > 10 && !unit && !ref) return false;
    if (!isNaN(num) && (unit || ref)) return true;
    if (!isNaN(num) && item.length <= 24) return true;
    return false;
  }

  function metricRowToNarrative(row) {
    var parts = [
      row.item || row.metric_name,
      row.value_text != null && row.value_text !== '' ? row.value_text : row.value,
      row.unit,
      row.ref || row.reference_range
    ].filter(function (x) { return x != null && String(x).trim() !== ''; });
    var content = parts.join(' ').trim();
    return {
      category: '报告原文',
      content: content,
      summary: content.length > 50 ? content.slice(0, 50) + '…' : content
    };
  }

  function rebalanceLedgerTracks(entry) {
    if (!entry) return;
    var metrics = [];
    var narratives = (entry.narratives || []).slice();
    (entry.metrics || []).forEach(function (r) {
      if (isPlausibleNumericMetric(r)) metrics.push(r);
      else if ((r.item || r.metric_name || '').trim()) narratives.push(metricRowToNarrative(r));
    });
    entry.metrics = metrics;
    entry.narratives = narratives;
    entry.extractedCount = ledgerPageCapturedCount(entry);
  }

  function splitTracksFromPageData(pageData) {
    var narratives = pageDataToNarrativeRows(pageData);
    var rawMetrics = [];
    if (pageData && pageData.metrics_preview && pageData.metrics_preview.length) {
      rawMetrics = pageData.metrics_preview.slice();
    } else if (pageData && pageData.extraction && pageData.extraction.results) {
      rawMetrics = pageData.extraction.results.map(function (r) {
        return {
          item: r.item,
          metric_name: r.item,
          value_text: r.value,
          unit: r.unit || '',
          ref: r.ref || '',
          reference_range: r.ref || '',
          is_abnormal: !!r.is_abnormal
        };
      });
    }
    var metrics = [];
    rawMetrics.forEach(function (r) {
      if (isPlausibleNumericMetric(r)) metrics.push(r);
      else if ((r.item || r.metric_name || '').trim()) narratives.push(metricRowToNarrative(r));
    });
    return { metrics: metrics, narratives: narratives };
  }

  function refreshLedgerChipAfterEdit() {
    syncPageEditsToLedger(activeLedgerPageIndex);
    rebalanceLedgerTracks(pageLedger[activeLedgerPageIndex]);
    renderPageLedger();
    updateLedgerSummaryHint();
    updatePageAlignHint(pageLedger[activeLedgerPageIndex]);
  }

  if (eventDate) eventDate.value = new Date().toISOString().slice(0, 10);

  function initPageLedger(totalPages) {
    pageLedger = [];
    for (var i = 0; i < totalPages; i++) {
      pageLedger.push({
        pageNum: i + 1,
        status: 'pending',
        metrics: [],
        narratives: [],
        hospital: '',
        total_detected_rows: null,
        extractedCount: 0
      });
    }
    activeLedgerPageIndex = 0;
    if (visionPageLedgerWrap) {
      if (totalPages > 1) visionPageLedgerWrap.classList.remove('hidden');
      else visionPageLedgerWrap.classList.add('hidden');
    }
    renderPageLedger();
    updateLedgerSummaryHint();
  }

  function ledgerChipStatus(entry) {
    if (!entry) return 'pending';
    if (entry.status === 'skipped') return 'skipped';
    if (entry.status === 'pending') return 'pending';
    if (ledgerAlignmentGap(entry) > 0) return 'mismatch';
    return 'success';
  }

  function updatePageAlignHint(entry) {
    if (!eventAlignHint) return;
    if (!entry) {
      eventAlignHint.textContent = '';
      eventAlignHint.className = 'pha-align-hint';
      return;
    }
    var gap = ledgerAlignmentGap(entry);
    var m = ledgerMetricCount(entry);
    var n = ledgerNarrativeCount(entry);
    if (entry.total_detected_rows == null) {
      eventAlignHint.textContent = '第 ' + entry.pageNum + ' 页：数字 ' + m + ' 项 · 叙事 ' + n + ' 段';
      eventAlignHint.className = 'pha-align-hint';
      return;
    }
    if (gap > 0) {
      eventAlignHint.textContent =
        '对齐缺口 ' + gap + ' = 可见约 ' + entry.total_detected_rows + ' 行 − (数字 ' + m + ' + 叙事 ' + n + ') · 请补录版块 B 或数字表';
      eventAlignHint.className = 'pha-align-hint warn';
    } else {
      eventAlignHint.textContent =
        '第 ' + entry.pageNum + ' 页已对齐：可见 ' + entry.total_detected_rows + ' 行 = 数字 ' + m + ' + 叙事 ' + n;
      eventAlignHint.className = 'pha-align-hint ok';
    }
  }

  function ledgerChipCountLabel(entry) {
    if (!entry || entry.status === 'pending') return '…';
    if (entry.status === 'skipped') return '跳过';
    var captured = ledgerPageCapturedCount(entry);
    var m = (entry.metrics || []).length;
    var narr = (entry.narratives || []).length;
    var det = entry.total_detected_rows;
    if (det != null && det > captured) return captured + '/' + det + ' 项';
    if (narr > 0) return m + '+' + narr;
    return captured + ' 项';
  }

  function renderPageLedger() {
    if (!visionPageLedger) return;
    visionPageLedger.innerHTML = '';
    pageLedger.forEach(function (entry, idx) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'pha-page-chip ' + ledgerChipStatus(entry) + (idx === activeLedgerPageIndex ? ' active' : '');
      chip.setAttribute('role', 'tab');
      chip.setAttribute('aria-selected', idx === activeLedgerPageIndex ? 'true' : 'false');
      chip.title = '第 ' + entry.pageNum + ' 页';
      chip.innerHTML = '<span>P' + entry.pageNum + '</span><span class="chip-count">' + esc(ledgerChipCountLabel(entry)) + '</span>';
      chip.addEventListener('click', function () { selectLedgerPage(idx); });
      visionPageLedger.appendChild(chip);
    });
  }

  function updateLedgerSummaryHint() {
    if (!visionPageLedgerHint) return;
    var totalMetrics = 0;
    var totalNarratives = 0;
    var gapPages = 0;
    pageLedger.forEach(function (p) {
      totalMetrics += (p.metrics || []).length;
      totalNarratives += (p.narratives || []).length;
      if (ledgerAlignmentGap(p) > 0) gapPages++;
    });
    if (!pageLedger.length) {
      visionPageLedgerHint.textContent = '';
      return;
    }
    var hint = '全报告：数字 ' + totalMetrics + ' 项 + 叙事 ' + totalNarratives + ' 段（提交时双轨入库）';
    if (gapPages) hint += ' · ⚠ ' + gapPages + ' 页可见行数 > 数字+叙事合计，请补录';
    visionPageLedgerHint.textContent = hint;
  }

  function syncTableToLedger(pageIdx) {
    if (pageIdx < 0 || pageIdx >= pageLedger.length) return;
    pageLedger[pageIdx].metrics = collectEventMetricsFromTable();
  }

  function syncNarrativesToLedger(pageIdx) {
    if (pageIdx < 0 || pageIdx >= pageLedger.length) return;
    pageLedger[pageIdx].narratives = collectNarrativesFromDom();
  }

  function syncPageEditsToLedger(pageIdx) {
    syncTableToLedger(pageIdx);
    syncNarrativesToLedger(pageIdx);
    if (pageLedger[pageIdx]) pageLedger[pageIdx].extractedCount = ledgerPageCapturedCount(pageLedger[pageIdx]);
  }

  function selectLedgerPage(idx) {
    if (idx < 0 || idx >= pageLedger.length) return;
    syncPageEditsToLedger(activeLedgerPageIndex);
    activeLedgerPageIndex = idx;
    var entry = pageLedger[idx];
    renderPageLedger();
    renderEventMetricsTable(entry.metrics, { pageNum: entry.pageNum, ledgerMode: true });
    renderPageNarratives(entry.narratives, { pageNum: entry.pageNum, ledgerMode: true });
    updateLedgerSummaryHint();
    updatePageAlignHint(entry);
  }

  function collectAllMetricsFromLedger() {
    syncPageEditsToLedger(activeLedgerPageIndex);
    var merged = [];
    pageLedger.forEach(function (p) {
      merged = mergeMetricRows(merged, p.metrics || []);
    });
    pendingEventParse.metrics = merged;
    return merged;
  }

  function narrativeRowKey(r) {
    return [(r.category || ''), (r.content || '')].join('|');
  }

  function mergeNarrativeRows(existing, incoming) {
    var seen = {};
    var out = [];
    (existing || []).concat(incoming || []).forEach(function (r) {
      var k = narrativeRowKey(r);
      if (!k || k === '|' || seen[k]) return;
      seen[k] = true;
      out.push(r);
    });
    return out;
  }

  function collectAllNarrativesFromLedger() {
    syncPageEditsToLedger(activeLedgerPageIndex);
    var merged = [];
    var hospital = '';
    pageLedger.forEach(function (p) {
      merged = mergeNarrativeRows(merged, p.narratives || []);
      if (!hospital && p.hospital) hospital = p.hospital;
    });
    if (!hospital && eventHospitalInput && eventHospitalInput.value.trim()) {
      hospital = eventHospitalInput.value.trim();
    }
    return { narratives: merged, hospital: hospital };
  }

  function renderEventMetricsTable(rows, opts) {
    opts = opts || {};
    if (!opts.ledgerMode) pendingEventParse.metrics = rows || [];
    if (!eventMetricsBody) return;
    eventMetricsBody.innerHTML = '';
    var abnormalN = 0;
    (rows || []).forEach(function (r, idx) {
      if (r.is_abnormal) abnormalN++;
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td><input data-k="item" data-i="' + idx + '" value="' + esc(r.item || r.metric_name || '') + '" /></td>' +
        '<td><input data-k="value" data-i="' + idx + '" value="' + esc(r.value_text != null && r.value_text !== '' ? r.value_text : (r.value != null ? r.value : '')) + '" /></td>' +
        '<td><input data-k="unit" data-i="' + idx + '" value="' + esc(r.unit || '') + '" /></td>' +
        '<td><input data-k="ref" data-i="' + idx + '" value="' + esc(r.ref || r.reference_range || '') + '" /></td>';
      eventMetricsBody.appendChild(tr);
    });
    var showPreview = opts.ledgerMode || pageLedger.length > 0;
    if (showPreview && eventPagePreview) eventPagePreview.classList.remove('hidden');
    else if (eventPagePreview && !pageLedger.length) eventPagePreview.classList.add('hidden');
    if (eventMetricsEmpty) {
      if ((rows || []).length) eventMetricsEmpty.classList.add('hidden');
      else eventMetricsEmpty.classList.remove('hidden');
    }
    if (eventMetricsTableWrap) {
      if ((rows || []).length) eventMetricsTableWrap.classList.remove('hidden');
      else eventMetricsTableWrap.classList.add('hidden');
    }
    if (eventMetricsPageLabel && opts.pageNum) {
      eventMetricsPageLabel.textContent = '版块 A · 第 ' + opts.pageNum + ' 页数字指标（' + (rows || []).length + ' 项）';
    }
    if (eventAbnormalHint) {
      eventAbnormalHint.textContent = abnormalN
        ? ('⚠ 本页数字指标异常约 ' + abnormalN + ' 个')
        : (pageLedger.length > 1 ? '仅数字检验项进版块 A；大段文字请放版块 B' : '');
    }
  }

  function collectEventMetricsFromTable() {
    if (!eventMetricsBody) return [];
    var out = [];
    eventMetricsBody.querySelectorAll('tr').forEach(function (tr) {
      var item = (tr.querySelector('input[data-k="item"]') || {}).value || '';
      var val = (tr.querySelector('input[data-k="value"]') || {}).value || '';
      var unit = (tr.querySelector('input[data-k="unit"]') || {}).value || '';
      var ref = (tr.querySelector('input[data-k="ref"]') || {}).value || '';
      if (!item.trim()) return;
      var num = parseFloat(String(val).replace(/,/g, ''));
      out.push({
        item: item.trim(),
        metric_name: item.trim(),
        value: isNaN(num) ? null : num,
        value_text: val,
        unit: unit.trim(),
        ref: ref.trim(),
        reference_range: ref.trim()
      });
    });
    return out;
  }

  function collectNarrativesFromDom() {
    if (!eventNarrativesList) return [];
    var out = [];
    eventNarrativesList.querySelectorAll('.pha-narrative-card').forEach(function (card) {
      var cat = (card.querySelector('.pha-narrative-category') || {}).value || '';
      var content = (card.querySelector('.pha-narrative-content') || {}).value || '';
      if (!content.trim()) return;
      var trimmed = content.trim();
      out.push({
        category: cat.trim() || '未分类',
        content: trimmed,
        summary: trimmed.length > 50 ? trimmed.slice(0, 50) + '…' : trimmed
      });
    });
    return out;
  }

  function renderPageNarratives(narratives, opts) {
    opts = opts || {};
    if (!eventNarrativesList) return;
    eventNarrativesList.innerHTML = '';
    (narratives || []).forEach(function (n, idx) {
      var card = document.createElement('div');
      card.className = 'pha-narrative-card';
      card.innerHTML =
        '<label>板块归类</label><input class="pha-narrative-category" value="' + esc(n.category || '') + '" />' +
        '<label style="margin-top:0.35rem">原文描述</label><textarea class="pha-narrative-content">' + esc(n.content || '') + '</textarea>' +
        '<button type="button" class="pha-narrative-remove" data-i="' + idx + '">删除本段</button>';
      eventNarrativesList.appendChild(card);
    });
    if (eventNarrativesEmpty) {
      if ((narratives || []).length) eventNarrativesEmpty.classList.add('hidden');
      else eventNarrativesEmpty.classList.remove('hidden');
    }
    if (eventNarrativesLabel && opts.pageNum) {
      eventNarrativesLabel.textContent = '版块 B · 第 ' + opts.pageNum + ' 页健康叙事（' + (narratives || []).length + ' 段）';
    }
    eventNarrativesList.querySelectorAll('.pha-narrative-remove').forEach(function (btn) {
      btn.addEventListener('click', function () {
        syncPageEditsToLedger(activeLedgerPageIndex);
        var rm = parseInt(btn.getAttribute('data-i'), 10);
        var entry = pageLedger[activeLedgerPageIndex];
        if (!entry) return;
        entry.narratives.splice(rm, 1);
        rebalanceLedgerTracks(entry);
        renderPageNarratives(entry.narratives, { pageNum: entry.pageNum, ledgerMode: true });
        renderPageLedger();
        updateLedgerSummaryHint();
        updatePageAlignHint(entry);
      });
    });
  }

  function pageDataToNarrativeRows(data) {
    if (!data) return [];
    if (data.narratives_preview && data.narratives_preview.length) return data.narratives_preview;
    var ext = data.extraction;
    if (!ext || !ext.narratives) return [];
    var hosp = ext.hospital || '';
    return ext.narratives.map(function (n) {
      var content = n.content || '';
      return {
        category: n.category || '未分类',
        content: content,
        summary: n.summary || (content.length > 50 ? content.slice(0, 50) + '…' : content),
        hospital: hosp
      };
    });
  }

  var VISION_PAGE_CONCURRENCY = 1;
  var VISION_PAGE_COOLDOWN_MS = 2000;

  function sleepMs(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }
  var pendingPageExtractions = [];

  function pageDataToMetricRows(data) {
    if (!data) return [];
    if (data.metrics_preview && data.metrics_preview.length) return data.metrics_preview;
    var ext = data.extraction;
    if (!ext || !ext.results) return [];
    return ext.results.map(function (r) {
      return {
        item: r.item,
        metric_name: r.item,
        value_text: r.value,
        unit: r.unit || '',
        ref: r.ref || '',
        reference_range: r.ref || '',
        is_abnormal: !!r.is_abnormal
      };
    });
  }

  function metricRowKey(r) {
    return [r.item || r.metric_name, r.value_text != null ? r.value_text : r.value, r.unit, r.ref || r.reference_range].join('|');
  }

  function mergeMetricRows(existing, incoming) {
    var seen = {};
    var out = [];
    (existing || []).concat(incoming || []).forEach(function (r) {
      var k = metricRowKey(r);
      if (!k || seen[k]) return;
      seen[k] = true;
      out.push(r);
    });
    return out;
  }

  function rebuildSummaryFromPages() {
    var lines = [];
    pendingPageExtractions.forEach(function (ext, i) {
      if (!ext) return;
      if (ext.title) lines.push('【报告·第' + (i + 1) + '页】' + ext.title);
      if (ext.date) lines.push('【日期】' + ext.date);
      (ext.results || []).forEach(function (r) {
        var seg = [r.item, r.value, r.unit, r.ref].filter(Boolean).join(' | ');
        if (seg) lines.push('- ' + seg);
      });
      (ext.narratives || []).forEach(function (n) {
        var seg = [(n.category || '叙事'), n.content].filter(Boolean).join(': ');
        if (seg) lines.push('- [' + seg + ']');
      });
    });
    var es = document.getElementById('event-summary');
    if (es && lines.length) es.value = lines.join('\n');
  }

  function updatePageLedgerEntry(pi, pageData, err) {
    if (!pageLedger[pi]) return;
    var entry = pageLedger[pi];
    if (err || !pageData || pageData.parse_ok === false) {
      entry.status = 'skipped';
      entry.metrics = [];
      entry.narratives = [];
      entry.total_detected_rows = null;
      entry.extractedCount = 0;
      if (pageData && pageData.parse_ok === false) {
        var warn = pageData.warning || '本页解析失败';
        showToast('⚠ 第 ' + entry.pageNum + ' 页已跳过: ' + warn, 'error');
      }
    } else {
      entry.status = 'success';
      if (pageData.vision_model) pendingEventParse.vision_model = pageData.vision_model;
      var tracks = splitTracksFromPageData(pageData);
      entry.metrics = tracks.metrics;
      entry.narratives = tracks.narratives;
      rebalanceLedgerTracks(entry);
      var det = pageData.total_detected_rows_in_page;
      if (det == null && pageData.extraction) det = pageData.extraction.total_detected_rows_in_page;
      entry.total_detected_rows = det != null ? Number(det) : null;
      if (pageData.extraction) {
        pendingPageExtractions[pi] = pageData.extraction;
        if (pageData.extraction.hospital) {
          entry.hospital = pageData.extraction.hospital;
          if (eventHospitalInput && !eventHospitalInput.value.trim()) {
            eventHospitalInput.value = pageData.extraction.hospital;
          }
        }
        if (pageData.extraction.title) {
          var et = document.getElementById('event-title');
          if (et && !et.value.trim()) et.value = pageData.extraction.title;
        }
        if (pageData.extraction.date) {
          var ed = document.getElementById('event-date');
          if (ed && pageData.extraction.date.length >= 8) ed.value = String(pageData.extraction.date).slice(0, 10);
        }
      }
      if (ledgerAlignmentGap(entry) > 0) {
        showToast(
          '⚠ 第 ' + entry.pageNum + ' 页对齐缺口 ' + ledgerAlignmentGap(entry) + '（可见 ' + entry.total_detected_rows + ' 行 − 数字 ' + ledgerMetricCount(entry) + ' − 叙事 ' + ledgerNarrativeCount(entry) + '）',
          'error'
        );
      }
      var etype = document.getElementById('event-type');
      if (etype) etype.value = 'lab_report';
    }
    renderPageLedger();
    updateLedgerSummaryHint();
    if (pi === activeLedgerPageIndex) {
      renderEventMetricsTable(entry.metrics, { pageNum: entry.pageNum, ledgerMode: true });
      renderPageNarratives(entry.narratives, { pageNum: entry.pageNum, ledgerMode: true });
      updatePageAlignHint(entry);
    }
    rebuildSummaryFromPages();
  }

  async function fetchParsePage(file, pageIndex, pageTotal) {
    var fd = new FormData();
    fd.append('file', file, file.name);
    fd.append('page_index', String(pageIndex));
    fd.append('page_total', String(pageTotal));
    var pdfOv = getPdfModelOverride();
    if (pdfOv) fd.append('pdf_model_override', pdfOv);
    var res = await fetch('/vision/parse-page', { method: 'POST', body: fd });
    if (!res.ok) {
      var pe = await readHttpErrorDetail(res);
      if (res.status !== 422) maybeShowParseErrorModal(res, pe);
      throw new Error(pe.detail || ('HTTP ' + res.status));
    }
    return await res.json();
  }

  async function runPagePool(file, total, concurrency, onPageDone) {
    var completed = 0;
    var nextIdx = 0;
    var errors = [];

    async function worker() {
      while (true) {
        var pi = nextIdx++;
        if (pi >= total) return;
        try {
          var data = await fetchParsePage(file, pi, total);
          completed++;
          if (onPageDone) onPageDone(pi, total, data, completed);
        } catch (e) {
          errors.push({ page: pi + 1, error: e });
          completed++;
          if (onPageDone) onPageDone(pi, total, null, completed, e);
          showToast('⚠ 第 ' + (pi + 1) + ' 页请求失败，已跳过: ' + (e.message || e), 'error');
        }
        if (pi + 1 < total) await sleepMs(VISION_PAGE_COOLDOWN_MS);
      }
    }

    var nWorkers = Math.max(1, Math.min(concurrency, total));
    var workers = [];
    for (var w = 0; w < nWorkers; w++) workers.push(worker());
    await Promise.all(workers);
    if (errors.length) {
      var msg = errors.map(function (x) { return '第' + x.page + '页: ' + (x.error.message || x.error); }).join('; ');
      var anyData = pageLedger.some(function (p) { return ledgerPageCapturedCount(p) > 0; });
      if (!anyData && pendingEventParse.metrics.length === 0) throw new Error(msg);
      showToast('⚠ 部分页面解析失败: ' + msg, 'error');
    }
  }

  async function visionParseSharded(file, opts) {
    opts = opts || {};
    var visionStatus = document.getElementById('vision-status');
    pendingEventParse.source_filename = file.name;
    pendingEventParse.metrics = [];
    pendingPageExtractions = [];
    renderEventMetricsTable([]);

    if (visionParseProgress) {
      visionParseProgress.classList.remove('hidden');
      visionParseProgress.value = 0;
    }
    if (visionStatus) visionStatus.textContent = 'AI 正在阅片…';

    var isPdf = /\.pdf$/i.test(file.name || '');
    var total = 1;

    if (isPdf) {
      if (visionStatus) visionStatus.textContent = '正在分析 PDF 页数…';
      var infoFd = new FormData();
      infoFd.append('file', file, file.name);
      var infoRes = await fetch('/vision/pdf-info', { method: 'POST', body: infoFd });
      if (!infoRes.ok) {
        var ie = await readHttpErrorDetail(infoRes);
        throw new Error(ie.detail || '无法读取 PDF 页数');
      }
      var info = await infoRes.json();
      total = info.pages_to_process || info.total_pages || 1;
      if (info.total_pages > info.pages_to_process) {
        showToast('PDF 共 ' + info.total_pages + ' 页，将处理前 ' + total + ' 页', 'info');
      }
    }

    initPageLedger(total);
    pendingPageExtractions = new Array(total);
    eventPagePreview && eventPagePreview.classList.remove('hidden');
    renderEventMetricsTable([], { pageNum: 1, ledgerMode: total > 0 });
    renderPageNarratives([], { pageNum: 1, ledgerMode: total > 0 });

    await runPagePool(file, total, VISION_PAGE_CONCURRENCY, function (pi, tot, data, completed, err) {
      var pct = Math.round((completed / tot) * 100);
      if (visionParseProgress) visionParseProgress.value = Math.min(99, pct);
      if (err) {
        updatePageLedgerEntry(pi, null, err);
        if (visionStatus) visionStatus.textContent = '第 ' + (pi + 1) + '/' + tot + ' 页失败: ' + (err.message || err);
        return;
      }
      updatePageLedgerEntry(pi, data, null);
      var pack = collectAllNarrativesFromLedger();
      var n = collectAllMetricsFromLedger().length;
      if (visionStatus) {
        visionStatus.textContent = '第 ' + (pi + 1) + '/' + tot + ' 页完成 · 合并数字 ' + n + ' 项 + 叙事 ' + pack.narratives.length + ' 段';
      }
      if (visionStatus) {
        visionStatus.textContent = '第 ' + (pi + 1) + '/' + tot + ' 页完成';
      }
    });

    if (visionParseProgress) visionParseProgress.value = 100;
    var mergedN = collectAllMetricsFromLedger().length;
    var mergedPack = collectAllNarrativesFromLedger();
    if (visionStatus) {
      visionStatus.textContent = '全部 ' + total + ' 页完成：数字 ' + mergedN + ' 项 + 叙事 ' + mergedPack.narratives.length + ' 段';
    }
    if (!opts.skipAutoIngest) {
      if (mergedN || mergedPack.narratives.length) {
        try {
          var ing = await autoIngestDrawerLedger(
            collectAllMetricsFromLedger(),
            mergedPack.narratives,
            mergedPack.hospital
          );
          if (visionStatus) {
            visionStatus.textContent +=
              ' · 已自动入库 ' + (ing.metrics_stored || 0) + ' 项（可核对后提交事件）';
          }
          showToast('✅ 抽屉阅片已自动入库 SQLite', 'success');
          await loadHealthAssets({ animateIn: true });
          await loadHeroStats();
        } catch (ingErr) {
          showToast('⚠ 自动入库失败: ' + (ingErr.message || ingErr), 'error');
          if (visionStatus) {
            visionStatus.textContent += ' · 自动入库失败，请点「提交事件」';
          }
        }
      } else {
        showToast('⚠ 阅片未提取到可入库指标，请检查文件或视觉模型', 'error');
      }
    }
  }

  if (eventMetricsAddRow) {
    eventMetricsAddRow.addEventListener('click', function () {
      if (!pageLedger.length) {
        var rows = collectEventMetricsFromTable();
        rows.push({ item: '', metric_name: '', value_text: '', unit: '', ref: '', reference_range: '' });
        renderEventMetricsTable(rows);
        return;
      }
      syncPageEditsToLedger(activeLedgerPageIndex);
      var entry = pageLedger[activeLedgerPageIndex];
      entry.metrics = (entry.metrics || []).concat([
        { item: '', metric_name: '', value_text: '', unit: '', ref: '', reference_range: '' }
      ]);
      entry.extractedCount = ledgerPageCapturedCount(entry);
      entry.status = ledgerPageCapturedCount(entry) ? 'success' : entry.status;
      renderPageLedger();
      renderEventMetricsTable(entry.metrics, { pageNum: entry.pageNum, ledgerMode: true });
      updateLedgerSummaryHint();
    });
  }

  if (eventPagePreview) {
    eventPagePreview.addEventListener('input', function () { refreshLedgerChipAfterEdit(); });
    eventPagePreview.addEventListener('change', function () { refreshLedgerChipAfterEdit(); });
  }

  if (eventNarrativesAdd) {
    eventNarrativesAdd.addEventListener('click', function () {
      if (!pageLedger.length) {
        var narr = collectNarrativesFromDom();
        narr.push({ category: '未分类', content: '', summary: '' });
        renderPageNarratives(narr);
        return;
      }
      syncPageEditsToLedger(activeLedgerPageIndex);
      var entry = pageLedger[activeLedgerPageIndex];
      entry.narratives = (entry.narratives || []).concat([{ category: '未分类', content: '', summary: '' }]);
      entry.extractedCount = ledgerPageCapturedCount(entry);
      entry.status = ledgerPageCapturedCount(entry) ? 'success' : entry.status;
      renderPageNarratives(entry.narratives, { pageNum: entry.pageNum, ledgerMode: true });
      renderPageLedger();
      updateLedgerSummaryHint();
    });
  }

  function resolveSubmitHospital(narrPack) {
    if (eventHospitalInput && eventHospitalInput.value.trim()) {
      return eventHospitalInput.value.trim();
    }
    if (narrPack && narrPack.hospital) return narrPack.hospital;
    for (var i = 0; i < pageLedger.length; i++) {
      if (pageLedger[i].hospital) return pageLedger[i].hospital;
    }
    return '';
  }

  function ensureEventTitleFallback(hospital) {
    var titleEl =
      document.getElementById('report-title') ||
      document.getElementById('event-title');
    if (!titleEl) return '';
    var current = titleEl.value.trim();
    if (current) return current;
    var dateStr =
      eventDate && eventDate.value
        ? String(eventDate.value).trim().slice(0, 10)
        : new Date().toISOString().slice(0, 10);
    var hosp = (hospital || '').trim();
    var fallback = hosp
      ? hosp + ' ' + dateStr + ' 体检报告'
      : dateStr + ' 体检报告';
    if (!hosp && pendingEventParse.source_filename) {
      var stem = pendingEventParse.source_filename.replace(/\.[^.]+$/, '');
      if (stem) fallback = stem + ' ' + dateStr + ' 体检报告';
    }
    titleEl.value = fallback;
    return fallback;
  }

  function buildEventSummaryForSubmit() {
    var full = (document.getElementById('event-summary') || {}).value;
    full = (full || '').trim();
    if (full.length <= 2000) return full;
    return full.substring(0, 2000) + '... (余下文本已安全存入叙事表)';
  }

  var eventSubmitBtn = document.getElementById('event-submit');
  if (eventSubmitBtn) eventSubmitBtn.addEventListener('click', async function () {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    var metrics = pageLedger.length ? collectAllMetricsFromLedger() : collectEventMetricsFromTable();
    var narrPack = pageLedger.length ? collectAllNarrativesFromLedger() : { narratives: collectNarrativesFromDom(), hospital: '' };
    var hospital = resolveSubmitHospital(narrPack);
    var title = ensureEventTitleFallback(hospital);
    var body = {
      user_id: uid,
      occurred_on: eventDate.value,
      event_type: document.getElementById('event-type').value,
      title: title,
      summary: buildEventSummaryForSubmit(),
      is_milestone: document.getElementById('event-milestone').checked,
      metrics: metrics,
      narratives: narrPack.narratives,
      hospital: hospital,
      source_filename: pendingEventParse.source_filename || '',
      vision_model: pendingEventParse.vision_model || '',
      persist_metrics: metrics.length > 0,
      persist_narratives: narrPack.narratives.length > 0
    };
    var es = document.getElementById('event-status');
    if (es) es.textContent = '正在提交…';
    try {
    var res = await fetch('/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        var er = await readHttpErrorDetail(res);
        throw new Error(er.detail);
      }
      var data = await res.json();
      if (es) {
        es.textContent = data.message || ('已保存，入库 ' + (data.metrics_stored || 0) + ' 项');
      }
      showParseToast('✅ ' + (data.message || '事件与指标已保存'), 'success');
      flashHeroStats();
      await Promise.all([loadHeroStats(), loadHealthAssets()]);
      pendingEventParse = { metrics: [], vision_model: '', source_filename: '' };
      pageLedger = [];
      pendingPageExtractions = [];
      if (visionPageLedgerWrap) visionPageLedgerWrap.classList.add('hidden');
      if (visionPageLedger) visionPageLedger.innerHTML = '';
      if (eventPagePreview) eventPagePreview.classList.add('hidden');
      if (eventNarrativesList) eventNarrativesList.innerHTML = '';
      if (eventHospitalInput) eventHospitalInput.value = '';
      renderEventMetricsTable([]);
      renderPageNarratives([]);
    } catch (e) {
      if (es) es.textContent = String(e.message || e);
      showToast('❌ ' + String(e.message || e), 'error');
    }
  });

  var reportPick = document.getElementById('report-pick');
  var reportFile = document.getElementById('report-file');
  if (pdfModelOverrideSelect) {
    pdfModelOverrideSelect.addEventListener('change', function () {
      persistPdfModelOverride(pdfModelOverrideSelect.value);
      var vs = document.getElementById('vision-status');
      if (vs && !window.pdfParsing) {
        if (pdfModelOverrideSelect.value === '__auto__') vs.textContent = 'PDF 解析：智能选择本地最大文本模型';
        else if (pdfModelOverrideSelect.value === 'FALLBACK_TO_HEURISTIC') vs.textContent = 'PDF 解析：纯规则提取（不调用 LLM）';
        else vs.textContent = 'PDF 解析锁定: ' + pdfModelOverrideSelect.value;
      }
    });
  }
  if (dataDrawerCheckbox) {
    dataDrawerCheckbox.addEventListener('change', function () {
      if (dataDrawerCheckbox.checked) {
        loadPdfTextModels();
        loadHealthAssets();
      }
    });
  }

  async function autoIngestDrawerLedger(metrics, narratives, hospital) {
    var mets = metrics || [];
    var narrs = narratives || [];
    if (!mets.length && !narrs.length) return null;
    var uid = (userIdInput.value || 'default').trim() || 'default';
    var reportDate =
      eventDate && eventDate.value
        ? String(eventDate.value).trim().slice(0, 10)
        : new Date().toISOString().slice(0, 10);
    var res = await fetch('/api/drawer/ingest-parsed', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: uid,
        report_date: reportDate,
        hospital: hospital || '',
        source_filename: pendingEventParse.source_filename || 'drawer_upload',
        vision_model: pendingEventParse.vision_model || '',
        metrics: mets,
        narratives: narrs
      })
    });
    if (!res.ok) {
      var err = await readHttpErrorDetail(res);
      throw new Error(err.detail || '抽屉自动入库失败');
    }
    return res.json();
  }
  document.addEventListener('pointerdown', function (e) {
    var drawer = document.getElementById('data-drawer');
    if (!drawer || !drawer.checked) return;

    var t = e.target;
    if (!t || !t.closest) return;

    if (t.closest('#data-import-panel') ||
        t.closest('#open-import-trigger-btn') ||
        t.closest('label[for="data-drawer"]') ||
        t.tagName === 'OPTION' ||
        t.tagName === 'SELECT' ||
        t.classList.contains('dropdown-item')) {
      return;
    }

    drawer.checked = false;
  });
  if (reportPick && reportFile) reportPick.addEventListener('click', function () { reportFile.click(); });
  if (reportFile) reportFile.addEventListener('change', async function () {
    var files = reportFile.files;
    if (!files || !files.length) return;
    updateDrawerVisionHint(files[0]);
    var total = files.length;
    try {
      var batchMetrics = [];
      var batchNarratives = [];
      var batchNames = [];
      for (var fi = 0; fi < total; fi++) {
        if (total > 1) {
          showToast('正在解析第 ' + (fi + 1) + '/' + total + ' 份：' + files[fi].name, 'info');
        }
        await visionParseSharded(files[fi], { skipAutoIngest: total > 1 });
        batchMetrics = mergeMetricRows(batchMetrics, collectAllMetricsFromLedger());
        var pack = collectAllNarrativesFromLedger();
        batchNarratives = mergeNarrativeRows(batchNarratives, pack.narratives);
        batchNames.push(files[fi].name);
      }
      if (total > 1) {
        pendingEventParse.metrics = batchMetrics;
        pendingEventParse.source_filename = batchNames.join(' + ');
        renderEventMetricsTable(batchMetrics);
        showToast('已完成 ' + total + ' 份报告阅片（指标已合并）', 'success');
        if (batchMetrics.length || batchNarratives.length) {
          try {
            var batchHosp = '';
            for (var hi = 0; hi < pageLedger.length; hi++) {
              if (pageLedger[hi].hospital) { batchHosp = pageLedger[hi].hospital; break; }
            }
            await autoIngestDrawerLedger(batchMetrics, batchNarratives, batchHosp);
            await loadHealthAssets({ animateIn: true });
            await loadHeroStats();
          } catch (batchIngErr) {
            showToast('⚠ 合并入库失败: ' + (batchIngErr.message || batchIngErr), 'error');
          }
        }
      }
    } catch (e) {
      var visionStatus = document.getElementById('vision-status');
      if (visionStatus) visionStatus.textContent = String(e.message || e);
    } finally {
      reportFile.value = '';
      hideChatStatus();
      if (visionParseProgress) {
        setTimeout(function () { visionParseProgress.classList.add('hidden'); }, 800);
      }
    }
  });

  if (q) {
    q.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendAsk(); }
    });
  }
  if (sendBtn) sendBtn.addEventListener('click', sendAsk);
  if (modelSelect) {
    modelSelect.addEventListener('change', async function () {
      var next = modelSelect.value;
      if (lastLoadedModel && lastLoadedModel !== next) await unloadOllamaModel(lastLoadedModel);
      lastLoadedModel = next;
      updateActiveModelLabel();
    });
  }
  function collapseMoreMetricsDrawer() {
    var details = document.getElementById('more-metrics-container');
    if (details) details.open = false;
  }

  function visibleGroupedMetricTags() {
    if (!groupedMetricsEl) return [];
    return Array.prototype.slice.call(groupedMetricsEl.querySelectorAll('.pha-metric-tag'));
  }

  function handleMetricSearchEnter() {
    if (!metricSearchBar) return;
    var q = metricSearchBar.value || '';
    renderGroupedMetrics((metricsPayload && metricsPayload.groups) || [], q);
    var tags = visibleGroupedMetricTags();
    var details = document.getElementById('more-metrics-container');
    if (tags.length === 1) {
      if (details) details.open = true;
      tags[0].click();
      renderDynamicMetricCharts();
      collapseMoreMetricsDrawer();
    } else if (tags.length > 1) {
      if (details) details.open = true;
    }
  }

  if (metricSearchBar) {
    metricSearchBar.addEventListener('input', function () {
      renderGroupedMetrics((metricsPayload && metricsPayload.groups) || [], metricSearchBar.value);
    });
    metricSearchBar.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      handleMetricSearchEnter();
    });
  }
  if (aiDoctorBtn) {
    aiDoctorBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      runAiDoctorReview(false);
    });
  }
  applyAlertsCacheToHero();
  if (refreshTrends) refreshTrends.addEventListener('click', loadTrends);
  if (metricTrendPicker) {
    metricTrendPicker.addEventListener('change', function () {
      renderDynamicMetricCharts();
    });
  }
  userIdInput.addEventListener('change', function () {
    applyAlertsCacheToHero();
    loadTrends();
    loadHeroStats();
    loadHealthAssets();
    loadSyncStatus();
  });

  var statMedicalCard = document.getElementById('stat-medical-card');
  if (statMedicalCard) {
    statMedicalCard.addEventListener('click', openMedicalAlertsModal);
    statMedicalCard.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMedicalAlertsModal(); }
    });
  }

  var auditStreamBusy = false;
  var auditReportMarkdownBuf = '';

  function setAuditButtonLoading(loading) {
    var btn = document.getElementById('sidebar-deep-audit');
    if (!btn) return;
    btn.disabled = !!loading;
    btn.classList.toggle('is-audit-loading', !!loading);
    if (loading) {
      btn.dataset.auditLabel = btn.textContent;
      btn.textContent = '深度审计进行中…';
    } else if (btn.dataset.auditLabel) {
      btn.textContent = btn.dataset.auditLabel;
    }
  }

  function scrollConsultationPanels() {
    var thinkPre = document.getElementById('consultation-thinking-pre');
    var reportPre = document.getElementById('consultation-report-pre');
    if (thinkPre) thinkPre.scrollTop = thinkPre.scrollHeight;
    if (reportPre) reportPre.scrollTop = reportPre.scrollHeight;
  }

  function renderAuditReportMarkdown() {
    var reportPre = document.getElementById('consultation-report-pre');
    if (!reportPre) return;
    reportPre.innerHTML = renderMarkdown(auditReportMarkdownBuf);
    scrollConsultationPanels();
  }

  async function runDeepConsultation() {
    if (auditStreamBusy) return;
    var uid = (userIdInput.value || 'default').trim() || 'default';
    var modal = document.getElementById('consultation-modal');
    var thinkPre = document.getElementById('consultation-thinking-pre');
    var reportPre = document.getElementById('consultation-report-pre');
    var meta = document.getElementById('consultation-meta');
    var shimmer = document.getElementById('consultation-cot-shimmer');
    var cotDefault = 'M4 显存已满载 · 本地 DeepSeek-R1:14b 正在疯狂推导中...';
    auditReportMarkdownBuf = '';
    if (thinkPre) thinkPre.textContent = '';
    if (reportPre) reportPre.innerHTML = '';
    if (meta) meta.textContent = '路由锁定 deepseek-r1:14b · 正在打包 SQLite 双轨卷宗…';
    if (shimmer) shimmer.textContent = cotDefault;
    if (modal) modal.showModal();
    setAuditButtonLoading(true);
    auditStreamBusy = true;
    showToast('PHA 大脑 v1.6 · DeepSeek-R1:14b 大审计已启动', 'info');
    try {
      var res = await fetch('/analytics/global-audit?user_id=' + encodeURIComponent(uid), { method: 'POST' });
      if (!res.ok) {
        var er = await readHttpErrorDetail(res);
        throw new Error(er.detail || '大审计请求失败');
      }
      if (!res.body || !res.body.getReader) {
        throw new Error('浏览器不支持流式响应');
      }
      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buf = '';

      function consumeAuditStreamLine(rawLine) {
        var line = (rawLine || '').trim();
        if (!line) return null;
        if (line.indexOf('data:') === 0) line = line.replace(/^data:\s*/, '');
        try { return JSON.parse(line); } catch (parseErr) { return null; }
      }

      function drainAuditStreamBuffer(flushAll) {
        var events = [];
        var sseIdx;
        while ((sseIdx = buf.indexOf('\n\n')) !== -1) {
          var block = buf.slice(0, sseIdx);
          buf = buf.slice(sseIdx + 2);
          block.split('\n').forEach(function (ln) {
            var ev = consumeAuditStreamLine(ln);
            if (ev) events.push(ev);
          });
        }
        if (flushAll && buf.trim()) {
          var tailEv = consumeAuditStreamLine(buf);
          buf = '';
          if (tailEv) events.push(tailEv);
        } else {
          var lines = buf.split('\n');
          buf = lines.pop() || '';
          lines.forEach(function (ln) {
            var ev = consumeAuditStreamLine(ln);
            if (ev) events.push(ev);
          });
        }
        return events;
      }

      function handleAuditStreamEvent(ev) {
        if (!ev || !ev.event) return;
        if (ev.event === 'status') {
          if (meta) meta.textContent = (ev.model ? ev.model + ' · ' : '') + (ev.message || '');
          if (shimmer && ev.message) shimmer.textContent = ev.message;
          scrollConsultationPanels();
        } else if (ev.event === 'thinking' && thinkPre) {
          thinkPre.textContent += ev.delta || '';
          scrollConsultationPanels();
        } else if (ev.event === 'report') {
          auditReportMarkdownBuf += ev.delta || '';
          renderAuditReportMarkdown();
        } else if (ev.event === 'done') {
          if (meta) meta.textContent = (ev.model || 'deepseek-r1:14b') + ' · ' + (ev.generated_on || '');
          if (shimmer) shimmer.textContent = '思维链已闭合 · 大白皮书渲染完成';
          if (thinkPre && ev.thinking && !thinkPre.textContent) thinkPre.textContent = ev.thinking;
          if (ev.report_markdown) {
            auditReportMarkdownBuf = ev.report_markdown;
            lastAuditReportMarkdown = ev.report_markdown;
            renderAuditReportMarkdown();
          }
          showToast('✅ PHA 历史上第一次纯离线大审计已完成', 'success');
        } else if (ev.event === 'error') {
          throw new Error(ev.message || '大审计失败');
        }
      }

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buf += decoder.decode(chunk.value, { stream: true });
        drainAuditStreamBuffer(false).forEach(handleAuditStreamEvent);
      }
      drainAuditStreamBuffer(true).forEach(handleAuditStreamEvent);
    } catch (e) {
      if (meta) meta.textContent = '审计失败 · ' + (e.message || e);
      if (shimmer) shimmer.textContent = '推理中断，请检查 Ollama 与 deepseek-r1:14b';
      showToast('❌ 大审计异常：' + (e.message || e), 'error');
    } finally {
      auditStreamBusy = false;
      setAuditButtonLoading(false);
    }
  }

  var sideAudit = document.getElementById('sidebar-deep-audit');
  if (sideAudit) sideAudit.addEventListener('click', runDeepConsultation);


  var currentChatSessionId = null;
  var chatExtraSystemContext = '';
  var lastLoadedModel = '';
  var streamingAssistantBubble = null;
  var streamingMarkdownBuf = '';
  var chatSessionListEl = document.getElementById('chat-session-list');
  var chatSessionNewBtn = document.getElementById('chat-session-new');
  var lastAuditReportMarkdown = '';

  function updateActiveModelLabel() {
    if (!activeModelLabel) return;
    var m = (modelSelect && modelSelect.value) ? modelSelect.value : '—';
    activeModelLabel.textContent = '算力引擎 · ' + m;
  }

  async function unloadOllamaModel(modelName) {
    if (!modelName) return;
    try {
      await fetch('/api/models/unload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelName })
      });
    } catch (e) { /* ignore */ }
  }

  async function loadChatConfig() {
    try {
      var res = await fetch('/api/chat/config');
      if (!res.ok) return;
      var cfg = await res.json();
      if (activeModelLabel && cfg.keep_alive !== undefined) {
        updateActiveModelLabel();
      }
    } catch (e) { /* ignore */ }
  }

  function renderChatSessions(sessions, activeId) {
    if (!chatSessionListEl) return;
    chatSessionListEl.innerHTML = '';
    (sessions || []).forEach(function (s) {
      var li = document.createElement('li');
      li.className = 'pha-chat-session-item' + (s.id === activeId ? ' active' : '');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'pha-chat-session-btn';
      btn.textContent = s.title || '新会话';
      btn.dataset.sessionId = s.id;
      var del = document.createElement('button');
      del.type = 'button';
      del.className = 'pha-chat-session-del';
      del.textContent = '×';
      del.title = '删除会话';
      del.dataset.sessionId = s.id;
      li.appendChild(btn);
      li.appendChild(del);
      chatSessionListEl.appendChild(li);
    });
  }

  async function loadChatSessions() {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    try {
      var res = await fetch('/api/chat/sessions?user_id=' + encodeURIComponent(uid));
      if (!res.ok) return;
      var data = await res.json();
      renderChatSessions(data.sessions || [], currentChatSessionId);
    } catch (e) { /* ignore */ }
  }

  async function loadChatSessionMessages(sessionId) {
    if (!sessionId || !chat) return;
    var uid = (userIdInput.value || 'default').trim() || 'default';
    chat.innerHTML = '';
    try {
      var res = await fetch(
        '/api/chat/sessions/' + encodeURIComponent(sessionId) + '/messages?user_id=' + encodeURIComponent(uid)
      );
      if (!res.ok) return;
      var data = await res.json();
      (data.messages || []).forEach(function (m) {
        if (m.role === 'user') appendChat(m.content, 'user');
        else appendAssistantWithEvidence(m.content, [], m.content);
      });
    } catch (e) { /* ignore */ }
  }

  async function createNewChatSession() {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    var res = await fetch('/api/chat/sessions?user_id=' + encodeURIComponent(uid), { method: 'POST' });
    if (!res.ok) return;
    var data = await res.json();
    currentChatSessionId = data.id;
    chatExtraSystemContext = '';
    if (chat) chat.innerHTML = '';
    await loadChatSessions();
  }

  function beginStreamingAssistantBubble() {
    streamingMarkdownBuf = '';
    streamingAssistantBubble = appendChat('<span class="text-slate-400">…</span>', 'assistant');
    return streamingAssistantBubble;
  }

  function appendStreamingAssistantDelta(delta) {
    if (!streamingAssistantBubble) beginStreamingAssistantBubble();
    streamingMarkdownBuf += delta || '';
    var bubble = streamingAssistantBubble.querySelector('.pha-chat-bubble');
    if (bubble) bubble.innerHTML = renderMarkdown(streamingMarkdownBuf);
    if (chat) chat.scrollTop = chat.scrollHeight;
  }

  function parseChatSsePayload(raw) {
    var line = (raw || '').trim();
    if (!line) return null;
    if (line.indexOf('data:') === 0) line = line.replace(/^data:\s*/, '');
    if (!line || line === '[DONE]') return null;
    try {
      var obj = JSON.parse(line);
      if (obj && !obj.event && obj.type) obj.event = obj.type;
      if (obj && !obj.event && obj.message && !obj.delta) obj.event = 'status';
      return obj;
    } catch (e) {
      return null;
    }
  }

  async function uploadChatAttachment(file) {
    var uid = (userIdInput.value || 'default').trim() || 'default';
    var fd = new FormData();
    fd.append('user_id', uid);
    fd.append('file', file);
    var res = await fetch('/api/chat/attachments', { method: 'POST', body: fd });
    if (!res.ok) {
      var err = await readHttpErrorDetail(res);
      throw new Error(err.detail || '附件上传失败');
    }
    return res.json();
  }

  if (chatAttachFile) {
    chatAttachFile.addEventListener('change', async function () {
      var files = chatAttachFile.files ? Array.prototype.slice.call(chatAttachFile.files) : [];
      pendingChatAttachment = null;
      pendingAttachMeta = null;
      pendingAttachBundle = null;
      attachParseInFlight = false;
      if (chatAttachLabel) chatAttachLabel.textContent = '';
      if (!files.length) return;
      var uid = (userIdInput.value || 'default').trim() || 'default';
      try {
        showChatStatus('📎 正在上传 ' + files.length + ' 个附件…', { pin: false });
        var paths = [];
        var names = [];
        for (var fi = 0; fi < files.length; fi++) {
          var f = files[fi];
          var meta = await uploadChatAttachment(f);
          paths.push(meta.attachment_path);
          names.push(meta.attachment_name || f.name);
        }
        pendingAttachBundle = { paths: paths, names: names };
        pendingAttachMeta = { attachment_path: paths[0], attachment_name: names[0] };
        if (chatAttachLabel) {
          chatAttachLabel.textContent = files.length > 1
            ? ('已上传：' + files.length + ' 个附件')
            : ('已上传：' + names[0]);
        }
        showChatStatus(
          '📎 已上传，可直接输入问题并发送（服务端将 OCR + 视觉解析）',
          { pin: false }
        );
        loadHealthAssets();
      } catch (e) {
        pendingAttachBundle = null;
        pendingAttachMeta = null;
        if (chatAttachLabel) chatAttachLabel.textContent = '上传异常';
        showChatStatus(String(e.message || e), { pin: true });
      }
    });
  }

  async function sendAsk() {
    var model = (modelSelect.value || '').trim();
    if (!model) return appendError({ status: 0 }, '未选择模型');
    var msg = (q.value || '').trim();
    if (!msg && !(pendingAttachBundle && pendingAttachBundle.paths && pendingAttachBundle.paths.length)) return;
    var attachLabel = '';
    if (pendingAttachBundle && pendingAttachBundle.names && pendingAttachBundle.names.length) {
      attachLabel = pendingAttachBundle.names.join(' + ');
    } else if (pendingChatAttachment && pendingChatAttachment.name) {
      attachLabel = pendingChatAttachment.name;
    }
    appendChat(msg || ('[附件] ' + attachLabel), 'user');
    q.value = '';
    sendBtn.disabled = true;
    pinnedTemporalStatus = '';
    auditPanelShownThisTurn = false;
    if (/睡眠|步数|心率|hrv|体检|分析|对比|20\d{2}/i.test(msg)) {
      showChatStatus('AI 正在勾兑时间轴：等待服务端确认年份与体检锚点…', { pin: false });
    }
    beginStreamingAssistantBubble();
    var uid = (userIdInput.value || 'default').trim() || 'default';
    var attachMeta = pendingAttachMeta || null;
    try {
      pendingChatAttachment = null;
      var bundleSend = pendingAttachBundle;
      pendingAttachBundle = null;
      pendingAttachMeta = null;
      if (chatAttachFile) chatAttachFile.value = '';
      if (chatAttachLabel) chatAttachLabel.textContent = '';
      var body = {
        user_id: uid,
        message: msg,
        model: model,
        session_id: currentChatSessionId,
        extra_system_context: chatExtraSystemContext || ''
      };
      if (bundleSend && bundleSend.paths && bundleSend.paths.length) {
        body.attachment_paths = bundleSend.paths;
        body.attachment_names = bundleSend.names;
        if (bundleSend.paths.length === 1) {
          body.attachment_path = bundleSend.paths[0];
          body.attachment_name = bundleSend.names[0];
        }
      } else if (attachMeta && attachMeta.attachment_path) {
        body.attachment_path = attachMeta.attachment_path;
        body.attachment_name = attachMeta.attachment_name;
      }
      var res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        var _pe = await readHttpErrorDetail(res);
        maybeShowParseErrorModal(res, _pe);
        hideChatStatus();
        return appendError(res, _pe.detail);
      }
      if (!res.body || !res.body.getReader) throw new Error('浏览器不支持流式响应');
      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buf = '';
      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buf += decoder.decode(chunk.value, { stream: true });
        var parts = buf.split('\n\n');
        buf = parts.pop() || '';
        parts.forEach(function (block) {
          block.split('\n').forEach(function (ln) {
            var ev = parseChatSsePayload(ln);
            if (!ev) return;
            handleChatSseEvent(ev);
          });
        });
      }
    } catch (e) {
      hideChatStatus();
      appendError({ status: 0 }, String(e));
    } finally {
      sendBtn.disabled = !modelSelect.value;
      streamingAssistantBubble = null;
    }
  }

  function exportConsultationMarkdown() {
    var reportEl = document.getElementById('consultation-report-pre');
    var thinkEl = document.getElementById('consultation-thinking-pre');
    var md = '# PHA 深度健康审计报告\n\n';
    if (thinkEl && thinkEl.textContent.trim()) {
      md += '## 思维链\n\n' + thinkEl.textContent.trim() + '\n\n';
    }
    md += (reportEl && reportEl.innerText) ? reportEl.innerText.trim() : (lastAuditReportMarkdown || '');
    var blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'PHA-audit-' + new Date().toISOString().slice(0, 10) + '.md';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function followUpFromAudit() {
    var reportEl = document.getElementById('consultation-report-pre');
    var md = (reportEl && reportEl.innerText) ? reportEl.innerText.trim() : (lastAuditReportMarkdown || '');
    if (!md) return showToast('暂无审计报告可追问', 'error');
    chatExtraSystemContext = '[System Context: 深度审计报告内容]\n' + md.slice(0, 12000);
    var modal = document.getElementById('consultation-modal');
    if (modal) modal.close();
    if (q) {
      q.value = '基于这份刚刚生成的深度审计报告，我想追问：';
      q.focus();
    }
    showToast('已注入审计报告上下文，请继续提问', 'success');
  }

  loadHealth();
  loadModels();
  loadPdfTextModels();
  loadChatConfig();
  loadChatSessions();
  if (chatSessionNewBtn) chatSessionNewBtn.addEventListener('click', createNewChatSession);
  if (chatSessionListEl) {
    chatSessionListEl.addEventListener('click', async function (e) {
      var t = e.target;
      if (!t || !t.dataset) return;
      var sid = t.dataset.sessionId;
      if (!sid) return;
      var uid = (userIdInput.value || 'default').trim() || 'default';
      if (t.classList.contains('pha-chat-session-del')) {
        if (!confirm('删除此会话？')) return;
        await fetch('/api/chat/sessions/' + encodeURIComponent(sid) + '?user_id=' + encodeURIComponent(uid), { method: 'DELETE' });
        if (currentChatSessionId === sid) { currentChatSessionId = null; if (chat) chat.innerHTML = ''; }
        await loadChatSessions();
        return;
      }
      currentChatSessionId = sid;
      chatExtraSystemContext = '';
      await loadChatSessions();
      await loadChatSessionMessages(sid);
    });
  }
  var exportMdBtn = document.getElementById('consultation-export-md');
  var followupBtn = document.getElementById('consultation-followup-chat');
  if (exportMdBtn) exportMdBtn.addEventListener('click', exportConsultationMarkdown);
  if (followupBtn) followupBtn.addEventListener('click', followUpFromAudit);
  userIdInput.addEventListener('change', function () { loadChatSessions(); });

  refreshVisionStatus();
  setInterval(refreshVisionStatus, 12000);
  loadTrends();
  loadHealthAssets();
  loadSyncModules();
  loadSyncStatus();
  setInterval(loadSyncStatus, 4000);
  if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
})();
