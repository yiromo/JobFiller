const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { firefox } = require("playwright");

const source = fs.readFileSync(path.join(__dirname, "../src/background.js"), "utf8");
const panelSource = fs.readFileSync(path.join(__dirname, "../src/content/panel.js"), "utf8");
const start = source.indexOf("function linkedInEasyApply(action)");
const end = source.indexOf("\nfunction submitJobForm()", start);
const stepsSource = source.slice(start, end);
const scanSource = source.slice(source.indexOf("function scanPage(scanId)"), source.indexOf("\nfunction attachGenerateButtons("));
const framesSource = source.slice(
  source.indexOf("function framesWithApplicationFields(injectionResults)"),
  source.indexOf("\nasync function handleScan(message, tabId)"),
);
const normalizePhoneSource = source.slice(
  source.indexOf("function normalizeLinkedInPhonePlan(formSnapshot, fieldMapping, pageUrl, logLines)"),
  source.indexOf("\nfunction arrayBufferToBase64(", source.indexOf("function normalizeLinkedInPhonePlan(")),
);
const settingsSource = source.slice(
  source.indexOf("function bestOptionMatch(options, value)"),
  source.indexOf("\nfunction arrayBufferToBase64(", source.indexOf("function bestOptionMatch(")),
);
const mainFillSource = panelSource.slice(
  panelSource.indexOf("async function runFill()"),
  panelSource.indexOf('    $("jf-scan-btn").addEventListener("click"'),
);

