"use strict";

// The form works without JavaScript; only password visibility is enhanced.
const password = document.getElementById("id_password");
const toggle = document.getElementById("toggle-password");
if (password && toggle) {
  toggle.hidden = false;
  toggle.addEventListener("click", () => {
    const visible = password.type === "password";
    password.type = visible ? "text" : "password";
    toggle.textContent = visible ? "Hide" : "Show";
    toggle.setAttribute("aria-label", visible ? "Hide password" : "Show password");
    toggle.setAttribute("aria-pressed", String(visible));
  });
}
