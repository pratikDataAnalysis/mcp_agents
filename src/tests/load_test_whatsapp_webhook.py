"""
End-to-end load test for the Twilio WhatsApp webhook.

Sends N form-encoded POST requests to /webhooks/whatsapp and then verifies end-to-end
processing by observing outbound Redis stream events that include our MessageSid in metadata.

Pass criteria (E2E):
- Webhook returned HTTP 200
- AND an outbound message appeared on the outbound Redis stream containing metadata.message_sid

Usage:
  python3 -m src.tests.load_test_whatsapp_webhook \\
    --url "http://localhost:8000/webhooks/whatsapp" \\
    --count 100 \\
    --concurrency 10 \\
    --from "whatsapp:+10000000000"

Optional:
  --timeout-s 60
  --redis-host localhost --redis-port 6379 --redis-db 0
  --outbound-stream outbound_messages
  --body-template "Make a note about item #{i}"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

try:
    import redis.asyncio as redis_async
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "redis asyncio support missing. Ensure 'redis' package is installed."
    ) from exc


@dataclass(frozen=True)
class SendResult:
    idx: int
    message_sid: str
    status_code: int
    latency_s: float
    error: Optional[str] = None


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    k = int(round((p / 100.0) * (len(values_sorted) - 1)))
    return values_sorted[max(0, min(k, len(values_sorted) - 1))]


async def _send_one(
    *,
    url: str,
    idx: int,
    from_value: str,
    body_template: str,
    sem: asyncio.Semaphore,
    executor: ThreadPoolExecutor,
) -> SendResult:
    msg_sid = f"SM_{uuid.uuid4().hex}"
    body = body_template.replace("{i}", str(idx))

    form = {
        "From": from_value,
        "Body": body,
        "MessageSid": msg_sid,
    }

    def _post_form() -> int:
        data = urlencode(form).encode("utf-8")
        req = Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urlopen(req, timeout=15.0) as resp:
                return int(getattr(resp, "status", 0) or 0)
        except HTTPError as e:
            return int(getattr(e, "code", 0) or 0)
        except URLError:
            return 0

    async with sem:
        t0 = time.perf_counter()
        try:
            loop = asyncio.get_running_loop()
            status = await loop.run_in_executor(executor, _post_form)
            dt = time.perf_counter() - t0
            return SendResult(
                idx=idx,
                message_sid=msg_sid,
                status_code=status,
                latency_s=dt,
            )
        except Exception as e:
            dt = time.perf_counter() - t0
            return SendResult(
                idx=idx,
                message_sid=msg_sid,
                status_code=0,
                latency_s=dt,
                error=str(e),
            )


async def _poll_outbound_for_sids(
    *,
    redis_client: "redis_async.Redis",
    outbound_stream: str,
    expected_sids: set[str],
    timeout_s: float,
) -> dict[str, dict[str, Any]]:
    """
    Returns mapping: message_sid -> outbound entry fields
    """
    found: dict[str, dict[str, Any]] = {}

    # Start from current last id to avoid scanning historical stream.
    try:
        info = await redis_client.xinfo_stream(outbound_stream)
        last_id = info.get("last-generated-id") or "$"
    except Exception:
        last_id = "$"

    deadline = time.time() + timeout_s
    current_id = last_id

    while time.time() < deadline and len(found) < len(expected_sids):
        # xread returns {stream: [(id, {field: val})...]}
        resp = await redis_client.xread({outbound_stream: current_id}, count=200, block=1000)
        if not resp:
            continue

        # redis-py returns list of tuples: [(stream, [(id, dict), ...])]
        for _stream_name, entries in resp:
            for entry_id, fields in entries:
                current_id = entry_id
                meta_raw = fields.get("metadata")
                if not meta_raw:
                    continue
                try:
                    meta = json.loads(meta_raw)
                except Exception:
                    continue
                sid = meta.get("message_sid")
                if sid and sid in expected_sids and sid not in found:
                    found[sid] = fields

    return found


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--concurrency", type=int, required=True)
    ap.add_argument("--from", dest="from_value", required=True)
    ap.add_argument("--timeout-s", type=float, default=60.0)
    ap.add_argument("--body-template", default="Make a note about item {i}")
    ap.add_argument("--redis-host", default="localhost")
    ap.add_argument("--redis-port", type=int, default=6379)
    ap.add_argument("--redis-db", type=int, default=0)
    ap.add_argument("--outbound-stream", default="outbound_messages")
    args = ap.parse_args()

    sem = asyncio.Semaphore(max(1, args.concurrency))

    print(f"Sending {args.count} requests to {args.url} with concurrency={args.concurrency}")
    print(f"From={args.from_value} outbound_stream={args.outbound_stream} timeout_s={args.timeout_s}")

    send_started_at = time.time()
    send_ts_by_sid: dict[str, float] = {}

    # Use a thread pool for HTTP requests (stdlib urllib).
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
        tasks = []
        for i in range(args.count):
            tasks.append(
                asyncio.create_task(
                    _send_one(
                        url=args.url,
                        idx=i,
                        from_value=args.from_value,
                        body_template=args.body_template,
                        sem=sem,
                        executor=executor,
                    )
                )
            )

        results: list[SendResult] = await asyncio.gather(*tasks)

    sent_sids = {r.message_sid for r in results}
    for r in results:
        send_ts_by_sid[r.message_sid] = send_started_at + 0.0  # coarse baseline

    http_ok = [r for r in results if r.status_code == 200]
    http_fail = [r for r in results if r.status_code != 200]
    http_lat = [r.latency_s for r in results if r.status_code != 0]

    print("\nHTTP results")
    print(f"- total: {len(results)}")
    print(f"- 200:   {len(http_ok)}")
    print(f"- non-200/err: {len(http_fail)}")
    if http_lat:
        print(
            f"- latency_s: p50={_pct(http_lat, 50):.3f} p95={_pct(http_lat, 95):.3f} max={max(http_lat):.3f}"
        )
    else:
        print("- latency_s: (no successful HTTP timings)")

    # End-to-end: only consider those that were accepted by webhook
    expected = {r.message_sid for r in http_ok}

    if not expected:
        print("\nNo accepted webhook requests (HTTP 200). Exiting.")
        return 2

    r = redis_async.Redis(
        host=args.redis_host,
        port=args.redis_port,
        db=args.redis_db,
        decode_responses=True,
    )

    try:
        print("\nPolling outbound stream for end-to-end completion...")
        found = await _poll_outbound_for_sids(
            redis_client=r,
            outbound_stream=args.outbound_stream,
            expected_sids=expected,
            timeout_s=args.timeout_s,
        )
    finally:
        await r.aclose()

    e2e_ok = len(found)
    e2e_missing = len(expected) - e2e_ok

    print("\nEnd-to-end results (outbound stream match by metadata.message_sid)")
    print(f"- expected (HTTP 200): {len(expected)}")
    print(f"- matched outbound:    {e2e_ok}")
    print(f"- missing/timeouts:    {e2e_missing}")

    # Basic success ratio
    ratio = (e2e_ok / len(expected)) if expected else 0.0
    print(f"- success_ratio:       {ratio:.3f}")

    # Show a few failures for debugging
    if e2e_missing:
        missing_sids = sorted(list(expected - set(found.keys())))[:10]
        print("\nSample missing MessageSid values (first 10):")
        for sid in missing_sids:
            print(f"- {sid}")

    # Exit non-zero if too many failures
    return 0 if e2e_missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

