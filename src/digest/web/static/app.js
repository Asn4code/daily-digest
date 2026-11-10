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
})();
