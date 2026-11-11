/**
 * Small progressive enhancements: theme toggle, copy-to-clipboard, and the
 * photo capture flow.
 *
 * Every page works without this script. It is loaded in <head> (not deferred)
 * so the saved theme is applied before the first paint, avoiding a flash of
 * the light theme for dark-theme users.
 */
(function () {
  "use strict";

  /** localStorage key holding the viewer's theme choice. */
  var THEME_KEY = "snapline-theme";
  /** How long the Copy button shows "Copied" before resetting, in ms. */
  var COPIED_RESET_MS = 2000;

  var root = document.documentElement;

  /**
   * Read the saved theme, tolerating browsers that block storage.
   * @return "dark", "light", or null if nothing is saved or storage fails.
   */
  function readSavedTheme() {
    try {
      return window.localStorage.getItem(THEME_KEY);
    } catch (e) {
      return null;
    }
  }

  /**
   * Save the theme choice, ignoring storage failures.
   * @param theme "dark" or "light".
   */
  function saveTheme(theme) {
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch (e) {
      /* Private mode or blocked storage: the choice lasts for this page only. */
    }
  }

  /**
   * Decide the starting theme: saved choice, else the OS preference.
   * @return True if the dark theme should be used.
   */
  function prefersDark() {
    var saved = readSavedTheme();
    if (saved) {
      return saved === "dark";
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  root.classList.toggle("dark", prefersDark());

  /**
   * Show the theme button and make it switch themes.
   * @param button The theme toggle button element.
   */
  function setUpThemeToggle(button) {
    function label() {
      button.textContent = root.classList.contains("dark") ? "Light theme" : "Dark theme";
    }
    button.addEventListener("click", function () {
      var dark = root.classList.toggle("dark");
      saveTheme(dark ? "dark" : "light");
      label();
    });
    label();
    button.hidden = false;
  }

  /**
   * Show a Copy button and make it copy its target field's value.
   * @param button A button whose data-copy-target holds the field's id.
   */
  function setUpCopyButton(button) {
    var target = document.getElementById(button.dataset.copyTarget);
    if (!target || !navigator.clipboard) {
      return;
    }
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(target.value).then(function () {
        button.textContent = "Copied";
        window.setTimeout(function () {
          button.textContent = "Copy";
        }, COPIED_RESET_MS);
      });
    });
    button.hidden = false;
  }

  /**
   * Turn the plain photo form into Take photo -> review -> Send/Retake.
   *
   * Without this script the page still works as a file picker plus a Send
   * button. With it, the picker is hidden behind a large "Take photo"
   * button, and the photo is previewed before the customer can send it.
   *
   * @param form The capture form element.
   */
  function setUpCapture(form) {
    var input = document.getElementById("capture-input");
    var picker = document.getElementById("capture-picker");
    var start = document.getElementById("capture-start");
    var review = document.getElementById("capture-review");
    var preview = document.getElementById("capture-preview");
    var send = document.getElementById("capture-send");
    var retake = document.getElementById("capture-retake");
    var previewUrl = null;

    function showReview(hasPhoto) {
      start.hidden = hasPhoto;
      review.hidden = !hasPhoto;
      send.hidden = !hasPhoto;
      retake.hidden = !hasPhoto;
    }

    input.addEventListener("change", function () {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        previewUrl = null;
      }
      var file = input.files && input.files[0];
      if (file) {
        previewUrl = URL.createObjectURL(file);
        preview.src = previewUrl;
      }
      showReview(Boolean(file));
    });

    function openCamera() {
      input.click();
    }
    start.addEventListener("click", openCamera);
    retake.addEventListener("click", openCamera);

    form.addEventListener("submit", function () {
      send.disabled = true;
      send.textContent = "Sending...";
    });

    picker.hidden = true;
    showReview(false);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var themeButton = document.getElementById("theme-toggle");
    if (themeButton) {
      setUpThemeToggle(themeButton);
    }
    document.querySelectorAll("[data-copy-target]").forEach(setUpCopyButton);
    var captureForm = document.getElementById("capture-form");
    if (captureForm) {
      setUpCapture(captureForm);
    }
  });
})();