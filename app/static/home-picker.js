/**
 * Custom 14-day strip: syncs selection to hidden input for POST /results.
 */
(function () {
  var hidden = document.getElementById("game_date");
  var strip = document.getElementById("date-strip");
  if (!hidden || !strip) return;

  function setSelected(iso) {
    hidden.value = iso;
    strip.querySelectorAll(".date-strip__cell").forEach(function (btn) {
      var on = btn.getAttribute("data-date") === iso;
      btn.classList.toggle("date-strip__cell--selected", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  strip.addEventListener("click", function (e) {
    var btn = e.target.closest(".date-strip__cell");
    if (!btn || btn.disabled) return;
    var iso = btn.getAttribute("data-date");
    if (iso) setSelected(iso);
  });

  strip.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    var cells = Array.prototype.slice.call(
      strip.querySelectorAll(".date-strip__cell")
    );
    var cur = strip.querySelector(".date-strip__cell--selected");
    var i = cur ? cells.indexOf(cur) : 0;
    if (e.key === "ArrowLeft") i = Math.max(0, i - 1);
    else i = Math.min(cells.length - 1, i + 1);
    cells[i].focus();
    setSelected(cells[i].getAttribute("data-date"));
    e.preventDefault();
  });

  setSelected(hidden.value || strip.dataset.defaultSelected || "");
})();
