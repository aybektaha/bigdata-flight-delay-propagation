# Flight Delay Propagation and Turnaround Buffers

YZV411E Big Data Analytics project by Aybek Taha Atılgan, Osmancan Sarı, and Yavuz Burak Yalçın.

We are studying how delays relate across consecutive flights operated by the same aircraft. We also plan to compare Spark with single-machine tools and test how different scheduled ground times relate to downstream delays. The [project proposal](proposal/proposal.pdf) describes the research plan.

## Current stage

The current milestone covers data auditing, airport time-zone references, and timestamp preparation for the full local 2022 file. The code uses DuckDB and PyArrow. It keeps every source row and marks failed checks. It does not yet contain a Spark pipeline or a validated flight-linking model.

We have checked one local Parquet file: **4,078,318 flights from January 1 to July 31, 2022**. Its size is about 142.7 MiB. The proposal's roughly 31.7 million flights and 9.8 GB refer to the intended multi-year scope, not data already processed by this repository.

## Start here

Put `Combined_Flights_2022.parquet` in `data/raw/`. The dataset referenced by the proposal is [Flight Delay Dataset 2018–2022](https://www.kaggle.com/datasets/robikscube/flight-delay-dataset-20182022). Compare your file's hash with the one in the audit notes before comparing results.

From the repository root, create an environment if needed and install the packages:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-audit.txt
```

The audit was tested with Python 3.9.6. On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe`.

Run the detailed data check:

```bash
.venv/bin/python -m src.quality data/raw/Combined_Flights_2022.parquet --output data/processed/audits/2022_quality.json
```

Run a timestamp sample using the shared airport lookup:

```bash
.venv/bin/python -m src.time_audit data/raw/Combined_Flights_2022.parquet --tail N102NN --date 2022-01-04 --airport-map reference/airport_timezones.json --output data/processed/audits/2022_time_sample.json
```

Run the tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

For full-file preparation and output validation, follow [the full-data instructions](docs/FULL_DATA_TIMESTAMPS.md). That run produced 3,944,622 consistent timestamp candidates, 133,402 excluded flights, and 294 flagged records, with all source rows preserved.

The scripts read the raw file and write separate reports. They do not change or remove flight records. Running again with the same output name replaces that report. Raw data and generated reports under `data/` stay outside Git.

## Notes for the team

- [First data checks](docs/DATA_AUDIT.md): setup, audit code, results, and limitations.
- [Checking flight timestamps](docs/TIME_MODEL.md): UTC reconstruction, DST cases, and sample results.
- [Airport time zones](docs/AIRPORT_TIMEZONES.md): the 375-code lookup, source version, historical-code override, and rebuild commands.
- [Full-file timestamp preparation](docs/FULL_DATA_TIMESTAMPS.md): batch processing, output fields, result counts, validation, and the handoff to flight linking.

## What we have learned

There are no exact duplicates across the 61 data fields in the checked file. However, 429 groups share the same tail, date, and scheduled departure clock. Those groups contain different flights, so we do not remove them as duplicates.

Local clock values cannot be used directly as a global flight order. We now check candidate UTC timestamps against reported clocks and elapsed times. The airport lookup covers all 375 codes in this file, with one documented historical-code override. Time-zone rules are pinned to `tzdata==2025.2`.

An actual flight sequence can have overlapping scheduled times. Our JFK–LAX–JFK example has a 46-minute actual ground interval but a negative scheduled interval. Actual links and feasible scheduled turnaround pairs therefore need separate rules.

For a valid linked pair, we plan to examine:

```text
scheduled ground time = next scheduled departure UTC - previous scheduled arrival UTC
actual ground time    = next actual departure UTC - previous actual arrival UTC
delay change          = next DepDelay - previous ArrDelay
```

Timestamp differences must be converted to minutes; subtracting raw HHMM numbers does not give a duration. Scheduled ground time is also not automatically spare buffer above the minimum time needed to turn an aircraft around. Delay changes alone do not establish a causal effect.

The checked schema has no `PrimaryDelay` or `LateAircraftDelay` column. We cannot currently calculate a primary-delay multiplier directly from these fields. Spark speed or memory advantages also remain to be measured.

## Roadmap

- [x] Project proposal
- [x] Reproducible audit of the local 2022 file
- [x] Duplicate, clock-format, and duration checks
- [x] Sourced airport lookup with complete code coverage for this file
- [x] Pinned time-zone rules and tested sample timestamp reconstruction
- [x] Full-file timestamp reconstruction with status counts and preserved source rows
- [ ] Review flagged records and define their treatment in flight linking
- [ ] Actual flight linking and scheduled-turnaround eligibility rules
- [ ] Remaining years, source/license checks, and schema consistency
- [ ] Spark processing and partitioned Parquet outputs
- [ ] Controlled single-machine versus Spark benchmarks
- [ ] Buffer analysis, scenarios, visualizations, and final report

The airport lookup is derived from airportsdata; its [license and attribution](reference/airportsdata-LICENSE.txt) are included. It is a current reference with an explicit historical-code exception, not a complete historical airport register.
