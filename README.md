# UK Boundary Atlas

First working version, researched and catalogued on 6 October 2026.

## Purpose

Find the correct official UK geography product without knowing the publisher's naming conventions. Compare available boundary vintages and download polygons for use in another spatial analysis package. The historical target is 2010 onwards.

## What this version does

- Searches 664 official ONS records by reporting level, boundary/reference vintage, country coverage, product and boundary detail.
- Covers local authorities (including their different official types), counties/upper tiers, combined authorities, metropolitan counties, English regions, UK ITL/NUTS regions, countries, wards, Westminster constituencies and England/Wales OA, LSOA and MSOA products, plus code history/register releases and selected official change lookups.
- Provides a clickable 2010–2026 matrix of indexed boundary vintages at every principal reporting level. The grid does not infer legal validity or abolition from snapshot availability.
- Queries official polygon services for a place name or a nine-character GSS code in two selected source releases.
- Overlays those polygons with pan, zoom and adjustable visibility, and lists matched names/codes.
- Exports the matched polygons as GeoJSON in EPSG:4326, preserving source attributes, source item identifiers, boundary vintage, detail, retrieval date, licence and attribution in a `boundaryAtlas` metadata member.
- Links whole-dataset downloads and original archives where those are indexed. Exports filtered catalogue rows as CSV.
- Includes source-linked Kirklees examples for December 2011 and May 2026, both BGC. These are map products, not the full-resolution analysis files.

The catalogue is a checked snapshot. Re-running `ingest.py` refreshes it. There is no automatic scheduled refresh. The required project scope is parity across all reporting levels and all UK nations since 2010; census and administrative families need their own release schedules and validity evidence.

## Explicit limits

This is a file finder and polygon comparison prototype, not yet a complete change-history engine. It does not certify legal boundaries for every intervening date, derive predecessor/successor relationships, calculate overlap weights or provide GeoPackage conversion.

The indexed local-authority collection has 2009 and 2011 products but no explicitly labelled 2010 product. Neither adjacent vintage is automatically certified as valid at a chosen 2010 date. For 2010 small-area statistics, 2001 census geography may be relevant; the statistical reference year and boundary vintage are different fields.

Scottish and Northern Irish census geography sources are linked but not yet indexed. UK/GB administrative layers include those countries only where the source explicitly provides coverage. England/Wales MSOAs are not a universal UK geography. Scotland uses Data Zones and Intermediate Zones; Northern Ireland's new 2021 Data Zones and Super Data Zones differ from its 2011 Small Areas and Super Output Areas.

Availability varies by year, geography, country and detail. Empty results mean no match in this inventory, not that no such official product exists anywhere. Live comparisons depend on ONS ArcGIS service availability. Searches with at least 100 matches are rejected so a truncated export is not presented as complete.

## Run locally

From this directory, with Python 3 installed:

```text
python -m http.server 8765 --bind 127.0.0.1 --directory dist
```

Open `http://127.0.0.1:8765/`. No package installation is required. Do not open `index.html` directly as a file: the browser needs HTTP to load the catalogue and examples.

Refresh official metadata and then the example polygons:

```text
python ingest.py
python cache_example.py
```

The ingestion script currently caps the inventory at 2026 and records a checked date of 6 October 2026. Update those values when conducting a later refresh. Publication and modification dates are deliberately not treated as legal effective dates.

## Recommended next development

1. Audit and reconstruct the 2010 baseline from official releases and effective-date evidence. Mark inferred or unverified coverage explicitly.
2. Import ONS Code History Database CSV tables, including listings, equivalents and change history. Support legacy pre-2011 identifiers so recoding is not mistaken for a polygon change.
3. Ingest Scottish and Northern Irish census vintages and their official lookups. Preserve nation-specific geography names and census dates.
4. Create event records for rename, recode, merger, split, partial transfer, administrative reorganisation and cartographic revision. Each record needs evidence and an effective date or an explicitly unknown date.
5. Add an area timeline, predecessor/successor navigation, and matched-precision map comparison, with a clear distinction between observed polygon difference and officially documented boundary change.
6. Add full-resolution GeoPackage exports and a stable machine-readable download API.

## Data model for a reliable history

| Record | Essential fields |
| --- | --- |
| Geography type | Nation, family, official type, aliases, reporting tier |
| Area version | Code system, code, name, official type, valid-from, valid-to, evidence |
| Boundary release | Publisher, item ID, boundary vintage, publication date, retrieval date, coverage, precision, coastal treatment, CRS, licence |
| Geometry version | Area version, release, geometry hash, file hash, storage location |
| Change event | Event kind, effective date, predecessors, successors, evidence, confidence |
| Crosswalk | Source code/vintage, target code/vintage, relationship, method, weight, denominator, evidence |

Use explicit validity intervals. Do not infer a legal change solely from a difference between two downloaded geometries. Generalisation, coastal clipping and changes in cartographic detail can create apparent differences.

## Translation requirements

Export the boundaries and lookups needed by the user's own package. Do not silently impose one weighting method.

- **Exact aggregation:** use where source areas wholly compose a target area.
- **Best fit:** assigns a source to one target; may lose information where boundaries cross.
- **Area overlap:** weights by intersecting area; does not imply population is evenly distributed.
- **Population or address weighting:** requires a stated weighting dataset, date and denominator.

For areal weights, calculate intersections in an appropriate projected CRS and distinguish land/coastal treatment. Preserve missing coverage and zero-area cases. Explain split and many-to-many relationships. Rates and percentages require numerator/denominator handling; weights cannot generally be applied to a rate as if it were a count.

## Kirklees example

Kirklees is an extant metropolitan district in West Yorkshire, GSS code E08000034. Its metropolitan council is single-tier; its geography classification is separate from the E06 unitary-authority class. It is within West Yorkshire metropolitan county and is a constituent council of West Yorkshire Combined Authority, founded in 2014. “Metropolitan area” needs an explicit definition: administrative metropolitan districts/counties, combined authorities and functional urban/metropolitan areas are distinct. Kirklees contains multiple MSOAs, a separate census reporting level. The two example snapshots share its GSS code, which alone does not certify unchanged geometry or uninterrupted legal validity.

## Primary sources

- [ONS Kirklees profile](https://www.ons.gov.uk/explore-local-statistics/areas/E08000034-kirklees)
- [ONS administrative geography: England](https://www.ons.gov.uk/methodology/geography/ukgeographies/administrativegeography/england)
- [ONS Code History Database](https://www.ons.gov.uk/methodology/geography/geographicalproducts/namescodesandlookups/codehistorydatabasechd)
- [ONS geography products and boundary detail](https://onsgeo.github.io/geospatial-training/docs/practical_geog_and_stats)
- [Scottish small-area statistics, boundaries and lookups](https://www.gov.scot/collections/small-area-statistics/)
- [NISRA geography](https://www.nisra.gov.uk/support/geography)
- [NISRA Census 2021 geography questions](https://datavis.nisra.gov.uk/census/census-2021-frequently-asked-questions.html)

Each catalogue row carries its own official source URL and publisher item ID. Retain the licence and attribution from each source. This prototype does not change the original data licence.
