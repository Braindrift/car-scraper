/**
 * table-sort.js — lightweight client-side table sorting.
 *
 * Usage: add `data-sort-type="text"` or `data-sort-type="number"` to any <th>
 * you want to be sortable. Optionally add `data-sort-value="<raw>"` to a <td>
 * to supply a plain numeric value for columns whose display text is formatted
 * (e.g. "150 000 kr" → data-sort-value="150000").
 *
 * Sort direction cycles: first click → descending, second → ascending,
 * third → back to original DOM order (reset).
 *
 * Visual indicator: ↓ (descending) / ↑ (ascending) appended to the header
 * text. No extra CSS needed.
 */
(function () {
  "use strict";

  const SORT_NONE = "none";
  const SORT_DESC = "desc";
  const SORT_ASC = "asc";

  /**
   * Return the sort key for a <td> in a given column.
   * Prefers data-sort-value, falls back to trimmed textContent.
   */
  function cellKey(td, type) {
    const raw =
      td.dataset.sortValue !== undefined
        ? td.dataset.sortValue
        : td.textContent.trim();
    if (type === "number") {
      const n = parseFloat(raw.replace(/\s/g, "").replace(",", "."));
      return isNaN(n) ? -Infinity : n;
    }
    return raw.toLowerCase();
  }

  /**
   * Compare two keys; returns negative / zero / positive.
   */
  function compareKeys(a, b) {
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a).localeCompare(String(b), "sv");
  }

  /**
   * Attach sort behaviour to a single <table> element.
   */
  function initTable(table) {
    const headers = table.querySelectorAll("thead th[data-sort-type]");
    if (!headers.length) return;

    // Store original row order so we can reset.
    const tbody = table.querySelector("tbody");
    if (!tbody) return;
    const originalOrder = Array.from(tbody.rows);

    // Per-table state.
    let activeHeader = null;
    let activeDirection = SORT_NONE;

    function setIndicator(th, direction) {
      // Remove any existing indicator spans from all headers.
      headers.forEach((h) => {
        const indicator = h.querySelector(".sort-indicator");
        if (indicator) indicator.remove();
      });
      if (direction === SORT_NONE) return;
      const span = document.createElement("span");
      span.className = "sort-indicator ml-1 text-blue-600";
      span.setAttribute("aria-hidden", "true");
      span.textContent = direction === SORT_DESC ? "↓" : "↑";
      th.appendChild(span);
    }

    function applySort(th, direction) {
      const colIndex = Array.from(th.parentElement.children).indexOf(th);
      const type = th.dataset.sortType;

      if (direction === SORT_NONE) {
        // Restore original order.
        originalOrder.forEach((row) => tbody.appendChild(row));
        return;
      }

      const rows = Array.from(tbody.rows);
      rows.sort((rowA, rowB) => {
        const a = cellKey(rowA.cells[colIndex], type);
        const b = cellKey(rowB.cells[colIndex], type);
        const cmp = compareKeys(a, b);
        return direction === SORT_DESC ? -cmp : cmp;
      });
      rows.forEach((row) => tbody.appendChild(row));
    }

    headers.forEach((th) => {
      th.style.cursor = "pointer";
      th.title = "Click to sort";

      th.addEventListener("click", () => {
        let nextDirection;
        if (activeHeader !== th) {
          // New column — start at descending.
          nextDirection = SORT_DESC;
        } else {
          // Same column — cycle desc → asc → none.
          if (activeDirection === SORT_DESC) nextDirection = SORT_ASC;
          else if (activeDirection === SORT_ASC) nextDirection = SORT_NONE;
          else nextDirection = SORT_DESC;
        }

        activeHeader = nextDirection === SORT_NONE ? null : th;
        activeDirection = nextDirection;

        applySort(th, nextDirection);
        setIndicator(th, nextDirection);
      });
    });
  }

  /**
   * Initialise all sortable tables in the document.
   * Also watches for dynamically injected tables (HTMX partial swaps).
   */
  function initAll() {
    document.querySelectorAll("table").forEach(initTable);
  }

  // Run on initial load.
  document.addEventListener("DOMContentLoaded", initAll);

  // Re-run after HTMX swaps new content into the DOM.
  document.addEventListener("htmx:afterSwap", function (event) {
    const target = event.detail.target;
    if (!target) return;
    target.querySelectorAll("table").forEach(initTable);
    // Also handle the case where target itself is a table.
    if (target.tagName === "TABLE") initTable(target);
  });
})();
