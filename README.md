# UK Boundary Atlas

A static, metadata-only explorer for official UK geography files and source-vintage coverage since 2010. The interface has two working surfaces: **Find files** and **Coverage & sources**.

England is the first-version priority, with Wales next. File search and the coverage grid open on England; Wales has a quick preset. Scottish and Northern Irish sources remain available through country filters and optional census presets, with their separate reporting systems preserved.

The original map-comparison prototype is preserved on `main` in the initial import. The expansion removes map comparison, polygon querying and the saved Kirklees polygons.

## Run locally

Python 3.10+ and Node 22+ are sufficient at runtime; the maintenance scripts use the standard library. Formatting, lint and type checks use separate development tools.

```bat
python -m http.server 8765 --directory dist
```

Open `http://localhost:8765`. Serve the files over HTTP rather than opening `index.html` directly. For the test commands below, first use the Conda development setup and install the Python package.

```bat
python -m unittest discover -s tests
node --test tests/catalogue.test.mjs
node --check dist/app.js
```

## Python API

The installable distribution is `uk-boundary-atlas`; import it as `uk_boundaries`. It uses the Python standard library, loads a local snapshot or the published catalogue, and downloads native publisher files into a chosen directory. The package contains code only: the website data and government polygons are not bundled in its wheel.

Install in an isolated Conda environment (Windows `cmd.exe`):

```bat
conda create --name uk-boundaries-client --channel conda-forge python=3.12 pip
conda activate uk-boundaries-client
python -m pip install git+https://github.com/hulsiejames/uk-boundaries.git
```

Or activate your own target Conda environment and install a checkout using `python -m pip install .`. Installation from GitHub requires Git.

```python
from uk_boundaries import Catalogue

catalogue = Catalogue.from_url()
# Offline alternatives: the shipped dist/catalogue.json or a website manifest export.
# catalogue = Catalogue.from_file("uk-boundary-manifest.json")

matches = catalogue.search(level="combined", country="England", year=2025, variant="BFC")
for dataset in matches:
    print(dataset.id, dataset.title)

# Select an exact record; never silently choose a different vintage or resolution.
record_id = "ons:46d178d0a81241a0ae8637b9eddf2378"
options = catalogue.resolve(record_id)
for option in options:
    print(option.format, option.url, option.layer_id)

result = catalogue.download(record_id, output_dir=r"C:\spatial\boundaries")
print(result.format)  # Actual saved format: gpkg or shapefile.
print(result.path)  # A path usable by GeoPandas, GDAL or another process.
print(result.manifest_path)  # Record ID, source, reference years, hash and download time.
```

`Catalogue.from_url()` retrieves the latest **published static snapshot**, not a live government catalogue scan. `from_file()` and `search()` work offline. Search uses reporting IDs from `catalogue.levels`, labelled reference years, country containment, whole-word text, product kind and boundary variant. It defaults to `kind="boundary"`; use `kind="centroid"`, `kind="lookup"` or `kind=None` as needed. Individual polygon/place names remain outside the index, except audited combined-authority names/codes.

`resolve()` returns indexed direct GeoPackage/shapefile links and live ArcGIS Hub export routes. It checks the actual service layer IDs and the publisher's download flag; a service's export capability alone is insufficient. Multiple service layers require an explicit `layer_id`. Direct bundles are downloaded whole; `layer_id` applies to service exports. All spatial primary files in a bundle are returned in `result.paths`; `result.path` raises `AmbiguousLayerError` when several exist.

