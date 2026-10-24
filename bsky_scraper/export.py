"""Conversione dei post grezzi (JSONL) in CSV tabellare."""

import csv
import json
from pathlib import Path

CSV_FIELDS = [
    "uri", "cid", "url", "created_at", "indexed_at",
    "author_did", "author_handle", "author_display_name", "author_created_at",
    "author_followers", "author_follows", "author_posts", "author_description",
    "text", "langs", "hashtags", "mentions", "links",
    "reply_count", "repost_count", "like_count", "quote_count", "bookmark_count",
    "is_reply", "reply_parent_uri", "reply_root_uri",
    "embed_type", "image_count", "image_urls", "image_alts",
    "video_playlist", "external_uri", "external_title", "external_description",
    "quoted_uri", "quoted_author", "quoted_text",
    "labels", "self_labels", "client_tags",
]


def _post_url(post):
    rkey = post["uri"].rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{post['author']['handle']}/post/{rkey}"


def _facets(record):
    tags, mentions, links = [], [], []
    for facet in record.get("facets") or []:
        for feat in facet.get("features", []):
            t = feat.get("$type", "")
            if t.endswith("#tag"):
                tags.append(feat.get("tag", ""))
            elif t.endswith("#mention"):
                mentions.append(feat.get("did", ""))
            elif t.endswith("#link"):
                links.append(feat.get("uri", ""))
    return tags, mentions, links


def _embed_fields(embed):
    """Estrae i campi dall'embed 'view' (già risolto dall'AppView)."""
    row = {}
    if not embed:
        return row
    t = embed.get("$type", "")
    row["embed_type"] = t.replace("app.bsky.embed.", "").replace("#view", "")
    media = embed.get("media") if t.endswith("recordWithMedia#view") else embed
    record = embed.get("record") if "record" in t else None
    if record and t.endswith("recordWithMedia#view"):
        record = record.get("record")

    if media:
        mt = media.get("$type", "")
        if mt.endswith("images#view"):
            imgs = media.get("images", [])
            row["image_count"] = len(imgs)
            row["image_urls"] = " | ".join(i.get("fullsize", "") for i in imgs)
            row["image_alts"] = " | ".join(i.get("alt", "") for i in imgs)
        elif mt.endswith("video#view"):
            row["video_playlist"] = media.get("playlist", "")
        elif mt.endswith("external#view"):
            ext = media.get("external", {})
            row["external_uri"] = ext.get("uri", "")
            row["external_title"] = ext.get("title", "")
            row["external_description"] = ext.get("description", "")

    if record and record.get("uri"):
        row["quoted_uri"] = record.get("uri", "")
        row["quoted_author"] = (record.get("author") or {}).get("handle", "")
        row["quoted_text"] = (record.get("value") or {}).get("text", "")
    return row


def flatten(post, profiles=None):
    record = post.get("record", {})
    author = post.get("author", {})
    profile = (profiles or {}).get(author.get("did"), {})
    tags, mentions, links = _facets(record)
    reply = record.get("reply") or {}
    self_labels = [v.get("val") for v in (record.get("labels") or {}).get("values", [])]

    row = {
        "uri": post.get("uri"),
        "cid": post.get("cid"),
        "url": _post_url(post),
        "created_at": record.get("createdAt"),
        "indexed_at": post.get("indexedAt"),
        "author_did": author.get("did"),
        "author_handle": author.get("handle"),
        "author_display_name": author.get("displayName", ""),
        "author_created_at": author.get("createdAt", ""),
        "author_followers": profile.get("followersCount", ""),
        "author_follows": profile.get("followsCount", ""),
        "author_posts": profile.get("postsCount", ""),
        "author_description": profile.get("description", ""),
        "text": record.get("text", ""),
        "langs": ",".join(record.get("langs") or []),
        "hashtags": ",".join(tags + (record.get("tags") or [])),
        "mentions": ",".join(mentions),
        "links": " | ".join(links),
        "reply_count": post.get("replyCount", 0),
        "repost_count": post.get("repostCount", 0),
        "like_count": post.get("likeCount", 0),
        "quote_count": post.get("quoteCount", 0),
        "bookmark_count": post.get("bookmarkCount", ""),
        "is_reply": bool(reply),
        "reply_parent_uri": (reply.get("parent") or {}).get("uri", ""),
        "reply_root_uri": (reply.get("root") or {}).get("uri", ""),
        "labels": ",".join(l.get("val", "") for l in post.get("labels") or []),
        "self_labels": ",".join(self_labels),
        "client_tags": ",".join(record.get("tags") or []),
    }
    row.update(_embed_fields(post.get("embed")))
    return row


def export_csv(posts_file, csv_file, profiles_file=None):
    profiles = {}
    if profiles_file and Path(profiles_file).exists():
        with open(profiles_file) as f:
            for line in f:
                p = json.loads(line)
                profiles[p["did"]] = p

    n = 0
    with open(posts_file) as f, open(csv_file, "w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for line in f:
            writer.writerow(flatten(json.loads(line), profiles))
            n += 1
    return n
