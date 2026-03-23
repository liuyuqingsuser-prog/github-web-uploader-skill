#!/usr/bin/env node

const fs = require("fs");
const { chromium } = require("playwright");

function fail(message, code = 1) {
  console.error(message);
  process.exit(code);
}

function parseArgs(argv) {
  const args = {
    cookies: "",
    manifest: "",
    repoOwner: "",
    repoName: "",
    visibility: "private",
    description: "",
    createRepo: false,
    dryRun: false,
    chromePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  };

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    const next = argv[index + 1];
    if (token === "--cookies") {
      args.cookies = next;
      index += 1;
    } else if (token === "--manifest") {
      args.manifest = next;
      index += 1;
    } else if (token === "--repo-owner") {
      args.repoOwner = next || "";
      index += 1;
    } else if (token === "--repo-name") {
      args.repoName = next || "";
      index += 1;
    } else if (token === "--visibility") {
      args.visibility = next || "private";
      index += 1;
    } else if (token === "--description") {
      args.description = next || "";
      index += 1;
    } else if (token === "--chrome-path") {
      args.chromePath = next || args.chromePath;
      index += 1;
    } else if (token === "--create-repo") {
      args.createRepo = true;
    } else if (token === "--dry-run") {
      args.dryRun = true;
    } else {
      fail(`Unknown argument: ${token}`);
    }
  }

  if (!args.cookies) {
    fail("--cookies is required.");
  }
  if (!args.manifest) {
    fail("--manifest is required.");
  }
  if (!args.repoName) {
    fail("--repo-name is required.");
  }

  return args;
}

async function navigate(page, url, options = {}, retries = 3) {
  let lastError = null;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      await page.goto(url, {
        waitUntil: "commit",
        timeout: 60000,
        ...options,
      });
      try {
        await page.waitForLoadState("domcontentloaded", { timeout: 15000 });
      } catch (_error) {
        // Some GitHub pages intermittently miss domcontentloaded in automation.
        // If the navigation already committed, continue and let page-specific waits verify readiness.
      }
      return;
    } catch (error) {
      lastError = error;
      if (attempt < retries) {
        await page.waitForTimeout(2000 * attempt);
      }
    }
  }
  throw lastError;
}

async function inferDefaultOwner(page) {
  await navigate(page, "https://github.com/new");
  await page.waitForTimeout(2500);
  const bodyText = await page.locator("body").innerText();
  const match = bodyText.match(/Owner[\s\S]*?\*\s+([A-Za-z0-9_.-]+)\s*\/\s*Repository name/);
  if (!match) {
    fail("Could not infer the default GitHub owner from the new-repository page.");
  }
  return match[1];
}

async function repoExists(page, repoBase) {
  await navigate(page, repoBase);
  await page.waitForTimeout(2500);
  const title = await page.title();
  const bodyText = await page.locator("body").innerText();
  if (title.includes("Page not found")) {
    return false;
  }
  if (bodyText.includes("There isn’t anything here") || bodyText.includes("Page not found")) {
    return false;
  }
  return true;
}

async function createRepository(page, owner, repoName, visibility, description) {
  await navigate(page, "https://github.com/new");
  await page.waitForTimeout(2500);

  await page.locator("#repository-name-input").fill(repoName);
  if (description) {
    const descriptionInput = page.getByLabel(/Description/i).first();
    await descriptionInput.fill(description);
  }

  const visibilityButton = page.locator("#visibility-anchor-button");
  const currentLabel = (await visibilityButton.innerText()).trim().toLowerCase();
  if (currentLabel !== visibility) {
    await visibilityButton.click();
    await page.waitForTimeout(700);
    await page.getByRole("menuitemradio", { name: new RegExp(`^${visibility}$`, "i") }).click();
    await page.waitForTimeout(700);
  }

  await page.getByRole("button", { name: /Create repository/i }).click();
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(3000);
}

function encodeRepoPath(repoPath) {
  return repoPath
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
}

