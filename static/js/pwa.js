(function () {
  const installButton = document.getElementById("installPwaButton");
  let deferredInstallPrompt = null;

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/service-worker.js").catch(function () {
        // App still works normally if the browser blocks service workers.
      });
    });
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferredInstallPrompt = event;
    if (installButton) {
      installButton.classList.remove("d-none");
    }
  });

  if (installButton) {
    installButton.addEventListener("click", async function () {
      if (!deferredInstallPrompt) return;
      installButton.setAttribute("disabled", "disabled");
      deferredInstallPrompt.prompt();
      await deferredInstallPrompt.userChoice.catch(function () {});
      deferredInstallPrompt = null;
      installButton.classList.add("d-none");
      installButton.removeAttribute("disabled");
    });
  }

  window.addEventListener("appinstalled", function () {
    deferredInstallPrompt = null;
    if (installButton) {
      installButton.classList.add("d-none");
    }
  });
})();
