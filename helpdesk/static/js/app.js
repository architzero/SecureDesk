(function () {
  "use strict";

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfMeta ? csrfMeta.getAttribute("content") : "";

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  // Confirmation prompts (data-confirm) and double-submit protection.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var message = form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
      return;
    }
    if ((form.getAttribute("method") || "").toLowerCase() === "post") {
      var buttons = form.querySelectorAll('button[type="submit"], button:not([type])');
      window.setTimeout(function () {
        buttons.forEach(function (b) { b.disabled = true; });
      }, 0);
    }
  });

  // Re-enable buttons when the browser restores a page from its back/forward cache.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) {
      document.querySelectorAll("form button[disabled]").forEach(function (b) {
        if (b.id !== "ai-draft-btn") b.disabled = false;
      });
    }
  });

  // Filters that apply as soon as they change.
  document.querySelectorAll("select[data-autosubmit]").forEach(function (select) {
    select.addEventListener("change", function () {
      var form = select.form;
      if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
    });
  });

  // Ctrl/Cmd + Enter sends from any textarea.
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
    var target = event.target;
    if (target && target.tagName === "TEXTAREA" && target.form) {
      event.preventDefault();
      target.form.requestSubmit ? target.form.requestSubmit() : target.form.submit();
    }
  });

  // Attachment picker: show the chosen file and catch files that are too big.
  document.querySelectorAll('input[type="file"][data-max-bytes]').forEach(function (input) {
    var status = document.getElementById(input.getAttribute("data-status"));
    if (!status) return;
    var defaultText = status.textContent;
    var maxBytes = parseInt(input.getAttribute("data-max-bytes"), 10);
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      status.classList.remove("is-error");
      if (!file) {
        status.textContent = defaultText;
        return;
      }
      if (file.size > maxBytes) {
        status.textContent = file.name + " is " + formatSize(file.size) +
          ". Files can be up to " + formatSize(maxBytes) + ". Choose a smaller file.";
        status.classList.add("is-error");
        input.value = "";
        return;
      }
      status.textContent = "Attaching " + file.name + " (" + formatSize(file.size) + ").";
    });
  });

  // "Draft reply with AI" for agents.
  var aiButton = document.getElementById("ai-draft-btn");
  if (aiButton && !aiButton.disabled) {
    var textarea = document.getElementById("reply-body");
    var note = document.getElementById("ai-note");
    var draftInput = document.getElementById("ai-draft-id");
    var label = aiButton.querySelector(".btn-label");
    var idleLabel = label.textContent;

    var showNote = function (text, isError) {
      note.textContent = text;
      note.classList.toggle("is-error", !!isError);
      note.hidden = !text;
    };

    aiButton.addEventListener("click", function () {
      if (textarea.value.trim() && !window.confirm("Replace what you've written with an AI draft?")) return;

      aiButton.disabled = true;
      aiButton.setAttribute("aria-busy", "true");
      label.textContent = "Drafting…";
      showNote("", false);

      fetch(aiButton.getAttribute("data-url"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf, "X-Requested-With": "fetch", "Accept": "application/json" }
      })
        .then(function (response) {
          var type = response.headers.get("content-type") || "";
          if (type.indexOf("application/json") === -1) {
            throw new Error("Your session may have expired. Reload the page and try again.");
          }
          return response.json().then(function (data) {
            if (!response.ok) throw new Error(data.error || "Couldn't create a draft. Try again.");
            return data;
          });
        })
        .then(function (data) {
          textarea.value = data.draft;
          draftInput.value = data.id;
          textarea.focus();
          textarea.setSelectionRange(0, 0);
          textarea.scrollTop = 0;
          showNote("Draft ready. Check every detail and edit it before you send.", false);
        })
        .catch(function (error) {
          showNote(error.message || "Couldn't create a draft. Try again.", true);
        })
        .finally(function () {
          aiButton.disabled = false;
          aiButton.removeAttribute("aria-busy");
          label.textContent = idleLabel;
        });
    });
  }
})();