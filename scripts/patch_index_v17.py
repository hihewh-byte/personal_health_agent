#!/usr/bin/env python3
from pathlib import Path

D = "div"

p = Path(__file__).resolve().parents[1] / "pha" / "index.html"
text = p.read_text(encoding="utf-8")

old_sidebar = (
    '        <label for="data-drawer" class="pha-nav-link">数据导入</label>\n'
    f"      </{D}>"
)
new_sidebar = (
    '        <label for="data-drawer" class="pha-nav-link">数据导入</label>\n'
    f'        <{D} class="pha-chat-sessions">\n'
    f'          <{D} class="pha-chat-sessions-head">\n'
    "            <span>历史健康会话</span>\n"
    '            <button type="button" id="chat-session-new" title="新建会话">+ 新建</button>\n'
    f"          </{D}>\n"
    '          <ul id="chat-session-list" aria-label="历史会话列表"></ul>\n'
    f"        </{D}>\n"
    f"      </{D}>"
)
if old_sidebar not in text:
    raise SystemExit("sidebar anchor not found")
text = text.replace(old_sidebar, new_sidebar, 1)

old_chat = (
    f'      <{D} class="pha-chat-panel">\n'
    f'        <{D} class="pha-chat-head">\n'
    '          <h2 style="margin:0;font-size:1rem;color:#f1f5f9">健康 AI 对话</h2>\n'
    '          <span style="font-size:0.75rem;color:#64748b">Cmd/Ctrl+Enter 发送</span>\n'
    f"        </{D}>\n"
    f'        <{D} id="chat-stream"></{D}>'
)
new_chat = (
    f'      <{D} class="pha-chat-panel">\n'
    f'        <{D} class="pha-chat-head">\n'
    '          <h2 style="margin:0;font-size:1rem;color:#f1f5f9">健康 AI 对话</h2>\n'
    '          <span style="font-size:0.75rem;color:#64748b">Cmd/Ctrl+Enter 发送 · SSE 流式</span>\n'
    f"        </{D}>\n"
    '        <p id="active-model-chip"><span id="active-model-label">算力引擎：探测中…</span></p>\n'
    f'        <{D} id="chat-stream"></{D}>\n'
)
if old_chat not in text:
    raise SystemExit("chat panel anchor not found")
text = text.replace(old_chat, new_chat, 1)

old_modal = (
    '      <button type="submit" style="margin-top:0.85rem">关闭</button>\n'
    "    </form>\n"
    "  </dialog>\n"
    "\n"
    '  <script src="/static/js/app.js"></script>'
)
new_modal = (
    f'      <{D} class="pha-consultation-actions">\n'
    '        <button type="button" id="consultation-export-md">📥 导出 Markdown</button>\n'
    '        <button type="button" id="consultation-followup-chat">💬 带着报告去追问</button>\n'
    f"      </{D}>\n"
    '      <button type="submit" style="margin-top:0.85rem">关闭</button>\n'
    "    </form>\n"
    "  </dialog>\n"
    "\n"
    '  <script src="/static/js/app.js"></script>'
)
if old_modal not in text:
    raise SystemExit("modal anchor not found")
text = text.replace(old_modal, new_modal, 1)

text = text.replace(
    "PHA 大脑 v1.6 · 纯离线全局大审计",
    "PHA 大脑 v1.7 · 工业级离线大审计",
    1,
)

p.write_text(text, encoding="utf-8")
print("ok", p)
