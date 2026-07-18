#!/usr/bin/env python3
"""
Publications -> Podcast pipeline.

Reads the newest Markdown digest from ./input/, turns it into clean narration,
synthesizes speech with the Google Cloud Text-to-Speech REST API (chunked to
respect the 5000-byte request limit), concatenates the audio into a single MP3
in ./episodes/, and updates a podcast RSS 2.0 feed (feed.xml) with an iTunes
namespace so the feed works in Apple Podcasts.

Run:
    export GOOGLE_TTS_API_KEY=...        # or put it in a .env file
    python generate_podcast.py

The API key is read from the GOOGLE_TTS_API_KEY environment variable (a .env
file is loaded automatically if present). It is never written to disk.
"""

from __future__ import annotations

import base64
import glob
import io
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.etree import ElementTree as ET

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass

from pydub import AudioSegment

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

# Where GitHub Pages serves this repo. The podcast enclosure URLs are built from
# this. GitHub Pages for a project repo lives at https://<user>.github.io/<repo>/
# so the default matches the actual repo name. Override with SITE_BASE_URL if you
# serve the feed from a different path (e.g. a custom domain).
SITE_BASE_URL = os.environ.get(
    "SITE_BASE_URL", "https://avivbz.github.io/AI-EDU-Podacast"
).rstrip("/")

INPUT_DIR = os.environ.get("INPUT_DIR", "input")
EPISODES_DIR = os.environ.get("EPISODES_DIR", "episodes")
FEED_PATH = os.environ.get("FEED_PATH", "feed.xml")

# Google TTS voice + audio settings.
TTS_VOICE = os.environ.get("TTS_VOICE", "en-US-Neural2-J")
TTS_LANGUAGE_CODE = os.environ.get("TTS_LANGUAGE_CODE", "en-US")
TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"

# The API accepts at most 5000 bytes of input per request; stay well under it.
MAX_CHUNK_BYTES = 4800

# Silence inserted between spoken items (milliseconds).
ITEM_PAUSE_MS = 800

# Podcast channel metadata.
PODCAST_TITLE = "AI in Education Publications"
PODCAST_DESCRIPTION = (
    "An automated audio digest of recent publications on AI in K-12 education "
    "and teaching. Each episode narrates a current-awareness roundup of "
    "peer-reviewed studies, articles, and commentary."
)
PODCAST_AUTHOR = "Aviv Ben-Zvi"
PODCAST_LANGUAGE = "en"
PODCAST_CATEGORY = "Education"
PODCAST_EMAIL = "avivbz@gmail.com"

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("atom", ATOM_NS)


# --------------------------------------------------------------------------- #
# Input discovery
# --------------------------------------------------------------------------- #

def find_newest_markdown(input_dir: str) -> str:
    files = glob.glob(os.path.join(input_dir, "*.md"))
    if not files:
        raise FileNotFoundError(f"No .md files found in {input_dir!r}")
    # Newest by modification time; ties broken by name (filenames encode a date).
    files.sort(key=lambda p: (os.path.getmtime(p), p))
    return files[-1]


