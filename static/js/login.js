(function () {
  const loginForm = document.getElementById("loginForm");
  const signupForm = document.getElementById("signupForm");
  const resetForm = document.getElementById("resetForm");
  const loginButton = document.getElementById("loginButton");
  const signupButton = document.getElementById("signupButton");
  const resetButton = document.getElementById("resetButton");
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

  signupForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    hideAlert();
    signupButton.disabled = true;
    signupButton.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Creating';

    const name = document.getElementById("signupName").value.trim();
    const email = document.getElementById("signupEmail").value.trim();
    const password = document.getElementById("signupPassword").value;
    const confirmPassword = document.getElementById("signupConfirmPassword").value;

    if (password !== confirmPassword) {
      showAlert("Passwords do not match.");
      restoreButton(signupButton, '<i class="bi bi-person-plus" aria-hidden="true"></i> Create account');
      return;
    }

    try {
      await postJson("/auth/signup", { name, email, password });
      window.location.assign(window.nextUrl || "/account");
    } catch (error) {
      showAlert(friendlyAuthMessage(error));
      restoreButton(signupButton, '<i class="bi bi-person-plus" aria-hidden="true"></i> Create account');
    }
  });

  resetForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    hideAlert();
    resetButton.disabled = true;
    resetButton.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Sending';

    const email = document.getElementById("resetEmail").value.trim();

    try {
      await postJson("/auth/reset", { email });
      showAlert("Password reset link sent. Please check your email.", "success");
      resetForm.reset();
    } catch (error) {
      showAlert(friendlyAuthMessage(error));
    } finally {
      restoreButton(resetButton, '<i class="bi bi-envelope-check" aria-hidden="true"></i> Send reset link');
    }
  });
})();
