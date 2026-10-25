// Renders 1080x1350 post images (Instagram portrait size) from a JSON list
// made by `python -m campaign.cards`. Uses Playwright's Chromium.
import { createRequire } from "node:module";
import { readFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

// createRequire also finds a globally installed Playwright (NODE_PATH).
const { chromium } = createRequire(import.meta.url)("playwright");

const esc = (s = "") =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const page = (c) => `<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700;12..96,800&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0}
body{width:1080px;height:1350px;background:${c.colors.bg};color:${c.colors.fg};
 font-family:"Source Sans 3",system-ui,sans-serif;padding:96px 88px;display:flex;flex-direction:column;gap:40px;position:relative;overflow:hidden}
body::after{content:"";position:absolute;right:-260px;bottom:-260px;width:760px;height:760px;border-radius:50%;
 border:70px solid ${c.colors.accent};opacity:.12;z-index:0}
body>*{position:relative;z-index:1}
.bar{width:120px;height:12px;background:${c.colors.accent};border-radius:6px}
.kicker{font-size:34px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:${c.colors.accent}}
h1{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-weight:800;line-height:1.04;letter-spacing:-.02em;
 font-size:${c.headline.length > 70 ? 76 : c.headline.length > 40 ? 96 : 120}px;text-wrap:balance}
.sub{font-size:44px;line-height:1.3;opacity:.92;max-width:880px;white-space:pre-line}
.spacer{flex:1}
footer{display:flex;justify-content:space-between;align-items:center;border-top:3px solid ${c.colors.accent};padding-top:32px;font-size:36px}
footer b{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:44px}
</style></head><body>
<div class="spacer"></div>
<div class="bar"></div>
${c.kicker ? `<div class="kicker">${esc(c.kicker)}</div>` : ""}
<h1>${esc(c.headline)}</h1>
${c.sub ? `<div class="sub">${esc(c.sub)}</div>` : ""}
<div class="spacer"></div>
<footer><b>${esc(c.brand)}</b><span>${esc(c.footer)}</span></footer>
</body></html>`;

const cards = JSON.parse(readFileSync(process.argv[2] || 0, "utf8"));
if (!cards.length) { console.log("No cards to render."); process.exit(0); }
const browser = await chromium.launch();
const tab = await browser.newPage({ viewport: { width: 1080, height: 1350 } });
for (const c of cards) {
  await tab.setContent(page(c), { waitUntil: "networkidle" }).catch(() => tab.setContent(page(c)));
  mkdirSync(dirname(c.out), { recursive: true });
  await tab.screenshot({ path: c.out, type: "png" });
  console.log("rendered", c.out);
}
await browser.close();
