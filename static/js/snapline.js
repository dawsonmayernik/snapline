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

  /**
   * Smallest hide box kept, as a fraction of the photo's width, so a stray
   * tap does not leave a tiny box behind.
   */
  var MIN_BOX_FRACTION = 0.02;

  /** JPEG quality used when a photo with hidden areas is re-encoded. */
  var REDACTED_JPEG_QUALITY = 0.9;
  
  /** Fill color for hidden areas: solid, so nothing can be recovered. */
  var HIDE_FILL = "#000";

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
   * Whether this browser supports hiding areas of a photo.
   * @return True if canvas export and replacing a file input's file work.
   */
  function canHideAreas() {
    return (
      typeof window.createImageBitmap === "function" &&
      typeof window.DataTransfer === "function" &&
      typeof HTMLCanvasElement.prototype.toBlob === "function"
    );
  }

  /**
   * Build the "Hide an area" tool for the capture form.
   *
   * The photo is drawn onto a canvas, and each area the customer drags over
   * is covered with a solid box. Solid boxes are used instead of blurring or
   * pixelating, which can be partially reversed. If any areas were hidden,
   * the canvas replaces the original file before upload, so the uncovered
   * photo never leaves the phone.
   *
   * @param form The capture form element.
   * @param input The form's file input.
   * @return An object with load(file), hasHiddenAreas(), and
   * replaceUpload(done) methods.
   */
  function createRedactor(form, input) {
    var canvas = document.getElementById("capture-canvas");
    var tools = document.getElementById("hide-tools");
    var toggle = document.getElementById("hide-toggle");
    var undo = document.getElementById("hide-undo");
    var help = document.getElementById("hide-help");
    var context = canvas.getContext("2d");
    var maxDimension = Number(form.dataset.maxDimension);
    var bitmap = null;
    var boxes = [];
    var dragStart = null;
    var dragBox = null;
    var hiding = false;

    function redraw() {
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      context.fillStyle = HIDE_FILL;
      boxes.concat(dragBox ? [dragBox] : []).forEach(function (box) {
        context.fillRect(box.x, box.y, box.w, box.h);
      });
      undo.hidden = boxes.length === 0;
    }

    function setHiding(on) {
      hiding = on;
      toggle.setAttribute("aria-pressed", String(on));
      toggle.textContent = on ? "Done hiding" : "Hide an area";
      help.hidden = !on;
      canvas.classList.toggle("hiding", on);
    }

    function toCanvasPoint(event) {
      var rect = canvas.getBoundingClientRect();
      return {
        x: (event.clientX - rect.left) * (canvas.width / rect.width),
        y: (event.clientY - rect.top) * (canvas.height / rect.height)
      };
    }

    function boxBetween(a, b) {
      return {
        x: Math.min(a.x, b.x),
        y: Math.min(a.y, b.y),
        w: Math.abs(b.x - a.x),
        h: Math.abs(b.y - a.y)
      };
    }

    canvas.addEventListener("pointerdown", function (event) {
      if (!hiding) {
        return;
      }
      event.preventDefault();
      canvas.setPointerCapture(event.pointerId);
      dragStart = toCanvasPoint(event);
    });

    canvas.addEventListener("pointermove", function (event) {
      if (!dragStart) {
        return;
      }
      dragBox = boxBetween(dragStart, toCanvasPoint(event));
      redraw();
    });

    canvas.addEventListener("pointerup", function (event) {
      if (!dragStart) {
        return;
      }
      var box = boxBetween(dragStart, toCanvasPoint(event));
      var minSize = canvas.width * MIN_BOX_FRACTION;
      dragStart = null;
      dragBox = null;
      if (box.w >= minSize && box.h >= minSize) {
        boxes.push(box);
      }
      redraw();
    });

    canvas.addEventListener("pointercancel", function () {
      dragStart = null;
      dragBox = null;
      redraw();
    });

    toggle.addEventListener("click", function () {
      setHiding(!hiding);
    });

    undo.addEventListener("click", function () {
      boxes.pop();
      redraw();
    });

    return {
      load: function (file) {
        boxes = [];
        setHiding(false);
        return window
          .createImageBitmap(file, { imageOrientation: "from-image" })
          .then(function (image) {
            if (bitmap) {
              bitmap.close();
            }
            bitmap = image;
            var scale = Math.min(1, maxDimension / Math.max(image.width, image.height));
            canvas.width = Math.round(image.width * scale);
            canvas.height = Math.round(image.height * scale);
            redraw();
            tools.hidden = false;
          });
      },
      hasHiddenAreas: function () {
        return boxes.length > 0;
      },
      replaceUpload: function (done) {
        canvas.toBlob(
          function (blob) {
            var transfer = new DataTransfer();
            transfer.items.add(new File([blob], "photo.jpg", { type: "image/jpeg" }));
            input.files = transfer.files;
            done();
          },
          "image/jpeg",
          REDACTED_JPEG_QUALITY
        );
      }
    };
  }

  /**
   * Turn the plain photo form into Take photo -> review -> Send/Retake.
   *
   * Without this script the page still works as a file picker plus a Send
   * button. With it, the picker is hidden behind a large "Take photo"
   * button, the photo is previewed before it can be sent, and (where the
   * browser supports it) the customer can hide areas of the photo.
   *
   * @param form The capture form element.
   */
  function setUpCapture(form) {
    var input = document.getElementById("capture-input");
    var picker = document.getElementById("capture-picker");
    var start = document.getElementById("capture-start");
    var review = document.getElementById("capture-review");
    var preview = document.getElementById("capture-preview");
    var canvas = document.getElementById("capture-canvas");
    var tools = document.getElementById("hide-tools");
    var send = document.getElementById("capture-send");
    var retake = document.getElementById("capture-retake");
    var redactor = canHideAreas() ? createRedactor(form, input) : null;
    var previewUrl = null;

    function showReview(hasPhoto) {
      start.hidden = hasPhoto;
      review.hidden = !hasPhoto;
      send.hidden = !hasPhoto;
      retake.hidden = !hasPhoto;
    }

    function showImagePreview(file) {
      previewUrl = URL.createObjectURL(file);
      preview.src = previewUrl;
      preview.hidden = false;
      canvas.hidden = true;
      tools.hidden = true;
    }

    input.addEventListener("change", function () {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        previewUrl = null;
      }
      var file = input.files && input.files[0];
      showReview(Boolean(file));
      if (!file) {
        return;
      }
      if (!redactor) {
        showImagePreview(file);
        return;
      }
      preview.hidden = true;
      canvas.hidden = false;
      redactor.load(file).catch(function () {
        showImagePreview(file);
      });
    });

    function openCamera() {
      input.click();
    }
    start.addEventListener("click", openCamera);
    retake.addEventListener("click", openCamera);

    form.addEventListener("submit", function (event) {
      send.disabled = true;
      send.textContent = "Sending...";
      if (redactor && redactor.hasHiddenAreas()) {
        event.preventDefault();
        redactor.replaceUpload(function () {
          form.submit();
        });
      }
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
