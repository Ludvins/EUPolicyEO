import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import article20Pilot from "../../../reports/article20_agreement.json" with { type: "json" };
import article20Comparison from "../../../reports/article20_comparison.json" with { type: "json" };
import type { Evidence, Manifest, Result } from "../../src/types";

const active = fs.existsSync("dist/active.json");
const base = process.env.PAGES_BASE || "/EUPolicyEO/";
const site = "http://127.0.0.1:" + (process.env.E2E_PORT || 4173) + base;
const releaseRoot = active ? "dist/releases/" + JSON.parse(fs.readFileSync("dist/active.json", "utf-8")).release_id : "";
const manifest: Manifest | undefined = active ? JSON.parse(fs.readFileSync(path.join(releaseRoot, "manifest.json"), "utf-8")) : undefined;

test("missing or corrupted release displays a retry control", async ({ page }) => {
  if (active) await page.route("**/active.json", route => route.fulfill({json: {release_id: "../bad"}}));
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "Evidence explorer" })).toBeVisible();
  await expect(page.getByRole("button", {name: "Retry loading"})).toBeVisible();
  await expect(page.locator("#workspace")).toBeHidden();
});

test("free-text default, Article 20 examples, and mobile keyword search", async ({ page }) => {
  test.skip(!active, "Requires a staged release");
  const external: string[] = [];
  page.on("request", request => {
    if (!request.url().startsWith(site)) external.push(request.url());
  });
  await page.setViewportSize({width: 390, height: 844});
  await page.goto("./");
  const startingPoint = page.getByLabel("Search starting point");
  const input = page.getByLabel("Search query");
  await expect(startingPoint).toHaveValue("");
  await expect(input).toHaveValue("");
  await expect(page.locator("#load-status")).toBeEmpty();
  await expect(page.locator("#evidence")).toBeHidden();
  await expect(page.locator("#legal-examples")).toHaveAttribute("label", "Real legal provisions · Article 20");
  if (await startingPoint.evaluate(element => getComputedStyle(element).appearance === "base-select")) {
    await startingPoint.focus();
    await page.keyboard.press("Space");
    await expect.poll(() => startingPoint.evaluate(element => element.matches(":open"))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(startingPoint).toHaveValue("");
    await page.keyboard.press("Space");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
  } else {
    await startingPoint.selectOption({ label: "20(1)(b) · Urban green space and tree canopy" });
  }
  await expect(input).toHaveValue(/urban tree canopy/i);
  await expect(page.locator("#evidence").getByText("Member States shall monitor the following:")).toBeVisible();
  const presetId = await startingPoint.inputValue();
  const extracted: Evidence[] = JSON.parse(fs.readFileSync(path.join(releaseRoot, "requirements.json"), "utf-8"));
  const preset = extracted.find(record => record.requirement.id === presetId)?.requirement;
  await expect(page.locator("#evidence")).not.toContainText(/review pending|unreviewed|validation required/i);
  await expect(page.locator("#evidence a")).toHaveAttribute("href", /eur-lex\.europa\.eu.*art_20/);
  await page.getByRole("button", { name: "Search", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#search-status")).toContainText("Keyword search");
  if (preset?.search_profile) {
    if (Object.values(preset.search_profile.record_evidence ?? {}).some(use => use.role === "direct_measurement")) {
      const first = page.locator("#eo article").first();
      await expect(first).toContainText("Tree Cover Density");
      await expect(first).toContainText("Direct measurement");
      await first.getByRole("button", {name: /Tree Cover Density/}).click();
      const detail = page.locator("#record-details");
      await expect(detail).toContainText("tree crown cover");
      await expect(detail.getByRole("link", {name: "Read the evidence source"}))
        .toHaveAttribute("href", /land\.copernicus\.eu/);
      await page.keyboard.press("Escape");
    }
    await startingPoint.selectOption({label: "20(1)(g) · Pollinator abundance and diversity"});
    await expect(input).toHaveValue(/pollinator species abundance/i);
    await expect(page.locator(".results")).toBeHidden();
    await expect(page.locator("#search-status")).toBeEmpty();
    await page.getByRole("button", {name: "Search", exact: true}).click();
    if (manifest!.parent_snapshot_id === article20Pilot.snapshot_id) {
      await expect(page.locator("#search-status")).toContainText("0 results");
      await expect(page.locator("#eo .empty")).toContainText("No records matched the legal topic");
    }
    const pollinator = extracted.find(record => record.requirement.id === "32024R1991:eng:20:1:g:r0");
    if (pollinator?.requirement.search_profile?.record_evidence?.["cordis:101135005"]) {
      const first = page.locator("#projects article").first();
      await expect(first).toContainText("Research method");
      await expect(page.locator("#eo .empty")).toContainText("No records matched the legal topic");
    }
  } else {
    await expect(page.locator("#eo article").first()).toBeVisible();
    await expect(page.locator("#projects article").first()).toBeVisible();
  }
  await input.fill("forest fragmentation across Europe");
  await expect(startingPoint).toHaveValue("");
  await expect(page.locator("#evidence")).toBeHidden();
  await expect(page.locator(".results")).toBeHidden();
  await page.getByText("Collection filters", {exact:true}).click();
  await page.getByLabel("West", {exact:true}).fill("175");
  await page.getByLabel("South", {exact:true}).fill("-25");
  await page.getByLabel("East", {exact:true}).fill("-170");
  await page.getByLabel("North", {exact:true}).fill("25");
  await page.getByRole("button", {name:"Search", exact:true}).click();
  await expect(page.locator("#search-status")).toContainText("Keyword search");
  await expect(page.locator("#eo article").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(external).toEqual([]);
});

test("editing an in-flight search discards its results", async ({page}) => {
  test.skip(!active, "Requires a staged release");
  await page.addInitScript(() => {
    const SearchWorker = window.Worker;
    window.Worker = class extends SearchWorker {
      constructor(url: string | URL, options?: WorkerOptions) {
        super(url, options);
        this.addEventListener("message", ({data}) => {
          if (Array.isArray(data.eo)) document.documentElement.dataset.searchFinished = String(data.eo.length);
        });
      }
    };
  });
  let resume!: () => void;
  const paused = new Promise<void>(resolve => { resume = resolve; });
  let requested!: () => void;
  const requestStarted = new Promise<void>(resolve => { requested = resolve; });
  await page.route("**/collections.json", async route => {
    requested();
    await paused;
    await route.continue();
  });
  await page.goto("./");
  await page.getByRole("button", {name: "Vegetation cover", exact: true}).click();
  await page.getByRole("button", {name: "Search", exact: true}).click();
  await requestStarted;
  try {
    await page.getByLabel("Search query").fill("urban tree canopy");
    await expect(page.locator("#search-status")).toBeEmpty();
  } finally {
    resume();
  }
  await expect(page.locator("html")).toHaveAttribute("data-search-finished", /^[1-9]\d*$/);
  await expect(page.locator(".results")).toBeHidden();
  await expect(page.locator("#search-status")).toBeEmpty();
});

test("readable source cards and real keyword results with secondary raw metadata", async ({page}) => {
  test.skip(!active, "Requires a staged release");
  await page.goto("./");
  await expect(page.getByRole("heading", {name:"Copernicus Data Space"})).toBeVisible();
  await expect(page.locator("#dataset")).toContainText("This explorer searches a fixed release in your browser.");
  const provenance = page.getByText("Release provenance", {exact: true});
  await expect(provenance).toBeVisible();
  await expect(page.locator("#dataset-data").getByText(manifest!.release_id, {exact: true})).toBeHidden();
  await provenance.click();
  await expect(page.locator("#dataset-data").getByText(manifest!.release_id, {exact: true})).toBeVisible();
  await provenance.click();
  await page.getByRole("button", {name:"Vegetation cover", exact:true}).click();
  await expect(page.getByLabel("Search query")).toHaveValue("fraction of green vegetation cover");
  await page.getByRole("button", {name:"Search", exact:true}).click();
  const title = page.locator("#eo article .result-title").first();
  await expect(title).toContainText(/Fraction of Green Vegetation Cover/i);
  const name = await title.textContent();
  await title.click();
  const detail = page.locator("#record-details");
  await expect(detail).toBeVisible();
  await expect(detail.getByRole("heading", { name: name!, exact: true })).toBeVisible();
  await expect(detail.getByRole("link", {name:"Open in the Copernicus catalogue"})).toHaveAttribute("href",
    /https:\/\/browser\.stac\.dataspace\.copernicus\.eu\/collections\//);
  const raw = detail.getByRole("link", { name: "Raw catalogue record (JSON)" });
  await expect(raw).toBeHidden();
  await detail.getByText("Source and provenance", {exact:true}).click();
  await expect(raw).toHaveAttribute("href", /https:\/\/stac\.dataspace\.copernicus\.eu\/v1\/collections\//);
  await page.keyboard.press("Escape");
  await expect(detail).toBeHidden();
  await expect(title).toBeFocused();
  if ([article20Pilot.public_corpus_hash, article20Comparison.public_corpus_hash].includes(manifest!.public_corpus_hash)) {
    await page.getByRole("button", {name: "Wetland restoration", exact:true}).click();
    await expect(page.getByLabel("Search query")).toHaveValue("wetland surface water restoration");
    await page.getByRole("button", {name: "Search", exact:true}).click();
    await expect(title).toHaveText("OPERA Dynamic Surface Water Extent from Sentinel-1 (Version 1)");
    await expect(page.locator("#projects .result-title").first()).toHaveText("Wetland restoration for the future");
    if (process.env.E2E_SCREENSHOT) {
      await page.setViewportSize({width: 1440, height: 1030});
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({path: process.env.E2E_SCREENSHOT});
    }
    await title.click();
    await expect(detail.getByRole("link", {name: "Open in NASA Earthdata"})).toHaveAttribute("href",
      "https://search.earthdata.nasa.gov/search/granules?p=C2949811996-POCLOUD");
    await page.keyboard.press("Escape");
  }
  const nasaTitle = "USGS Land Use and Land Cover, 200m";
  const catalogue = JSON.parse(fs.readFileSync(path.join(releaseRoot, "collections.json"), "utf-8"));
  if (catalogue.some((record: {title: string}) => record.title === nasaTitle)) {
    await page.getByLabel("Search query").fill(nasaTitle);
    await page.getByRole("button", {name: "Search", exact: true}).click();
    await page.getByRole("button", {name: nasaTitle, exact: true}).click();
    await expect(detail.getByRole("link", {name: "Open in NASA Earthdata"})).toHaveAttribute("href",
      "https://search.earthdata.nasa.gov/search/granules?p=C1214055278-SCIOPS");
    await expect(raw).toBeHidden();
    await detail.getByText("Source and provenance", {exact: true}).click();
    await expect(raw).toHaveAttribute("href", /collections\.umm_json\?concept_id=C1214055278-SCIOPS$/);
    await page.keyboard.press("Escape");
  }
  if (process.env.E2E_DATASET_SCREENSHOT) {
    await page.locator("#dataset").screenshot({type:"jpeg", quality:90, path:process.env.E2E_DATASET_SCREENSHOT});
  }
});

test("portfolio preserves dataset provenance without displaying benchmark reports", async ({page}) => {
  test.skip(!active, "Requires a staged release");
  const reportRequests: string[] = [];
  page.on("request", request => {
    const { pathname } = new URL(request.url());
    if (/\/reports\/(?:benchmark|evaluation|ingestion|model_lineage)\.json$/.test(pathname)) {
      reportRequests.push(pathname);
    }
  });
  await page.setViewportSize({width: 390, height: 844});
  await page.goto("./");
  const dataset = page.locator("#dataset");
  await expect(dataset.getByRole("heading", {name: "Dataset and methodology"})).toBeVisible();
  await dataset.getByText("Release provenance", {exact: true}).click();
  await expect(dataset.getByText(manifest!.release_id, {exact: true})).toBeVisible();
  await expect(page.locator('#reports, nav a[href="#reports"]')).toHaveCount(0);
  await expect(page.getByRole("heading", {name: /benchmark|evaluation|browser validation|known-record/i})).toHaveCount(0);
  expect(reportRequests).toEqual([]);
});

test("Article 20 assessment screens the returned collections with editable criteria", async ({ page }) => {
  test.skip(!active, "Requires a staged release");
  const requirements: Evidence[] = JSON.parse(fs.readFileSync(path.join(releaseRoot, "requirements.json"), "utf-8"));
  const canopy = requirements.find(row => row.requirement.id === "32024R1991:eng:20:1:b:r0");
  test.skip(!canopy?.requirement.search_profile?.record_evidence?.["cdse:clms_vlcc_tree-cover-density_europe_100m_yearly_v1"],
    "Requires the portfolio release with documented Tree Cover Density collections");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("./");
  const provision = page.getByLabel("Search starting point");
  const search = page.getByRole("button", { name: "Search", exact: true });
  const panel = page.locator("#search-assessment");
  await expect(panel).toBeHidden();
  await provision.selectOption({ label: "20(1)(b) · Urban green space and tree canopy" });
  await page.getByText("Collection filters", { exact: true }).click();
  await page.getByLabel("From (UTC)", { exact: true }).fill("2021-01-01");
  await search.click();
  await panel.getByText("Assess these collections", { exact: true }).click();
  await expect(panel.getByRole("heading")).toContainText("Article 20(1)(b)");
  await expect(page.locator("#eo .result-title").first()).toBeVisible();
  const assessmentStart = panel.getByLabel("Assessment from (UTC)", { exact: true });
  await expect(assessmentStart).toHaveValue("2021-01-01");
  await assessmentStart.fill("");
  const titles = await page.locator("#eo .result-title").allTextContents();
  const maximum = panel.getByLabel("Maximum spatial resolution (m)", { exact: true });
  const assess = panel.getByRole("button", { name: "Assess collections", exact: true });
  const matrix = panel.getByRole("table", { name: "Assessment of search results" });
  const coarse = matrix.getByRole("row").filter({ hasText: /Tree Cover Density \(TCD\) Europe 100m yearly V1 \(COG\)/ });
  const fine = matrix.getByRole("row").filter({ hasText: /Tree Cover Density \(TCD\) Europe 10m yearly V1 \(COG\)/ });
  await maximum.fill("20");
  await assess.click();
  await expect(matrix.getByRole("rowheader")).toHaveText(titles);
  await expect(coarse.getByRole("cell")).toHaveText(["Meets", "Fails", "Fails"]);
  await expect(fine.getByRole("cell")).toHaveText(["Meets", "Meets", "Meets"]);
  await panel.getByText("Evidence by collection", { exact: true }).click();
  const coarseEvidence = panel.locator(".assessment-evidence > details").filter({ hasText: /Evidence for .*Europe 100m yearly V1 \(COG\)/ });
  await coarseEvidence.locator("summary").click();
  await expect(coarseEvidence.getByRole("link", { name: "Read evidence" })).toHaveAttribute("href", /land\.copernicus\.eu/);
  await fine.getByRole("button").click();
  await expect(page.getByRole("dialog")).toContainText("Tree Cover Density");
  await page.keyboard.press("Escape");

  await maximum.fill("120");
  await expect(matrix).toBeHidden();
  await panel.getByLabel("Assessment through (UTC)").fill("2017-12-31");
  await assess.click();
  await expect(coarse.getByRole("cell")).toHaveText(["Meets", "Meets", "Fails", "Fails"]);
  await expect(matrix.getByRole("rowheader")).toHaveText(titles);
  await expect(page.locator("#eo .result-title")).toHaveText(titles);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);

  await provision.selectOption({ label: "20(1)(h) · Habitat area and condition" });
  await expect(panel).toBeHidden();
  await search.click();
  await panel.getByText("Assess these collections", { exact: true }).click();
  await expect(panel.getByRole("heading")).toContainText("Article 20(1)(h)");
  await assessmentStart.fill("");
  await maximum.fill("");
  await assess.click();
  await expect(matrix.getByRole("rowheader")).toHaveText(await page.locator("#eo .result-title").allTextContents());
  const glance = matrix.getByRole("row").filter({ hasText: "Global Land Cover Mapping and Estimation Yearly 30 m V001" });
  if (await glance.count()) {
    await expect(glance.getByRole("cell")).toHaveText(["Partial", "Partial"]);
    await expect(matrix.getByRole("row").filter({ hasText: "Mt. Pisgah Campground" })).toHaveCount(0);
    await maximum.fill("20");
    await assess.click();
    await expect(glance.getByRole("cell")).toHaveText(["Partial", "Fails", "Fails"]);
    await maximum.fill("");
    await assessmentStart.fill("2020-01-01");
    await assess.click();
    await expect(glance.getByRole("cell")).toHaveText(["Partial", "Unknown", "Unknown"]);
  }

  await provision.selectOption({ label: "20(1)(g) · Pollinator abundance and diversity" });
  await search.click();
  await expect(page.locator("#search-status")).toContainText("Keyword search");
  if (await page.locator("#eo .result-title").count() === 0) await expect(panel).toBeHidden();
});

test("habitat condition search returns the source-checked collections in all three modes", async ({ page }) => {
  test.skip(!manifest?.dense || manifest.public_corpus_hash !== "b344066e91e016f9fbd2f46e692d04578103498126ecd78ad0ff43ad5db3efc7",
    "Uses the known habitat records in the portfolio release");
  await page.goto("./");
  const search = page.getByRole("button", { name: "Search", exact: true });
  const mode = page.getByLabel("Search mode");
  const titles = page.locator("#eo .result-title");
  await page.getByLabel("Search starting point").selectOption({ label: "20(1)(a) · Habitat condition and trends" });
  for (const [id, label] of [["bm25", "Keyword search"], ["dense", "Semantic search"], ["hybrid", "Hybrid search"]]) {
    await mode.selectOption(id);
    await search.click();
    await expect(page.locator("#search-status")).toHaveText(new RegExp("^\\d+ results? · " + label + "$"), { timeout: 90_000 });
    await expect(titles).toHaveCount(3);
    await expect(page.locator("#eo")).toContainText("Urban Atlas Land Cover and Land Use Change");
    await expect(page.locator("#eo")).toContainText("Vegetation Quality Index for Europe");
    await expect(page.locator("#eo")).toContainText("Land Cover Map (LCM)");
  }
  await titles.filter({ hasText: "Vegetation Quality Index for Europe" }).click();
  await expect(page.getByRole("link", { name: "Read the evidence source (CMR JSON)" }))
    .toHaveAttribute("href", /concept_id=C1214155224-SCIOPS/);
  await page.keyboard.press("Escape");
  const panel = page.locator("#search-assessment");
  await panel.getByText("Assess these collections", { exact: true }).click();
  await panel.getByRole("button", { name: "Assess collections", exact: true }).click();
  await expect(panel.locator("tbody td:last-child")).toHaveText(["Partial", "Partial", "Partial"]);

  await mode.selectOption("bm25");
  await page.getByLabel("Search query").fill("National Surface Water Survey");
  await search.click();
  await expect(titles.first()).toHaveText("National Surface Water Survey (NSWS)");
});

test("source-linked suitability matrix compares indicators and exposes sampled coverage", async ({page}) => {
  test.skip(!manifest?.assets["reports/suitability.json"], "Requires a released assessment");
  await page.setViewportSize({width: 390, height: 844});
  await page.goto("./");
  await page.getByRole("link", {name: "See the Andalusia worked example"}).click();
  const assessment = page.locator("#assessment");
  const matrix = assessment.getByRole("table", {name: "Fitness-for-purpose matrix"});
  await expect(matrix).toBeVisible();
  await expect(matrix.getByRole("row")).toHaveCount(5);
  await expect(assessment).toContainText("Urban boundaries and local accuracy");
  await expect(assessment).not.toContainText(/placeholder|validation (?:is |are |still )*required/i);
  await assessment.getByText("Legal obligation", {exact: true}).click();
  await expect(assessment.getByRole("link", {name: "Article 20(1)(b) on EUR-Lex"})).toBeVisible();
  await assessment.getByText("Analyst screening criteria", {exact: true}).click();
  await expect(assessment.getByText("Raster resolution of 20 m or finer")).toBeVisible();
  await assessment.locator(".assessment-evidence summary").first().click();
  await expect(assessment.getByRole("link", {name: "2024 · 3 intersecting items (STAC JSON)", exact: true})).toHaveAttribute("href", /stac\.dataspace\.copernicus\.eu/);
  await assessment.getByRole("button", {name: "Urban green space", exact: true}).click();
  await expect(assessment.getByRole("button", {name: "Urban green space", exact: true})).toHaveAttribute("aria-pressed", "true");
  await expect(assessment).toContainText("full green-space indicator");
  const example = assessment.getByText("Example reporting brief", {exact: true});
  if (await example.count()) {
    await example.click();
    await expect(assessment.locator(".assessment-brief")).toContainText("summarise the assessment evidence and cite its sources");
    await expect(assessment.locator(".assessment-brief li")).toHaveCount(4);
    await expect(assessment.locator(".assessment-brief").getByRole("link", {name: "Article 20(1)(b)"}))
      .toHaveAttribute("href", /eur-lex\.europa\.eu/);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  if (process.env.E2E_ASSESSMENT_SCREENSHOT) {
    await page.setViewportSize({width: 1440, height: 1040});
    await page.reload();
    await expect(matrix).toBeVisible();
    await assessment.screenshot({type: "jpeg", quality: 90, path: process.env.E2E_ASSESSMENT_SCREENSHOT});
  }
});

test("hybrid search combines the browser rankers and supports a keyword fallback", async ({page}) => {
  test.skip(!active, "Requires a staged release");
  const external: string[] = [];
  page.on("request", request => { if (!request.url().startsWith(site)) external.push(request.url()); });
  await page.goto("./");
  await expect(page.locator("#workspace")).toBeVisible();
  const mode = page.getByLabel("Search mode");
  if (!manifest?.dense) {
    await expect(mode.locator('option[value="hybrid"]')).toBeDisabled();
    return;
  }
  await mode.selectOption({label: "Hybrid search"});
  await page.getByRole("button", {name: "Vegetation cover", exact: true}).click();
  await page.getByRole("button", {name: "Search", exact: true}).click();
  await expect(page.locator("#search-status")).toContainText(/\d+ results? · Hybrid search/, {timeout: 90_000});
  const result = page.locator("#eo article").first();
  await expect(result).toContainText("Fraction of Green Vegetation Cover");
  await expect(result).toContainText("Hybrid score");
  await result.locator(".result-title").click();
  await expect(page.locator("#record-details")).toContainText("Combines the positions of a record in keyword and semantic search.");

  await page.route("**/models/model.onnx", route => route.abort());
  await page.reload();
  await mode.selectOption("hybrid");
  await page.getByRole("button", {name: "Vegetation cover", exact: true}).click();
  await page.getByRole("button", {name: "Search", exact: true}).click();
  await page.getByRole("button", {name: "Search with BM25"}).click();
  await expect(page.locator("#search-status")).toContainText("Keyword search");
  expect(external).toEqual([]);
});

test("real WASM inference, similarity scores, interactive embedding projection and fallback", async ({page}) => {
  test.skip(!manifest?.dense, "Requires dense model release");
  const external: string[] = [];
  page.on("request", req => { if (!req.url().startsWith(site)) external.push(req.url()); });
  await page.goto("./");
  await page.getByLabel("Search mode").selectOption("dense");
  await page.getByLabel("Search query").fill(manifest!.free_text_policy ? "tree cover density" : "canopy shade from vegetation in a town");
  await page.getByRole("button", {name:"Search", exact:true}).click();
  await expect(page.locator("#search-status")).toContainText("Semantic search", {timeout: 90_000});
  await expect(page.locator("#eo article").first()).toContainText("Similarity score");
  await page.getByText("Embedding map", {exact: true}).click();
  const chart = page.getByRole("group", {name:"Projected query and result embeddings"});
  await expect(chart).toBeVisible();
  await expect(chart.getByRole("button")).toHaveCount(1 + await page.locator("#eo article, #projects article").count());
  await expect(chart.getByRole("button", {name:"Your query"})).toHaveAttribute("aria-pressed", "true");
  await chart.locator("[data-group=eo]").first().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".embedding-selection")).toContainText("Similarity score");
  await page.getByRole("button", {name:"View result"}).click();
  await expect(page.locator("#record-details")).toBeVisible();
  await page.getByRole("button", {name:"Close",exact:true}).click();
  if (manifest!.free_text_policy) {
    for (const mode of ["dense", "bm25"]) {
      await page.getByLabel("Search mode").selectOption(mode);
      await page.getByLabel("Search query").fill("oxygen concentration in the atmosphere of Jupiter’s moon Europa");
      await page.getByRole("button", {name:"Search", exact:true}).click();
      await expect(page.locator("#search-status")).toContainText("0 results");
      await expect(page.locator("#eo .empty")).toContainText("No records had enough matching evidence");
      await expect(page.locator("#projects .empty")).toContainText("No records had enough matching evidence");
    }
  }
  expect(external).toEqual([]);
  await page.route("**/models/model.onnx", route => route.abort());
  await page.reload();
  await page.getByLabel("Search mode").selectOption("dense");
  await page.getByLabel("Search query").fill("urban tree canopy");
  await page.getByRole("button", {name:"Search", exact:true}).click();
  await page.getByRole("button", {name:"Search with BM25"}).click();
  await expect(page.locator("#search-status")).toContainText("Keyword search");
  await expect(page.locator("#embedding-map")).toBeHidden();
});

test("optional map draws bounds and marks real collection extents under the project path", async ({page}) => {
  test.skip(!active, "Requires a staged release");
  const requests: string[] = [];
  page.on("request", request => requests.push(request.url()));
  await page.goto("./");
  await page.getByText("Collection filters", {exact:true}).click();
  const canvas = page.getByRole("img", {name:"Area of interest and selected collection extent"});
  await expect(canvas).toBeHidden();
  await page.getByText("Draw or view area on map", {exact:true}).click();
  await expect(canvas).toBeVisible();
  await page.getByRole("button", {name:"Andalusia example"}).click();
  await expect(page.getByRole("spinbutton", {name:"West", exact:true})).toHaveValue("-7.5");
  await expect(page.getByRole("spinbutton", {name:"North", exact:true})).toHaveValue("38.8");
  await page.getByLabel("Search query").fill("land cover and vegetation");
  await page.getByRole("button", {name:"Search", exact:true}).click();
  await page.locator("#eo").getByRole("button", {name:"Show extent on map"}).first().click();
  await expect(page.locator("#map-selection")).toContainText(/intersects the area|outside the area/);
  await page.getByRole("button", {name:"Clear collection extent"}).click();
  await page.getByRole("spinbutton", {name:"West", exact:true}).fill("175");
  await expect(page.locator(".results")).toBeHidden();
  await page.getByRole("spinbutton", {name:"East", exact:true}).fill("-170");
  await expect(page.locator("#map-selection")).toContainText("Area crosses the 180° meridian.");
  await page.getByRole("button", {name:"World view"}).click();
  await page.getByRole("button", {name:"Draw area"}).click();
  await canvas.scrollIntoViewIfNeeded();
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.4, box.y + box.height * 0.25);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.42, {steps: 5});
  await page.mouse.up();
  const west = Number(await page.getByRole("spinbutton", {name:"West", exact:true}).inputValue());
  const east = Number(await page.getByRole("spinbutton", {name:"East", exact:true}).inputValue());
  expect(west).toBeCloseTo(-36, 0);
  expect(east).toBeCloseTo(18, 0);
  expect(requests.some(url => /\/map-land-[\w-]+\.json$/.test(url))).toBe(true);
  const lookup = page.getByLabel("Find a city");
  await lookup.fill("Seville");
  await lookup.press("Enter");
  await expect(lookup).toHaveValue("Seville, Spain");
  await page.getByRole("button", {name:"Pan map"}).click();
  await page.getByRole("button", {name:"Zoom in"}).click();
  await canvas.scrollIntoViewIfNeeded();
  const region = (await canvas.boundingBox())!;
  await page.mouse.move(region.x + region.width * .50, region.y + region.height * .5);
  await page.mouse.down();
  await page.mouse.move(region.x + region.width * .65, region.y + region.height * .5, {steps: 4});
  await page.mouse.up();
  await expect(page.getByLabel("West", {exact:true})).toHaveValue(String(west));
  await page.getByRole("button", {name:"Draw area"}).click();
  await page.mouse.move(region.x + region.width * .32, region.y + region.height * .31);
  await page.mouse.down();
  await page.mouse.move(region.x + region.width * .63, region.y + region.height * .59, {steps: 4});
  await page.mouse.up();
  const localWest = Number(await page.getByLabel("West", {exact:true}).inputValue());
  const localEast = Number(await page.getByLabel("East", {exact:true}).inputValue());
  expect(localWest).toBeGreaterThan(-7);
  expect(localEast).toBeLessThan(-5);
  expect(localEast - localWest).toBeLessThan(.4);
  expect(requests.some(url => /\/map-detail-[\w-]+\.json$/.test(url))).toBe(true);
  expect(requests.every(url => url.startsWith(site))).toBe(true);
  if (process.env.E2E_MAP_SCREENSHOT) {
    await page.getByRole("button", {name:"Andalusia example"}).click();
    await page.getByRole("button", {name:"Search", exact:true}).click();
    await page.locator("#eo").getByRole("button", {name:"Show extent on map"}).first().click();
    await page.locator("#map-details").screenshot({path:process.env.E2E_MAP_SCREENSHOT});
  }
});

test("Python and production browser worker parity", async ({page, browser}) => {
  test.skip(!manifest, "Requires a staged release");
  await page.goto("./");
  const report = await page.evaluate(async ({ base, id, dense }) => {
    const root = new URL(`${base}releases/${id}/`, location.origin);
    const index = await (await fetch(new URL(`${base}index.html`, location.origin))).text();
    const mainPath = index.match(/src="([^"]+\.js)"/)![1];
    const main = await (await fetch(mainPath)).text();
    const workerPath = main.match(/([^"'\s]*search\.worker-[A-Za-z0-9_-]+\.js)/)![1];
    const worker = new Worker(new URL(workerPath, location.origin), {type:"module"});
    let count = 0;
    const ask = (query: string, mode: string, constraints: object, profile?: object) => new Promise<Record<string, any>>((resolve,reject) => {
      worker.onmessage = ({data}) => data.error ? reject(new Error(data.error)) : resolve(data);
      worker.onerror = reject;
      worker.postMessage({id: ++count, releaseId: id, query, mode, constraints, profile, parity: true});
    });
    let maxScoreDelta = 0;
    let lexicalCases = 0;
    let lexicalMismatches = 0;
    for (const ref of await (await fetch(new URL("lexical/reference.json", root))).json()) {
      const observed = (await ask(ref.query, "bm25", ref.constraints, ref.profile))[ref.corpus] as Result[];
      lexicalCases++;
      if (observed.length !== ref.results.length || observed.some((row,i) => row.doc.id !== ref.results[i].id ||
          row.compatibility !== ref.results[i].compatibility)) lexicalMismatches++;
      observed.forEach((row,i) => { if (ref.results[i]) maxScoreDelta = Math.max(maxScoreDelta, Math.abs(row.score-ref.results[i].score)); });
    }
    const cosine: number[] = [], overlap: number[] = [], timings: number[] = [];
    let denseNonEmptyComparisons = 0;
    const resourcesBefore = performance.getEntriesByType("resource").length;
    if (dense) {
      for (const ref of await (await fetch(new URL("vectors/reference.json", root))).json()) {
        const result = await ask(ref.query, "dense", {});
        const vector = result.vector as number[];
        const dot = vector.reduce((sum,v,i) => sum + v * ref.vector[i], 0);
        cosine.push(dot / (Math.hypot(...vector) * Math.hypot(...ref.vector as number[])));
        timings.push(result.elapsedMs);
        for (const corpus of ["eo","projects"]) {
          const actual = (result[corpus] as Result[]).map(row => row.doc.id);
          const expected: string[] = ref.ranks[corpus];
          const denominator = Math.max(actual.length, expected.length);
          if (denominator) denseNonEmptyComparisons++;
          overlap.push(denominator ? actual.filter(id => expected.includes(id)).length / denominator : 1);
        }
      }
    }
    worker.terminate();
    return {lexicalCases,lexicalMismatches,maxScoreDelta,denseCases:cosine.length,denseNonEmptyComparisons,
      minCosine:cosine.length ? Math.min(...cosine) : null,
      meanTop10Overlap:overlap.length ? overlap.reduce((a,b) => a+b,0)/overlap.length : null,
      denseColdMs:timings[0] ?? null,denseWarmMs:timings.slice(1),
      documentResourceCount:performance.getEntriesByType("resource").length-resourcesBefore};
  }, {base, id: manifest!.release_id, dense: !!manifest!.dense});
  if (process.env.E2E_REPORT) {
    fs.writeFileSync(process.env.E2E_REPORT, JSON.stringify({ ...report, releaseId: manifest!.release_id,
      recordedAt: new Date().toISOString(), browser: browser.version(), platform: process.platform }, null, 2));
  }
  expect(report.lexicalMismatches).toBe(0);
  expect(report.lexicalCases).toBeGreaterThanOrEqual(40);
  expect(report.maxScoreDelta).toBeLessThanOrEqual(1e-6);
  if (manifest!.dense) {
    expect(report.denseCases).toBeGreaterThanOrEqual(20);
    expect(report.minCosine).toBeGreaterThanOrEqual(manifest!.dense.parity_gates.min_cosine);
    expect(report.meanTop10Overlap).toBeGreaterThanOrEqual(manifest!.dense.parity_gates.mean_top10_overlap);
  }
});
