/**
 * Compact date field + calendar icon opens dark 14-day popover.
 */
(function () {
  var hidden = document.getElementById("game_date");
  var strip = document.getElementById("date-strip");
  var trigger = document.getElementById("date-trigger");
  var popover = document.getElementById("date-popover");
  var display = document.getElementById("date-display");
  var wrap = document.querySelector(".date-trigger-wrap");

  if (!hidden || !strip || !trigger || !popover || !display || !wrap) return;

  function formatIso(iso) {
    var d = new Date(iso + "T12:00:00");
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }

  function setSelected(iso) {
    hidden.value = iso;
    display.textContent = formatIso(iso);
    strip.querySelectorAll(".date-strip__cell").forEach(function (btn) {
      var on = btn.getAttribute("data-date") === iso;
      btn.classList.toggle("date-strip__cell--selected", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function isOpen() {
    return !popover.hidden;
  }

  function openPopover() {
    popover.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    document.body.classList.add("date-popover-open");
    var first = strip.querySelector(".date-strip__cell--selected") || strip.querySelector(".date-strip__cell");
    if (first) first.focus();
  }

  function closePopover() {
    popover.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    document.body.classList.remove("date-popover-open");
    trigger.focus();
  }

  function togglePopover() {
    if (isOpen()) closePopover();
    else openPopover();
  }

  trigger.addEventListener("click", function (e) {
    e.stopPropagation();
    togglePopover();
  });

  strip.addEventListener("click", function (e) {
    var btn = e.target.closest(".date-strip__cell");
    if (!btn || btn.disabled) return;
    var iso = btn.getAttribute("data-date");
    if (iso) {
      setSelected(iso);
      closePopover();
    }
  });

  strip.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    var cells = Array.prototype.slice.call(strip.querySelectorAll(".date-strip__cell"));
    var cur = strip.querySelector(".date-strip__cell--selected");
    var i = cur ? cells.indexOf(cur) : 0;
    if (e.key === "ArrowLeft") i = Math.max(0, i - 1);
    else i = Math.min(cells.length - 1, i + 1);
    cells[i].focus();
    setSelected(cells[i].getAttribute("data-date"));
    e.preventDefault();
  });

  document.addEventListener("click", function (e) {
    if (isOpen() && !wrap.contains(e.target)) closePopover();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && isOpen()) {
      e.preventDefault();
      closePopover();
    }
  });

  setSelected(hidden.value || strip.dataset.defaultSelected || "");
})();
