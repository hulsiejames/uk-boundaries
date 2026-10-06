# UK Boundary Atlas

A static, metadata-only explorer for official UK geography files and source-vintage coverage since 2010. The interface has two working surfaces: **Find files** and **Coverage & sources**.

England is the first-version priority, with Wales next. File search and the coverage grid open on England; Wales has a quick preset. Scottish and Northern Irish sources remain available through country filters and optional census presets, with their separate reporting systems preserved.

The original map-comparison prototype is preserved on `main` in the initial import. The expansion removes map comparison, polygon querying and the saved Kirklees polygons.

## Run locally

Python 3.10+ and Node 22+ are sufficient; there are no third-party dependencies.

```sh
python -m http.server 8765 --directory dist
```

Open `http://localhost:8765`. Serve the files over HTTP rather than opening `index.html` directly.

```sh
python -m unittest discover -s tests
node --test tests/catalogue.test.mjs
node --check dist/app.js
```

## Coverage

The checked 6 October 2026 snapshot contains **3,077 source records**, from a scan of **3,291 ONS items** plus **106 curated source records**, organised into **63 reporting levels** and nine publisher routes. Counts describe source items and file variants, not geographic areas or independent boundary changes.

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

## Refresh and audit

```sh
python ingest.py
python ingest.py --verify-sources
python ingest.py --ons-cache /path/to/ons-raw.json
```

The normal refresh paginates supported item types in the official ONS ArcGIS organisation `ESMARspQHYMw9BZ9`, rejects incomplete/duplicate pagination, classifies boundary/lookup/centroid/reference products, and combines them with the curated registry. Unknown country scope and unlabelled years remain unknown. Source records are formatted one per line to keep refresh diffs reviewable.

The curated registry is deliberately manual: its records were explored and checked against national publisher pages and Scottish ISO/CSW metadata. Refreshing ONS does not automatically rediscover changed Scottish, Welsh, NISRA or OSNI links. Revisit those sources, amend `source_records.json`, and update its `checked` date. `--verify-sources` checks landing-page responses without downloading GIS files; it does not prove every file or service is available. Individual curated records retain their own check date.

`catalogue_config.py` owns the taxonomy, aliases and publisher routes. `ingest.py` owns normalisation. `dist/catalogue-core.mjs` owns filtering, country matching, coverage cells and CSV escaping, shared by the browser and regression checks.

`metadata_overrides.json` retains the manually audited authority-name snapshots, CCA code classification source and the workplace-centroid methodology override. Refreshing the ONS catalogue does not refresh these audits: recheck the matching source vintage before adding or changing an override. CSV/JSON exports retain centroid weighting, weighting basis/year, algorithm/methodology and audited area names alongside the existing source metadata.

See [docs/source-audit.md](docs/source-audit.md) for the explored sources, date semantics and remaining gaps.

## Date and translation semantics

**A file vintage is not a legal effective date.** A 2026 upload can describe 2011 geometry. Lookups preserve all source/target/assignment years rather than having one invented boundary year. The coverage grid measures indexed source vintages only: a gap does not indicate a change or abolition, and a tick does not certify annual legal validity.

Census geographies can remain in use between revisions. Small-area reporting around 2010 may use a 2001 geography. An explicitly labelled 2010 local-authority polygon has not been found in this index; neither 2009 nor 2011 is silently certified as the boundary at a selected date in 2010.

Use full-resolution, consistently clipped geometry and suitable projected coordinates for overlaps. Keep source code/vintage, target code/vintage, relationship and weighting method distinct. Exact-fit aggregation, best-fit assignments, area matching and population matching are different operations. A code lookup alone does not supply population weights. This project supplies discovery and provenance; it does not calculate a translation matrix or import a certified change ledger.

## Hosting

`.openai/hosting.json` identifies the existing owner-private Site and its `dist` static directory. Local use and GitHub do not require Sites. Publishing uses the same Site identity and preserves its audience.

Each dataset retains its publisher's own licence and attribution. There is no blanket licence for externally linked GIS data; inspect the official source before use.
