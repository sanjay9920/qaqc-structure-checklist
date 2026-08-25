(function () {
  const form = document.getElementById("loginForm");
  const button = document.getElementById("loginButton");
  const alertBox = document.getElementById("loginAlert");

  function showError(message) {
    alertBox.textContent = message;
    alertBox.classList.remove("d-none");
  }

  if (!window.firebaseConfig || !window.firebaseConfig.apiKey) {
    showError("Firebase web configuration is missing. Check your .env file.");
    button.disabled = true;
    return;
  }

  firebase.initializeApp(window.firebaseConfig);

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    alertBox.classList.add("d-none");
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Signing in';

    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;

    try {
      const credential = await firebase.auth().signInWithEmailAndPassword(email, password);
      const idToken = await credential.user.getIdToken();
      const response = await fetch("/session-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idToken })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Login failed.");
      }
      window.location.assign(window.nextUrl || "/admin");
    } catch (error) {
      showError(error.message || "Login failed.");
      button.disabled = false;
      button.innerHTML = '<i class="bi bi-shield-lock" aria-hidden="true"></i> Sign in';
    }
  });
})();
