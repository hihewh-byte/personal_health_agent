#!/usr/bin/env python3
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
app = root / "pha" / "static" / "js" / "app.js"
patch = Path(__file__).resolve().parent / "patch_app_v17.js"
text = app.read_text(encoding="utf-8")
patch_text = patch.read_text(encoding="utf-8")

# Remove old updateActiveModelLabel and sendAsk
text = re.sub(
    r"\n  function updateActiveModelLabel\(\) \{.*?\n  \}\n",
    "\n",
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r"\n  async function sendAsk\(\) \{.*?\n  \}\n",
    "\n",
    text,
    count=1,
    flags=re.S,
)

# Insert patch before loadHealth
anchor = "  loadHealth();"
if patch_text.strip() not in text:
    text = text.replace(anchor, patch_text + "\n" + anchor, 1)

# model select: unload on change
old_listener = "  if (modelSelect) modelSelect.addEventListener('change', updateActiveModelLabel);"
new_listener = """  if (modelSelect) {
    modelSelect.addEventListener('change', async function () {
      var next = modelSelect.value;
      if (lastLoadedModel && lastLoadedModel !== next) await unloadOllamaModel(lastLoadedModel);
      lastLoadedModel = next;
      updateActiveModelLabel();
    });
  }"""
if old_listener in text:
    text = text.replace(old_listener, new_listener, 1)

# init hooks
init_anchor = "  loadModels();"
extra_init = """  loadChatConfig();
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
"""
if "loadChatSessions();" not in text.split("loadModels();")[1][:800]:
    text = text.replace(init_anchor, init_anchor + "\n" + extra_init, 1)

# lastAuditReportMarkdown in audit done
text = text.replace(
    "auditReportMarkdownBuf = ev.report_markdown;",
    "auditReportMarkdownBuf = ev.report_markdown;\n            lastAuditReportMarkdown = ev.report_markdown;",
)

# loadModels set lastLoadedModel
text = text.replace(
    "      selectDefaultModel(models);\n      updateActiveModelLabel();",
    "      selectDefaultModel(models);\n      lastLoadedModel = modelSelect.value || '';\n      updateActiveModelLabel();",
)

app.write_text(text, encoding="utf-8")
print("merged app.js")
