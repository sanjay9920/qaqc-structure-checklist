(function () {
  const config = window.adminDashboard || {};
  const tableBody = document.getElementById("structuresTableBody");
  const blockSummaryBody = document.getElementById("blockSummaryBody");
  const searchForm = document.querySelector(".search-row");
  const totalBlocksEl = document.getElementById("totalBlocks");
  const projectTotalStructuresEl = document.getElementById("projectTotalStructures");
  const projectCompletedPercentEl = document.getElementById("projectCompletedPercent");
  const projectPendingPercentEl = document.getElementById("projectPendingPercent");
  const projectCompletedPointsEl = document.getElementById("projectCompletedPoints");
  const projectPendingPointsEl = document.getElementById("projectPendingPoints");
  const projectCompletedStructuresEl = document.getElementById("projectCompletedStructures");
  const projectPendingStructuresEl = document.getElementById("projectPendingStructures");
  const projectCompletedStructuresNoteEl = document.getElementById("projectCompletedStructuresNote");
  const projectPendingStructuresNoteEl = document.getElementById("projectPendingStructuresNote");
  const selectedBlockLabelEl = document.getElementById("selectedBlockLabel");
  const dashboardTitle = document.getElementById("dashboardTitle");
  const dashboardScope = document.getElementById("dashboardScope");
  const projectOptions = document.getElementById("projectOptions");
  const projectFilterInput = document.getElementById("project_filter");
  const blockFilterInput = document.getElementById("block_filter");
  const createProjectInput = document.getElementById("project_single");
  const createBlockInput = document.getElementById("block_single");
  const createIdInput = document.getElementById("structure_id");
  const projectRenameInput = document.getElementById("project_display_name");
  const projectRenameEditButton = document.getElementById("editProjectName");
  const projectRenameSaveButton = document.getElementById("saveProjectName");
  const blockOpenSelect = document.getElementById("block_open_select");
  const structureOpenSelect = document.getElementById("structure_open_select");

  if (!config.apiUrl || !searchForm) return;

  let refreshInFlight = false;
  let projectSubmitTimer = null;

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function displayValue(value) {
    return value ? escapeHtml(value) : "-";
  }

  function scopeName(value) {
    return String(value || "").replace(/-/g, " ");
  }

  function projectRecord(project) {
    if (!project) return null;
    if (typeof project === "string") {
      return { project_id: project, display_name: scopeName(project) };
    }
    return {
      project_id: project.project_id || project.id || "",
      display_name: project.display_name || scopeName(project.project_id || project.id || "")
    };
  }

  function blockLabel(value) {
    const block = String(value || "");
    return block.startsWith("BLOCK-") ? block.replace("BLOCK-", "") : block;
  }

  function structureNumber(value) {
    const match = String(value || "").match(/(?:^|-)STR-(\d+)$/);
    if (!match) return String(value || "");
    return String(Number(match[1])).padStart(2, "0");
  }

  function comparableValue(value) {
    return String(value || "").trim().replace(/\s+/g, " ").toUpperCase();
  }

  function knownProjectValues() {
    if (!projectOptions) return [];
    return Array.from(projectOptions.querySelectorAll("option")).map((option) =>
      comparableValue(option.value)
    );
  }

  function isKnownProject(value) {
    const comparable = comparableValue(value);
    return Boolean(comparable && knownProjectValues().includes(comparable));
  }

  function structureUrl(structureId) {
    return `/admin/structures/${encodeURIComponent(structureId)}`;
  }

  function dashboardUrl(project, block) {
    const params = new URLSearchParams();
    if (project) params.set("project", project);
    if (block) params.set("block", block);
    return `/admin?${params.toString()}`;
  }

  function renderProjectOptions(projects, selectedProject) {
    if (!Array.isArray(projects)) return;
    const projectRows = projects.map(projectRecord).filter((project) => project && project.project_id);

    if (projectOptions) {
      projectOptions.innerHTML = projectRows
        .map((project) => `<option value="${escapeHtml(project.display_name)}"></option>`)
        .join("");
    }

    if (projectFilterInput && projectFilterInput.tagName === "SELECT") {
      const currentValue = selectedProject || projectFilterInput.value || "";
      const options = projectRows
        .map((project) => {
          const selected = project.project_id === currentValue ? " selected" : "";
          return `<option value="${escapeHtml(project.project_id)}"${selected}>${escapeHtml(project.display_name)}</option>`;
        })
        .join("");
      projectFilterInput.innerHTML = `<option value="">Select project</option>${options}`;
      projectFilterInput.value = currentValue;
    }
  }

  function renderBlockOptions(blocks, selectedBlock) {
    if (!blockFilterInput || blockFilterInput.tagName !== "SELECT") return;
    const blockRows = Array.isArray(blocks) ? blocks.filter((block) => block.block) : [];
    const hasSelectedBlock = blockRows.some((block) => block.block === selectedBlock);
    const selectedOption = selectedBlock && !hasSelectedBlock
      ? `<option value="${escapeHtml(selectedBlock)}" selected>Block ${escapeHtml(blockLabel(selectedBlock))} - new</option>`
      : "";
    const options = blockRows
      .map((block) => {
        const selected = block.block === selectedBlock ? " selected" : "";
        const label = `Block ${block.block_display} - ${block.total_structures} structure${block.total_structures === 1 ? "" : "s"}`;
        return `<option value="${escapeHtml(block.block)}"${selected}>${escapeHtml(label)}</option>`;
      })
      .join("");
    blockFilterInput.innerHTML = `<option value="">All blocks</option>${selectedOption}${options}`;
    blockFilterInput.value = selectedBlock || "";
  }

  function renderProjectSummary(summary) {
    if (!summary) return;
    const activeSummary = summary.selected_block
      ? (summary.selected_block_summary || {})
      : summary;
    if (totalBlocksEl) totalBlocksEl.textContent = summary.total_blocks || 0;
    if (projectTotalStructuresEl) {
      projectTotalStructuresEl.textContent = activeSummary.total_structures || 0;
    }
    if (projectCompletedPercentEl) {
      projectCompletedPercentEl.textContent = activeSummary.completed_percent || 0;
    }
    if (projectPendingPercentEl) {
      projectPendingPercentEl.textContent = activeSummary.pending_percent || 0;
    }
    if (projectCompletedPointsEl) {
      projectCompletedPointsEl.textContent = `${activeSummary.checklist_completed || 0} / ${activeSummary.checklist_total || 0} points`;
    }
    if (projectPendingPointsEl) {
      projectPendingPointsEl.textContent = `${activeSummary.checklist_pending || 0} / ${activeSummary.checklist_total || 0} points`;
    }
    if (projectCompletedStructuresEl) {
      projectCompletedStructuresEl.textContent = activeSummary.completed_structures || 0;
    }
    if (projectPendingStructuresEl) {
      projectPendingStructuresEl.textContent = activeSummary.pending_structures || 0;
    }
    if (projectCompletedStructuresNoteEl) {
      projectCompletedStructuresNoteEl.textContent = `${activeSummary.completed_structures || 0} / ${activeSummary.total_structures || 0} structures (${activeSummary.structure_percent || 0}%)`;
    }
    if (projectPendingStructuresNoteEl) {
      projectPendingStructuresNoteEl.textContent = `${activeSummary.pending_structures || 0} / ${activeSummary.total_structures || 0} structures (${activeSummary.pending_structure_percent || 0}%)`;
    }
    if (selectedBlockLabelEl && summary.selected_block) {
      selectedBlockLabelEl.textContent = blockLabel(summary.selected_block);
    }
  }

  function renderBlockSummary(project, blocks) {
    if (!blockSummaryBody) return;
    const blockRows = Array.isArray(blocks) ? blocks : [];
    if (!blockRows.length) {
      blockSummaryBody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center text-muted py-4">No blocks found. Create the first block below.</td>
        </tr>
      `;
      return;
    }

    blockSummaryBody.innerHTML = blockRows
      .map((block) => {
        const blockName = block.block ? `Block ${block.block_display}` : block.block_display;
        const action = block.block
          ? `<a class="btn btn-sm ${block.selected ? "btn-primary" : "btn-outline-dark"}" href="${dashboardUrl(project, block.block)}">Select</a>`
          : `<span class="text-muted small">No block</span>`;
        return `
          <tr class="${block.selected ? "table-primary" : ""}">
            <td class="fw-semibold">${escapeHtml(blockName)}</td>
            <td>${block.total_structures || 0}</td>
            <td>
              <strong>${block.completed_structures || 0}</strong>
              <small class="d-block text-muted">${block.structure_percent || 0}%</small>
            </td>
            <td>
              <strong>${block.pending_structures || 0}</strong>
              <small class="d-block text-muted">${block.pending_structure_percent || 0}%</small>
            </td>
            <td>${block.checklist_completed || 0} / ${block.checklist_total || 0}</td>
            <td>${block.checklist_pending || 0} / ${block.checklist_total || 0}</td>
            <td>
              <div class="progress table-progress">
                <div class="progress-bar" style="width: ${block.completed_percent || 0}%"></div>
              </div>
              <span class="small text-muted">${block.completed_percent || 0}%</span>
            </td>
            <td class="text-end">${action}</td>
          </tr>
        `;
      })
      .join("");
  }

  function renderDashboardScope(payload) {
    const projectName = payload.project_display_name || scopeName(payload.project);
    if (dashboardTitle) {
      dashboardTitle.textContent = payload.project
        ? `${projectName} Dashboard`
        : "Project Home";
    }
    if (dashboardScope) {
      dashboardScope.textContent = payload.project
        ? (payload.block ? `Block: ${blockLabel(payload.block)}` : "All blocks")
        : "Create or select a project";
    }
  }

  function renderRow(structure, projectDisplayNames) {
    const structureId = structure.structure_id;
    const counts = structure.counts || {};
    const progress = counts.progress || 0;
    const projectName = (projectDisplayNames || {})[structure.project] || structure.project;

    return `
      <tr>
        <td>${displayValue(projectName)}</td>
        <td>${displayValue(structure.block_display || blockLabel(structure.block))}</td>
        <td class="fw-semibold" title="${escapeHtml(structureId)}">${escapeHtml(structure.structure_number || structureNumber(structureId))}</td>
        <td>${counts.completed || 0} / ${counts.total || 0}</td>
        <td>${counts.pending || 0} / ${counts.total || 0}</td>
        <td>
          <div class="progress table-progress">
            <div class="progress-bar" style="width: ${progress}%"></div>
          </div>
          <span class="small text-muted">${progress}%</span>
        </td>
        <td class="text-end">
          <div class="table-actions">
            <a class="btn btn-sm btn-outline-dark" href="${structureUrl(structureId)}">
              <i class="bi bi-eye" aria-hidden="true"></i>
              View
            </a>
            <a class="btn btn-sm btn-outline-dark" href="${structureUrl(structureId)}/qr.png">
              <i class="bi bi-qr-code" aria-hidden="true"></i>
              QR
            </a>
            <form
              action="${structureUrl(structureId)}/delete"
              method="post"
              class="delete-structure-form d-inline"
              data-structure-id="${escapeHtml(structureId)}"
              data-project="${escapeHtml(structure.project)}"
              data-block="${escapeHtml(structure.block)}"
            >
              <button class="btn btn-sm btn-outline-danger" type="submit">
                <i class="bi bi-trash" aria-hidden="true"></i>
                Delete
              </button>
            </form>
          </div>
        </td>
      </tr>
    `;
  }

  function renderDashboard(payload) {
    const summary = payload.project_summary || {};
    renderProjectOptions(payload.project_records || payload.projects, payload.project || "");
    renderBlockOptions(summary.blocks || [], payload.block || "");
    renderProjectSummary(summary);
    renderBlockSummary(payload.project || "", summary.blocks || []);
    renderDashboardScope(payload);

    if (!tableBody) return;

    const structures = payload.structures || [];
    if (!structures.length) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="7" class="text-center text-muted py-4">No structures found.</td>
        </tr>
      `;
      return;
    }

    tableBody.innerHTML = structures
      .map((structure) => renderRow(structure, payload.project_display_names || {}))
      .join("");
  }

  async function readJson(response) {
    if (response.redirected) {
      window.location.assign(response.url);
      return null;
    }
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return response.json();
    }
    throw new Error("Unexpected server response. Please try again.");
  }

  async function refreshDashboard() {
    if (refreshInFlight || document.hidden) return;
    refreshInFlight = true;
    try {
      const params = new URLSearchParams(new FormData(searchForm));
      const response = await fetch(`${config.apiUrl}?${params.toString()}`, {
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) return;
      const payload = await readJson(response);
      if (payload) renderDashboard(payload);
    } catch (_error) {
      // Keep the current dashboard visible if a background refresh fails.
    } finally {
      refreshInFlight = false;
    }
  }

  if (tableBody) {
    tableBody.addEventListener("submit", async function (event) {
      const form = event.target.closest(".delete-structure-form");
      if (!form) return;

      event.preventDefault();
      const structureId = form.dataset.structureId;
      const confirmed = confirm(
        `Delete ${structureId} checklist data and history? Same ID can be created again.`
      );
      if (!confirmed) return;

      const button = form.querySelector("button");
      if (button) button.disabled = true;

      try {
        const response = await fetch(form.action, {
          method: "POST",
          headers: {
            "Accept": "application/json",
            "X-Requested-With": "fetch"
          }
        });
        const payload = await readJson(response);
        if (!response.ok) {
          throw new Error((payload && payload.error) || "Delete failed.");
        }

        const deleted = payload.deleted || {};
        if (createBlockInput) createBlockInput.value = blockLabel(deleted.block);
        if (createIdInput) createIdInput.value = structureNumber(deleted.structure_id || structureId);

        await refreshDashboard();
      } catch (error) {
        alert(error.message || "Delete failed.");
        if (button) button.disabled = false;
      }
    });
  }

  searchForm.addEventListener("submit", function () {
    setTimeout(refreshDashboard, 100);
  });

  function submitProjectDashboard() {
    if (searchForm.requestSubmit) {
      searchForm.requestSubmit();
    } else {
      searchForm.submit();
    }
  }

  if (projectFilterInput) {
    projectFilterInput.addEventListener("input", function () {
      if (projectFilterInput.tagName === "SELECT") return;
      clearTimeout(projectSubmitTimer);
      if (!isKnownProject(projectFilterInput.value)) return;
      projectSubmitTimer = setTimeout(submitProjectDashboard, 250);
    });
  }

  if (projectRenameInput && projectRenameEditButton) {
    projectRenameEditButton.addEventListener("click", function () {
      projectRenameInput.readOnly = false;
      projectRenameInput.focus();
      projectRenameInput.select();
      if (projectRenameSaveButton) projectRenameSaveButton.disabled = false;
      projectRenameEditButton.disabled = true;
    });
  }

  if (blockOpenSelect) {
    blockOpenSelect.addEventListener("change", function () {
      if (!blockOpenSelect.value) return;
      const form = blockOpenSelect.closest("form");
      if (form && form.requestSubmit) {
        form.requestSubmit();
      } else if (form) {
        form.submit();
      }
    });
  }

  if (structureOpenSelect) {
    structureOpenSelect.addEventListener("change", function () {
      if (!structureOpenSelect.value) return;
      const form = structureOpenSelect.closest("form");
      if (form && form.requestSubmit) {
        form.requestSubmit();
      } else if (form) {
        form.submit();
      }
    });
  }

  [projectFilterInput, blockFilterInput].forEach((input) => {
    if (!input) return;
    input.addEventListener("change", submitProjectDashboard);
  });

  setInterval(refreshDashboard, 60000);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) refreshDashboard();
  });
})();