async function openEditorForPath(page, repoBase, repoPath) {
  const editUrl = `${repoBase}/edit/main/${encodeRepoPath(repoPath)}`;
  await navigate(page, editUrl);
  await page.waitForTimeout(2200);
  const title = await page.title();
  const bodyText = await page.locator("body").innerText();

  if (!title.includes("Page not found") && !bodyText.includes("Page not found")) {
    const editor = page.locator('[contenteditable="true"][role="textbox"]').first();
    if ((await editor.count()) > 0) {
      return "edit";
    }
  }

  await navigate(page, `${repoBase}/new/main`);
  await page.waitForTimeout(2200);
  const nameInput = page.locator('input[aria-label="File name"]').first();
  await nameInput.fill(repoPath);
  return "create";
}

async function commitCurrentPage(page, message) {
  await page.getByRole("button", { name: /^Commit changes/i }).last().click();
  await page.waitForTimeout(900);
  const summaryInput = page.locator("#commit-summary-input").first();
  if ((await summaryInput.count()) > 0 && message) {
    await summaryInput.fill(message);
  }
  await page.getByRole("button", { name: /^Commit changes$/ }).first().click();
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(1800);
}

async function uploadFile(page, repoBase, entry) {
  const mode = await openEditorForPath(page, repoBase, entry.repo_path);
  const editor = page.locator('[contenteditable="true"][role="textbox"]').first();
  await editor.click();
  await editor.fill(entry.content);
  await page.waitForTimeout(500);
  const message = `${mode === "edit" ? "Update" : "Create"} ${entry.repo_path.split("/").pop()}`;
  await commitCurrentPage(page, message);
  return { repo_path: entry.repo_path, mode };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (!fs.existsSync(args.cookies)) {
    fail(`Cookie file not found: ${args.cookies}`);
  }
  if (!fs.existsSync(args.manifest)) {
    fail(`Manifest file not found: ${args.manifest}`);
  }
  if (!fs.existsSync(args.chromePath)) {
    fail(`Chrome executable not found: ${args.chromePath}`);
  }

  const cookies = JSON.parse(fs.readFileSync(args.cookies, "utf8"));
  const manifest = JSON.parse(fs.readFileSync(args.manifest, "utf8"));
  const files = manifest.files || [];
  const skippedBinary = manifest.skipped_binary || [];
  if (!Array.isArray(files) || files.length === 0) {
    fail("Manifest contains no files.");
  }

  const browser = await chromium.launch({
    executablePath: args.chromePath,
    headless: false,
    args: ["--disable-blink-features=AutomationControlled"],
  });

  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
    });
    await context.addCookies(cookies);
    const page = await context.newPage();

    const owner = args.repoOwner || (await inferDefaultOwner(page));
    const repoBase = `https://github.com/${owner}/${args.repoName}`;
    const exists = await repoExists(page, repoBase);

    if (!exists && !args.createRepo && !args.dryRun) {
      fail(`Repository ${owner}/${args.repoName} does not exist. Re-run with --create-repo.`);
    }

    if (!exists && args.createRepo && !args.dryRun) {
      await createRepository(page, owner, args.repoName, args.visibility, args.description);
    }

    if (args.dryRun) {
      console.log(
        JSON.stringify(
          {
            ok: 1,
            dry_run: true,
            repo_owner: owner,
            repo_name: args.repoName,
            repo_url: repoBase,
            repo_exists: exists,
            would_create_repo: !exists && args.createRepo,
            file_count: files.length,
            skipped_binary: skippedBinary,
          },
          null,
          2,
        ),
      );
      return;
    }

    const uploaded = [];
    for (const entry of files) {
      uploaded.push(await uploadFile(page, repoBase, entry));
    }

    await navigate(page, repoBase);
    await page.waitForTimeout(2500);

    console.log(
      JSON.stringify(
        {
          ok: 1,
          repo_owner: owner,
          repo_name: args.repoName,
          repo_url: repoBase,
          uploaded_count: uploaded.length,
          uploaded,
          skipped_binary: skippedBinary,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  fail(error && error.message ? error.message : String(error));
});
