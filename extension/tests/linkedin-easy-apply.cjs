const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { firefox } = require("playwright");

const source = fs.readFileSync(path.join(__dirname, "../src/background.js"), "utf8");
const start = source.indexOf("function linkedInEasyApply(action)");
const end = source.indexOf("\nfunction submitJobForm()", start);
const stepsSource = source.slice(start, end);
const scanSource = source.slice(source.indexOf("function scanPage(scanId)"), source.indexOf("\nfunction attachGenerateButtons("));

async function main() {
  const browser = await firefox.launch({ headless: true, executablePath: process.env.FIREFOX_PATH });
  const page = await browser.newPage();
  try {
    const markup = `
      <button class="jobs-apply-button" aria-label="Easy Apply to Example">Easy Apply</button>
      <input id="search" required placeholder="Search jobs">
      <div role="dialog" aria-label="Easy Apply application" class="jobs-easy-apply-modal" hidden></div>
      <script>(() => {
        const dialog = document.querySelector('[role="dialog"]');
        const screens = [
          '<h2>Contact info</h2><label>Phone<input id="phone" required></label><button data-easy-apply-next-button>Continue</button>',
          '<h2>Additional questions</h2><label>Years of experience<input id="years" required></label><button>Review application</button>',
          '<h2>Review your application</h2><button>Submit application</button>',
        ];
        let screen = 0;
        document.querySelector('.jobs-apply-button').onclick = () => {
          dialog.hidden = false;
          dialog.innerHTML = screens[screen];
        };
        dialog.onclick = (event) => {
          if (!event.target.matches('button')) return;
          if (screen < 2) dialog.innerHTML = screens[++screen];
          else dialog.innerHTML = '<h2>Application sent</h2>';
        };
      })();</script>
    `;
    await page.setContent(markup);
    await page.evaluate((script) => window.eval(`${script}\nwindow.jfStep = linkedInEasyApply;`), stepsSource);

    let result = await page.evaluate(() => window.jfStep("open"));
    assert.equal(result.ok, true);
    result = await page.evaluate(() => window.jfStep("inspect"));
    assert.equal(result.kind, "next");
    assert.equal(result.fieldCount, 1);
    const scanned = await page.evaluate((script) => {
      window.eval(`${script}\nwindow.jfScan = scanPage;`);
      return window.jfScan("test").form_snapshot;
    }, scanSource);
    assert.deepEqual(scanned.map((field) => field.id), ["phone"]);

    result = await page.evaluate(() => window.jfStep("next"));
    assert.equal(result.ok, false);
    assert.match(result.reason, /invalid fields/);
    assert.equal(await page.locator("#years").count(), 0);

    await page.locator("#phone").fill("123456789");
    result = await page.evaluate(() => window.jfStep("next"));
    assert.equal(result.ok, true);
    result = await page.evaluate(() => window.jfStep("inspect"));
    assert.equal(result.kind, "review");
    assert.equal(result.fieldCount, 1);

    await page.locator("#years").fill("4");
    result = await page.evaluate(() => window.jfStep("review"));
    assert.equal(result.ok, true);
    result = await page.evaluate(() => window.jfStep("inspect"));
    assert.equal(result.kind, "submit");
    assert.equal(result.fieldCount, 0);
    assert.equal(await page.getByText("Application sent").count(), 0);

    result = await page.evaluate(() => window.jfStep("submit"));
    assert.equal(result.ok, true);
    assert.equal(await page.getByText("Application sent").count(), 1);

    await page.setContent(markup);
    result = await page.evaluate(async (script) => {
      window.browser = {
        tabs: { get: async () => ({ url: "https://www.linkedin.com/jobs/view/123" }) },
        scripting: {
          executeScript: async ({ func, args = [] }) => [{ result: await func(...args) }],
        },
      };
      window.eval(`
        async function handleScan() {
          const fields = [...document.querySelectorAll('[role="dialog"] input')].map((el) => ({ ref: el.id, required: el.required }));
          return { formSnapshot: fields, fieldMapping: fields.map((field) => ({ ref: field.ref, action: 'type' })) };
        }
        async function handleFill(scan) {
          for (const field of scan.formSnapshot) document.getElementById(field.ref).value = 'answer';
          return { failedCount: 0, logLines: ['Filled ' + scan.formSnapshot.length + ' field(s)'] };
        }
        function submittedConfirmation() { return /Application sent/.test(document.body.innerText); }
        ${script}
        window.jfFlow = fillLinkedInSteps;
      `);
      return window.jfFlow(1, 42, false);
    }, stepsSource);
    assert.equal(result.status, "ready_to_submit");
    assert.equal(result.logLines.length, 2);
    assert.equal(await page.getByText("Application sent").count(), 0);

    result = await page.evaluate(() => window.jfFlow(1, 42, true));
    assert.equal(result.status, "applied");
    assert.equal(await page.getByText("Application sent").count(), 1);

    await page.setContent(markup);
    const error = await page.evaluate(async () => {
      window.handleScan = async () => ({
        formSnapshot: [{ ref: "phone", required: true }],
        fieldMapping: [{ ref: "phone", action: "skip" }],
      });
      try {
        await window.jfFlow(1, 42, true);
        return "";
      } catch (err) {
        return String(err);
      }
    });
    assert.match(error, /required fields need an answer/);
    assert.equal(await page.getByText("Application sent").count(), 0);
    console.log("PASS LinkedIn Easy Apply steps, full flow, and manual review stop");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
