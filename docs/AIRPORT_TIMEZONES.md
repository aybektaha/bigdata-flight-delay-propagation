# Airport time zones

We now have a time-zone lookup for all 375 airport codes in our January–July 2022 file. This completes the reference-data part of our first audit milestone. It does not mean all flight timestamps or aircraft sequences have been validated.

## Files

| File | Purpose |
|---|---|
| [`reference/airport_timezones.json`](../reference/airport_timezones.json) | The lookup, coverage counts, BTS airport IDs, input fingerprint, and source details. |
| [`reference/airports_source.json`](../reference/airports_source.json) | Exact upstream URLs, commit, and SHA-256 values. |
| [`reference/airport_code_overrides.json`](../reference/airport_code_overrides.json) | One documented historical-code exception. |
| [`reference/airportsdata-LICENSE.txt`](../reference/airportsdata-LICENSE.txt) | The source data's license and attribution. |
| [`src/airport_zones.py`](../src/airport_zones.py) | Rebuilds and checks the lookup. |
| [`src/timezones.py`](../src/timezones.py) | Loads the pinned time-zone rules. |

These small reference files can be shared with the code. The full airport source CSV and flight dataset remain under the ignored `data/` directory.

## Source and coverage

We used [airportsdata](https://github.com/mborsetti/airportsdata), at commit `6adf0985697b5f5d2264ff9578158eeeded1e3d1`. The project supplies IATA codes and IANA time-zone names under the MIT license. Its data describes current airports, not a historical airport register, so we need to keep that limitation in mind when using it with 2022 flights.

The source CSV's SHA-256 is:

```text
564322214d61deea3b029588fed8f9c0068408314fcbf065ad665dfb5de53e8b
```

There were 374 direct IATA matches and one explicit override. No airport codes were left unmapped, and all resulting zone names loaded with our pinned time-zone data. The builder stops if a needed source code is missing or matches more than one source row. It does not pick a match silently.

## Why PBI needs an override

Our flight file uses `PBI`, while the pinned current source uses `DJT` for that airport. The [airport's own announcement](https://flydjt.org/articles/post/president-donald-j-trump-international-airport-name-change-takes-effect/) describes the code change in 2026.

We preserve `PBI` in the flight lookup and use the source's `DJT` row to obtain `America/New_York`. The override also requires BTS airport ID `14027`. If that ID differs in another input, the builder stops for review. We do not rename the raw flight records.

This exception was reviewed for our current 2022 file. It is not a general crosswalk for all historical airport-code changes. Matching all codes is a coverage check, not independent proof of every airport's historical identity or zone.

## Fixed time-zone rules

The requirements now include `tzdata==2025.2`, which provides IANA release `2025b`. We selected a fixed release for reproducible historical checks; this is not a claim that it is the latest release.

`load_zone()` reads zone files directly from that package and caches the loaded objects. It does not fall back to the computer's system time-zone data. The package version is checked, and the version is recorded in the lookup and time-audit reports. Any future version change should be deliberate and followed by rebuilding the lookup and rerunning the tests.

Update an existing environment with:

```bash
.venv/bin/python -m pip install -r requirements-audit.txt
```

## Use the shared lookup

Once the code and reference files are available in your checkout, you do not need to download the airport source just to run a sample:

```bash
.venv/bin/python -m src.time_audit data/raw/Combined_Flights_2022.parquet \
  --tail N364NW --date 2022-03-12 \
  --airport-map reference/airport_timezones.json \
  --output data/processed/audits/2022_dst_mapped.json
```

Use either `--airport-map` or repeated `--airport-zone` arguments. The CLI does not accept both together. The report records the lookup's hash as well as the flight file's hash.

For the March sample, the shared map gives five consistent candidates and one excluded flight. The earlier manual map covered only ATL and TYS, so four of those flights were previously unmapped. The JFK/LAX example still gives two consistent candidates under the pinned rules.

The time audit also attempts reconstruction of every row flagged by the naive departure-clock check. These results appear under `flagged_departure_checks` and use the same supplied map. With the full lookup, 21 of the 22 flagged rows produce consistent candidates; one retains an arrival-clock mismatch. A partial manual map can still leave some rows unmapped.

## Rebuild from the pinned source

To fetch the exact reference files listed in the manifest and rebuild:

```bash
.venv/bin/python -m src.airport_zones data/raw/Combined_Flights_2022.parquet --download
```

Downloads go to `data/reference/airportsdata/`. Their hashes must match before they are used. The builder writes the small lookup to `reference/airport_timezones.json` and copies the source license beside it. Rebuilding replaces those generated reference outputs.

If the source files are already present, the command can run without network access:

```bash
.venv/bin/python -m src.airport_zones data/raw/Combined_Flights_2022.parquet
```

The builder uses the codes actually found in the input, stores their BTS IDs, and records the input filename, hash, and date range. Use a different `--output` when exploring another dataset so you do not replace the reviewed lookup by mistake.

## What remains

We have a reproducible lookup and have now run [full-file timestamp preparation](FULL_DATA_TIMESTAMPS.md). The next task is to review flagged rows and define actual flight links and scheduled-buffer eligibility. The timestamp output preserves every row; it is not a final cleaned flight table or a rotation model.
