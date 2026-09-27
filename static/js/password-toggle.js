(function () {
  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-password-toggle]");
    if (!button) {
      return;
    }

    const input = document.getElementById(button.dataset.passwordToggle);
    if (!input) {
      return;
    }

    const showPassword = input.type === "password";
    const label = showPassword ? "Hide password" : "Show password";
    input.type = showPassword ? "text" : "password";
    button.setAttribute("aria-label", label);
    button.setAttribute("aria-pressed", String(showPassword));
    button.title = label;

    const icon = button.querySelector("i");
    if (icon) {
      icon.className = showPassword ? "bi bi-eye-slash" : "bi bi-eye";
    }
  });
})();
