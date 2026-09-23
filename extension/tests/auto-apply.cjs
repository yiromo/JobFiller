const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { firefox } = require("playwright");

const source = fs.readFileSync(path.join(__dirname, "../src/background.js"), "utf8");
const start = source.indexOf("function submitJobForm()");
const end = source.indexOf("\nfunction submittedConfirmation()", start);
const submitSource = source.slice(start, end);

async function main() {
  const browser = await firefox.launch({
    headless: true,
    executablePath: process.env.FIREFOX_PATH,
  });
  const page = await browser.newPage();
  try {
    async function test(markup) {
      await page.setContent(markup);
      await page.evaluate((script) => window.eval(`${script}\nwindow.submitJobForm = submitJobForm;`), submitSource);
      return page.evaluate(() => window.submitJobForm());
    }

    let result = await test(
      '<form><input required><button type="submit">Submit application</button></form>',
    );
    assert.equal(result.clicked, false);
    assert.match(result.reason, /invalid required fields/);

    result = await test(
      '<form onsubmit="window.submitted=true;return false"><input required value="ready"><button type="submit">Submit application</button></form>',
    );
    assert.equal(result.clicked, true);
    assert.equal(await page.evaluate(() => window.submitted), true);

    result = await test(
      '<form><button type="submit">Submit application</button><button type="submit">Submit application</button></form>',
    );
    assert.equal(result.clicked, false);
    assert.match(result.reason, /2 final submit buttons/);
    console.log("PASS auto-apply final submit checks");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
