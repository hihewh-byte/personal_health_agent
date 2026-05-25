"""One-off: rebuild index.html body tail."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
src = ROOT / "index.html"
lines = src.read_text(encoding="utf-8").splitlines()
out = []
for line in lines:
    if "<motion>" in line or "</motion>" in line:
        continue
    if 'pha-sidebar-logo">PHA' in line and "</motion>" in line:
        continue
    if "pha-sidebar-logo">PHA" in line and "</motion>" not in line and "</motion>" not in line:
        out.append('        <motion></motion>')
        continue
    out.append(line)
    if "today-steps" in line and "pha-card" in line:
        break

# fix sidebar if we skipped broken lines
if not any("pha-sidebar-logo" in l for l in out):
    pass

TAIL = """
        <div class="pha-card"><p class="pha-card-label">平均 HRV</p><p id="avg-hrv" class="pha-card-value">—</p><p class="pha-card-desc">RMSSD · ms</p></div>
        <div class="pha-card"><p class="pha-card-label">睡眠时长</p><p id="sleep-duration" class="pha-card-value">—</p><p class="pha-card-desc">近 7 日均 · h</p></div>
        <div id="stat-medical-card" class="pha-card" role="button" tabindex="0"><p class="pha-card-label">体检预警</p><p id="stat-medical" class="pha-card-value">—</p><p class="pha-card-desc">近 1 年</p></div>
      </div>
      <div class="pha-section">
        <div class="pha-section-head">
          <h2>趋势分析</h2>
          <div class="pha-tabs">
            <button type="button" class="tab-trends tab-active" data-trends-tab="charts">图表</button>
            <button type="button" class="tab-trends" data-trends-tab="raw">原始数据</button>
          </div>
          <button type="button" id="refresh-trends">刷新</button>
        </div>
        <div id="trends-charts-panel">
          <motion></motion>
"""

print("broken")
