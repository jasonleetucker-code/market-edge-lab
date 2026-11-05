/* Market Edge Terminal v1: progressive enhancements only (docs/design/UI_CONTRACT.md §20).
   Navigation, filters, account selection and disclosures all work without this file.
   The intel packet's copy button (UI_CONTRACT §14, 2026-11-05) is hidden until this file reveals it.
   No network requests, no polling, no storage of financial data, no innerHTML. */
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.add("js");

  // Tape: desktop left/right controls scroll the tape's own container (never the page).
  var tape = document.querySelector("[data-tape]");
  if (tape) {
    var track = tape.querySelector("[data-tape-track]");
    var prev = tape.querySelector("[data-tape-prev]");
    var next = tape.querySelector("[data-tape-next]");
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var step = function (dir) {
      if (!track) { return; }
      track.scrollBy({ left: dir * Math.max(track.clientWidth * 0.8, 200), behavior: reduce ? "auto" : "smooth" });
    };
    var sync = function () {
      if (!track || !prev || !next) { return; }
      var max = track.scrollWidth - track.clientWidth - 1;
      prev.disabled = track.scrollLeft <= 0;
      next.disabled = track.scrollLeft >= max;
      prev.hidden = next.hidden = max <= 0;
    };
    if (prev) { prev.hidden = false; prev.addEventListener("click", function () { step(-1); }); }
    if (next) { next.hidden = false; next.addEventListener("click", function () { step(1); }); }
    if (track) {
      track.addEventListener("scroll", sync, { passive: true });
      window.addEventListener("resize", sync);
      sync();
    }
  }

  // Copy: a button with data-copy-target="<id of a readonly textarea>" copies its text. Clipboard API
  // first; otherwise the text is selected so the owner can copy it. Nothing is sent anywhere.
  var copyButtons = document.querySelectorAll("[data-copy-target]");
  Array.prototype.forEach.call(copyButtons, function (btn) {
    var target = document.getElementById(btn.getAttribute("data-copy-target"));
    var status = document.getElementById(btn.getAttribute("data-copy-status") || "");
    if (!target) { return; }
    var say = function (msg) { if (status) { status.textContent = msg; } };
    var selectAll = function () { target.focus(); target.select(); };
    btn.hidden = false;
    btn.addEventListener("click", function () {
      var text = target.value;
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(function () { say("Copied to the clipboard."); }, function () {
          selectAll();
          say("Copy was blocked: the text is selected, copy it with Ctrl+C or long-press.");
        });
        return;
      }
      selectAll();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      say(ok ? "Copied to the clipboard." : "The text is selected: copy it with Ctrl+C or long-press.");
    });
  });
})();
