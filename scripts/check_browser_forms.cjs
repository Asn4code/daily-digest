// Optional check with an installed Playwright and Chromium. Never saves a topic.
"use strict";
const { chromium } = require(process.env.DIGEST_PLAYWRIGHT_MODULE || "playwright");

(async () => {
  const base = new URL(process.argv[2] || "http://127.0.0.1:8091");
  if (base.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(base.hostname)) {
    throw Error("Use a local validation URL");
  }
  const browser = await chromium.launch({
    executablePath: process.env.DIGEST_CHROMIUM_EXECUTABLE || "/usr/bin/chromium-browser",
    headless: true,
    args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
  });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const response = await page.goto(new URL("/watchlist", base).href);
    if (response.status() !== 200 || response.headers()["referrer-policy"] !== "same-origin") {
      throw Error("Monitoring page or referrer policy unavailable");
    }
    await page.locator("[name=text]").fill("Comprobación del formulario; no guardar");
    if (process.argv[3]) {
      const other = new URL(process.argv[3]);
      if (other.protocol !== "http:" || other.hostname !== base.hostname) throw Error("Use another local instance");
      const tab = await context.newPage();
      await tab.goto(other.href);
      await tab.close();
    }
    let observed;
    const previewURL = new URL("/watchlist/preview", base).href;
    page.on("request", request => {
      if (request.url() === previewURL && request.method() === "POST") observed = request;
    });
    const [preview] = await Promise.all([
      page.waitForNavigation(),
      page.getByRole("button", { name: "Revisar lista", exact: true }).click(),
    ]);
    const headers = observed ? await observed.allHeaders() : {};
    if (preview.status() !== 200 || headers.origin !== base.origin || !headers.cookie) {
      throw Error("Browser form failed: status=" + preview.status() + " origin=" + headers.origin);
    }
    if (!await page.getByRole("heading", {name:"Revisar lista de seguimiento",exact:true}).count()) {
      throw Error("Preview not displayed");
    }
    console.log("PASS: browser preview, exact Origin and session cookie; nothing saved.");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
