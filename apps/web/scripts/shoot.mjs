/**
 * Drive the real app and capture frames.
 *
 * The UI skill's done-gate asks for evidence, not intent: "checked at 1440x900 and 375px; key
 * content unclipped inside its panel; declared motion actually reads in the render." This script
 * walks the whole review loop against a running dev server and writes PNGs, then reports any
 * element whose content overflows its own box so a cutoff is caught by measurement rather than by
 * squinting.
 *
 *   node scripts/shoot.mjs [baseUrl] [outDir]
 */

import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const BASE = process.argv[2] ?? "http://127.0.0.1:5173";
const OUT = process.argv[3] ?? "shots";

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 375, height: 844 };

/**
 * Report genuine cutoff only.
 *
 * "Cut off" means content the user cannot reach: clipped by `overflow: hidden`/`clip` with no
 * scroller, or drawn outside the viewport. Content that overflows an `overflow: visible` box is
 * not cut off - that is how an expanded hit area or a drop shadow is supposed to behave, and
 * flagging it buries the real findings in noise.
 */
const CUTOFF_PROBE = () => {
  const findings = [];
  const seen = new Set();

  const hasScrollableDescendant = (el) => {
    for (const child of el.querySelectorAll("*")) {
      const s = getComputedStyle(child);
      if (s.overflowY === "auto" || s.overflowY === "scroll") return true;
    }
    return false;
  };

  for (const el of document.querySelectorAll("body *")) {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") continue;
    const box = el.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) continue;

    const cls = (el.className || "").toString().trim().split(/\s+/)[0] || "";
    const tag = cls ? `${el.tagName.toLowerCase()}.${cls}` : el.tagName.toLowerCase();
    if (seen.has(tag)) continue;

    const clipsY = style.overflowY === "hidden" || style.overflowY === "clip";
    const clipsX = style.overflowX === "hidden" || style.overflowX === "clip";

    if (clipsY && el.scrollHeight - el.clientHeight > 2 && !hasScrollableDescendant(el)) {
      findings.push({ tag, kind: "clipped-vertically", by: el.scrollHeight - el.clientHeight });
      seen.add(tag);
    } else if (clipsX && el.scrollWidth - el.clientWidth > 2 && !hasScrollableDescendant(el)) {
      findings.push({ tag, kind: "clipped-horizontally", by: el.scrollWidth - el.clientWidth });
      seen.add(tag);
    } else if (box.right > window.innerWidth + 1 || box.left < -1) {
      // Ignore purely decorative layers; a readable element off-frame is the fault.
      if (el.textContent && el.textContent.trim().length > 0) {
        findings.push({
          tag,
          kind: "off-viewport",
          by: Math.round(Math.max(box.right - window.innerWidth, -box.left)),
        });
        seen.add(tag);
      }
    }
  }
  return {
    findings,
    pageScrollsHorizontally: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
};

async function shoot(page, name, size) {
  await page.setViewportSize(size);
  await page.waitForTimeout(700);
  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: `${OUT}/${name}.png` });
  const report = await page.evaluate(CUTOFF_PROBE);
  const label = `${name} @ ${size.width}x${size.height}`;
  if (report.findings.length === 0 && !report.pageScrollsHorizontally) {
    console.log(`  OK    ${label}`);
  } else {
    console.log(`  CHECK ${label}`);
    if (report.pageScrollsHorizontally) console.log("          page scrolls horizontally");
    for (const finding of report.findings.slice(0, 6)) {
      console.log(`          ${finding.kind} by ${finding.by}px  ${finding.tag}`);
    }
  }
  return report;
}

// Headless Chromium ships without a GPU, so WebGL needs the software rasteriser turned on
// explicitly. Without these the schematic silently never paints.
const browser = await chromium.launch({
  args: [
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist",
  ],
});
const page = await browser.newPage({ viewport: DESKTOP, deviceScaleFactor: 2 });
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(String(error)));
// Record which request failed, not just that one did: "a 500 happened" is not actionable.
page.on("response", (response) => {
  if (response.status() >= 400) {
    consoleErrors.push(`${response.status()} ${response.request().method()} ${response.url()}`);
  }
});

const all = [];

console.log(`\ndriving ${BASE}\n`);
await page.goto(BASE, { waitUntil: "networkidle" });

