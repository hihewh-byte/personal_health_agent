
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
    try { return JSON.parse(line); } catch (e) { return null; }
  }

  async function sendAsk() {
    var model = (modelSelect.value || '').trim();
    if (!model) return appendError({ status: 0 }, '未选择模型');
    var msg = (q.value || '').trim();
    if (!msg) return;
    appendChat(msg, 'user');
    q.value = '';
    sendBtn.disabled = true;
    if (/睡眠|步数|心率|hrv|体检|分析/i.test(msg)) showChatStatus('🔍 正在扫描 SQLite 并注入语义历史…');
    beginStreamingAssistantBubble();
    var uid = (userIdInput.value || 'default').trim() || 'default';
    try {
      var res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: uid,
          message: msg,
          model: model,
          session_id: currentChatSessionId,
          extra_system_context: chatExtraSystemContext || ''
        })
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
            if (ev.event === 'status') {
              showChatStatus(ev.message || '处理中…');
              if (ev.session_id) currentChatSessionId = ev.session_id;
            } else if (ev.event === 'delta') {
              appendStreamingAssistantDelta(ev.delta || '');
            } else if (ev.event === 'done') {
              hideChatStatus();
              if (ev.session_id) currentChatSessionId = ev.session_id;
              var ans = ev.answer || {};
              var rawReply = ans.model_reply_raw || ans.answer_text || streamingMarkdownBuf;
              var parsed = parseEvidence(rawReply);
              var bubble = streamingAssistantBubble && streamingAssistantBubble.querySelector('.pha-chat-bubble');
              if (bubble) bubble.innerHTML = renderMarkdown(parsed.display || ans.answer_text || streamingMarkdownBuf);
              if (parsed.ids.length && ans.evidence_items && ans.evidence_items.length && streamingAssistantBubble) {
                var pills = document.createElement('div');
                pills.className = 'mt-2 flex flex-wrap gap-1';
                var map = {};
                ans.evidence_items.forEach(function (it) { if (it.ref_id) map[it.ref_id] = it.title || it.ref_id; });
                parsed.ids.forEach(function (id) {
                  var b = document.createElement('button');
                  b.className = 'rounded border border-gray-600 px-2 py-0.5 text-xs text-slate-300';
                  b.textContent = id;
                  b.title = map[id] || id;
                  pills.appendChild(b);
                });
                streamingAssistantBubble.querySelector('.pha-chat-bubble').appendChild(pills);
              }
              streamingAssistantBubble = null;
              loadChatSessions();
              loadTrends();
            } else if (ev.event === 'error') {
              throw new Error(ev.message || '对话失败');
            }
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
