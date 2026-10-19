# Greater Manchester: 2021 OA population-weighted centroids

This example uses the installed `uk_boundaries` API to search the static catalogue,
resolve live publisher download routes, and download two official ONS datasets.
GeoPandas then selects the Greater Manchester polygon and the OA centroids strictly
within it. The website is independent of this optional spatial example.

From the repository root, in Windows `cmd.exe`:

```bat
conda env create --file examples\environment.yml
conda activate uk-boundaries-example
python -m pip install --no-build-isolation --no-deps .
python -m examples.greater_manchester --catalogue dist/catalogue.json --output-dir work\greater-manchester
```

Conda installs the spatial libraries first; pip installs this package inside that
environment. To read the latest **published** catalogue instead of the checkout,
omit `--catalogue`. This is a static snapshot, not a live government catalogue
scan. Live network access is needed for publisher downloads in either case.

The output directory must be new. Use another `--output-dir` for subsequent runs;
existing results are preserved. The workflow stages its downloads and results
together, then moves them to the destination after successful processing.

The example searches for these specific products rather than choosing the first
match across years or geography levels:

| Input | Selection | Record in the 10 October 2026 snapshot |
| --- | --- | --- |
| OA centroids | England/Wales OA, 2021 reference geography, population weighting | `ons:558170d37ab04f34845034db91a86914` — December 2021 EW PWC (V4) |
| Authority boundary | Combined authorities, 2021, BFC (full resolution, clipped) | `ons:3f826d170e224924bcf602d2d0d53b3c` — December 2021 EN BFC |

If a future snapshot has no match or multiple matching products, it stops and
lists the candidates instead of silently changing versions. Reference years
describe the geography, not an inferred population weighting year or upload date.

“MSA” is interpreted here as the Greater Manchester **combined authority**, GSS
code `E47000001`, which [ONS identifies as a combined authority](https://www.ons.gov.uk/explore-local-statistics/areas/E47000001-greater-manchester).
It selects that exact code from the national authority file using its `CAUTHxxCD`
field. It does not use the City of Manchester district or a built-up/functional
urban area. Both selected products describe December 2021 geography.

The downloader prefers native GeoPackage and falls back to publisher shapefile.
The example reads either format and writes its own GeoPackage output. The original
download format and any failed preferred-format attempt remain in the download
manifest. No national spatial data is committed to this repository.

The spatial step checks OA IDs, geometry and declared coordinate systems, then
reprojects the selected authority into the centroid CRS. It preserves centroid
attributes and coordinates. The spatial index evaluates polygon `contains(point)`,
equivalent to point [`within(polygon)`](https://geopandas.org/en/stable/docs/reference/api/geopandas.GeoSeries.within.html).
Points exactly on the polygon boundary are excluded and counted in the report.
This assigns centroid locations; it is not an OA polygon overlap, population
allocation or an official OA-to-authority lookup.

The output uses a separate [GeoPackage primary-key field](https://gdal.org/en/stable/drivers/vector/gpkg.html#layer-creation-options),
so a source attribute named `FID` is retained as a regular attribute.

Outputs under the chosen directory:

- `greater_manchester_oa2021.gpkg`: `oa2021_pwc` points and
  `greater_manchester_boundary` polygon layers, both in the source centroid CRS.
- `processing-report.json`: source record IDs, catalogue check date, reference
  years, actual download formats, processing time, CRS and feature counts.
- `downloads/`: original publisher files and the API's download manifests, with
  source URLs, download timestamps and SHA-256 payload hashes.

Read the result from another process:

```python
import geopandas as gpd

points = gpd.read_file(
    "work/greater-manchester/greater_manchester_oa2021.gpkg", layer="oa2021_pwc"
)
print(points[["OA21CD", "geometry"]])
```

Run the example's offline spatial and mocked-download regression tests in this
environment using `python -m unittest discover -s tests -p test_example.py`.
For development checks, also run `python -m mypy examples` and
`python -m pylint examples` after installing the project's development tools.
CI runs those tests with the optional spatial dependencies; it does not download
national datasets on every pull request. Retain ONS attribution and inspect the
licence on each [centroid](https://geoportal.statistics.gov.uk/datasets/558170d37ab04f34845034db91a86914/about)
and [boundary](https://geoportal.statistics.gov.uk/datasets/3f826d170e224924bcf602d2d0d53b3c/about)
source page before reusing the data.

A live run on 19 October 2026 downloaded the centroid shapefile and boundary
GeoPackage through the API. It selected **8,966 of 188,880** OA centroids, with
**zero** points exactly on the boundary, and wrote both output layers in
**EPSG:27700**. The saved points were independently checked against a direct
`within` filter of the downloaded source, including their source attributes and
geometry. These are results for the named source versions, not fixed expected
counts for future publisher revisions.
