const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { firefox } = require("playwright");

const source = fs.readFileSync(path.join(__dirname, "../src/background.js"), "utf8");
const start = source.indexOf("async function applyFillPlan(");
const end = source.indexOf("\nfunction ", start);
const nextAsync = source.indexOf("\nasync function ", start + 1);
const fillSource = source.slice(start, Math.min(...[end, nextAsync].filter((n) => n > start)));

async function main() {
  const browser = await firefox.launch({
    headless: true,
    executablePath: process.env.FIREFOX_PATH,
  });
  const page = await browser.newPage({ viewport: null });
  let passed = 0;
  async function run(name, markup, setup, check, value = "Canada") {
    await page.setContent(`<style>[role=option]{padding:8px} .field{width:300px}</style>${markup}`);
    if (setup) {
      for (const prepare of Array.isArray(setup) ? setup : [setup]) await page.evaluate(prepare);
    }
    await page.evaluate((source) => {
      window.eval(`${source}\nwindow.fill = applyFillPlan;`);
    }, fillSource);
    const result = await page.evaluate(
      (value) => window.fill([{ ref: "country", action: "select", value }], {}),
      value,
    );
    await check(result, page);
    passed++;
    console.log(`PASS ${name}`);
  }
  const success = (result) => assert.equal(result.results[0].ok, true, JSON.stringify(result));
  const markup = `<div class="field"><input data-jf-ref="country" role="combobox" aria-expanded="false"><span id="chosen"></span><div role="listbox" id="choices" hidden><div role="option">Canada</div><div role="option">France</div></div></div>`;
  const setup = () => {
    const input = document.querySelector("input");
    const menu = document.querySelector("[role=listbox]");
    input.addEventListener("click", () => {
      input.setAttribute("aria-expanded", "true");
      menu.hidden = false;
    });
    menu.addEventListener("click", (event) => {
      document.querySelector("#chosen").textContent = event.target.textContent;
      input.value = "";
      input.setAttribute("aria-expanded", "false");
      menu.hidden = true;
    });
  };
  try {
    await run(
      "native setter bypasses controlled value tracker",
      `<select data-jf-ref="country"><option value="">Pick</option><option value="CA">Canada</option></select>`,
      () => {
        const select = document.querySelector("select");
        const native = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
        let tracked = select.value;
        Object.defineProperty(select, "value", {
          get() {
            return native.get.call(this);
          },
          set(value) {
            tracked = value;
            native.set.call(this, value);
          },
        });
        select.addEventListener("change", () => {
          window.accepted = tracked !== select.value;
        });
      },
      async (result, page) => {
        success(result);
        assert.equal(await page.evaluate(() => window.accepted), true);
      },
    );
    await run("pre-rendered hidden options become discoverable", markup, setup, success);
    await run(
      "multiple ARIA control IDs",
      markup,
      [
        setup,
        () => {
          const input = document.querySelector("input");
          input.setAttribute("aria-controls", "help choices");
          const help = document.createElement("div");
          help.id = "help";
          document.body.append(help);
        },
      ],
      success,
    );
    await run(
      "search runs when expanded menu starts empty",
      markup,
      () => {
        const input = document.querySelector("input");
        const menu = document.querySelector("[role=listbox]");
        menu.replaceChildren();
        input.setAttribute("aria-controls", "choices");
        input.addEventListener("click", () => {
          input.setAttribute("aria-expanded", "true");
          menu.hidden = false;
        });
        input.addEventListener("input", () => {
          if (input.value === "Canada")
            setTimeout(() => {
              menu.innerHTML = '<div role="option">Canada</div>';
            }, 150);
        });
        menu.addEventListener("click", (event) => {
          document.querySelector("#chosen").textContent = event.target.textContent;
          input.value = "";
          menu.hidden = true;
          input.setAttribute("aria-expanded", "false");
        });
      },
      success,
    );
    await run(
      "multi-select commits once while list stays open",
      markup,
      () => {
        const input = document.querySelector("input");
        const menu = document.querySelector("[role=listbox]");
        input.setAttribute("aria-controls", "choices");
        input.addEventListener("click", () => {
          input.setAttribute("aria-expanded", "true");
          menu.hidden = false;
        });
        window.commits = 0;
        menu.addEventListener("pointerup", (event) => {
          if (!(event instanceof PointerEvent) || event.pointerType !== "mouse") return;
          window.commits++;
          event.target.setAttribute(
            "aria-selected",
            event.target.getAttribute("aria-selected") !== "true",
          );
        });
      },
      async (result, page) => {
        success(result);
        assert.equal(await page.evaluate(() => window.commits), 1);
      },
    );
    await run(
      "typed query alone is not a committed selection",
      markup,
      () => {
        const input = document.querySelector("input");
        const menu = document.querySelector("[role=listbox]");
        menu.replaceChildren();
        input.addEventListener("click", () => {
          input.setAttribute("aria-expanded", "true");
          menu.hidden = false;
        });
        input.addEventListener("input", () => {
          if (input.value === "Canada") menu.innerHTML = '<div role="option">Canada</div>';
        });
        input.addEventListener("blur", () => {
          menu.hidden = true;
          input.setAttribute("aria-expanded", "false");
        });
      },
      (result) => {
        assert.equal(result.results[0].ok, false);
        assert.match(result.results[0].reason, /selection-not-confirmed/);
      },
    );
    await run(
      "disabled native option is never selected",
      `<select data-jf-ref="country"><option>France</option><option disabled>Canada</option></select>`,
      null,
      (result) => {
        assert.equal(result.results[0].ok, false);
        assert.deepEqual(result.unresolved[0].options, ["France"]);
      },
    );
    await run(
      "unrelated visible options are excluded",
      `<div role="option" id="foreign">Canada</div>${markup}`,
      () => {
        const input = document.querySelector("input");
        input.readOnly = true;
        const menu = document.querySelector("[role=listbox]");
        menu.innerHTML = '<div role="option">France</div>';
        input.addEventListener("click", () => {
          menu.hidden = false;
          input.setAttribute("aria-expanded", "true");
        });
        document.querySelector("#foreign").addEventListener("click", () => {
          window.wrongClick = true;
        });
      },
      async (result, page) => {
        assert.deepEqual(result.unresolved[0].options, ["France"]);
        assert.equal(await page.evaluate(() => Boolean(window.wrongClick)), false);
      },
    );
    for (const mode of ["event", "close", "revert"]) {
      await run(
        `autocomplete commit evidence: ${mode}`,
        markup.replace('<input ', `<input data-commit="${mode}" `),
        () => {
          const input = document.querySelector("input");
          const menu = document.querySelector("[role=listbox]");
          menu.replaceChildren();
          input.setAttribute("aria-controls", "choices");
          input.addEventListener("click", () => {
            menu.hidden = false;
            input.setAttribute("aria-expanded", "true");
          });
          input.addEventListener("input", () => {
            if (input.value === "Canada") menu.innerHTML = '<div role="option">Canada</div>';
          });
          menu.addEventListener("click", () => {
            input.value = "Canada";
            if (input.dataset.commit === "event") {
              input.dispatchEvent(new Event("change", { bubbles: true }));
            }
            menu.hidden = true;
            input.setAttribute("aria-expanded", "false");
          });
          input.addEventListener("blur", () => {
            if (input.dataset.commit === "revert") input.value = "";
          });
        },
        mode === "revert" ? (result) => assert.equal(result.results[0].ok, false) : success,
      );
    }
    await run(
      "shadow root option IDs win over document IDs",
      `<div id="choices" role="listbox"><div role="option">France</div></div><div id="host"></div>`,
      () => {
        const root = document.querySelector("#host").attachShadow({ mode: "open" });
        root.innerHTML =
          '<div style="width:300px"><input data-jf-ref="country" role="combobox" aria-controls="choices" aria-expanded="false"><span></span><div id="choices" role="listbox" hidden><div role="option">Canada</div></div></div>';
        const input = root.querySelector("input");
        const menu = root.querySelector("[role=listbox]");
        input.addEventListener("click", () => {
          menu.hidden = false;
          input.setAttribute("aria-expanded", "true");
        });
        menu.addEventListener("click", () => {
          root.querySelector("span").textContent = "Canada";
          input.setAttribute("aria-expanded", "false");
          menu.hidden = true;
        });
      },
      success,
    );
    await run(
      "virtualized options accumulate across scroll pages",
      markup,
      () => {
        const input = document.querySelector("input");
        input.readOnly = true;
        input.setAttribute("aria-controls", "choices");
        const menu = document.querySelector("[role=listbox]");
        menu.style.cssText = "height:60px; overflow-y:auto";
        menu.innerHTML =
          '<div style="height:240px"><div role="option" style="position:sticky;top:0">France</div></div>';
        input.addEventListener("click", () => {
          menu.hidden = false;
          input.setAttribute("aria-expanded", "true");
        });
        menu.addEventListener("scroll", () => {
          menu.querySelector("[role=option]").textContent =
            menu.scrollTop < 60 ? "France" : "Germany";
        });
      },
      (result) => {
        assert.equal(result.results[0].ok, false);
        assert.deepEqual(result.unresolved[0].options, ["France", "Germany"]);
      },
    );
    await run(
      "substring cannot select the opposite answer",
      `<select data-jf-ref="country"><option>Female</option><option>Prefer not to say</option></select>`,
      null,
      (result) => {
        assert.equal(result.results[0].ok, false);
        assert.equal(result.unresolved[0].wanted, "Male");
      },
      "Male",
    );
    console.log(`${passed} Firefox dropdown regression checks passed`);
  } finally {
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
