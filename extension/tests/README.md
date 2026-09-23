# Dropdown regression checks

The fixtures run the actual `applyFillPlan` function in headless Firefox. They cover native
selects, hidden menus, ARIA relationships, asynchronous search, multi-select commits,
shadow roots, virtualized options, disabled options, and ambiguous text matching.
They do not replace loading the extension and testing Scan/Fill on a real application.

Install the test driver outside the extension, then run from the repository root:

```sh
npm install --prefix /tmp/job-filler-browser-tests playwright@1.57.0
/tmp/job-filler-browser-tests/node_modules/.bin/playwright install firefox
NODE_PATH=/tmp/job-filler-browser-tests/node_modules node extension/tests/select-fill.cjs
```

`FIREFOX_PATH` can point to a compatible Playwright Firefox executable already installed.
The tests use isolated browser pages and do not access your Zen profile or submit applications.

The final submit checks use the same isolated Firefox fixture:

```sh
NODE_PATH=/tmp/job-filler-browser-tests/node_modules node extension/tests/auto-apply.cjs
```

The LinkedIn fixture covers modal-only scanning, required-field validation, Continue/Review
navigation, and the manual stop before final submission:

```sh
NODE_PATH=/tmp/job-filler-browser-tests/node_modules node extension/tests/linkedin-easy-apply.cjs
```
