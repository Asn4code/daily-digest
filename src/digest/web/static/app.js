"use strict";
(() => {
  const body = document.body;
  const stored = localStorage.getItem("digest-theme");
  if (stored === "light" || stored === "dark") body.classList.add(stored);
  document.getElementById("theme")?.addEventListener("click", () => {
    const dark = body.classList.contains("dark") || (!body.classList.contains("light") && matchMedia("(prefers-color-scheme: dark)").matches);
    body.classList.toggle("light", dark);
    body.classList.toggle("dark", !dark);
    localStorage.setItem("digest-theme", dark ? "light" : "dark");
  });
  function reveal() {
    const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (!target) return;
    for (let item = target; item; item = item.parentElement) if (item.tagName === "DETAILS") item.open = true;
    target.scrollIntoView({block: "start"});
  }
  addEventListener("hashchange", reveal);
  if (location.hash) reveal();
  const graph = document.querySelector("[data-notebook-graph]");
  if (graph) {
    let scale = 1;
    document.querySelectorAll("[data-graph-zoom]").forEach(button => {
      button.addEventListener("click", () => {
        scale = button.dataset.graphZoom === "reset" ? 1 : Math.max(.3, Math.min(2, scale * (button.dataset.graphZoom === "in" ? 1.2 : 1/1.2)));
        graph.setAttribute("width", Math.round(Number(graph.dataset.width) * scale));
        graph.setAttribute("height", Math.round(Number(graph.dataset.height) * scale));
      });
    });
  }
  const queuePanel = document.querySelector("[data-queue-status]");
  if (queuePanel) {
    let attempts = 0, dirty = false;
    queuePanel.addEventListener("input", () => { dirty = true; });
    const timer = setInterval(async () => {
      if (++attempts > 720) { clearInterval(timer); return; }
      if (document.hidden || dirty) return;
      try {
        const response = await fetch(queuePanel.dataset.queueStatus, {credentials: "same-origin", cache: "no-store"});
        if (!response.ok) { clearInterval(timer); return; }
        if ((await response.json()).signature !== queuePanel.dataset.signature) location.reload();
      } catch { clearInterval(timer); }
    }, 5000);
  }
  const pending = document.querySelector("[data-review-state=pending]");
  if (pending) {
    let attempts = 0;
    const timer = setInterval(async () => {
      if (++attempts > 120) { clearInterval(timer); return; }
      if (document.hidden) return;
      try {
        const response = await fetch(pending.dataset.statusUrl, {credentials: "same-origin", cache: "no-store"});
        if (!response.ok) { clearInterval(timer); return; }
        const status = (await response.json()).state;
        if (status !== "pending") {
          clearInterval(timer);
          if (status !== "failed" || !pending.querySelector("form")) location.reload();
        }
      } catch { clearInterval(timer); }
    }, 5000);
  }
})();
