// Optima — front-end glue. Theme + preferences live in localStorage as a
// quick win for re-applying user prefs before the server roundtrip lands.

(function () {
  function applyPrefs(p) {
    const root = document.documentElement;
    root.setAttribute("data-theme", p.theme || "light");
    root.setAttribute("data-contrast", p.high_contrast ? "high" : "normal");
    root.setAttribute("data-focus", p.focus_highlights ? "on" : "off");
    document.body.style.zoom = (p.zoom || 100) + "%";
  }

  // Read whatever the server rendered into the <html> data-* attributes so
  // the first paint matches the user's saved preferences, then back it up to
  // localStorage for quick boots.
  const root = document.documentElement;
  const fromAttr = {
    theme: root.getAttribute("data-theme") || "light",
    high_contrast: root.getAttribute("data-contrast") === "high",
    focus_highlights: root.getAttribute("data-focus") === "on",
    zoom: parseInt(root.getAttribute("data-zoom") || "100", 10),
  };
  applyPrefs(fromAttr);
  try { localStorage.setItem("optima.prefs", JSON.stringify(fromAttr)); } catch (e) {}

  // -- Zoom via keyboard ---------------------------------------------------
  // The native pywebview window has no browser chrome, so the OS Ctrl/Cmd +/-
  // shortcuts never reach the page. We handle them ourselves: clamp to the
  // same 75–200% range the server enforces, apply instantly, cache to
  // localStorage, and debounce a save so a restart remembers the level.
  const ZOOM_MIN = 75, ZOOM_MAX = 200, ZOOM_STEP = 10;
  let currentZoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, fromAttr.zoom || 100));
  let zoomSaveTimer = null;

  function persistZoom() {
    clearTimeout(zoomSaveTimer);
    zoomSaveTimer = setTimeout(function () {
      fetch("/api/preferences/zoom", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ zoom: currentZoom }),
      }).catch(function (err) { console.error(err); });
    }, 400);
  }

  function setZoom(next) {
    currentZoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(next)));
    document.body.style.zoom = currentZoom + "%";
    // Keep the cached prefs and the preferences-page input (if shown) in sync.
    try {
      const cached = JSON.parse(localStorage.getItem("optima.prefs") || "{}");
      cached.zoom = currentZoom;
      localStorage.setItem("optima.prefs", JSON.stringify(cached));
    } catch (e) {}
    const input = document.querySelector('input[name="zoom"]');
    if (input) input.value = currentZoom;
    persistZoom();
  }

  document.addEventListener("keydown", function (e) {
    if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
    if (e.key === "+" || e.key === "=") {           // = is the unshifted "+"
      e.preventDefault(); setZoom(currentZoom + ZOOM_STEP);
    } else if (e.key === "-" || e.key === "_") {
      e.preventDefault(); setZoom(currentZoom - ZOOM_STEP);
    } else if (e.key === "0") {                      // reset to 100%
      e.preventDefault(); setZoom(100);
    }
  });

  // Toggle progress sliders inline on the dashboard. We update three
  // bits of UI on every input tick so the user sees their drag reflected
  // immediately — the bar fill, the "%" label next to the slider, and
  // the "h left" figure inside the task's sub-line. The actual save is
  // deferred to the 'change' event below so we don't fire a request on
  // every pixel of drag.
  document.addEventListener("input", function (e) {
    const t = e.target;
    if (t && t.classList.contains("progress-slider")) {
      const taskId = t.getAttribute("data-task");
      const value = parseFloat(t.value) / 100;
      const bar = document.querySelector(`[data-progress-bar="${taskId}"]`);
      if (bar) bar.style.width = (value * 100) + "%";
      const pctEl = document.querySelector(`[data-task-pct-label="${taskId}"]`);
      if (pctEl) pctEl.textContent = Math.round(value * 100) + "%";
      const hLeftEl = document.querySelector(`[data-task-h-left="${taskId}"]`);
      const hoursRequired = parseFloat(t.getAttribute("data-hours-required") || "0");
      if (hLeftEl && isFinite(hoursRequired)) {
        const remaining = Math.max(0, hoursRequired * (1 - value));
        hLeftEl.textContent = remaining.toFixed(1);
      }
      // Throttle save: only persist on change end, not every tick.
      t.dataset.pending = "1";
    }
  });

  document.addEventListener("change", async function (e) {
    const t = e.target;
    if (t && t.classList.contains("progress-slider") && t.dataset.pending === "1") {
      t.dataset.pending = "";
      const taskId = t.getAttribute("data-task");
      const value = parseFloat(t.value) / 100;
      try {
        const r = await fetch(`/api/tasks/${taskId}/progress`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ completion_percent: value }),
        });
        if (!r.ok) console.warn("save failed", r.status);
      } catch (err) { console.error(err); }
    }
  });

  // Splash stays up until the user clicks Sign in or Create account.
  // (The earlier auto-redirect on a 1.5s timer was removed — a tester
  // could blink and miss the brand frame entirely.)
})();
