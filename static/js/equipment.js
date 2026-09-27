(function () {
  const statusClasses = {
    completed: "text-bg-success",
    pending: "text-bg-warning",
    na: "text-bg-secondary"
  };
  const baseUrl = `/api/equipment/${encodeURIComponent(window.equipmentId)}`;
  const detailsForm = document.getElementById("equipmentDetailsForm");
  const identificationInput = document.getElementById("equipmentIdentification");
  const specificationInput = document.getElementById("equipmentSpecification");
  const vendorInput = document.getElementById("equipmentVendor");
  const detailInputs = [identificationInput, specificationInput, vendorInput].filter(Boolean);

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

  function setText(id, value, fallback) {
    const element = document.getElementById(id);
    if (element) element.textContent = value || fallback;
  }

  function renderDetails(payload) {
    setText("equipmentIdentificationHeader", payload.equipment_identification, "Not set");
    setText("equipmentSpecificationHeader", payload.specification, "Not set");
    setText("equipmentVendorHeader", payload.vendor_name, "Not set");
    setText("equipmentIdentificationValue", payload.equipment_identification, "-");
    setText("equipmentSpecificationValue", payload.specification, "-");
    setText("equipmentVendorValue", payload.vendor_name, "-");

    const detailsFocused = detailInputs.includes(document.activeElement);
    if (detailInputs.length && (detailsForm.dataset.saving === "true" || (!detailsFocused && detailsForm.dataset.dirty !== "true"))) {
      identificationInput.value = payload.equipment_identification || "";
      specificationInput.value = payload.specification || "";
      vendorInput.value = payload.vendor_name || "";
      detailInputs.forEach(function (input) { input.dataset.previousValue = input.value; });
      detailsForm.dataset.dirty = "false";
    }
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
    const measurementInputs = Array.from(row.querySelectorAll(".measurement-input"));
    const measurementFocused = measurementInputs.includes(document.activeElement);
    if (measurementInputs.length && (row.dataset.measurementSaving === "true" || (!measurementFocused && row.dataset.measurementDirty !== "true"))) {
      measurementInputs.forEach(function (measurementInput) {
        const value = (item.measurements || {})[measurementInput.dataset.fieldKey] || "";
        measurementInput.value = value;
        measurementInput.dataset.previousValue = value;
      });
      row.dataset.measurementDirty = "false";
    }
    const measurementMeta = row.querySelector(".measurement-updated-by");
    if (measurementMeta) measurementMeta.textContent = item.measurement_updated_by ? "Observation by " + item.measurement_updated_by : "";
    const publicValues = row.querySelector(".recorded-values");
    let hasPublicValue = false;
    row.querySelectorAll(".recorded-value-entry").forEach(function (entry) {
      const value = (item.measurements || {})[entry.dataset.fieldKey] || "";
      const text = entry.querySelector(".recorded-value-text");
      if (text) text.textContent = value;
      entry.classList.toggle("d-none", !value);
      if (value) hasPublicValue = true;
    });
    if (publicValues) publicValues.classList.toggle("d-none", !hasPublicValue);
  }

  function renderRecord(payload) {
    updateSummary(payload.counts);
    renderDetails(payload);
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
    const measurementInputs = Array.from(row.querySelectorAll(".measurement-input"));
    const measurementSave = row.querySelector(".save-measurements");
    const measurementClear = row.querySelector(".clear-measurements");
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
    measurementInputs.forEach(function (measurementInput) {
      measurementInput.dataset.previousValue = measurementInput.value;
      measurementInput.addEventListener("input", function () {
        row.dataset.measurementDirty = String(measurementInputs.some(function (candidate) {
          return candidate.value !== candidate.dataset.previousValue;
        }));
      });
    });
    row.dataset.measurementDirty = "false";
    async function saveMeasurements() {
      const measurements = {};
      measurementInputs.forEach(function (measurementInput) {
        measurements[measurementInput.dataset.fieldKey] = measurementInput.value;
      });
      row.dataset.measurementSaving = "true";
      row.classList.add("is-saving");
      try {
        const payload = await post(`${baseUrl}/items/${itemId}/measurements`, { measurements: measurements });
        row.dataset.measurementDirty = "false";
        renderRecord(payload);
      } catch (error) {
        measurementInputs.forEach(function (measurementInput) {
          measurementInput.value = measurementInput.dataset.previousValue || "";
        });
        alert(error.message);
      } finally {
        row.dataset.measurementSaving = "false";
        row.classList.remove("is-saving");
      }
    }
    if (measurementSave && measurementInputs.length) measurementSave.addEventListener("click", saveMeasurements);
    if (measurementClear && measurementInputs.length) measurementClear.addEventListener("click", function () {
      measurementInputs.forEach(function (measurementInput) { measurementInput.value = ""; });
      saveMeasurements();
    });
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

  if (detailsForm) {
    detailsForm.dataset.dirty = "false";
    detailInputs.forEach(function (input) {
      input.dataset.previousValue = input.value;
      input.addEventListener("input", function () {
        detailsForm.dataset.dirty = String(detailInputs.some(function (candidate) {
          return candidate.value !== candidate.dataset.previousValue;
        }));
      });
    });
    detailsForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      const button = document.getElementById("saveEquipmentDetails");
      const status = document.getElementById("equipmentDetailsStatus");
      detailsForm.dataset.saving = "true";
      if (button) button.disabled = true;
      if (status) status.textContent = "Saving...";
      try {
        const payload = await post(`${baseUrl}/details`, {
          equipment_identification: identificationInput.value,
          specification: specificationInput.value,
          vendor_name: vendorInput.value
        });
        renderRecord(payload);
        if (status) status.textContent = "Details saved";
      } catch (error) {
        detailInputs.forEach(function (input) {
          input.value = input.dataset.previousValue || "";
        });
        if (status) status.textContent = "Save failed";
        alert(error.message);
      } finally {
        detailsForm.dataset.saving = "false";
        if (button) button.disabled = false;
      }
    });
  }

  setInterval(refreshRecord, 15000);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) refreshRecord();
  });
  window.addEventListener("online", refreshRecord);
})();
