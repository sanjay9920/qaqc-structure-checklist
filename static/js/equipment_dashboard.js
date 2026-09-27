(function () {
  const config = window.equipmentTypeDashboard || {};
  const recordsBody = document.getElementById("equipmentTypeRecordsBody");
  const recordNumberInput = document.getElementById("equipment_record_number");
  const refreshStatus = document.getElementById("equipmentDashboardRefreshStatus");
  const recordSearch = document.getElementById("equipmentRecordSearch");
  const recordStatus = document.getElementById("equipmentRecordStatus");
  const recordResultCount = document.getElementById("equipmentRecordResultCount");
  if (!config.apiUrl || !recordsBody) return;

  let refreshInFlight = false;

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function equipmentUrl(equipmentId) {
    return `/equipment/${encodeURIComponent(equipmentId)}`;
  }

  function renderSummary(summary) {
    const values = summary || {};
    setText("typeTotalRecords", values.total_records || 0);
    setText("typeCompletedRecords", values.completed_records || 0);
    setText("typePendingRecords", values.pending_records || 0);
    setText("typeInProgressRecords", values.in_progress_records || 0);
    setText("typeNotStartedRecords", values.not_started_records || 0);
    setText("typeUniqueEquipment", values.unique_equipment_count || 0);
    setText("typeMissingIdentity", values.missing_identity_records || 0);
    setText("typeCompletedPoints", values.completed_points || 0);
    setText("typePendingPoints", values.pending_points || 0);
    setText("typeTotalPointsA", values.total_points || 0);
    setText("typeTotalPointsB", values.total_points || 0);
    setText("typeProgress", `${values.progress || 0}%`);
  }

  function renderRecord(record) {
    const counts = record.counts || {};
    const equipmentId = record.equipment_id || "";
    const progress = counts.progress || 0;
    const state = counts.pending === 0 && counts.total > 0
      ? "completed"
      : (counts.completed > 0 ? "in_progress" : "not_started");
    const statusLabel = state === "completed" ? "Complete" : (state === "in_progress" ? "In progress" : "Not started");
    const searchText = [record.record_number, record.equipment_identification, record.specification, record.vendor_name]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return `
      <tr data-record-search="${escapeHtml(searchText)}" data-record-status="${state}" data-missing-id="${record.equipment_identification ? "0" : "1"}">
        <td>${escapeHtml(record.record_number || "")}</td>
        <td><strong>${escapeHtml(record.equipment_identification || "Not set")}</strong></td>
        <td>${escapeHtml(record.specification || "-")}</td>
        <td>${escapeHtml(record.vendor_name || "-")}</td>
        <td><span class="record-state-badge record-state-${state}">${statusLabel}</span></td>
        <td>${counts.completed || 0} / ${counts.total || 0}</td>
        <td>${counts.pending || 0} / ${counts.total || 0}</td>
        <td>
          <div class="progress table-progress"><div class="progress-bar" style="width: ${progress}%"></div></div>
          <span class="small text-muted">${progress}%</span>
        </td>
        <td class="text-end">
          <div class="table-actions">
            <a class="btn btn-sm btn-outline-dark" href="${equipmentUrl(equipmentId)}"><i class="bi bi-eye" aria-hidden="true"></i> Open</a>
            <a class="btn btn-sm btn-outline-dark" href="${equipmentUrl(equipmentId)}/qr.png?download=1" download="${escapeHtml(equipmentId)}.png"><i class="bi bi-download" aria-hidden="true"></i> QR</a>
            <form action="/admin/equipment/${encodeURIComponent(equipmentId)}/delete" method="post" class="delete-equipment-form d-inline" data-equipment-id="${escapeHtml(equipmentId)}">
              <button class="btn btn-sm btn-danger" type="submit"><i class="bi bi-trash3" aria-hidden="true"></i> Delete permanently</button>
            </form>
          </div>
        </td>
      </tr>
    `;
  }

  function filterRecords() {
    const query = String(recordSearch && recordSearch.value || "").trim().toLowerCase();
    const status = recordStatus ? recordStatus.value : "all";
    const rows = Array.from(recordsBody.querySelectorAll("tr[data-record-search]"));
    let shown = 0;
    rows.forEach(function (row) {
      const matchesQuery = !query || String(row.dataset.recordSearch || "").includes(query);
      const matchesStatus = status === "all"
        || (status === "missing_id" && row.dataset.missingId === "1")
        || row.dataset.recordStatus === status;
      const visible = matchesQuery && matchesStatus;
      row.classList.toggle("d-none", !visible);
      if (visible) shown += 1;
    });
    if (recordResultCount) recordResultCount.textContent = `${shown} shown`;
  }

  function render(payload) {
    const records = Array.isArray(payload.records) ? payload.records : [];
    renderSummary(payload.summary || {});
    recordsBody.innerHTML = records.length
      ? records.map(renderRecord).join("")
      : '<tr><td colspan="9" class="text-center text-muted py-4">No equipment created. Add the first record above.</td></tr>';
    filterRecords();
    if (recordNumberInput && document.activeElement !== recordNumberInput) {
      recordNumberInput.value = payload.next_record_number || "01";
    }
  }

  async function readJson(response) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) return response.json();
    throw new Error("Unexpected server response. Please try again.");
  }

  async function refresh() {
    if (refreshInFlight || document.hidden) return;
    refreshInFlight = true;
    try {
      const response = await fetch(config.apiUrl, {
        headers: { "Accept": "application/json" }
      });
      const payload = await readJson(response);
      if (!response.ok) throw new Error(payload.error || "Refresh failed.");
      render(payload);
      if (refreshStatus) refreshStatus.textContent = "Live data updated";
    } catch (_error) {
      if (refreshStatus) refreshStatus.textContent = "Waiting for connection";
    } finally {
      refreshInFlight = false;
    }
  }

  recordsBody.addEventListener("submit", async function (event) {
    const form = event.target.closest(".delete-equipment-form");
    if (!form) return;
    event.preventDefault();
    const equipmentId = form.dataset.equipmentId;
    if (!confirm(`Permanently delete ${equipmentId} checklist, all saved points, remarks and history? This cannot be undone.`)) return;

    const button = form.querySelector("button");
    if (button) button.disabled = true;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { "Accept": "application/json", "X-Requested-With": "fetch" }
      });
      const payload = await readJson(response);
      if (!response.ok) throw new Error(payload.error || "Delete failed.");
      await refresh();
    } catch (error) {
      alert(error.message || "Delete failed.");
      if (button) button.disabled = false;
    }
  });

  if (recordSearch) recordSearch.addEventListener("input", filterRecords);
  if (recordStatus) recordStatus.addEventListener("change", filterRecords);

  setInterval(refresh, 30000);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) refresh();
  });
  window.addEventListener("online", refresh);
})();
