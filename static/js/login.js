(function () {
  const loginForm = document.getElementById("loginForm");
  const loginButton = document.getElementById("loginButton");
  const alertBox = document.getElementById("authAlert");

  function showAlert(message, type) {
    alertBox.textContent = message;
    alertBox.className = `alert alert-${type || "danger"}`;
    alertBox.classList.remove("d-none");
  }

  function hideAlert() {
    alertBox.classList.add("d-none");
  }

  function friendlyAuthMessage(error) {
    const messages = {
      "Failed to fetch": "Network problem. Please check your internet connection."
    };
    return messages[error.message] || error.message || "Request failed. Please try again.";
  }

  async function postJson(url, data) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Request failed.");
    }
    return payload;
  }

  function restoreButton(button, html) {
    button.disabled = false;
    button.innerHTML = html;
  }

  loginForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    hideAlert();
    loginButton.disabled = true;
    loginButton.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Signing in';

    const email = document.getElementById("loginEmail").value.trim();
    const password = document.getElementById("loginPassword").value;

    try {
      await postJson("/auth/login", { email, password });
      window.location.assign(window.nextUrl || "/account");
    } catch (error) {
      showAlert(friendlyAuthMessage(error));
      restoreButton(loginButton, '<i class="bi bi-shield-lock" aria-hidden="true"></i> Sign in');
    }
  });
})();
