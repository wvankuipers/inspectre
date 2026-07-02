#!/usr/bin/env python3
"""Inspectre performance test — ramps concurrent POST /tests uploads."""

import argparse
import asyncio
import io
import os
import sys
import time
from dataclasses import dataclass, replace

import httpx
from PIL import Image


def make_unique_image() -> bytes:
    """Return a unique 400x300 PNG with random RGB noise."""
    data = os.urandom(400 * 300 * 3)
    img = Image.frombytes("RGB", (400, 300), data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Inspectre performance test")
    p.add_argument("--url", default="http://localhost:8000", help="Base URL of target server")
    p.add_argument("--max-workers", type=int, default=1024, help="Highest concurrency level")
    p.add_argument("--duration", type=float, default=10.0, help="Seconds per concurrency level")
    p.add_argument("--error-threshold", type=float, default=0.10, help="Error rate that triggers early stop")
    return p.parse_args()


@dataclass
class RequestResult:
    latency_ms: float
    success: bool


async def create_run(client: httpx.AsyncClient, base_url: str) -> int:
    """POST /runs and return the run id."""
    resp = await client.post(
        f"{base_url}/runs",
        data={"project": "perf-test", "suite": "load"},
    )
    resp.raise_for_status()
    try:
        return resp.json()["id"]
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"Unexpected /runs response: {resp.text[:200]}") from exc


async def upload_worker(
    client: httpx.AsyncClient,
    base_url: str,
    run_id: int,
    deadline: float,
    results: list[RequestResult],
    worker_id: int,
) -> None:
    """Loop posting unique images until deadline, appending to results."""
    test_index = 0
    while time.monotonic() < deadline:
        image_bytes = make_unique_image()
        test_name = f"perf-{worker_id}-{test_index}"
        test_index += 1
        start = time.monotonic()
        try:
            resp = await client.post(
                f"{base_url}/tests",
                data={
                    "run_id": run_id,
                    "name": test_name,
                    "browser": "chrome",
                    "size": "1280x800",
                },
                files={"screenshot": ("screenshot.png", image_bytes, "image/png")},
                timeout=60.0,
            )
            success = resp.is_success
        except httpx.HTTPError:
            success = False
        except Exception:  # noqa: BLE001
            success = False
        elapsed_ms = (time.monotonic() - start) * 1000
        results.append(RequestResult(latency_ms=elapsed_ms, success=success))


@dataclass
class LevelResult:
    workers: int
    req_per_s: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate: float
    stopped: bool = False


async def run_level(
    base_url: str,
    run_id: int,
    workers: int,
    duration: float,
) -> LevelResult:
    """Run one concurrency level; return aggregated metrics."""
    results: list[RequestResult] = []
    deadline = time.monotonic() + duration

    async with httpx.AsyncClient() as client:
        tasks = [
            asyncio.create_task(
                upload_worker(client, base_url, run_id, deadline, results, worker_id=i)
            )
            for i in range(workers)
        ]
        await asyncio.gather(*tasks)

    if not results:
        return LevelResult(workers=workers, req_per_s=0, p50_ms=0, p95_ms=0, p99_ms=0, error_rate=1.0)

    latencies = sorted(r.latency_ms for r in results)
    errors = sum(1 for r in results if not r.success)

    def percentile(data: list[float], pct: float) -> float:
        idx = int(len(data) * pct / 100)
        return data[min(idx, len(data) - 1)]

    return LevelResult(
        workers=workers,
        req_per_s=len(results) / duration,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        error_rate=errors / len(results),
    )


def print_header() -> None:
    print(f"{'Workers':>7} │ {'Req/s':>6} │ {'p50ms':>5} │ {'p95ms':>5} │ {'p99ms':>5} │ {'Errors':>6}")
    print("─" * 8 + "┼" + "─" * 8 + "┼" + "─" * 7 + "┼" + "─" * 7 + "┼" + "─" * 7 + "┼" + "─" * 8)


def print_row(r: LevelResult) -> None:
    flag = "  ← STOPPED" if r.stopped else ""
    print(
        f"{r.workers:>7} │ {r.req_per_s:>6.1f} │ {r.p50_ms:>5.0f} │"
        f" {r.p95_ms:>5.0f} │ {r.p99_ms:>5.0f} │ {r.error_rate:>5.1%}{flag}"
    )


async def main() -> int:
    args = parse_args()
    concurrency_levels = [w for w in [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024] if w <= args.max_workers]
    if not concurrency_levels or concurrency_levels[-1] < args.max_workers:
        concurrency_levels.append(args.max_workers)

    print(f"Target: {args.url}")
    print(f"Ramp:   {concurrency_levels}")
    print(f"Hold:   {args.duration}s per level   Stop at: {args.error_threshold:.0%} errors\n")

    async with httpx.AsyncClient() as client:
        run_id = await create_run(client, args.url)
    print(f"Created run id={run_id}\n")

    print_header()
    last_stable: int | None = None
    any_failed = False

    try:
        for workers in concurrency_levels:
            result = await run_level(args.url, run_id, workers, args.duration)
            if result.error_rate > args.error_threshold:
                result = replace(result, stopped=True)
                print_row(result)
                any_failed = True
                break
            print_row(result)
            last_stable = workers
    except asyncio.CancelledError:
        print("\nInterrupted.")
        raise
    finally:
        print()
        if last_stable is not None:
            print(f"Breaking point: {last_stable} workers (last stable level)")
        else:
            print("No stable level found — server was already failing at 1 worker.")
        print("\nTest data left in DB. Run `make seed` from repo root to wipe it.")
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