def extract_episode_date(md_text: str, filename: str) -> str:
    """Return the episode date as YYYY-MM-DD.

    Prefers an 8-digit date embedded in the filename (e.g. ..._20260709.md),
    then a 'Compiled: DD Month YYYY' line, then today's date.
    """
    m = re.search(r"(\d{4})(\d{2})(\d{2})", os.path.basename(filename))
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    m = re.search(r"Compiled:\**\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", md_text)
    if m:
        try:
            dt = datetime.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y"
            )
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def human_date(date_str: str) -> str:
    """2026-07-09 -> 9 July 2026."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.day} {dt.strftime('%B %Y')}"


# --------------------------------------------------------------------------- #
# Markdown -> narration
# --------------------------------------------------------------------------- #

def strip_markdown(text: str) -> str:
    """Reduce Markdown to plain, speakable prose."""
    # Links: [label](url) -> label
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # Bare URLs -> drop (not worth reading aloud)
    text = re.sub(r"https?://\S+", "", text)
    # Bold / italic / inline code markers
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"(?<!\w)\*(?!\s)", "", text)
    text = re.sub(r"(?<!\s)\*(?!\w)", "", text)
    # Heading markers / horizontal rules already handled by the caller, but be safe
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^-{3,}\s*$", "", text, flags=re.MULTILINE)
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _field(block: str, name: str) -> str | None:
    """Extract the value of a '**Name:** value' field from an item block.

    The value runs until the next numbered '**Field:**' marker or end of block.
    """
    pattern = re.compile(
        r"\*\*" + re.escape(name) + r":\*\*\s*(.*?)"
        r"(?=\n\s*\d+\.\s*\*\*[A-Za-z]|\Z)",
        re.DOTALL,
    )
    m = pattern.search(block)
    if not m:
        return None
    return strip_markdown(m.group(1))


def parse_digest(md_text: str) -> list[dict]:
    """Parse the 'Included publications' section into a list of item dicts.

    Falls back gracefully: if the expected structure is absent, returns a single
    item containing the whole stripped document body.
    """
    # Isolate the included-publications section (before "Unverified / excluded").
    included = md_text
    m = re.search(r"##\s*Included publications", md_text)
    if m:
        start = m.end()
        end_m = re.search(r"\n##\s+", md_text[start:])
        end = start + end_m.start() if end_m else len(md_text)
        included = md_text[start:end]

    # Split into item blocks at '### N. Title' headers.
    parts = re.split(r"\n###\s+\d+\.\s*", "\n" + included)
    blocks = [p for p in parts[1:] if p.strip()]

    items: list[dict] = []
    for block in blocks:
        title = _field(block, "Title")
        if not title:
            # First line of the block is the header title.
            title = strip_markdown(block.splitlines()[0])
        summary = _field(block, "Summary")
        conclusions = _field(block, "Main conclusions / central claims")
        publisher = _field(block, "Institution / publisher / platform")
        authors = _field(block, "Author(s)")
        if not (summary or conclusions):
            continue
        items.append(
            {
                "title": title,
                "publisher": publisher,
                "authors": authors,
                "summary": summary,
                "conclusions": conclusions,
            }
        )

    if not items:
        # Fallback: narrate the whole document body.
        items.append(
            {
                "title": "Full digest",
                "publisher": None,
                "authors": None,
                "summary": strip_markdown(md_text),
                "conclusions": None,
            }
        )
    return items


def build_segments(md_text: str, date_str: str) -> tuple[list[str], int]:
    """Build a list of narration segments (intro + one per item).

    Returns (segments, item_count). Segments are separated by a spoken pause in
    the final audio.
    """
    items = parse_digest(md_text)
    n = len(items)

    intro = (
        f"Publications digest for {human_date(date_str)}. "
        f"{n} new {'item' if n == 1 else 'items'}. "
        "Here are the latest publications on AI in K through 12 education and teaching."
    )

    segments = [intro]
    for idx, item in enumerate(items, start=1):
        lines = [f"Item {idx}. {item['title']}."]
        byline = []
        if item.get("publisher"):
            byline.append(f"Published by {item['publisher']}")
        if item.get("authors"):
            byline.append(f"Written by {item['authors']}")
        if byline:
            lines.append(". ".join(byline) + ".")
        if item.get("summary"):
            lines.append(item["summary"])
        if item.get("conclusions"):
            lines.append("Main takeaway. " + item["conclusions"])
        segments.append(" ".join(lines))

    outro = (
        "That concludes this publications digest. "
        "Subscribe for the next update on AI in education."
    )
    segments.append(outro)
    return segments, n


# --------------------------------------------------------------------------- #
# Chunking (respect the 5000-byte TTS input limit)
# --------------------------------------------------------------------------- #

_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|\Z)", re.DOTALL)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]


def chunk_text(text: str, max_bytes: int = MAX_CHUNK_BYTES) -> list[str]:
    """Split text into <max_bytes (UTF-8) chunks at sentence boundaries."""
    chunks: list[str] = []
    current = ""

    for sentence in split_sentences(text):
        candidate = (current + " " + sentence).strip() if current else sentence
        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        # A single sentence longer than the limit: hard-split on word boundaries.
        if len(sentence.encode("utf-8")) > max_bytes:
            chunks.extend(_split_long(sentence, max_bytes))
        else:
            current = sentence

    if current:
        chunks.append(current)
    return chunks


def _split_long(sentence: str, max_bytes: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for word in sentence.split():
        candidate = (current + " " + word).strip() if current else word
        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


# --------------------------------------------------------------------------- #
# Google Cloud Text-to-Speech
# --------------------------------------------------------------------------- #

def synthesize_chunk(text: str, api_key: str) -> bytes:
    """Synthesize one text chunk to MP3 bytes via the Google TTS REST API."""
    payload = {
        "input": {"text": text},
        "voice": {"languageCode": TTS_LANGUAGE_CODE, "name": TTS_VOICE},
        "audioConfig": {"audioEncoding": "MP3"},
    }
    resp = requests.post(
        TTS_ENDPOINT,
        params={"key": api_key},
        json=payload,
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"TTS request failed ({resp.status_code}): {resp.text[:500]}"
        )
    audio_content = resp.json().get("audioContent")
    if not audio_content:
        raise RuntimeError("TTS response contained no audioContent")
    return base64.b64decode(audio_content)


def synthesize_segments(segments: list[str], api_key: str) -> AudioSegment:
    """Synthesize all segments, concatenating with a pause between items."""
    combined = AudioSegment.empty()
    pause = AudioSegment.silent(duration=ITEM_PAUSE_MS)

    total_chunks = sum(len(chunk_text(seg)) for seg in segments)
    done = 0
    for i, segment in enumerate(segments):
        for chunk in chunk_text(segment):
            done += 1
            print(f"  synthesizing chunk {done}/{total_chunks} "
                  f"({len(chunk.encode('utf-8'))} bytes)...")
            mp3_bytes = synthesize_chunk(chunk, api_key)
            combined += AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")
        if i < len(segments) - 1:
            combined += pause
    return combined


# --------------------------------------------------------------------------- #
# RSS feed
# --------------------------------------------------------------------------- #

def _q(tag: str) -> str:
    """iTunes-namespaced tag name for ElementTree."""
    return f"{{{ITUNES_NS}}}{tag}"


def format_duration(milliseconds: int) -> str:
    total = int(round(milliseconds / 1000))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def load_existing_items(feed_path: str) -> list[ET.Element]:
    if not os.path.exists(feed_path):
        return []
    try:
        tree = ET.parse(feed_path)
    except ET.ParseError:
        return []
    channel = tree.getroot().find("channel")
    if channel is None:
        return []
    return channel.findall("item")


def build_item(date_str: str, mp3_url: str, length_bytes: int,
               duration_ms: int, item_count: int) -> ET.Element:
    item = ET.Element("item")

    title = ET.SubElement(item, "title")
    title.text = f"Publications Digest - {human_date(date_str)}"

    desc = ET.SubElement(item, "description")
    desc.text = (
        f"Audio digest of {item_count} recent "
        f"{'publication' if item_count == 1 else 'publications'} on AI in K-12 "
        f"education and teaching, covering the {human_date(date_str)} roundup."
    )

    guid = ET.SubElement(item, "guid")
    guid.set("isPermaLink", "false")
    guid.text = f"ai-edu-podcast-{date_str}"

    pub = ET.SubElement(item, "pubDate")
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=12, tzinfo=timezone.utc
    )
    pub.text = format_datetime(dt)

    enclosure = ET.SubElement(item, "enclosure")
    enclosure.set("url", mp3_url)
    enclosure.set("type", "audio/mpeg")
    enclosure.set("length", str(length_bytes))

    itunes_duration = ET.SubElement(item, _q("duration"))
    itunes_duration.text = format_duration(duration_ms)

    itunes_explicit = ET.SubElement(item, _q("explicit"))
    itunes_explicit.text = "false"

    itunes_title = ET.SubElement(item, _q("title"))
    itunes_title.text = title.text

    itunes_summary = ET.SubElement(item, _q("summary"))
    itunes_summary.text = desc.text

    return item


def build_feed(date_str: str, mp3_url: str, length_bytes: int,
               duration_ms: int, item_count: int, feed_path: str) -> str:
    """Rebuild the RSS feed: fresh channel metadata + full item history."""
    new_guid = f"ai-edu-podcast-{date_str}"
    existing = [
        it for it in load_existing_items(feed_path)
        if (it.findtext("guid") or "") != new_guid
    ]

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = PODCAST_TITLE
    ET.SubElement(channel, "link").text = SITE_BASE_URL + "/"
    ET.SubElement(channel, "language").text = PODCAST_LANGUAGE
    ET.SubElement(channel, "description").text = PODCAST_DESCRIPTION
    ET.SubElement(channel, "generator").text = "AI-EDU-Podacast pipeline"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc)
    )

    # Atom self link (recommended for podcast feeds).
    atom_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", f"{SITE_BASE_URL}/{os.path.basename(feed_path)}")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    ET.SubElement(channel, _q("author")).text = PODCAST_AUTHOR
    ET.SubElement(channel, _q("summary")).text = PODCAST_DESCRIPTION
    ET.SubElement(channel, _q("explicit")).text = "false"
    ET.SubElement(channel, _q("type")).text = "episodic"

    image_url = f"{SITE_BASE_URL}/cover.jpg"
    itunes_image = ET.SubElement(channel, _q("image"))
    itunes_image.set("href", image_url)
    # Standard RSS image block as well (broader reader support).
    image = ET.SubElement(channel, "image")
    ET.SubElement(image, "url").text = image_url
    ET.SubElement(image, "title").text = PODCAST_TITLE
    ET.SubElement(image, "link").text = SITE_BASE_URL + "/"

    category = ET.SubElement(channel, _q("category"))
    category.set("text", PODCAST_CATEGORY)

    owner = ET.SubElement(channel, _q("owner"))
    ET.SubElement(owner, _q("name")).text = PODCAST_AUTHOR
    ET.SubElement(owner, _q("email")).text = PODCAST_EMAIL

    # New episode first, then history.
    channel.append(
        build_item(date_str, mp3_url, length_bytes, duration_ms, item_count)
    )
    for it in existing:
        channel.append(it)

    ET.indent(rss, space="  ")
    xml_body = ET.tostring(rss, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body + "\n"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    api_key = os.environ.get("GOOGLE_TTS_API_KEY")
    if not api_key:
        print(
            "ERROR: GOOGLE_TTS_API_KEY is not set. Export it or add it to a "
            ".env file (see .env.example).",
            file=sys.stderr,
        )
        return 1

    os.makedirs(EPISODES_DIR, exist_ok=True)

    md_path = find_newest_markdown(INPUT_DIR)
    print(f"Input digest: {md_path}")
    with open(md_path, "r", encoding="utf-8") as fh:
        md_text = fh.read()

    date_str = extract_episode_date(md_text, md_path)
    print(f"Episode date: {date_str}")

    segments, item_count = build_segments(md_text, date_str)
    total_bytes = sum(len(s.encode("utf-8")) for s in segments)
    print(f"Parsed {item_count} item(s); narration ~{total_bytes} bytes "
          f"across {len(segments)} segment(s).")

    print("Synthesizing speech via Google Cloud Text-to-Speech...")
    audio = synthesize_segments(segments, api_key)

    mp3_path = os.path.join(EPISODES_DIR, f"{date_str}.mp3")
    audio.export(mp3_path, format="mp3")
    length_bytes = os.path.getsize(mp3_path)
    duration_ms = len(audio)
    print(f"Wrote {mp3_path} ({length_bytes} bytes, "
          f"{format_duration(duration_ms)}).")

    mp3_url = f"{SITE_BASE_URL}/{EPISODES_DIR}/{date_str}.mp3"
    feed_xml = build_feed(
        date_str, mp3_url, length_bytes, duration_ms, item_count, FEED_PATH
    )
    with open(FEED_PATH, "w", encoding="utf-8") as fh:
        fh.write(feed_xml)
    print(f"Updated {FEED_PATH} (enclosure: {mp3_url}).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
