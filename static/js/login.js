(function () {
  const loginForm = document.getElementById("loginForm");
  const loginButton = document.getElementById("loginButton");
  const forgotPasswordForm = document.getElementById("forgotPasswordForm");
  const resetPasswordButton = document.getElementById("resetPasswordButton");
  const showForgotPassword = document.getElementById("showForgotPassword");
  const backToLogin = document.getElementById("backToLogin");
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

  function showPasswordReset() {
    hideAlert();
    const loginEmail = document.getElementById("loginEmail").value.trim();
    document.getElementById("resetEmail").value = loginEmail;
    loginForm.classList.add("d-none");
    forgotPasswordForm.classList.remove("d-none");
    document.getElementById("resetEmail").focus();
  }

  function showLogin() {
    hideAlert();
    const resetEmail = document.getElementById("resetEmail").value.trim();
    if (resetEmail) document.getElementById("loginEmail").value = resetEmail;
    forgotPasswordForm.classList.add("d-none");
    loginForm.classList.remove("d-none");
    document.getElementById("loginEmail").focus();
  }

  showForgotPassword.addEventListener("click", showPasswordReset);
  backToLogin.addEventListener("click", showLogin);

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

  forgotPasswordForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    hideAlert();
    resetPasswordButton.disabled = true;
    resetPasswordButton.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Sending link';

    try {
      const result = await postJson("/auth/forgot-password", {
        email: document.getElementById("resetEmail").value.trim()
      });
      showAlert(result.message || "Password reset link sent.", "success");
    } catch (error) {
      showAlert(friendlyAuthMessage(error));
    } finally {
      restoreButton(resetPasswordButton, '<i class="bi bi-envelope" aria-hidden="true"></i> Send Reset Link');
    }
  });
})();
