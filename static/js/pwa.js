(function () {
  const installButton = document.getElementById("installPwaButton");
  let deferredInstallPrompt = null;
  const isInstalled = window.matchMedia("(display-mode: standalone)").matches
    || window.navigator.standalone === true;

  if (isInstalled && installButton) {
    installButton.classList.add("d-none");
  }

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker
        .register("/service-worker.js", { updateViaCache: "none" })
        .then(function (registration) {
          return registration.update();
        })
        .catch(function () {
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
      const choice = await deferredInstallPrompt.userChoice.catch(function () {
        return { outcome: "dismissed" };
      });
      deferredInstallPrompt = null;
      if (choice.outcome === "accepted") {
        installButton.classList.add("d-none");
      } else {
        installButton.classList.remove("d-none");
      }
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
