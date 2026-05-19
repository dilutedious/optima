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

  // Toggle progress sliders inline on the dashboard
  document.addEventListener("input", function (e) {
    const t = e.target;
    if (t && t.classList.contains("progress-slider")) {
      const taskId = t.getAttribute("data-task");
      const value = parseFloat(t.value) / 100;
      const bar = document.querySelector(`[data-progress-bar="${taskId}"]`);
      if (bar) bar.style.width = (value * 100) + "%";
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

  // Splash auto-redirect — gives a beat of brand animation before login.
  if (document.body.classList.contains("splash-page")) {
    const next = document.body.getAttribute("data-next") || "/login";
    setTimeout(() => { window.location.href = next; }, 1500);
  }
})();
