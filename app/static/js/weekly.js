// Optima weekly editor — interactive calendar for fixed events.
//
// All state lives in three places:
//   1. The server (authoritative). Wire format is decimal hours.
//   2. `state.events` — last-fetched server snapshot for the visible week.
//   3. `state.selection` — Set of ("<constraintId>@<isoDate>") occurrence keys.
//
// Everything else (drag offsets, modal context, etc.) is local to a handler.
// Times are *only* converted to/from "10:30am"/"22:30" strings at the DOM
// boundary; the backend never sees clock strings.

(function () {
  "use strict";

  const grid = document.getElementById("weekGrid");
  if (!grid) return;

  const initialData = JSON.parse(document.getElementById("initialData").textContent);
  const HOUR_PX = 48;
  const HOUR_START = parseInt(grid.dataset.hourStart, 10);
  const HOUR_END = parseInt(grid.dataset.hourEnd, 10);
  const SNAP_MIN = parseInt(grid.dataset.snapMin, 10) || 5;
  const SNAP_HOURS = SNAP_MIN / 60;

  const state = {
    timeFormat: initialData.time_format,
    subjects: initialData.subjects,
    events: [],          // [{id, date, name, start_time, end_time, kind, recurrence, ...}]
    blocks: [],          // read-only study + break blocks
    periods: [],         // preset times from Settings
    sleepStart: 22.5,
    sleepEnd: 6.5,
    selection: new Set(),
    weekStart: new Date(grid.dataset.weekStart + "T00:00:00"),
  };

  // ------------------------------------------------------------------
  // Time formatting helpers — decimal hours ↔ user-facing clock strings.
  // ------------------------------------------------------------------
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function snap(v) {
    return Math.round(v / SNAP_HOURS) * SNAP_HOURS;
  }

  function decimalToHM(dec) {
    const h = Math.floor(dec);
    const m = Math.round((dec - h) * 60);
    return { h: m === 60 ? h + 1 : h, m: m === 60 ? 0 : m };
  }

  // Pixels-per-hour as currently rendered. Derived from the day-col's
  // ACTUAL height so the math is right regardless of the user's zoom
  // pref — the constant HOUR_PX is CSS px, but e.clientY / rect.top are
  // in zoomed viewport px, so dividing y by HOUR_PX gave the wrong hour
  // count whenever zoom != 100%.
  function dayHourPx(col) {
    if (!col) return HOUR_PX;
    const rect = col.getBoundingClientRect();
    const hours = HOUR_END - HOUR_START;
    return hours > 0 ? rect.height / hours : HOUR_PX;
  }

  function formatTime(dec) {
    const { h, m } = decimalToHM(dec);
    if (state.timeFormat === "12h") {
      const ampm = h < 12 ? "am" : "pm";
      const h12 = ((h + 11) % 12) + 1;
      return m === 0 ? `${h12}${ampm}` : `${h12}:${String(m).padStart(2, "0")}${ampm}`;
    }
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  }

  function parseTime(raw) {
    // Accepts "9:30am", "21:00", "9", "9.5". Returns decimal hours or NaN.
    if (raw == null) return NaN;
    const s = String(raw).trim().toLowerCase().replace(/\s+/g, "");
    if (!s) return NaN;
    const ampmMatch = s.match(/^(\d{1,2})(?::(\d{1,2}))?(am|pm)$/);
    if (ampmMatch) {
      let h = parseInt(ampmMatch[1], 10);
      const m = ampmMatch[2] ? parseInt(ampmMatch[2], 10) : 0;
      const ap = ampmMatch[3];
      if (h === 12) h = 0;
      if (ap === "pm") h += 12;
      return h + m / 60;
    }
    const hmMatch = s.match(/^(\d{1,2}):(\d{1,2})$/);
    if (hmMatch) return parseInt(hmMatch[1], 10) + parseInt(hmMatch[2], 10) / 60;
    const decMatch = s.match(/^(\d+(?:\.\d+)?)$/);
    if (decMatch) return parseFloat(decMatch[1]);
    return NaN;
  }

  function isoDate(d) {
    // Format the LOCAL date components — toISOString() returns UTC and would
    // shift by the timezone offset for users not on UTC, which makes events
    // jump a day under daylight saving / non-UTC zones.
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }
  function addDays(d, n) {
    const r = new Date(d);
    r.setDate(r.getDate() + n);
    return r;
  }

  // Repaint the hour-label gutter to honour the user's time-format pref.
  function paintHourLabels() {
    grid.querySelectorAll("[data-hour]").forEach((el) => {
      const h = parseInt(el.dataset.hour, 10);
      el.textContent = formatTime(h);
    });
  }

  // ------------------------------------------------------------------
  // Server I/O
  // ------------------------------------------------------------------
  async function fetchWeek() {
    const start = isoDate(state.weekStart);
    const end = isoDate(addDays(state.weekStart, 6));
    const r = await fetch(`/api/events?start=${start}&end=${end}`, {
      headers: { "Accept": "application/json" },
    });
    if (!r.ok) throw new Error(`Fetch failed: ${r.status}`);
    const data = await r.json();
    state.events = data.events || [];
    state.blocks = data.blocks || [];
    state.subjects = data.subjects || state.subjects;
    state.periods = data.periods || [];
    state.timeFormat = data.time_format || state.timeFormat;
    if (typeof data.sleep_start === "number") state.sleepStart = data.sleep_start;
    if (typeof data.sleep_end === "number") state.sleepEnd = data.sleep_end;
    paintHourLabels();
    render();
  }

  async function apiCreate(payload) {
    const r = await fetch("/api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return r.json().then((data) => ({ ok: r.ok, data }));
  }

  async function apiUpdate(id, payload) {
    const r = await fetch(`/api/events/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return r.json().then((data) => ({ ok: r.ok, data }));
  }

  async function apiDelete(id, scope, onDate) {
    const qs = new URLSearchParams({ scope });
    if (onDate) qs.set("date", onDate);
    const r = await fetch(`/api/events/${id}?${qs}`, { method: "DELETE" });
    return r.json().then((data) => ({ ok: r.ok, data }));
  }

  async function apiMove(moves) {
    const r = await fetch("/api/events/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ moves }),
    });
    return r.json().then((data) => ({ ok: r.ok, data }));
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------
  function dayCol(iso) {
    return grid.querySelector(`.day-col[data-date="${iso}"]`);
  }

  function render() {
    // Clear all event blocks but keep hour-row dividers.
    grid.querySelectorAll(".day-col").forEach((col) => {
      col.querySelectorAll(".ev, .study-block, .sleep-overlay, .now-line").forEach((n) => n.remove());
      paintSleepOverlay(col);
    });

    for (const ev of state.events) {
      const col = dayCol(ev.date);
      if (!col) continue;
      col.appendChild(renderEvent(ev));
    }
    for (const b of state.blocks) {
      const col = dayCol(b.date);
      if (!col || b.is_break) continue;   // breaks are implicit on the grid
      col.appendChild(renderBlock(b));
    }
    paintNowLine();
    annotateBreaks();
    updateToolbar();
  }

  function paintNowLine() {
    // Place a red horizontal line at the current time in today's column.
    // Only renders if today is actually visible in the current week range.
    const todayIso = grid.dataset.today;
    const col = dayCol(todayIso);
    if (!col) return;
    col.querySelectorAll(".now-line").forEach((n) => n.remove());
    const now = new Date();
    const dec = now.getHours() + now.getMinutes() / 60;
    if (dec < HOUR_START || dec > HOUR_END) return;
    const line = document.createElement("div");
    line.className = "now-line";
    line.style.top = `${(dec - HOUR_START) * HOUR_PX}px`;
    line.title = `Now · ${formatTime(dec)}`;
    col.appendChild(line);
  }

  // Refresh the now-line once a minute. Tab might be inactive longer than
  // that — the next visible refresh corrects it.
  setInterval(paintNowLine, 60 * 1000);

  function paintSleepOverlay(col) {
    // The sleep window can wrap past midnight — split into two rectangles
    // if it does. Each rectangle is clipped to the visible hour range.
    const intervals = [];
    if (state.sleepStart === state.sleepEnd) return;
    if (state.sleepStart < state.sleepEnd) {
      intervals.push([state.sleepStart, state.sleepEnd]);
    } else {
      intervals.push([state.sleepStart, 24]);
      intervals.push([0, state.sleepEnd]);
    }
    for (const [s, e] of intervals) {
      const clippedStart = Math.max(s, HOUR_START);
      const clippedEnd = Math.min(e, HOUR_END);
      if (clippedEnd <= clippedStart) continue;
      const div = document.createElement("div");
      div.className = "sleep-overlay";
      div.title = `Sleep · ${formatTime(s)} – ${formatTime(e)}`;
      div.style.top = `${(clippedStart - HOUR_START) * HOUR_PX}px`;
      div.style.height = `${(clippedEnd - clippedStart) * HOUR_PX}px`;
      col.appendChild(div);
    }
  }

  function annotateBreaks() {
    // For each day, build a tooltip listing planned breaks and any
    // overlapping study-block intervals, then attach to the .day-col.
    grid.querySelectorAll(".day-col").forEach((col) => {
      const iso = col.dataset.date;
      const breaks = state.blocks.filter((b) => b.date === iso && b.is_break);
      const studies = state.blocks.filter((b) => b.date === iso && !b.is_break);
      if (!breaks.length && !studies.length) {
        col.removeAttribute("title");
        return;
      }
      const lines = [];
      if (studies.length) {
        lines.push("Study sessions:");
        for (const s of studies) {
          lines.push(`  ${formatTime(s.start_time)} – ${formatTime(s.end_time)}  ${s.name}`);
        }
      }
      if (breaks.length) {
        lines.push("Breaks:");
        for (const b of breaks) {
          lines.push(`  ${formatTime(b.start_time)} – ${formatTime(b.end_time)}`);
        }
      }
      col.title = lines.join("\n");
    });
  }

  function evKey(ev) { return `${ev.id}@${ev.date}`; }

  function renderEvent(ev) {
    const el = document.createElement("div");
    el.className = `ev kind-${ev.kind}`;
    el.dataset.evId = ev.id;
    el.dataset.evDate = ev.date;
    el.dataset.recurrence = ev.recurrence;
    el.style.background = ev.colour;
    positionEvent(el, ev.start_time, ev.end_time);
    el.innerHTML = `
      <span class="ev-name">${escapeHtml(ev.name)}</span>
      <span class="ev-time">${formatTime(ev.start_time)} – ${formatTime(ev.end_time)}</span>
      ${ev.recurrence && ev.recurrence !== "none" ? `<span class="ev-recur" title="${ev.recurrence}">↻</span>` : ""}
    `;
    if (state.selection.has(evKey(ev))) el.classList.add("selected");
    return el;
  }

  function renderBlock(b) {
    const el = document.createElement("div");
    el.className = "study-block";
    // ~35 min and shorter can't hold two stacked lines of text without
    // looking cramped — collapse to a single-line layout instead.
    if ((b.end_time - b.start_time) < 0.6) el.classList.add("compact");
    el.style.background = b.colour;
    positionEvent(el, b.start_time, b.end_time);
    el.innerHTML = `
      <span class="ev-name">${escapeHtml(b.name)}</span>
      <span class="ev-time">${formatTime(b.start_time)} – ${formatTime(b.end_time)}</span>
    `;
    return el;
  }

  function positionEvent(el, start, end) {
    const top = (start - HOUR_START) * HOUR_PX;
    const height = Math.max(20, (end - start) * HOUR_PX);
    el.style.top = `${top}px`;
    el.style.height = `${height}px`;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  // ------------------------------------------------------------------
  // Selection
  // ------------------------------------------------------------------
  function toggleSelect(key, additive) {
    if (!additive) state.selection.clear();
    if (state.selection.has(key)) state.selection.delete(key);
    else state.selection.add(key);
    updateToolbar();
    repaintSelection();
  }

  function clearSelection() {
    state.selection.clear();
    updateToolbar();
    repaintSelection();
  }

  function repaintSelection() {
    grid.querySelectorAll(".ev").forEach((el) => {
      const key = `${el.dataset.evId}@${el.dataset.evDate}`;
      el.classList.toggle("selected", state.selection.has(key));
    });
  }

  function updateToolbar() {
    const n = state.selection.size;
    const status = document.getElementById("multiStatus");
    const btnDel = document.getElementById("btnDeleteSelected");
    const btnNone = document.getElementById("btnDeselect");
    status.textContent = n === 0
      ? "Nothing selected"
      : `${n} occurrence${n === 1 ? "" : "s"} selected`;
    btnDel.disabled = n === 0;
    btnNone.disabled = n === 0;
  }

  // ------------------------------------------------------------------
  // Modal helpers
  // ------------------------------------------------------------------
  function fillSelect(select, options, current) {
    select.innerHTML = "";
    for (const o of options) {
      const opt = document.createElement("option");
      opt.value = o.value;
      opt.textContent = o.label;
      if (o.value === current) opt.selected = true;
      select.appendChild(opt);
    }
  }

  function fillSubjects(select, current) {
    while (select.options.length > 1) select.remove(1);
    for (const s of state.subjects) {
      const opt = document.createElement("option");
      opt.value = String(s.id);
      opt.textContent = s.name;
      if (current === s.id) opt.selected = true;
      select.appendChild(opt);
    }
  }

  function fillPeriodPresets(select) {
    select.innerHTML = "";
    const none = document.createElement("option");
    none.value = ""; none.textContent = "— None —";
    select.appendChild(none);
    for (const p of state.periods) {
      const opt = document.createElement("option");
      opt.value = String(p.id);
      opt.textContent = `${p.name} (${formatTime(p.start_time)} – ${formatTime(p.end_time)})`;
      opt.dataset.start = p.start_time;
      opt.dataset.end = p.end_time;
      select.appendChild(opt);
    }
  }

  function openModal(modeCtx) {
    const modal = document.getElementById("eventModal");
    const form = document.getElementById("evForm");
    const title = document.getElementById("evTitle");
    const errors = document.getElementById("evErrors");
    const delBtn = document.getElementById("evDelete");

    errors.hidden = true;
    errors.textContent = "";

    fillSelect(form.elements.kind, initialData.kinds, modeCtx.kind || "subject");
    fillSelect(form.elements.recurrence, initialData.recurrences,
               modeCtx.recurrence || initialData.default_recurrence || "fortnightly");
    fillSubjects(form.elements.subject_id, modeCtx.subject_id || null);
    fillPeriodPresets(form.elements.period_preset);

    form.elements.name.value = modeCtx.name || "";
    form.elements.start_time.value = modeCtx.start_time;
    form.elements.end_time.value = modeCtx.end_time;
    form.elements.start_display.value = formatTime(modeCtx.start_time);
    form.elements.end_display.value = formatTime(modeCtx.end_time);
    form.elements.anchor_date.value = modeCtx.anchor_date || modeCtx.date;

    title.textContent = modeCtx.id ? "Edit event" : "New event";
    delBtn.hidden = !modeCtx.id;

    form.dataset.mode = modeCtx.id ? "edit" : "create";
    form.dataset.evId = modeCtx.id || "";
    form.dataset.onDate = modeCtx.date || "";

    modal.hidden = false;
    setTimeout(() => form.elements.name.focus(), 30);
  }

  function closeModal() {
    document.getElementById("eventModal").hidden = true;
  }

  // Confirm modal: returns a Promise resolving to the chosen button value.
  function confirmChoice({ title, body, choices }) {
    const modal = document.getElementById("confirmModal");
    document.getElementById("cfTitle").textContent = title;
    document.getElementById("cfBody").textContent = body;
    const wrap = document.getElementById("cfChoices");
    wrap.innerHTML = "";
    modal.hidden = false;
    return new Promise((resolve) => {
      for (const c of choices) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = `btn${c.variant ? " " + c.variant : ""}`;
        b.textContent = c.label;
        b.addEventListener("click", () => {
          modal.hidden = true;
          resolve(c.value);
        });
        wrap.appendChild(b);
      }
    });
  }

  // ------------------------------------------------------------------
  // Form submission
  // ------------------------------------------------------------------
  document.getElementById("evForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    const errors = document.getElementById("evErrors");
    errors.hidden = true;
    errors.textContent = "";

    const startDec = parseTime(form.elements.start_display.value);
    const endDec = parseTime(form.elements.end_display.value);
    if (!isFinite(startDec) || !isFinite(endDec)) {
      errors.textContent = "Couldn't parse those times. Try 9:30am or 21:00.";
      errors.hidden = false;
      return;
    }
    if (endDec <= startDec) {
      errors.textContent = "End time must be after start time.";
      errors.hidden = false;
      return;
    }

    const subjId = form.elements.subject_id.value;
    const payload = {
      name: form.elements.name.value,
      kind: form.elements.kind.value,
      recurrence: form.elements.recurrence.value,
      start_time: snap(startDec),
      end_time: snap(endDec),
      anchor_date: form.elements.anchor_date.value,
      subject_id: subjId ? parseInt(subjId, 10) : null,
    };

    let result;
    if (form.dataset.mode === "edit") {
      const id = parseInt(form.dataset.evId, 10);
      const original = state.events.find((e) => e.id === id && e.date === form.dataset.onDate);
      const isRecurring = original && original.recurrence && original.recurrence !== "none";
      let scope = "all";
      if (isRecurring) {
        const choice = await confirmChoice({
          title: "Edit recurring event",
          body: `"${original.name}" repeats. Apply your changes to all occurrences, or only the one on ${original.date}?`,
          choices: [
            { value: "cancel", label: "Cancel", variant: "ghost" },
            { value: "this", label: "Only this one" },
            { value: "all", label: "All occurrences" },
          ],
        });
        if (choice === "cancel") return;
        scope = choice;
      }
      payload.scope = scope;
      if (scope === "this") payload.on_date = form.dataset.onDate;
      result = await apiUpdate(id, payload);
    } else {
      result = await apiCreate(payload);
    }

    if (!result.ok) {
      errors.textContent = (result.data.errors || ["Save failed."]).join(" ");
      errors.hidden = false;
      return;
    }
    closeModal();
    clearSelection();
    await fetchWeek();
  });

  document.getElementById("evClose").addEventListener("click", closeModal);
  document.getElementById("evCancel").addEventListener("click", closeModal);

  document.getElementById("evDelete").addEventListener("click", async () => {
    const form = document.getElementById("evForm");
    const id = parseInt(form.dataset.evId, 10);
    const onDate = form.dataset.onDate;
    const original = state.events.find((e) => e.id === id && e.date === onDate);
    const isRecurring = original && original.recurrence && original.recurrence !== "none";
    let scope = "all";
    if (isRecurring) {
      const choice = await confirmChoice({
        title: "Delete recurring event",
        body: `"${original.name}" repeats. Remove just the one on ${original.date}, or every occurrence?`,
        choices: [
          { value: "cancel", label: "Cancel", variant: "ghost" },
          { value: "this", label: "Only this one", variant: "danger" },
          { value: "all", label: "All occurrences", variant: "danger" },
        ],
      });
      if (choice === "cancel") return;
      scope = choice;
    } else {
      const ok = await confirmChoice({
        title: "Delete event",
        body: `Delete "${original.name}"?`,
        choices: [
          { value: "cancel", label: "Cancel", variant: "ghost" },
          { value: "all", label: "Delete", variant: "danger" },
        ],
      });
      if (ok === "cancel") return;
    }
    const r = await apiDelete(id, scope, onDate);
    if (!r.ok) { alert("Delete failed: " + ((r.data.errors || []).join(" ") || r.data)); return; }
    closeModal();
    clearSelection();
    await fetchWeek();
  });

  // Sync hidden time inputs from the display fields as the user types so the
  // form's required validation still passes even if the user is mid-edit.
  ["start", "end"].forEach((side) => {
    const disp = document.querySelector(`[name="${side}_display"]`);
    const hidden = document.querySelector(`[name="${side}_time"]`);
    disp.addEventListener("input", () => {
      const v = parseTime(disp.value);
      if (isFinite(v)) hidden.value = v.toString();
    });
  });

  // Period preset → populate start/end. Selecting "None" leaves the
  // inputs untouched so the user can still type custom times after.
  const presetSelect = document.querySelector('[name="period_preset"]');
  if (presetSelect) {
    presetSelect.addEventListener("change", () => {
      const opt = presetSelect.options[presetSelect.selectedIndex];
      if (!opt || !opt.value) return;
      const s = parseFloat(opt.dataset.start);
      const e = parseFloat(opt.dataset.end);
      if (!isFinite(s) || !isFinite(e)) return;
      const form = document.getElementById("evForm");
      form.elements.start_display.value = formatTime(s);
      form.elements.end_display.value = formatTime(e);
      form.elements.start_time.value = String(s);
      form.elements.end_time.value = String(e);
    });
  }

  // ------------------------------------------------------------------
  // Click-to-create / click-to-edit / drag-to-move on the grid
  // ------------------------------------------------------------------
  let dragCtx = null;
  // dragCtx shapes:
  //   { kind: "create", colEl, startY, currentY, ghost }
  //   { kind: "move",   evEls: [{el, ev, originalTop, originalDate}], pointerStartY }

  function decimalFromY(y, col) {
    return HOUR_START + y / dayHourPx(col);
  }

  grid.addEventListener("mousedown", (e) => {
    const evEl = e.target.closest(".ev");
    const col = e.target.closest(".day-col");

    if (evEl) {
      // Click on an event — selection / start move.
      const key = `${evEl.dataset.evId}@${evEl.dataset.evDate}`;
      const additive = e.shiftKey || e.metaKey || e.ctrlKey;
      if (!state.selection.has(key) && !additive) clearSelection();
      if (!state.selection.has(key)) toggleSelect(key, additive);
      else if (additive) toggleSelect(key, additive);

      // Begin a potential drag — actual move only commits on mousemove.
      const startY = e.clientY;
      const elements = [];
      grid.querySelectorAll(".ev.selected").forEach((sel) => {
        const id = parseInt(sel.dataset.evId, 10);
        const onDate = sel.dataset.evDate;
        const ev = state.events.find((x) => x.id === id && x.date === onDate);
        if (!ev) return;
        elements.push({
          el: sel,
          ev,
          originalTop: parseFloat(sel.style.top),
          originalDateCol: sel.closest(".day-col"),
        });
      });
      dragCtx = {
        kind: "move",
        startY,
        moved: false,
        elements,
        deltaHours: 0,
        deltaDays: 0,
        startEvKey: key,
      };
      e.preventDefault();
      return;
    }

    if (col && e.button === 0) {
      // Empty space — drag to define a new event range. Refuse the gesture
      // when the click lands inside the sleep window so the user doesn't
      // accidentally schedule a class for 2 AM. The server rejects this
      // case too — but the client refusal lets us show "no entry" feedback
      // immediately instead of after a round-trip.
      const rect = col.getBoundingClientRect();
      const hourPx = dayHourPx(col);
      const startY = e.clientY - rect.top;
      const unsnappedDec = HOUR_START + startY / hourPx;
      if (inSleepWindow(unsnappedDec)) {
        flashSleepBlocked(col);
        e.preventDefault();
        return;
      }
      // The ghost block is positioned at the RAW click y so its top sits
      // exactly under the cursor — no snap drift visible during the drag.
      // Snap only happens at mouseup when we open the modal with rounded
      // times. Prior versions snapped startDec here and used that to
      // compute the ghost top, which produced a 1-4 px gap between cursor
      // and ghost — perceived as "shifted up" especially at high zoom.
      const ghost = document.createElement("div");
      ghost.className = "ev creating";
      ghost.style.top = `${startY}px`;
      ghost.style.height = `${Math.max(20, hourPx * 0.5)}px`;
      col.appendChild(ghost);
      dragCtx = {
        kind: "create",
        col,
        hourPx,
        startY,                 // visual anchor in px
        currentY: startY + hourPx * 0.5,
        startDec: unsnappedDec, // raw — snap on release
        currentDec: unsnappedDec + 0.5,
        ghost,
      };
      e.preventDefault();
    }
  });

  function inSleepWindow(decHour) {
    // Returns true if decHour is inside the user's sleep range — handles
    // the wrap-past-midnight case.
    if (state.sleepStart === state.sleepEnd) return false;
    if (state.sleepStart < state.sleepEnd) {
      return decHour >= state.sleepStart && decHour < state.sleepEnd;
    }
    return decHour >= state.sleepStart || decHour < state.sleepEnd;
  }

  function clampForSleep(startDec, endDec) {
    // Find the start of the first sleep interval that begins at-or-after
    // startDec, and refuse to drag past it.
    const intervals = [];
    if (state.sleepStart === state.sleepEnd) return endDec;
    if (state.sleepStart < state.sleepEnd) {
      intervals.push(state.sleepStart);
    } else {
      intervals.push(state.sleepStart);
      // No need to add the wrap-around boundary at 0 — we're never
      // dragging downward across midnight in a single column.
    }
    for (const boundary of intervals) {
      if (boundary > startDec && endDec > boundary) return boundary;
    }
    return endDec;
  }

  function flashSleepBlocked(col) {
    // Brief pulse on the sleep overlay so the user gets some feedback.
    col.querySelectorAll(".sleep-overlay").forEach((el) => {
      el.classList.add("flash");
      setTimeout(() => el.classList.remove("flash"), 600);
    });
  }

  document.addEventListener("mousemove", (e) => {
    if (!dragCtx) return;
    if (dragCtx.kind === "create") {
      const rect = dragCtx.col.getBoundingClientRect();
      const y = clamp(e.clientY - rect.top, 0, rect.height);
      const hourPx = dragCtx.hourPx;
      // Convert the cursor's y back to a decimal so we can apply the
      // sleep-window clamp in the same units the clamp helper expects.
      let dec = HOUR_START + y / hourPx;
      dec = clampForSleep(dragCtx.startDec, dec);
      // Re-derive the visual end y from the (possibly clamped) decimal.
      const endY = (dec - HOUR_START) * hourPx;
      const minEnd = dragCtx.startY + hourPx * SNAP_HOURS;
      dragCtx.currentY = Math.max(minEnd, endY);
      dragCtx.currentDec = HOUR_START + dragCtx.currentY / hourPx;
      // Ghost top + height follow the raw cursor — no snap drift while
      // the user is moving. Snap only when the modal opens (mouseup).
      dragCtx.ghost.style.top = `${dragCtx.startY}px`;
      dragCtx.ghost.style.height = `${Math.max(20, dragCtx.currentY - dragCtx.startY)}px`;
      return;
    }
    if (dragCtx.kind === "move") {
      const dy = e.clientY - dragCtx.startY;
      if (Math.abs(dy) < 3) return;
      dragCtx.moved = true;
      const deltaHours = snap(dy / HOUR_PX);
      dragCtx.deltaHours = deltaHours;

      // Horizontal column shift — figure out new column by hit-testing.
      const hovered = document.elementFromPoint(e.clientX, e.clientY);
      const hoveredCol = hovered ? hovered.closest(".day-col") : null;
      let deltaDays = 0;
      if (hoveredCol) {
        const orig = dragCtx.elements[0].originalDateCol;
        if (orig && hoveredCol !== orig) {
          const dest = new Date(hoveredCol.dataset.date + "T00:00:00");
          const src = new Date(orig.dataset.date + "T00:00:00");
          deltaDays = Math.round((dest - src) / 86400000);
        }
      }
      dragCtx.deltaDays = deltaDays;

      grid.querySelectorAll(".day-col.drag-over").forEach((c) => c.classList.remove("drag-over"));
      for (const item of dragCtx.elements) {
        item.el.classList.add("dragging");
        const newStart = clamp(item.ev.start_time + deltaHours, HOUR_START, HOUR_END - (item.ev.end_time - item.ev.start_time));
        const newEnd = newStart + (item.ev.end_time - item.ev.start_time);
        positionEvent(item.el, newStart, newEnd);
        if (deltaDays !== 0) {
          const targetDate = addDays(new Date(item.ev.date + "T00:00:00"), deltaDays);
          const targetCol = dayCol(isoDate(targetDate));
          if (targetCol && item.el.parentElement !== targetCol) {
            targetCol.appendChild(item.el);
            targetCol.classList.add("drag-over");
          }
        }
      }
    }
  });

  document.addEventListener("mouseup", async () => {
    if (!dragCtx) return;
    const ctx = dragCtx;
    dragCtx = null;

    if (ctx.kind === "create") {
      ctx.ghost.remove();
      // Snap to 5-minute boundaries ONLY now, at handoff to the modal.
      // During the drag the ghost tracked the cursor raw, but the stored
      // times need to be on the grid so the scheduler's math stays clean.
      const snappedStart = snap(ctx.startDec);
      const snappedEnd = snap(ctx.currentDec);
      if (snappedEnd - snappedStart < SNAP_HOURS) return;
      openModal({
        date: ctx.col.dataset.date,
        anchor_date: ctx.col.dataset.date,
        start_time: snappedStart,
        end_time: snappedEnd,
        recurrence: initialData.default_recurrence || "fortnightly",
        kind: "subject",
      });
      return;
    }

    if (ctx.kind === "move") {
      grid.querySelectorAll(".drag-over").forEach((c) => c.classList.remove("drag-over"));
      grid.querySelectorAll(".dragging").forEach((c) => c.classList.remove("dragging"));
      if (!ctx.moved) {
        // No drag — single click counts as "open editor".
        const [first] = ctx.elements;
        if (first && state.selection.size === 1) {
          openModal({
            id: first.ev.id,
            date: first.ev.date,
            anchor_date: first.ev.date,
            name: first.ev.name,
            kind: first.ev.kind,
            recurrence: first.ev.recurrence,
            subject_id: first.ev.subject_id,
            start_time: first.ev.start_time,
            end_time: first.ev.end_time,
          });
        }
        return;
      }
      // Persist the move.
      const moves = ctx.elements.map((item) => {
        const newStart = clamp(item.ev.start_time + ctx.deltaHours, HOUR_START, HOUR_END - (item.ev.end_time - item.ev.start_time));
        const newEnd = newStart + (item.ev.end_time - item.ev.start_time);
        const newDate = ctx.deltaDays
          ? isoDate(addDays(new Date(item.ev.date + "T00:00:00"), ctx.deltaDays))
          : item.ev.date;
        // If recurring, "this" instance only; else "all" (move the master).
        const recurring = item.ev.recurrence && item.ev.recurrence !== "none";
        // When the user drags across days, recurring events can't stay
        // recurring on the new column with their old anchor — so we fall back
        // to a per-instance override that pins this date+time. The "all"
        // path is only used for same-day moves of non-recurring events.
        const scope = recurring || ctx.deltaDays !== 0 ? "this" : "all";
        return {
          id: item.ev.id,
          on_date: scope === "this" ? newDate : null,
          new_start: newStart,
          new_end: newEnd,
          scope,
        };
      });
      const r = await apiMove(moves);
      if (!r.ok) alert("Move failed: " + ((r.data.errors || []).join(" ") || ""));
      await fetchWeek();
    }
  });

  // Click outside the modal card closes it.
  document.getElementById("eventModal").addEventListener("click", (e) => {
    if (e.target.id === "eventModal") closeModal();
  });

  // ------------------------------------------------------------------
  // Keyboard shortcuts
  // ------------------------------------------------------------------
  document.addEventListener("keydown", async (e) => {
    if (document.getElementById("eventModal").hidden === false) return;
    if (e.target.matches("input, textarea, select")) return;
    if (e.key === "Escape") clearSelection();
    if ((e.key === "Delete" || e.key === "Backspace") && state.selection.size > 0) {
      e.preventDefault();
      await deleteSelected();
    }
  });

  document.getElementById("btnDeselect").addEventListener("click", clearSelection);
  document.getElementById("btnDeleteSelected").addEventListener("click", deleteSelected);

  async function deleteSelected() {
    const keys = [...state.selection];
    if (!keys.length) return;
    // Group by id to figure out the recurring/non-recurring story.
    const byId = new Map();
    for (const k of keys) {
      const [idStr, dateStr] = k.split("@");
      const id = parseInt(idStr, 10);
      const ev = state.events.find((x) => x.id === id && x.date === dateStr);
      if (!ev) continue;
      if (!byId.has(id)) byId.set(id, []);
      byId.get(id).push(ev);
    }
    const anyRecurring = [...byId.values()].some((evs) =>
      evs.some((ev) => ev.recurrence && ev.recurrence !== "none"));

    let scope = "all";
    if (anyRecurring) {
      const choice = await confirmChoice({
        title: "Delete events",
        body: `${keys.length} occurrence${keys.length === 1 ? "" : "s"} selected. Some repeat — should we remove the selected instances only, or every occurrence of each?`,
        choices: [
          { value: "cancel", label: "Cancel", variant: "ghost" },
          { value: "this", label: "Only the selected dates", variant: "danger" },
          { value: "all", label: "All occurrences", variant: "danger" },
        ],
      });
      if (choice === "cancel") return;
      scope = choice;
    } else {
      const ok = await confirmChoice({
        title: "Delete events",
        body: `Delete ${keys.length} event${keys.length === 1 ? "" : "s"}?`,
        choices: [
          { value: "cancel", label: "Cancel", variant: "ghost" },
          { value: "all", label: "Delete", variant: "danger" },
        ],
      });
      if (ok === "cancel") return;
    }

    // Fan-out deletes; for scope=all we only need ONE call per id, not per occurrence.
    const done = new Set();
    for (const [id, evs] of byId) {
      if (scope === "all") {
        if (done.has(id)) continue;
        done.add(id);
        await apiDelete(id, "all");
      } else {
        for (const ev of evs) await apiDelete(id, "this", ev.date);
      }
    }
    clearSelection();
    await fetchWeek();
  }

  // ------------------------------------------------------------------
  // Boot
  // ------------------------------------------------------------------
  paintHourLabels();
  fetchWeek().catch((err) => {
    console.error(err);
    alert("Couldn't load this week's events. Try refreshing.");
  });
})();
