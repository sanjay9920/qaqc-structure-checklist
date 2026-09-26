(function () {
  const statusClasses = {
    completed: "text-bg-success",
    pending: "text-bg-warning",
    na: "text-bg-secondary"
  };
  const baseUrl = `/api/equipment/${encodeURIComponent(window.equipmentId)}`;

  function labelFor(status) {
    return window.statusLabels[status] || status;
  }

  function updateSummary(counts) {
    document.getElementById("completedCount").textContent = counts.completed;
    document.getElementById("pendingCount").textContent = counts.pending;
    document.getElementById("naCount").textContent = counts.na;
    document.getElementById("totalCountA").textContent = counts.total;
    document.getElementById("totalCountB").textContent = counts.total;
    document.getElementById("progressValue").textContent = counts.progress + "%";
    document.getElementById("progressBar").style.width = counts.progress + "%";
  }

  function renderItem(item) {
    const row = document.querySelector(`[data-item-id="${item.item_id}"]`);
    if (!row) return;
    const badge = row.querySelector(".status-badge");
    if (badge) {
      badge.textContent = labelFor(item.status);
      badge.className = "badge status-badge " + (statusClasses[item.status] || "text-bg-light");
    }
    const select = row.querySelector(".status-select");
    if (select) {
      select.value = item.status;
      select.dataset.previousStatus = item.status;
    }
    const updatedBy = row.querySelector(".updated-by");
    if (updatedBy) updatedBy.textContent = item.updated_by || "Not updated";
    const input = row.querySelector(".remark-input");
    if (input && (input.dataset.saving === "true" || (document.activeElement !== input && row.dataset.remarkDirty !== "true"))) {
      input.value = item.remark || "";
      input.dataset.previousRemark = item.remark || "";
      row.dataset.remarkDirty = "false";
    }
    const meta = row.querySelector(".remark-updated-by");
    if (meta) meta.textContent = item.remark_updated_by ? "Remark by " + item.remark_updated_by : "";
  }

  function renderRecord(payload) {
    updateSummary(payload.counts);
    payload.checklist.forEach(renderItem);
    const finalInput = document.getElementById("finalRemark");
    const finalMeta = document.getElementById("finalRemarkMeta");
    if (finalInput && (finalInput.dataset.saving === "true" || (document.activeElement !== finalInput && finalInput.dataset.dirty !== "true"))) {
      finalInput.value = payload.final_remark || "";
      finalInput.dataset.previousRemark = payload.final_remark || "";
      finalInput.dataset.dirty = "false";
    }
    if (finalMeta) finalMeta.textContent = payload.final_remark_updated_by ? "Final remark by " + payload.final_remark_updated_by : "No final remark saved";
  }

  async function readJson(response) {
    const type = response.headers.get("content-type") || "";
    if (type.includes("application/json")) return response.json();
    const text = await response.text();
    throw new Error(text.includes("<!doctype") ? "Server error. Please refresh and try again." : text || "Unexpected server response.");
  }

  async function post(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body)
    });
    if (response.redirected) {
      window.location.assign(response.url);
      return null;
    }
    const payload = await readJson(response);
    if (!response.ok) throw new Error(payload.error || "Update failed.");
    return payload;
  }

  async function refreshRecord() {
    if (document.hidden) return;
    try {
      const response = await fetch(baseUrl, { headers: { "Accept": "application/json" } });
      if (response.ok) renderRecord(await readJson(response));
    } catch (_error) {
      // Keep current values visible when background refresh fails.
    }
  }

  document.querySelectorAll(".checklist-item").forEach(function (row) {
    const itemId = row.dataset.itemId;
    const select = row.querySelector(".status-select");
    const input = row.querySelector(".remark-input");
    const save = row.querySelector(".save-remark");
    const clear = row.querySelector(".clear-remark");
    if (select) {
      select.dataset.previousStatus = select.value;
      select.addEventListener("change", async function () {
        if (select.value === select.dataset.previousStatus) return;
        const previous = select.dataset.previousStatus;
        select.disabled = true;
        row.classList.add("is-saving");
        try {
          renderRecord(await post(`${baseUrl}/items/${itemId}`, { status: select.value }));
        } catch (error) {
          select.value = previous;
          alert(error.message);
        } finally {
          select.disabled = false;
          row.classList.remove("is-saving");
        }
      });
    }
    if (input) {
      input.dataset.previousRemark = input.value;
      row.dataset.remarkDirty = "false";
      input.addEventListener("input", function () {
        row.dataset.remarkDirty = String(input.value !== input.dataset.previousRemark);
      });
    }
    async function saveRemark(value) {
      input.dataset.saving = "true";
      row.classList.add("is-saving");
      try {
        const payload = await post(`${baseUrl}/items/${itemId}/remark`, { remark: value });
        input.dataset.previousRemark = value;
        row.dataset.remarkDirty = "false";
        renderRecord(payload);
      } catch (error) {
        input.value = input.dataset.previousRemark || "";
        alert(error.message);
      } finally {
        input.dataset.saving = "false";
        row.classList.remove("is-saving");
      }
    }
    if (save && input) save.addEventListener("click", function () { saveRemark(input.value); });
    if (clear && input) clear.addEventListener("click", function () { input.value = ""; saveRemark(""); });
  });

  const finalInput = document.getElementById("finalRemark");
  const finalSave = document.getElementById("saveFinalRemark");
  const finalClear = document.getElementById("clearFinalRemark");
  if (finalInput) {
    finalInput.dataset.previousRemark = finalInput.value;
    finalInput.dataset.dirty = "false";
    finalInput.addEventListener("input", function () {
      finalInput.dataset.dirty = String(finalInput.value !== finalInput.dataset.previousRemark);
    });
  }
  async function saveFinal(value) {
    finalInput.dataset.saving = "true";
    try {
      const payload = await post(`${baseUrl}/final-remark`, { remark: value });
      finalInput.dataset.previousRemark = value;
      finalInput.dataset.dirty = "false";
      renderRecord(payload);
    } catch (error) {
      finalInput.value = finalInput.dataset.previousRemark || "";
      alert(error.message);
    } finally {
      finalInput.dataset.saving = "false";
    }
  }
  if (finalSave && finalInput) finalSave.addEventListener("click", function () { saveFinal(finalInput.value); });
  if (finalClear && finalInput) finalClear.addEventListener("click", function () { finalInput.value = ""; saveFinal(""); });

  setInterval(refreshRecord, 5000);
})();
