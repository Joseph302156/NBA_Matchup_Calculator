/**
 * Date row shows MM/DD/YYYY; only the calendar icon opens the dark 2-row picker.
 */
(function () {
  var hidden = document.getElementById("game_date");
  var strip = document.getElementById("date-strip");
  var calendarBtn = document.getElementById("date-calendar-btn");
  var popover = document.getElementById("date-popover");
  var display = document.getElementById("date-display");
  var wrap = document.querySelector(".date-trigger-wrap");

  if (!hidden || !strip || !calendarBtn || !popover || !display || !wrap) return;

  function pad2(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function formatDisplay(iso) {
    var d = new Date(iso + "T12:00:00");
    if (isNaN(d.getTime())) return iso;
    return pad2(d.getMonth() + 1) + "/" + pad2(d.getDate()) + "/" + d.getFullYear();
  }

  function setSelected(iso) {
    hidden.value = iso;
    display.textContent = formatDisplay(iso);
    strip.querySelectorAll(".date-strip__cell").forEach(function (btn) {
      var on = btn.getAttribute("data-date") === iso;
      btn.classList.toggle("date-strip__cell--selected", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  function isOpen() {
    return !popover.hidden;
  }

  function openPopover() {
    popover.hidden = false;
    calendarBtn.setAttribute("aria-expanded", "true");
    document.body.classList.add("date-popover-open");
    var first =
      strip.querySelector(".date-strip__cell--selected") ||
      strip.querySelector(".date-strip__cell");
    if (first) first.focus();
  }

  function closePopover() {
    popover.hidden = true;
    calendarBtn.setAttribute("aria-expanded", "false");
    document.body.classList.remove("date-popover-open");
    calendarBtn.focus();
  }

  function togglePopover() {
    if (isOpen()) closePopover();
    else openPopover();
  }

  calendarBtn.addEventListener("click", function (e) {
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
    var cells = Array.prototype.slice.call(strip.querySelectorAll(".date-strip__cell"));
    var cur = strip.querySelector(".date-strip__cell--selected");
    var i = cur ? cells.indexOf(cur) : 0;
    var next = i;
    if (e.key === "ArrowRight") next = Math.min(cells.length - 1, i + 1);
    else if (e.key === "ArrowLeft") next = Math.max(0, i - 1);
    else if (e.key === "ArrowDown") next = Math.min(cells.length - 1, i + 7);
    else if (e.key === "ArrowUp") next = Math.max(0, i - 7);
    else return;
    cells[next].focus();
    setSelected(cells[next].getAttribute("data-date"));
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
