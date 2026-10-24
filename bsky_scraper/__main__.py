"""Interfaccia a riga di comando.

Esempi:
    python3 -m bsky_scraper search "intelligenza artificiale"
    python3 -m bsky_scraper search "#elezioni" --since 2026-01-01 --lang it
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .client import BskyClient, BskyError, load_dotenv
from .export import export_csv
from .search import fetch_profiles, search_posts


def _date(s):
    """Accetta YYYY-MM-DD o un datetime ISO e restituisce un timestamp ISO UTC."""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"data non valida: {s} (usa YYYY-MM-DD)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(text):
    return re.sub(r"[^\w-]+", "_", text.strip().lstrip("#")).strip("_")[:60] or "query"


def cmd_search(args):
    client = BskyClient(os.environ.get("BSKY_HANDLE"), os.environ.get("BSKY_APP_PASSWORD"))
    client.login()
    print(f"Autenticato come @{client.session['handle']}")

    out_dir = Path(args.out or f"data/search_{_slug(args.query)}")
    print(f"Ricerca: {args.query!r} -> {out_dir}/")
    if not args.resume:
        for name in ("posts.jsonl", "state.json", "profiles.jsonl"):
            (out_dir / name).unlink(missing_ok=True)

    total = search_posts(client, args.query, out_dir, since=args.since, until=args.until,
                         lang=args.lang, author=args.author, domain=args.domain,
                         tags=args.tag, max_posts=args.max, resume=args.resume)
    posts_file = out_dir / "posts.jsonl"
    if total == 0 or not posts_file.exists():
        print("Nessun post trovato.")
        return

    profiles_file = out_dir / "profiles.jsonl"
    if args.profiles:
        fetch_profiles(client, posts_file, profiles_file)

    n = export_csv(posts_file, out_dir / "posts.csv", profiles_file)
    print(f"\nFatto: {n} post")
    print(f"  dati grezzi completi: {posts_file}")
    print(f"  tabella CSV:          {out_dir / 'posts.csv'}")
    if args.profiles:
        print(f"  profili autori:       {profiles_file}")


def main(argv=None):
    load_dotenv()
    parser = argparse.ArgumentParser(prog="bsky_scraper", description="Scraper per Bluesky")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="scarica tutti i post che contengono un termine o hashtag")
    s.add_argument("query", help='termine di ricerca, es. "clima" o "#clima" (supporta la sintassi di ricerca di Bluesky)')
    s.add_argument("--since", type=_date, help="solo post da questa data (YYYY-MM-DD)")
    s.add_argument("--until", type=_date, help="solo post fino a questa data (YYYY-MM-DD)")
    s.add_argument("--lang", help="codice lingua, es. it, en")
    s.add_argument("--author", help="solo post di questo utente (handle o DID)")
    s.add_argument("--domain", help="solo post che linkano questo dominio")
    s.add_argument("--tag", action="append", help="filtra per hashtag (senza #), ripetibile")
    s.add_argument("--max", type=int, help="numero massimo di post da scaricare")
    s.add_argument("--out", help="cartella di output (default: data/search_<query>)")
    s.add_argument("--no-profiles", dest="profiles", action="store_false",
                   help="non scaricare i profili completi degli autori")
    s.add_argument("--no-resume", dest="resume", action="store_false",
                   help="ricomincia da zero invece di riprendere una ricerca interrotta")
    s.set_defaults(func=cmd_search)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrotto. Rilancia lo stesso comando per riprendere da dove eri rimasto.")
        sys.exit(130)
    except (BskyError, RuntimeError) as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
