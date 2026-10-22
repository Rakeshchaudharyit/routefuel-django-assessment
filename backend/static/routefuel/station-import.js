// Prevents accidental double submission of the import forms (the server also refuses repeats).
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-import-form")) return;
  if (form.dataset.submitted === "true") {
    event.preventDefault();
    return;
  }
  form.dataset.submitted = "true";
  form.querySelectorAll('button[type="submit"]').forEach((button) => {
    button.setAttribute("aria-disabled", "true");
    if (button.dataset.busyLabel) button.textContent = button.dataset.busyLabel;
  });
});
