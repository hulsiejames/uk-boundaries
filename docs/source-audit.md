# UK source exploration and audit

Checked: 6 October 2026. This documents the expansion's sources and limits. Source IDs, URLs, vintages and delivery formats are retained in `source_records.json` and the shipped catalogue.

| Publisher | Exploration and indexed products | Date treatment |
|---|---|---|
| [ONS Open Geography](https://geoportal.statistics.gov.uk/) | All supported metadata item types in official organisation `ESMARspQHYMw9BZ9`; boundaries, lookups, centroids, names/codes and directories. The original narrow family-prefix search was replaced. | Title-labelled years; upload/update timestamps stay separate. Lookups retain every referenced year. |
| [Scottish Government small-area statistics](https://www.gov.scot/collections/small-area-statistics/) / [SpatialData](https://spatialdata.gov.scot/) | ISO/CSW records and distribution links for 2001/2011/2022 Data Zones and Intermediate Zones; centroids; area/population matching workbook; 2022 higher-geography lookup; health board and integration authority files. | 2001/2011/2022 are census vintages. Scottish health files use the publisher's 2019 filename edition, explicitly distinguished from legal commencement. |
| [NRS geography products](https://www.nrscotland.gov.uk/statistics-and-data/geography-products/) / [2022 census products](https://www.nrscotland.gov.uk/publications/2022-census-geography-products/) | OA 2001/2011 via official Scottish services and archive metadata; 2022 full/coast-clipped/part-removed shapefiles; centroids; settlements/localities/islands; OA linkage 2011–2022; OA to DZ/IZ, ITL, Westminster, Scottish Parliament and community council lookups. | 2022 census areas remain labelled 2022 even if first released later. Pre-operative Scottish Parliament 2025 lookups are explicitly labelled pre-operative. |
| [NISRA geography](https://www.nisra.gov.uk/support/geography) | OA 2001; Small Areas/SOAs 2011; DZ/SDZ 2021; direct Shapefile/GeoJSON/Geodatabase/MapInfo routes where supplied; ODS/Excel administrative lookup tables; workplace, settlement and TTWA files. | Distinct 2011 and 2021 systems. Publisher scheme labels and publication dates are not interchanged. |
| [OSNI / SpatialNI](https://osni-spatialni.hub.arcgis.com/) | Official publisher identified through NISRA's linked boundary application; selected LGD and DEA legacy/current-scheme services and HSC Trust source metadata. | 1993/2012 are source scheme labels, not legal commencement dates. Service access can vary. |
| [DataMapWales](https://datamap.gov.wales/) | Welsh communities, Senedd 2026 constituencies, pre/post April 2019 LHB definitions and WFS routes. | Community layer copyright/update dates are not promoted to historical vintages. Pre-April 2019 is an interval description with no invented start year. |
| [OS Boundary-Line](https://osdatahub.os.uk/downloads/open/BoundaryLine) | Current GB administrative/electoral download route, including GeoPackage. | Kept as an unlabelled reference route, not a fabricated annual archive. |

The Scottish government page directly links the 2022 DZ/IZ metadata. CSW distribution records also expose the older editions and official NRS WFS services. Archived NRS pages are useful context, but public file/service routes are preferable where available. Frozen postcode polygon products with PSGA restrictions were excluded from public-download indexing.

The new ONS alpha catalogue was inspected for combined authorities. Its own licence note recommends the established portal until March 2027. An undated “Latest Combined Authority” service was therefore not used to backfill any historical year. The broad established-portal scan remains the automated inventory source.

## What the expansion does not certify

- Exhaustive annual legal boundary histories, every local electoral order, every geometry revision or every bespoke local reporting area.
- That absence from a source index means abolition, or that a census vintage remained valid for every later reporting date.
- Complete separate polygon series for CCAs, Scottish community councils or NI Assembly areas. Some official files/lookup routes cover these through shared or higher geographies. The relevant gaps remain visible.
- Census-to-census area/population weights across all systems. Indexed NRS linkage and Scottish matching products retain their publisher definitions; no weights are invented.
- That title-only ONS classification resolves the legal type of every constituent feature. LAD files intentionally group districts, UAs, metropolitan districts, London boroughs, Welsh authorities, council areas and LGDs.
- Automatic re-discovery of the curated non-ONS pages, or successful access to every linked GIS file. The landing-page audit is separate from file/service availability.

## Verification

Regression checks cover upload-date/vintage separation, mixed-year lookups, unknown country scope, regional classification, national census baselines, acronym search, country containment, pre-2010 opt-in, CSV escaping and coverage-cell drill-down equality. Browser checks exercise representative filters and grid navigation. The source audit checks curated landing pages and representative download headers without mirroring polygons.
