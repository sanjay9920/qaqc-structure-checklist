(function () {
  const container = document.getElementById("smartTrackingContent");
  if (!container) return;

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function safeUrl(value) {
    const url = String(value || "");
    return url.startsWith("/") && !url.startsWith("//") ? escapeHtml(url) : "";
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function percent(value) {
    return Math.max(0, Math.min(100, number(value)));
  }

  function renderEmpty() {
    return `
      <div class="smart-empty-state">
        <i class="bi bi-clipboard2-plus" aria-hidden="true"></i>
        <div><strong>Tracking starts with the first checklist</strong><span>Create a structure or equipment checklist to see priorities, bottlenecks and stale work.</span></div>
      </div>
    `;
  }

  function renderPriority(items) {
    if (!items.length) {
      return '<div class="smart-list-empty"><i class="bi bi-check-circle" aria-hidden="true"></i> All created work is complete.</div>';
    }
    return items.map(function (item) {
      const url = safeUrl(item.url);
      const progress = percent(item.progress);
      const content = `
        <span class="smart-severity is-${escapeHtml(item.severity || "normal")}">${escapeHtml(item.severity_label || "Next")}</span>
        <div class="smart-action-main"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.subtitle)} · Block ${escapeHtml(item.block_display || "-")}</small><span>${escapeHtml(item.reason)}</span></div>
        <div class="smart-action-progress"><b>${progress}%</b><div class="progress"><div class="progress-bar" style="width:${progress}%"></div></div></div>
        <i class="bi bi-chevron-right" aria-hidden="true"></i>
      `;
      return url ? `<a class="smart-action-row" href="${url}">${content}</a>` : `<div class="smart-action-row">${content}</div>`;
    }).join("");
  }

  function renderBlockPressure(items) {
    return items.map(function (item) {
      const progress = percent(item.progress);
      const url = safeUrl(item.url);
      return `
        <a class="smart-pressure-row" href="${url || "#"}">
          <div><strong>Block ${escapeHtml(item.block_display)}</strong><small>${number(item.pending_points)} pending points · ${number(item.pending_structures)} structures · ${number(item.pending_equipment)} equipment</small></div>
          <span class="smart-state is-${escapeHtml(item.state || "active")}">${escapeHtml(item.state_label || "In progress")}</span>
          <div class="smart-bar"><div style="width:${progress}%"></div></div><b>${progress}%</b>
        </a>
      `;
    }).join("");
  }

  function renderBottlenecks(items) {
    if (!items.length) {
      return '<div class="smart-list-empty"><i class="bi bi-check-circle" aria-hidden="true"></i> No checklist bottleneck.</div>';
    }
    return items.map(function (item) {
      const progress = percent(item.progress);
      const url = safeUrl(item.url);
      const tag = url ? "a" : "div";
      const href = url ? ` href="${url}"` : "";
      return `
        <${tag} class="smart-pressure-row"${href}>
          <div><strong>${escapeHtml(item.name)}</strong><small>${number(item.pending_records)} pending records · ${number(item.pending_points)} points</small></div>
          <span class="smart-state is-active">${progress}%</span>
          <div class="smart-bar"><div style="width:${progress}%"></div></div><b>${number(item.pending_points)}</b>
        </${tag}>
      `;
    }).join("");
  }

  function render(payload) {
    const data = payload || {};
    if (!data.has_work) {
      container.innerHTML = renderEmpty();
      return;
    }

    const priorityItems = Array.isArray(data.priority_items) ? data.priority_items : [];
    const blockItems = Array.isArray(data.block_pressure) ? data.block_pressure : [];
    const bottlenecks = Array.isArray(data.bottlenecks) ? data.bottlenecks : [];
    const insights = Array.isArray(data.insights) ? data.insights : [];
    const blockLane = blockItems.length ? `
      <section class="smart-lane" aria-labelledby="smartBlockTitle">
        <div class="smart-lane-heading"><div><span>Project pressure</span><h3 id="smartBlockTitle">Blocks needing focus</h3></div><b>${blockItems.length}</b></div>
        <div class="smart-list">${renderBlockPressure(blockItems)}</div>
      </section>
    ` : "";

    container.innerHTML = `
      <div class="smart-kpi-grid" aria-label="Smart tracking summary">
        <div class="smart-kpi"><i class="bi bi-list-check" aria-hidden="true"></i><div><span>Open points</span><strong>${number(data.pending_points)}</strong><small>${number(data.open_records)} open records</small></div></div>
        <div class="smart-kpi is-active"><i class="bi bi-activity" aria-hidden="true"></i><div><span>Active work</span><strong>${number(data.active_work)}</strong><small>${number(data.not_started)} not started</small></div></div>
        <div class="smart-kpi${number(data.stale_work) ? " is-warning" : ""}"><i class="bi bi-clock-history" aria-hidden="true"></i><div><span>Stale 7+ days</span><strong>${number(data.stale_work)}</strong><small>${number(data.updated_last_7_days)} updated recently</small></div></div>
        <div class="smart-kpi${number(data.data_gaps) ? " is-danger" : ""}"><i class="bi bi-exclamation-diamond" aria-hidden="true"></i><div><span>Data gaps</span><strong>${number(data.data_gaps)}</strong><small>${number(data.missing_identity)} IDs · ${number(data.missing_vendor)} vendors</small></div></div>
      </div>
      <div class="smart-insight-strip" aria-label="Automatic insights"><i class="bi bi-lightbulb" aria-hidden="true"></i><div>${insights.map(function (item) { return `<span>${escapeHtml(item)}</span>`; }).join("")}</div></div>
      <div class="smart-lanes${blockItems.length ? "" : " smart-lanes-two"}">
        <section class="smart-lane" aria-labelledby="smartPriorityTitle">
          <div class="smart-lane-heading"><div><span>Action queue</span><h3 id="smartPriorityTitle">Do next</h3></div><b>${number(data.priority_total)}</b></div>
          <div class="smart-list smart-priority-list">${renderPriority(priorityItems)}</div>
        </section>
        ${blockLane}
        <section class="smart-lane" aria-labelledby="smartBottleneckTitle">
          <div class="smart-lane-heading"><div><span>Pending load</span><h3 id="smartBottleneckTitle">Checklist bottlenecks</h3></div><b>${bottlenecks.length}</b></div>
          <div class="smart-list">${renderBottlenecks(bottlenecks)}</div>
        </section>
      </div>
    `;
  }

  window.smartTracking = { render: render };
})();
