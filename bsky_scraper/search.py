"""Ricerca esaustiva di post per termine o hashtag.

L'endpoint app.bsky.feed.searchPosts restituisce al massimo 100 post per pagina
e smette di fornire il cursore dopo un certo numero di risultati. Per superare
questo limite, quando il cursore si esaurisce la ricerca riparte con
`until` = timestamp del post più vecchio visto finora (finestre temporali
a ritroso), deduplicando per URI.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sort_at(post):
    """Timestamp usato dalla ricerca per since/until: min(createdAt, indexedAt)."""
    times = [t for t in (_parse_ts(post.get("record", {}).get("createdAt")),
                         _parse_ts(post.get("indexedAt"))) if t]
    times = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in times]
    return min(times) if times else None


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def search_posts(client, query, out_dir, since=None, until=None, lang=None,
                 author=None, domain=None, tags=None, max_posts=None, resume=True):
    """Scarica tutti i post che corrispondono alla query in out_dir/posts.jsonl.

    Restituisce il numero totale di post salvati. Lo stato viene salvato in
    out_dir/state.json dopo ogni pagina, così un'interruzione può riprendere.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    posts_file = out_dir / "posts.jsonl"
    state_file = out_dir / "state.json"

    seen = set()
    if resume and posts_file.exists():
        with posts_file.open() as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["uri"])
                except (ValueError, KeyError):
                    pass

    key = [query, since, until, lang, author, domain, sorted(tags or [])]
    state = {"key": key, "until": until, "cursor": None, "done": False}
    if resume and state_file.exists():
        saved = json.loads(state_file.read_text())
        if saved.get("key") == key:
            state.update(saved)
            if state["done"]:
                print(f"Ricerca già completata ({len(seen)} post). Usa --no-resume per ripartire.")
                return len(seen)
            print(f"Riprendo: {len(seen)} post già salvati, until={state['until']}")

    base_params = {"q": query, "sort": "latest", "limit": 100}
    if lang:
        base_params["lang"] = lang
    if author:
        base_params["author"] = author
    if domain:
        base_params["domain"] = domain
    if tags:
        base_params["tag"] = list(tags)
    if since:
        base_params["since"] = since

    total = len(seen)
    with posts_file.open("a") as out:
        while True:
            params = dict(base_params)
            if state["until"]:
                params["until"] = state["until"]
            if state["cursor"]:
                params["cursor"] = state["cursor"]

            data = client.get("app.bsky.feed.searchPosts", params)
            posts = data.get("posts", [])
            new = 0
            oldest = None
            for post in posts:
                ts = _sort_at(post)
                if ts and (oldest is None or ts < oldest):
                    oldest = ts
                if post["uri"] in seen:
                    continue
                seen.add(post["uri"])
                out.write(json.dumps(post, ensure_ascii=False) + "\n")
                new += 1
            out.flush()
            total += new

            hits = data.get("hitsTotal")
            window = f" finestra fino a {state['until']}" if state["until"] else ""
            print(f"  +{new:3d} post (totale {total}{f', stimati {hits}' if hits else ''}){window}")

            if max_posts and total >= max_posts:
                print(f"Raggiunto il limite di {max_posts} post.")
                break

            cursor = data.get("cursor")
            if posts and cursor:
                state["cursor"] = cursor
            elif posts and oldest and new > 0:
                # Cursore esaurito: nuova finestra temporale a ritroso.
                # until è inclusivo, quindi i post al confine vengono deduplicati.
                state["until"] = _iso(oldest)
                state["cursor"] = None
            else:
                state["done"] = True
                state_file.write_text(json.dumps(state))
                break
            state_file.write_text(json.dumps(state))

    return total


def fetch_profiles(client, posts_file, out_file):
    """Scarica i profili completi (follower, bio, ecc.) degli autori dei post."""
    dids = set()
    with open(posts_file) as f:
        for line in f:
            dids.add(json.loads(line)["author"]["did"])

    done = set()
    out_file = Path(out_file)
    if out_file.exists():
        with out_file.open() as f:
            for line in f:
                done.add(json.loads(line)["did"])

    todo = sorted(dids - done)
    print(f"Profili: {len(done)} già salvati, {len(todo)} da scaricare")
    with out_file.open("a") as out:
        for i in range(0, len(todo), 25):  # getProfiles accetta max 25 attori
            batch = todo[i:i + 25]
            data = client.get("app.bsky.actor.getProfiles", {"actors": batch})
            for profile in data.get("profiles", []):
                out.write(json.dumps(profile, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  profili {min(i + 25, len(todo))}/{len(todo)}")
