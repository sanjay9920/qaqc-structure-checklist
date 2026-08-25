(function () {
  const readerEl = document.getElementById("qrReader");
  const startButton = document.getElementById("startScanner");
  const stopButton = document.getElementById("stopScanner");
  const statusEl = document.getElementById("scannerStatus");
  const manualForm = document.getElementById("manualStructureForm");
  const manualInput = document.getElementById("manualStructureId");

  if (!readerEl || !startButton || !stopButton || !statusEl) return;

  let scanner = null;
  let isScanning = false;
  let isOpening = false;

  function setStatus(message, tone) {
    statusEl.textContent = message;
    statusEl.classList.remove("text-danger", "text-success", "text-muted");
    statusEl.classList.add(tone || "text-muted");
  }

  function structureUrlFromValue(value) {
    const rawValue = String(value || "").trim();
    if (!rawValue) return "";

    try {
      const url = new URL(rawValue);
      const marker = "/structure/";
      const index = url.pathname.indexOf(marker);
      if (index >= 0) {
        const structureId = decodeURIComponent(url.pathname.slice(index + marker.length));
        return structureId ? `/structure/${encodeURIComponent(structureId)}` : "";
      }
    } catch (_error) {
      // Not a full URL; continue with path or plain Structure ID handling.
    }

    if (rawValue.startsWith("/structure/")) {
      const structureId = decodeURIComponent(rawValue.slice("/structure/".length));
      return structureId ? `/structure/${encodeURIComponent(structureId)}` : "";
    }

    if (/^[A-Za-z0-9._ -]+$/.test(rawValue) && rawValue.toUpperCase().includes("STR-")) {
      return `/structure/${encodeURIComponent(rawValue)}`;
    }

    return "";
  }

  function openStructure(value) {
    if (isOpening) return;
    const nextUrl = structureUrlFromValue(value);
    if (!nextUrl) {
      setStatus("QR code me valid Structure link/ID nahi mila.", "text-danger");
      return;
    }

    isOpening = true;
    setStatus("Checklist open ho rahi hai...", "text-success");
    window.location.href = nextUrl;
  }

  function qrBoxSize(width, height) {
    const edge = Math.min(width, height);
    const size = Math.floor(edge * 0.72);
    return { width: size, height: size };
  }

  async function startScanner() {
    if (isScanning) return;
    if (!window.Html5Qrcode) {
      setStatus("Scanner library load nahi hui. Internet connection check karein.", "text-danger");
      return;
    }

    scanner = scanner || new Html5Qrcode("qrReader", false);
    startButton.setAttribute("disabled", "disabled");
    setStatus("Camera permission allow karein...", "text-muted");

    try {
      await scanner.start(
        { facingMode: "environment" },
        {
          fps: 10,
          qrbox: qrBoxSize,
          aspectRatio: 1
        },
        function (decodedText) {
          openStructure(decodedText);
        }
      );
      isScanning = true;
      stopButton.removeAttribute("disabled");
      setStatus("QR code ko camera box ke andar rakhein.", "text-muted");
    } catch (error) {
      startButton.removeAttribute("disabled");
      stopButton.setAttribute("disabled", "disabled");
      setStatus("Camera start nahi hua. Browser permission/settings check karein.", "text-danger");
    }
  }

  async function stopScanner() {
    if (!scanner || !isScanning) return;
    stopButton.setAttribute("disabled", "disabled");
    try {
      await scanner.stop();
      await scanner.clear();
    } catch (_error) {
      // Scanner can already be stopped while navigating away.
    }
    isScanning = false;
    startButton.removeAttribute("disabled");
    setStatus("Scan stopped.", "text-muted");
  }

  startButton.addEventListener("click", startScanner);
  stopButton.addEventListener("click", stopScanner);

  if (manualForm && manualInput) {
    manualForm.addEventListener("submit", function (event) {
      event.preventDefault();
      openStructure(manualInput.value);
    });
  }

  window.addEventListener("pagehide", function () {
    if (scanner && isScanning) {
      scanner.stop().catch(function () {});
    }
  });
})();