async function main() {
  const pickFrames = new Function(`${framesSource}\nreturn framesWithApplicationFields;`)();
  assert.deepEqual(pickFrames([
    { frameId: 0, result: { easy_apply_modal: true, form_snapshot: [{ ref: "phone" }] } },
    { frameId: 123, result: { easy_apply_modal: false, form_snapshot: [{ ref: "unrelated" }] } },
  ]).map((frame) => frame.frameId), [0]);
  const normalizePhone = new Function(`${normalizePhoneSource}\nreturn normalizeLinkedInPhonePlan;`)();
  const applySettings = new Function(`${settingsSource}\nreturn applyEeoSettings;`)();
  const phoneFields = [
    { ref: "country", label: "Phone country code*", selected_option: "Kazakhstan (+7)" },
    { ref: "mobile", label: "Mobile phone number*", type: "tel" },
  ];
  const phonePlan = [{ ref: "mobile", action: "type", value: "+71234567890", confidence: 1 }];
  assert.equal(normalizePhone(phoneFields, phonePlan, "https://www.linkedin.com/jobs/view/123", [])[0].value, "1234567890");
  assert.equal(normalizePhone(phoneFields, phonePlan, "https://example.com/apply", [])[0].value, "+71234567890");
  assert.equal(normalizePhone(phoneFields, [{ ...phonePlan[0], value: "+15551234567" }],
    "https://www.linkedin.com/jobs/view/123", [])[0].action, "skip");
  const fromSettings = applySettings(phoneFields,
    [{ ref: "country", action: "skip", value: "" }, { ref: "mobile", action: "skip", value: "" }],
    [{ match: "Mobile phone number", answer: "+71234567890" }], []);
  assert.equal(normalizePhone(phoneFields, fromSettings,
    "https://www.linkedin.com/jobs/view/123", []).find((entry) => entry.ref === "mobile").value,
  "1234567890");
  const browser = await firefox.launch({ headless: true, executablePath: process.env.FIREFOX_PATH });
  const page = await browser.newPage();
  try {
    await page.route("https://www.linkedin.com/**", (route) => route.fulfill({
      status: 200, contentType: "text/html", body: "<html><body>LinkedIn fixture</body></html>",
    }));
    await page.goto("https://www.linkedin.com/jobs/view/123");
    const markup = `
      <button class="jobs-apply-button" aria-label="Easy Apply to Example">Easy Apply</button>
      <input id="search" required placeholder="Search jobs">
      <div role="dialog" aria-label="Easy Apply application" class="jobs-easy-apply-modal" hidden></div>
      <script>(() => {
        const dialog = document.querySelector('[role="dialog"]');
        const screens = [
          '<h2>Contact info</h2><label>Phone<input id="phone" required></label><button data-easy-apply-next-button>Continue</button>',
          '<h2>Additional questions</h2><label>Years of experience*<input id="years"></label><button>Review application</button>',
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
    await page.evaluate((script) => window.eval(`${script}\nwindow.jfStep = linkedInEasyApply; window.jfUnanswered = unansweredLinkedInFields;`), stepsSource);

    let result = await page.evaluate(() => window.jfStep("open"));
    assert.equal(result.ok, true);
    result = await page.evaluate(() => window.jfStep("inspect"));
    assert.equal(result.kind, "next");
    assert.equal(result.fieldCount, 1);
    const scanned = await page.evaluate((script) => {
      window.eval(`${script}\nwindow.jfScan = scanPage;`);
      return window.jfScan("test");
    }, scanSource);
    assert.equal(scanned.easy_apply_modal, true);
    assert.deepEqual(scanned.form_snapshot.map((field) => field.id), ["phone"]);

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
    const requiredOnSecondPage = await page.evaluate(() => window.jfScan("second").form_snapshot);
    assert.equal(requiredOnSecondPage[0].required, true);
    assert.deepEqual(await page.evaluate(() => window.jfUnanswered(["second-years"])), ["second-years"]);

    await page.locator("#years").fill("4");
    assert.deepEqual(await page.evaluate(() => window.jfUnanswered(["second-years"])), []);
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
          const fields = [...document.querySelectorAll('[role="dialog"] input')].map((el) => {
            el.setAttribute('data-jf-ref', el.id);
            return { ref: el.id, required: el.required || (el.closest('label')?.innerText || '').trim().endsWith('*'), label: el.closest('label')?.innerText || '' };
          });
          return { formSnapshot: fields, fieldMapping: fields.map((field) => ({ ref: field.ref, action: 'type' })),
            refFrameMap: Object.fromEntries(fields.map((field) => [field.ref, { frameId: 0, localRef: field.ref }])) };
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
    assert.match(error, /answer required field/);
    assert.equal(await page.getByText("Application sent").count(), 0);

    await page.setContent(markup);
    const applicantAnswer = await page.evaluate(async () => {
      window.eval("window.jfRequired = unansweredLinkedInRequired;");
      window.jfStep("open");
      const input = document.querySelector("#phone");
      input.setAttribute("data-jf-ref", "manual");
      const scan = { refFrameMap: { "0:manual": { frameId: 0, localRef: "manual" } } };
      const entry = [{ ref: "0:manual", action: "skip" }];
      const missing = await window.jfRequired(1, scan, entry);
      input.value = "Applicant-provided answer";
      const answered = await window.jfRequired(1, scan, entry);
      return { missing, answered };
    });
    assert.deepEqual(applicantAnswer.missing, ["0:manual"]);
    assert.deepEqual(applicantAnswer.answered, []);
    const defaultCountry = await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]');
      dialog.insertAdjacentHTML("beforeend", '<select data-jf-ref="country"><option value="ad">Andorra (+376)</option><option value="kz">Kazakhstan (+7)</option></select><div class="artdeco-inline-feedback--error">Choose a valid phone country code</div>');
      const before = window.jfUnanswered(["country"]);
      dialog.querySelector("select").value = "kz";
      const after = window.jfUnanswered(["country"]);
      const diagnosis = window.jfStep("diagnose");
      return { before, after, diagnosis };
    });
    assert.deepEqual(defaultCountry.before, ["country"]);
    assert.deepEqual(defaultCountry.after, []);
    assert.match(defaultCountry.diagnosis.issues.join(" "), /valid phone country code/);
    assert.equal((await page.evaluate(() => window.jfScan("country").form_snapshot))
      .find((field) => field.tag === "select").selected_option, "Kazakhstan (+7)");

    await page.setContent(markup);
    const clearedByRerender = await page.evaluate(async () => {
      window.handleScan = async () => {
        const input = document.querySelector("#phone");
        input.setAttribute("data-jf-ref", "phone");
        return { formSnapshot: [{ ref: "phone", label: "Phone*", required: true }],
          fieldMapping: [{ ref: "phone", action: "type", value: "123" }],
          refFrameMap: { phone: { frameId: 0, localRef: "phone" } } };
      };
      window.handleFill = async () => {
        const input = document.querySelector("#phone");
        input.value = "123";
        setTimeout(() => { input.value = ""; }, 50);
        return { failedCount: 0, logLines: ["Filled 1 field"] };
      };
      try {
        await window.jfFlow(1, 42, false);
        return "";
      } catch (err) {
        return String(err);
      }
    });
    assert.match(clearedByRerender, /answer required field: Phone/);

    await page.goto("https://www.linkedin.com/jobs/view/123");
    const routed = await page.evaluate(async (script) => {
      window.eval(`async function runLinkedInSteps() { window.easyApplyCalled = true; }\n${script}\nwindow.jfMainFill = runFill;`);
      await window.jfMainFill();
      return window.easyApplyCalled;
    }, mainFillSource);
    assert.equal(routed, true);
    console.log("PASS LinkedIn Easy Apply steps, full flow, and manual review stop");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
