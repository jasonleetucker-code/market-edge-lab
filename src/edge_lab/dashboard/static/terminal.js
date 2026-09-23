/* Market Edge Terminal v1: progressive enhancements only (docs/design/UI_CONTRACT.md §20).
   Navigation, filters, account selection and disclosures all work without this file.
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
})();
