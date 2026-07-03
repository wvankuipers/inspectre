# Inspectre Performance Test

Ramps concurrent image uploads at `POST /tests` until the error threshold is hit.

## Prerequisites

- Python 3.12+
- A running Inspectre stack (`make up` from the repo root)

## Install dependencies

```bash
pip install -r perf/requirements.txt
```

## Run

```bash
# Against local dev stack (default)
python perf/run_perf.py

# Against staging
python perf/run_perf.py --url https://inspectre.example.com

# Custom ramp
python perf/run_perf.py --max-workers 128 --duration 15 --error-threshold 0.05
```

Or via Make:

```bash
make perf
make perf ARGS="--url https://inspectre.example.com --max-workers 32"
```

## Options

| Flag                | Default                 | Description                                  |
| ------------------- | ----------------------- | -------------------------------------------- |
| `--url`             | `http://localhost:8000` | Base URL of the target server                |
| `--max-workers`     | `64`                    | Highest concurrency level                    |
| `--duration`        | `10`                    | Seconds to hold each concurrency level       |
| `--error-threshold` | `0.10`                  | Error rate fraction that triggers early stop |

## Output

```text
Workers │ Req/s  │ p50ms │ p95ms │ p99ms │ Errors
────────┼────────┼───────┼───────┼───────┼───────
      1 │   3.2  │   310 │   420 │   510 │  0.0%
      2 │   6.1  │   325 │   450 │   540 │  0.0%
      4 │  11.4  │   350 │   520 │   630 │  0.0%
     16 │  18.2  │   870 │  2100 │  3400 │ 14.3%  ← STOPPED

Breaking point: 8 workers (last stable level)
```

Exit code 0 if all levels pass, 1 if the error threshold was exceeded.

## Cleanup

Test data is left in the database. Run `make seed` from the repo root to wipe it.