`download()` tries GeoPackage first and falls back to shapefile when the preferred public download fails or is unavailable. Set `format_preference=("gpkg",)` to require GeoPackage or `("shapefile",)` to request shapefile only. Files retain their publisher geometry, CRS and fields; the API performs no conversions, clipping or translations. Native GeoPackages and ZIPs are supported; shapefile archives must contain the `.shp`, `.shx` and `.dbf` sidecars. [Esri's download settings](https://doc.esri.com/en/arcgis-hub/latest/build/data-download-settings.html) explain why formats and anonymous availability vary by service.

Downloads are streamed into a staging directory, checked and then moved into a separate record/format directory. Existing results are preserved unless `overwrite=True`; even then, validation completes before replacement. Unsafe archive paths, symlinks, duplicate paths, incomplete transfers and unexpected file contents are rejected. `max_bytes` defaults to 2 GB for both the transfer and total uncompressed contents; raise it explicitly for large national datasets. `timeout` controls each request and `max_wait` bounds export preparation/polling. A provenance manifest records the actual format, selected layer, public URLs and SHA-256 payload hash; temporary redirect tokens are omitted.

The API supports public direct-file routes and public ArcGIS Hub exports. Page-only, restricted, WFS-only or unsupported sources raise `DownloadUnavailableError` with the source route rather than inventing a file. Other errors derive from `BoundaryError`; an existing output raises `FileExistsError`. A current successful download does not make its geography vintage a legal effective date. Retain the publisher's licence and attribution with downstream use.

An end-to-end [Greater Manchester example](examples/README.md) searches for and
downloads 2021 OA population-weighted centroids and the 2021 combined-authority
boundary, then writes a GeoPackage containing the centroids within that boundary.
It uses optional GeoPandas dependencies in a separate Conda environment.

## Python development

The Python conventions follow [caf.toolkit](https://github.com/Transport-for-the-North/caf.toolkit/blob/main/pyproject.toml) and [cookiecutter-caf](https://github.com/Transport-for-the-North/cookiecutter-caf): Ruff at 95 columns, NumPy-style production docstrings, explicit function annotations, strict mypy and Pylint. The `src/uk_boundaries` package has independent data-location semantics: local snapshots are explicit paths and the default remote source is the published catalogue. The existing `ingest.py` and `refresh.py` maintenance commands retain their repository-relative inputs/outputs.

Create the project-local Conda environment, install Conda dependencies first, then install the package with pip inside it:

```bat
conda env create --prefix .\.conda --file environment.yml
conda activate .\.conda
python -m pip install --no-build-isolation --no-deps -e .
```

`environment.yml` provides Python and the development tools from conda-forge. Its Ruff package provides the `ruff` executable. `requirements_dev.txt` supplies the matching tool versions for the isolated GitHub runners. Run checks from the repository root:

```bat
ruff format .
ruff check .
python -m mypy
python -m pylint catalogue_config.py metadata_types.py dataset_metadata.py ingest.py refresh.py refresh_notify.py src/uk_boundaries
python -m unittest discover -s tests
node --test tests/catalogue.test.mjs
node --check dist/app.js
python -m build --no-isolation --outdir work\package-dist
```

Ruff checks Python source/tests; mypy and Pylint check the maintenance modules and API. Test scenario names and prescribed unittest hooks are exempt from production docstring/annotation naming rules. Publisher JSON values remain extensible while function and HTTP contracts are typed. CI installs the package as a wheel and checks Python **3.10 and 3.12**; website deployment requires quality and regression tests to pass. The refresh workflow checks code quality before contacting publishers, then tests the candidate.

The API's offline regression tests cover selection, actual nonzero layer IDs, public download flags, native GeoPackage/shapefile output, format fallback, queued responses, safe extraction and preservation of existing outputs. The maintenance CLI tests cover report-only runs, applying a validated candidate and preserving published files after rejection. The earlier style refactor compared all 3,077 records and 844 cached link outcomes at a fixed clock, including serialized catalogue/schema bytes. Website assets and published snapshots remain independent of the package.

## Coverage

The checked 10 October 2026 snapshot contains **3,077 source records**, from a scan of **3,291 ONS items** plus **106 curated source records**, organised into **63 reporting levels** and nine publisher routes. Counts describe source items and file variants, not geographic areas or independent boundary changes.

- England and Wales: OA, LSOA and MSOA reference vintages 2001, 2011 and 2021.
- Scotland: OA, Data Zones and Intermediate Zones for 2001, 2011 and 2022; centroids, census linkage and higher-area lookups.
- Northern Ireland: OA 2001, Small Areas/SOAs 2011, Data Zones/Super Data Zones 2021; local government, electoral, health, workplace and travel-to-work sources.
- UK administrative layers: LAD/UA/council areas/LGD, counties/upper tiers, metropolitan counties, combined authorities, wards/divisions, parishes/communities and country boundaries.
- Regions and elections: English regions, historic NUTS, ITL, Westminster and devolved constituencies/regions, including Welsh Senedd 2026 and Scottish Parliament 2026 products.
- Wider reporting geographies: NHS/ICB/CCG/health boards, built-up areas, functional urban areas, travel-to-work areas, planning, police, fire, national parks and other official reporting areas.

Not every listed reporting level has an indexed boundary product in every country/year. Empty cells remain empty. Some sources only provide a current layer or a lookup. For example, combined county authorities can occur within combined-authority products rather than a separately named layer; inspect the publisher's names/codes and specification. Scottish community councils have a lookup route but no complete historical polygon series in this index.

## Find files

Search matches titles, geography aliases, country names/abbreviations, reference vintages and formats. It never changes selected filters. OA and MSOA acronym searches stay distinct. Individual place names or GSS codes inside polygons are not indexed.

The exception is combined-authority discovery: names and codes were audited against 11 ONS snapshots from June 2016 to December 2025, and those named areas are searchable. The **Mayoral authorities** preset groups CA, CCA and GLA files; it is a discovery category, not a claim that every included authority had an elected mayor at that vintage. CCA features are identified inside shared CA bundles from audited codes. Greater London has its own official, unlabelled current boundary service. Four 2026 establishment instruments are indexed as reference documents, while their missing dated GIS polygons remain explicit.

The **Population centroids** and **Employment centroids** presets select centroid products and their weighting. The centroid filter also supports address, geometric and unspecified methods, and it is available in the coverage grid. Employment/workplace weighting is confirmed for the ONS 2011 England/Wales Workplace Zone product by the linked methodology: it weights Census workers using a median-centre algorithm, despite the publisher's population-weighted title. It is not BRES job weighting. Other source methods remain unspecified unless documented; no centroid or weighting is calculated here. There is no promise of a weighted centroid at every level/year.

Filters include reporting level, country covered, reference year, product, publisher, boundary detail, reporting group, format, delivery and lookup method. A UK-wide file is included when selecting any constituent nation. Pre-2010 products are opt-in support vintages, with a separate “Pre-2010 only” option.

**Boundary detail** is available in both tabs, with code-first labels for BFC, BFE, BGC, BSC, BUC and the indexed BGG/BGE/BUE products. Options follow the actual indexed variants; unspecified or publisher-specific details remain explicit. BGE is deliberately left to the source specification because the historical products use differing grid descriptions. A selected detail is carried from a coverage cell into file search and retained in exports. Boundary-only controls clear when switching to another product.

Coverage shows only reporting rows with at least one indexed file in the displayed vintages, including “Earlier” and “Not labelled”. Entirely empty rows are retained in a closed **Not found** section, with the selected-filter context. On mobile, reporting-level cards show only available vintage/count buttons; desktop retains the annual grid. The complete selected reporting inventory, including empty rows, remains in the coverage CSV.

Exports contain the complete filtered result set:

- Catalogue CSV: source provenance, referenced years, formats, download/service links and method notes. Formula-like cells are neutralised for spreadsheet use.
- Manifest JSON: schema version, current filters, taxonomy, publishers and source records for consumption by a spatial package.
- Coverage CSV: country, level, year, product, boundary variant, centroid weighting and indexed-record count for the selected coverage view, including “Not found” rows.

GIS downloads come from the original publisher. No national polygon datasets are checked into this repository. The shipped `dist/catalogue.json` is necessary metadata for the static application; `source_records.json` is the audited national-source registry used to rebuild it.

Every result has a **download availability tag**. Direct file links and publisher-confirmed Hub downloads are distinct; an ArcGIS service or an export capability alone does not confirm a publisher download. Delivery filters select either route or all downloadable records. Tags are a metadata snapshot, not a guarantee that every remote file has been tested. The publisher supplies licences, formats and any generated download files.

**Attributes** opens a schema panel where captured: field names, aliases, types, lengths, nullability, layer name, geometry type, CRS and publisher record count. These are publisher **layer** schemas; a downloaded format may omit or truncate fields. `dist/dataset-metadata.json` contains this metadata, loads only when opening attributes or exporting, and contains no feature records or polygons. CSV and JSON exports include the full schemas, availability and date provenance. A failed schema fetch offers a retry instead of silently omitting fields from an export.

The enrichment snapshot captured **2,275 layers across 2,274 source records**, rechecked on **10 October 2026 (UTC)**, including every indexed ONS feature service. There are **775 direct-download records**, **2,273 publisher-download records**, and **29 records with unconfirmed download availability**. Unconfirmed includes source directories, legislation and services for which publisher downloads were not exposed. Direct CSV/Excel/ZIP files and non-ArcGIS/WFS sources do not automatically have captured schemas. Five OSNI services denied anonymous metadata access; their existing discovery routes remain visible. The ONS inventory was rescanned on 10 October.

## Refresh and audit

**The live catalogue does not automatically update each week.** Weekly automation
checks sources and prepares a tested candidate; publishing requires a reviewed
metadata commit to `main`. Static hosting supports automatic deployment of that
commit, but the refresh workflow does not commit its candidate.

The **Check and refresh catalogue** workflow runs weekly (Monday, 04:23 UTC), and can also be started from **Actions → Check and refresh catalogue → Run workflow**. It refreshes ONS discovery and ArcGIS schemas, checks curated landing pages/WFS routes and direct file links, runs regression tests, and saves a **catalogue-refresh-report** artifact plus a run summary. It then **opens a GitHub issue mentioning `@hulsiejames`**, with the candidate's download link, change counts and publishing instructions. The published site changes after a reviewed metadata commit reaches `main`.

The notification runs in a separate job even when the refresh fails. Only a
successful refresh, passing candidate tests, a checked report with no validation
errors and a saved artifact produce a “ready for review” notice. Failures produce
an issue linking to diagnostic logs instead. There is one issue per scheduled or
manual workflow run; reruns update the same issue, including closed issues, without
reopening it. The bot does not close issues automatically: close a ready notice
after publishing and checking the update.

The refresh job remains read-only. Only the notification job receives
`issues: write`; neither job receives repository-write or PR permissions.
It uses the built-in `GITHUB_TOKEN`, so no personal token or PR-creation setting
is needed. [GitHub documents issue creation with this token](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token).
GitHub delivers mention notifications according to your account's notification
settings. Issue contents explicitly distinguish a prepared candidate from a
published update. Artifacts expire after 30 days; rerun the workflow for a fresh
candidate if the linked artifact has expired.

On 19 October 2026, the scheduled run completed its refresh, validation and artifact upload, then failed because GitHub Actions could not create PRs. Automatic PR creation has been removed and issue notifications replace it. [Issue #10](https://github.com/hulsiejames/uk-boundaries/issues/10) mentions the maintainer and links to that run's tested candidate, which expires on 18 November 2026. No personal token or repository setting change is required for future notifications.

To apply a saved candidate manually, download and extract its artifact, inspect `summary.md` and confirm `refresh-status.json` has `status: "checked"` and no validation errors. Copy only `catalogue.json`, `dataset-metadata.json` and `refresh-status.json` into `dist/`, run the Python/Node checks, and review/commit those three files through the normal Git workflow. Rejected or failed captures can still have diagnostic artifacts; do not publish those candidates. The same refresh/review can be run from a local checkout. In public repositories, GitHub can disable schedules after 60 days of inactivity; the manual run route and 14-day published-snapshot warning remain available.

The same operation is available locally:

```bat
REM Save a candidate and report; dist is untouched.
python refresh.py
REM Stage a validated candidate in dist, then review and commit it.
python refresh.py --apply
```

The checker uses HEAD requests, with a bounded range GET fallback; it never saves GIS file contents. It distinguishes missing (404/410), restricted (401/403), and inconclusive checks (timeouts, rate limiting or server failures). HTTP 200 does not certify usable data or licence rights, and SPA landing-page responses do not prove a dataset exists. ONS existence is checked against the current publisher item search. Redirect destinations are reported, with temporary query tokens removed, rather than silently replacing historical URLs.

Historical ONS records absent from a fresh scan are retained and flagged. Widespread new disappearance or metadata failures reject the candidate, preserving the published version. The published `dist/refresh-status.json` contains per-link results and the change report; result cards flag issues, and the Delivery filter includes **Links needing attention**. Downloads known missing are excluded from “Downloadable”; restricted/inconclusive files remain unconfirmed. Curated non-ONS sources still need occasional human rediscovery when a publisher changes its catalogue structure, and audited authority-name/centroid-methodology overrides are not automatically recertified.

```bat
python ingest.py
python ingest.py --verify-sources
python ingest.py --ons-cache C:\data\ons-raw.json --ons-checked 2026-10-06
python ingest.py --refresh-metadata
```

The normal refresh paginates supported item types in the official ONS ArcGIS organisation `ESMARspQHYMw9BZ9`, rejects incomplete/duplicate pagination, classifies boundary/lookup/centroid/reference products, and combines them with the curated registry. Unknown country scope and unlabelled years remain unknown. Source records are formatted one per line to keep refresh diffs reviewable.

`--refresh-metadata` captures public ArcGIS service/layer definitions and the matching ArcGIS Hub dataset metadata using actual layer IDs, including tables and nonzero IDs. It never queries features, generates an export or downloads a GIS file. The checked-in cache is reused by ordinary builds. Unavailable refreshes retain the last successful snapshot with its original check date and record the failed attempt. Changing a source service invalidates the old schema association. Cached ONS builds require the original scan date so the inventory is not labelled freshly checked.

The curated registry is deliberately manual: its records were explored and checked against national publisher pages and Scottish ISO/CSW metadata. Refreshing ONS does not automatically rediscover changed Scottish, Welsh, NISRA or OSNI links. Revisit those sources, amend `source_records.json`, and update its `checked` date. `--verify-sources` checks landing-page responses without downloading GIS files; it does not prove every file or service is available. Individual curated records retain their own check date.

`catalogue_config.py` owns the taxonomy, aliases and publisher routes. `ingest.py` owns normalisation. `dist/catalogue-core.mjs` owns filtering, country matching, coverage cells and CSV escaping, shared by the browser and regression checks.

`metadata_overrides.json` retains the manually audited authority-name snapshots, CCA code classification source and the workplace-centroid methodology override. Refreshing the ONS catalogue does not refresh these audits: recheck the matching source vintage before adding or changing an override. CSV/JSON exports retain centroid weighting, weighting basis/year, algorithm/methodology and audited area names alongside the existing source metadata.

The first automated checking candidate was run on 10 October 2026. Its ONS discovery found no additions, removals or changed listing URLs relative to the 6 October inventory. All 844 distinct page/download links responded successfully. Of 2,279 ArcGIS service captures, five OSNI services denied anonymous access and GLA's Hub metadata was absent (its service schema and direct file link remain available). See `dist/refresh-status.json` for the actual link results and updated schema comparison; link availability and boundary vintage are separate facts.

See [docs/source-audit.md](docs/source-audit.md) for the explored sources, date semantics and remaining gaps.

## Date and translation semantics

**A file vintage is not a legal effective date.** A 2026 upload can describe 2011 geometry. Lookups preserve all source/target/assignment years rather than having one invented boundary year. The coverage grid measures indexed source vintages only: a gap does not indicate a change or abolition, and a tick does not certify annual legal validity.

The dates panel distinguishes **publisher publication**, **uploaded / item created**, **info updated**, and **data updated**, with a source and basis retained for each. Publisher citation publication/revision dates take precedence over service data edits. A generic item modification or schema edit is not promoted to a data update. Different dates in a multilayer service stay per layer. Missing dates remain “Not supplied”; timestamps retain their precision and supplied time zone. UTC item timestamps are labelled UTC; publisher timestamps without an offset are explicitly labelled “time zone not supplied”. Legacy `published`/`modified` fields retain their existing item-created/item-modified meanings; the additive `dates` object provides the separate, precise dates.

Census geographies can remain in use between revisions. Small-area reporting around 2010 may use a 2001 geography. An explicitly labelled 2010 local-authority polygon has not been found in this index; neither 2009 nor 2011 is silently certified as the boundary at a selected date in 2010.

Use full-resolution, consistently clipped geometry and suitable projected coordinates for overlaps. Keep source code/vintage, target code/vintage, relationship and weighting method distinct. Exact-fit aggregation, best-fit assignments, area matching and population matching are different operations. A code lookup alone does not supply population weights. This project supplies discovery and provenance; it does not calculate a translation matrix or import a certified change ledger.

## Hosting

The public website is hosted at **https://hulsiejames.github.io/uk-boundaries/** using free GitHub Pages hosting for this public repository.

`.github/workflows/pages.yml` runs the Python and Node regression suites and checks browser JavaScript syntax on pull requests and pushes to `main`. After successful checks on `main`, it publishes only `dist/` using GitHub's Pages actions. Pull requests run tests without publishing. A manual deployment can also be started from the Actions tab. Repository Settings → Pages must use **GitHub Actions** as its source. The workflow uses GitHub's built-in token; no personal deployment credentials are needed.

All application asset, module and catalogue paths are relative, so the `/uk-boundaries/` project path works without rewriting URLs. Updating the website does not rescan official sources: refresh and commit the catalogue separately when needed.

`.openai/hosting.json` retains the existing owner-private Site identity for the earlier preview. Local use and GitHub Pages do not require Sites.

Each dataset retains its publisher's own licence and attribution. There is no blanket licence for externally linked GIS data; inspect the official source before use.
