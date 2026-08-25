(function () {
  const statusClasses = {
    completed: "text-bg-success",
    pending: "text-bg-warning",
    na: "text-bg-secondary"
  };

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
    if (updatedBy) {
      updatedBy.textContent = item.updated_by || "Not updated";
    }

    const remarkInput = row.querySelector(".remark-input");
    if (
      remarkInput &&
      (remarkInput.dataset.saving === "true" ||
        (document.activeElement !== remarkInput && row.dataset.remarkDirty !== "true"))
    ) {
      remarkInput.value = item.remark || "";
      remarkInput.dataset.previousRemark = item.remark || "";
      row.dataset.remarkDirty = "false";
    }

    const remarkUpdatedBy = row.querySelector(".remark-updated-by");
    if (remarkUpdatedBy) {
      remarkUpdatedBy.textContent = item.remark_updated_by
        ? "Remark by " + item.remark_updated_by
        : "";
    }
  }

  function renderFinalRemark(payload) {
    const input = document.getElementById("finalRemark");
    const meta = document.getElementById("finalRemarkMeta");
    if (
      input &&
      (input.dataset.saving === "true" ||
        (document.activeElement !== input && input.dataset.dirty !== "true"))
    ) {
      input.value = payload.final_remark || "";
      input.dataset.previousRemark = payload.final_remark || "";
      input.dataset.dirty = "false";
    }
    if (meta) {
      meta.textContent = payload.final_remark_updated_by
        ? "Final remark by " + payload.final_remark_updated_by
        : "No final remark saved";
    }
  }

  function renderStructure(payload) {
    updateSummary(payload.counts);
    payload.checklist.forEach(renderItem);
    renderFinalRemark(payload);
  }

  async function readJsonResponse(response) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return response.json();
    }
    const text = await response.text();
    const message = text.includes("<!doctype")
      ? "Server error. Please refresh the page and try again."
      : text || "Unexpected server response.";
    throw new Error(message);
  }

  async function refreshStructure() {
    const response = await fetch(`/api/structure/${window.structureId}`, {
      headers: { "Accept": "application/json" }
    });
    if (response.redirected) {
      window.location.assign(response.url);
      return;
    }
    if (!response.ok) return;
    renderStructure(await readJsonResponse(response));
  }

  async function updateStatus(itemId, status, row) {
    const select = row.querySelector(".status-select");
    const previousStatus = select ? select.dataset.previousStatus : null;

    row.classList.add("is-saving");
    if (select) select.disabled = true;

    try {
      const response = await fetch(`/api/structure/${window.structureId}/items/${itemId}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify({ status })
      });
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      const payload = await readJsonResponse(response);
      if (!response.ok) {
        throw new Error(payload.error || "Update failed.");
      }
      renderStructure(payload);
    } catch (error) {
      if (select && previousStatus) {
        select.value = previousStatus;
      }
      alert(error.message || "Update failed.");
    } finally {
      row.classList.remove("is-saving");
      if (select) select.disabled = false;
    }
  }

  async function updateRemark(itemId, remark, row) {
    const input = row.querySelector(".remark-input");
    const buttons = row.querySelectorAll(".save-remark, .clear-remark");
    const previousRemark = input ? input.dataset.previousRemark || "" : "";

    row.classList.add("is-saving");
    if (input) input.dataset.saving = "true";
    buttons.forEach(function (button) {
      button.disabled = true;
    });

    try {
      const response = await fetch(`/api/structure/${window.structureId}/items/${itemId}/remark`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify({ remark })
      });
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      const payload = await readJsonResponse(response);
      if (!response.ok) {
        throw new Error(payload.error || "Remark update failed.");
      }
      if (input) {
        input.dataset.previousRemark = remark;
        row.dataset.remarkDirty = "false";
      }
      renderStructure(payload);
    } catch (error) {
      if (input) {
        input.value = previousRemark;
        row.dataset.remarkDirty = "false";
      }
      alert(error.message || "Remark update failed.");
    } finally {
      row.classList.remove("is-saving");
      if (input) input.dataset.saving = "false";
      buttons.forEach(function (button) {
        button.disabled = false;
      });
    }
  }

  async function updateFinalRemark(remark) {
    const input = document.getElementById("finalRemark");
    const saveButton = document.getElementById("saveFinalRemark");
    const clearButton = document.getElementById("clearFinalRemark");
    const previousRemark = input ? input.dataset.previousRemark || "" : "";

    if (input) input.dataset.saving = "true";
    if (saveButton) saveButton.disabled = true;
    if (clearButton) clearButton.disabled = true;

    try {
      const response = await fetch(`/api/structure/${window.structureId}/final-remark`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify({ remark })
      });
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      const payload = await readJsonResponse(response);
      if (!response.ok) {
        throw new Error(payload.error || "Final remark update failed.");
      }
      if (input) {
        input.dataset.previousRemark = remark;
        input.dataset.dirty = "false";
      }
      renderStructure(payload);
    } catch (error) {
      if (input) {
        input.value = previousRemark;
        input.dataset.dirty = "false";
      }
      alert(error.message || "Final remark update failed.");
    } finally {
      if (input) input.dataset.saving = "false";
      if (saveButton) saveButton.disabled = false;
      if (clearButton) clearButton.disabled = false;
    }
  }

  document.querySelectorAll(".checklist-item").forEach(function (row) {
    const select = row.querySelector(".status-select");
    if (select) {
      select.dataset.previousStatus = select.value;
      select.addEventListener("change", function () {
        if (select.value === select.dataset.previousStatus) return;
        updateStatus(row.dataset.itemId, select.value, row);
      });
    }

    const remarkInput = row.querySelector(".remark-input");
    const saveRemark = row.querySelector(".save-remark");
    const clearRemark = row.querySelector(".clear-remark");
    if (remarkInput) {
      remarkInput.dataset.previousRemark = remarkInput.value;
      row.dataset.remarkDirty = "false";
      remarkInput.addEventListener("input", function () {
        row.dataset.remarkDirty = String(remarkInput.value !== remarkInput.dataset.previousRemark);
      });
    }
    if (saveRemark && remarkInput) {
      saveRemark.addEventListener("click", function () {
        updateRemark(row.dataset.itemId, remarkInput.value, row);
      });
    }
    if (clearRemark && remarkInput) {
      clearRemark.addEventListener("click", function () {
        remarkInput.value = "";
        updateRemark(row.dataset.itemId, "", row);
      });
    }
  });

  const finalRemark = document.getElementById("finalRemark");
  const saveFinalRemark = document.getElementById("saveFinalRemark");
  const clearFinalRemark = document.getElementById("clearFinalRemark");
  if (finalRemark) {
    finalRemark.dataset.previousRemark = finalRemark.value;
    finalRemark.dataset.dirty = "false";
    finalRemark.addEventListener("input", function () {
      finalRemark.dataset.dirty = String(finalRemark.value !== finalRemark.dataset.previousRemark);
    });
  }
  if (saveFinalRemark && finalRemark) {
    saveFinalRemark.addEventListener("click", function () {
      updateFinalRemark(finalRemark.value);
    });
  }
  if (clearFinalRemark && finalRemark) {
    clearFinalRemark.addEventListener("click", function () {
      finalRemark.value = "";
      updateFinalRemark("");
    });
  }

  setInterval(refreshStructure, 5000);
})();
