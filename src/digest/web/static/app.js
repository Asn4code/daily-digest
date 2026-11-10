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
