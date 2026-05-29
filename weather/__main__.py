"""CLI entry point: ``python -m weather <location> --proxies proxies.json``."""
from __future__ import annotations

import argparse
import logging
import sys

from . import client
from .proxy_session import AllProxiesFailedError, ProxyRotatingSession, load_proxies


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="weather",
        description="Fetch current weather for a location through a rotating proxy pool.",
    )
    p.add_argument("location", help="Place name to look up, e.g. 'Tokyo' or 'Austin, TX'.")
    p.add_argument(
        "-p", "--proxies", default="proxies.json",
        help="Path to the JSON proxy file (default: proxies.json).",
    )
    p.add_argument(
        "--cooldown", type=float, default=60.0,
        help="Seconds to skip a proxy after it fails (default: 60).",
    )
    p.add_argument(
        "--timeout", type=float, default=15.0,
        help="Per-request timeout in seconds (default: 15).",
    )
    p.add_argument(
        "--max-attempts", type=int, default=0,
        help="Total tries across all proxies (default: one per proxy).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log proxy rotation.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        proxies = load_proxies(args.proxies)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    with ProxyRotatingSession(
        proxies,
        cooldown_seconds=args.cooldown,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
    ) as session:
        try:
            place = client.geocode(session, args.location)
            weather = client.current_weather(session, place)
        except LookupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except AllProxiesFailedError as exc:
            print(f"error: every proxy failed: {exc}", file=sys.stderr)
            return 3

    print(f"{weather.place.label()}")
    print(f"  {weather.description}")
    print(f"  {weather.temperature_c:.1f}°C, wind {weather.windspeed_kmh:.0f} km/h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
