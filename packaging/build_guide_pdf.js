// Rebuilds docs/guide/Pylon-User-Guide.pdf from docs/guide.html, the way Chromium prints it (A4, the guide's
// own print styles: dark cover, light pages, page numbers). Run it after the guide changes or the version goes up
// (packaging/sync_metadata.py updates the version the guide names):
//
//     node packaging/build_guide_pdf.js
//
// Needs Node with Playwright and its Chromium (npm install playwright && npx playwright install chromium), and
// the internet for the guide's Google fonts.
const path = require("path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const html = path.join(root, "docs", "guide.html");
const out = path.join(root, "docs", "guide", "Pylon-User-Guide.pdf");

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto("file://" + html, { waitUntil: "networkidle" });
    // every picture in, including the ones the page loads only when you scroll to them
    await page.evaluate(async () => {
      document.querySelectorAll('img[loading="lazy"]').forEach((img) => { img.loading = "eager"; });
      await Promise.all(Array.from(document.images, (img) => img.complete ? null : new Promise((ok) => {
        img.addEventListener("load", ok, { once: true });
        img.addEventListener("error", ok, { once: true });
      })));
      await document.fonts.ready;
    });
    const missing = await page.evaluate(() => Array.from(document.images)
      .filter((img) => !img.naturalWidth).map((img) => img.getAttribute("src")));
    if (missing.length) throw new Error("Pictures that didn't load: " + missing.join(", "));
    if (!(await page.evaluate(() => document.fonts.check('16px "Hanken Grotesk"'))))
      throw new Error("The guide's fonts didn't load (no internet?)");
    await page.emulateMedia({ media: "print" });
    await page.pdf({ path: out, preferCSSPageSize: true, printBackground: true });
    console.log("Wrote " + path.relative(root, out));
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e.message || e); process.exit(1); });
