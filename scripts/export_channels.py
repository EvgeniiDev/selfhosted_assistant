"""Export posts from public Telegram channels via t.me/s/ web preview.

No API keys required — uses the public web preview endpoint that Telegram
exposes for all public channels.

Usage examples:
    .venv\\Scripts\\python.exe scripts/export_channels.py --days 7
    .venv\\Scripts\\python.exe scripts/export_channels.py --days 30 --output data/posts.jsonl
    .venv\\Scripts\\python.exe scripts/export_channels.py --days 7 --channels VectorCapital_Investments ProfitGate
    .venv\\Scripts\\python.exe scripts/export_channels.py --days 7 --keep-urls
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator

import requests
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Default channel list
# ---------------------------------------------------------------------------

DEFAULT_CHANNELS = [
    "VectorCapital_Investments",
    "ProfitGate",
    "Polyakov_Ant",
    "BizLike",
    "profitanet",
    "CashflowTime",
]

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }
)

# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

# Matches everything outside: printable ASCII (0x20-0x7E), Cyrillic (U+0400-U+04FF),
# more Cyrillic supplements, common Latin extended, whitespace.
_NON_TEXT = re.compile(
    r"[^\u0020-\u007E"           # Basic Latin printable
    r"\u00C0-\u024F"             # Latin Extended-A/B
    r"\u0400-\u04FF"             # Cyrillic
    r"\u0500-\u052F"             # Cyrillic Supplement
    r"\t\n\r]"
)
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_URL = re.compile(r"https?://\S+")


def clean_text(raw: str, keep_urls: bool = False) -> str:
    """Strip emoji, special symbols, optionally URLs, and normalise whitespace."""
    text = raw
    if not keep_urls:
        text = _URL.sub(" ", text)
    text = _NON_TEXT.sub(" ", text)
    # Collapse all newlines into spaces — RAG needs continuous flowing text
    text = text.replace("\n", " ")
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def _parse_page(html: str) -> list[dict]:
    """Return list of {message_id, date, text_raw} dicts from one page of t.me/s/."""
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for msg in soup.select(".tgme_widget_message"):
        # message_id
        post_attr = msg.get("data-post", "")
        try:
            message_id = int(post_attr.split("/")[-1])
        except (ValueError, IndexError):
            continue

        # date
        time_tag = msg.select_one("time[datetime]")
        if not time_tag:
            continue
        try:
            dt = datetime.fromisoformat(time_tag["datetime"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        # text  — concatenate all text nodes, preserve newlines between <br>
        text_div = msg.select_one(".tgme_widget_message_text")
        if text_div:
            # Replace <br> tags with newline before getting text
            for br in text_div.find_all("br"):
                br.replace_with("\n")
            raw_text = text_div.get_text(separator="\n")
        else:
            raw_text = ""

        posts.append({"message_id": message_id, "date": dt, "text_raw": raw_text})

    return posts


def iter_channel_posts(channel: str, cutoff: datetime) -> Iterator[dict]:
    """Yield post dicts (message_id, date, text_raw) from newest to oldest,
    stopping when post date is older than cutoff."""
    url = f"https://t.me/s/{channel}"
    before_id: int | None = None
    consecutive_errors = 0

    while True:
        req_url = f"{url}?before={before_id}" if before_id else url
        try:
            resp = SESSION.get(req_url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            consecutive_errors += 1
            print(f"  [warn] {channel}: HTTP error: {exc}", file=sys.stderr)
            if consecutive_errors >= 3:
                print(f"  [error] {channel}: 3 consecutive errors, stopping.", file=sys.stderr)
                return
            time.sleep(2.0)
            continue

        consecutive_errors = 0
        posts = _parse_page(resp.text)

        if not posts:
            return  # no more content

        # t.me/s returns posts in ascending order; walk from newest to find cutoff
        reached_cutoff = False
        for post in reversed(posts):
            if post["date"] < cutoff:
                reached_cutoff = True
                continue
            yield post

        if reached_cutoff:
            return  # we've gone past the requested window

        # Paginate: the oldest post_id on current page becomes the ?before= param
        oldest_id = min(p["message_id"] for p in posts)
        if before_id is not None and oldest_id >= before_id:
            return  # stuck — safety exit
        before_id = oldest_id

        time.sleep(0.4)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export public Telegram channel posts for RAG indexing."
    )
    p.add_argument(
        "--days",
        type=int,
        default=7,
        metavar="N",
        help="Export posts from the last N days (default: 7)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("channel_export.jsonl"),
        help="Output file path (default: channel_export.jsonl)",
    )
    p.add_argument(
        "--channels",
        nargs="+",
        metavar="SLUG",
        default=None,
        help="Override the default channel list (space-separated slugs)",
    )
    p.add_argument(
        "--keep-urls",
        action="store_true",
        default=False,
        help="Keep URLs in output text (by default URLs are removed as noise for RAG)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    channels = args.channels or DEFAULT_CHANNELS
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=args.days)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"Exporting {len(channels)} channel(s) | last {args.days} days | cutoff: {cutoff.date()}",
        file=sys.stderr,
    )

    total = 0
    with args.output.open("w", encoding="utf-8") as fout:
        for slug in channels:
            count = 0
            print(f"  -> {slug} ...", file=sys.stderr, end="", flush=True)
            try:
                for post in iter_channel_posts(slug, cutoff):
                    text = clean_text(post["text_raw"], keep_urls=args.keep_urls)
                    if not text:
                        continue  # skip media-only / empty posts
                    record = {
                        "channel": slug,
                        "date": post["date"].strftime("%Y-%m-%d"),
                        "message_id": post["message_id"],
                        "text": text,
                    }
                    fout.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1
            except Exception as exc:  # noqa: BLE001
                print(f" ERROR: {exc}", file=sys.stderr)
                continue
            print(f" {count} posts", file=sys.stderr)
            total += count

    print(f"\nDone. Total posts written: {total} -> {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