all.push(["landing", await shoot(page, "01-landing", DESKTOP)]);
all.push(["landing-mobile", await shoot(page, "01-landing-mobile", MOBILE)]);
await page.setViewportSize(DESKTOP);

// 1. import
await page.getByRole("button", { name: /Import a design/i }).click();
await page.waitForSelector(".schematic-canvas canvas", { timeout: 30000 });
await page.waitForTimeout(1500);
all.push(["inspect", await shoot(page, "02-inspect-unconfirmed", DESKTOP)]);

// 2. select the part with no mass
await page.getByRole("button", { name: /Wiring harness/i }).click();
await page.waitForTimeout(800);
all.push(["selected-unknown", await shoot(page, "03-unknown-mass-selected", DESKTOP)]);

// 3. improve, pre-confirm: the app should ask for the value instead of proposing an edit
await page.getByRole("button", { name: "Improve", exact: true }).click();
await page.getByRole("button", { name: /Generate proposals/i }).click();
await page.waitForTimeout(2500);
all.push(["evidence-request", await shoot(page, "04-asks-for-evidence", DESKTOP)]);

// 4. confirm units, frame, and the reconstruction — the gate that unblocks every edit
await page.getByRole("button", { name: "Inspect", exact: true }).click();
await page.waitForTimeout(400);
all.push(["gate", await shoot(page, "05-confirm-gate", DESKTOP)]);
const confirm = page.getByRole("button", { name: /Confirm units, frame/i });
if (await confirm.count()) {
  await confirm.click();
  await page.waitForTimeout(3500);
}

// 5. supply the missing mass with provenance.
// Selection toggles, so clear it first rather than clicking a part that may already be selected.
await page.keyboard.press("Escape");
await page.waitForTimeout(300);
await page.getByRole("button", { name: /Wiring harness/i }).click();
await page.waitForTimeout(800);
const massInput = page.locator("#mass-entry");
console.log(`  step  mass-entry field present: ${await massInput.count()}`);
if (await massInput.count()) {
  await massInput.fill("0.045");
  const record = page.getByRole("button", { name: /^Record$/ });
  console.log(`  step  Record enabled: ${await record.isEnabled()}`);
  await record.click();
  await page.waitForTimeout(4000);
} else {
  console.log("  step  SKIPPED: the mass entry form never appeared");
}
all.push(["confirmed", await shoot(page, "06-mass-supplied", DESKTOP)]);

// 6. proposals, now that the checks can be computed
await page.getByRole("button", { name: "Improve", exact: true }).click();
await page.getByRole("button", { name: /Generate proposals|Regenerate proposals/i }).click();
await page.waitForTimeout(6000);
all.push(["proposals", await shoot(page, "07-proposals", DESKTOP)]);
all.push(["proposals-mobile", await shoot(page, "07-proposals-mobile", MOBILE)]);
await page.setViewportSize(DESKTOP);

// 6. simulate
await page.getByRole("button", { name: "Simulate", exact: true }).click();
await page.waitForTimeout(400);
const run = page.getByRole("button", { name: /Run the mission model/i });
if (await run.count()) {
  await run.click();
  await page.waitForTimeout(2500);
}
all.push(["simulate", await shoot(page, "08-simulate", DESKTOP)]);

// 7. rails collapsed: the schematic alone
await page.getByRole("button", { name: "Inspect", exact: true }).click();
await page.keyboard.press("[");
await page.keyboard.press("]");
await page.waitForTimeout(700);
all.push(["schematic-only", await shoot(page, "09-schematic-full", DESKTOP)]);

const failures = all.filter(
  ([, report]) => report.findings.length > 0 || report.pageScrollsHorizontally,
);

console.log(`\nconsole errors: ${consoleErrors.length}`);
for (const error of consoleErrors.slice(0, 8)) console.log(`  ${error.slice(0, 160)}`);
console.log(`frames with a cutoff finding: ${failures.length} of ${all.length}`);

await writeFile(
  `${OUT}/report.json`,
  JSON.stringify({ frames: all.map(([n, r]) => ({ name: n, ...r })), consoleErrors }, null, 2),
);
await browser.close();
process.exit(failures.length > 0 || consoleErrors.length > 0 ? 1 : 0);
