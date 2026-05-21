// Usage: node dashboard_check.mjs <targetRepo> "<sel>=<expected>" ["<sel>=<expected>" ...]
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const [target, ...pairs] = process.argv.slice(2);
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".jsonl": "application/json", ".json": "application/json", ".css": "text/css", ".md": "text/markdown" };

const server = createServer(async (req, res) => {
  try {
    const p = normalize(join(target, decodeURIComponent(req.url.split("?")[0])));
    if (!p.startsWith(target)) { res.writeHead(403).end(); return; }
    await stat(p);
    res.writeHead(200, { "content-type": TYPES[extname(p)] || "application/octet-stream" });
    res.end(await readFile(p));
  } catch { res.writeHead(404).end(); }
});

await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;
const url = `http://127.0.0.1:${port}/.specship/dashboard/dashboard.html`;

const browser = await chromium.launch();
const page = await browser.newPage();
let failures = 0;
try {
  await page.goto(url, { waitUntil: "networkidle" });
  await page.waitForTimeout(500); // let the ledger fetch + render settle
  for (const pair of pairs) {
    const idx = pair.lastIndexOf("=");
    const sel = pair.slice(0, idx);
    const expected = pair.slice(idx + 1);
    const text = (await page.locator(sel).first().innerText().catch(() => "")).trim();
    if (text.includes(expected)) {
      console.log(`PASS dashboard ${sel} contains "${expected}"`);
    } else {
      console.error(`FAIL dashboard ${sel}: got "${text}", expected to contain "${expected}"`);
      failures++;
    }
  }
} finally {
  await browser.close();
  server.close();
}
process.exit(failures === 0 ? 0 : 1);
