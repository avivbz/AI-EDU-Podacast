# AI in Education — Publications Podcast

An automated pipeline that turns a Markdown digest of academic publications into
a narrated podcast episode and publishes it to a GitHub Pages RSS feed you can
follow in Apple Podcasts.

**What it does, end to end:**

1. Reads the newest `.md` file from [`input/`](input/).
2. Converts it to clean narration text (strips Markdown, expands it into
   readable sentences, adds a spoken intro — *"Publications digest for
   `<date>`. `<N>` new items."* — and a short pause between items).
3. Synthesizes speech with the **Google Cloud Text-to-Speech** REST API
   (English Neural2 voice, MP3), splitting the narration into sub-5000-byte
   chunks at sentence boundaries and concatenating the audio with `ffmpeg`
   (via `pydub`).
4. Saves the episode to `episodes/<YYYY-MM-DD>.mp3`.
5. Creates/updates [`feed.xml`](feed.xml) — a valid RSS 2.0 podcast feed with the
   iTunes namespace — adding a new `<item>` and keeping older items for history.
6. Commits and pushes the new MP3 and feed to `main` (done by GitHub Actions, or
   by the local runner).

---

## Repository layout

```
AI-EDU-Podacast/
├── input/                     # drop your Markdown digests here (newest wins)
├── episodes/                  # generated MP3s (one per episode)
├── generate_podcast.py        # the pipeline
├── make_cover.py              # regenerates cover.jpg (run once; optional)
├── cover.jpg                  # podcast artwork (1500x1500)
├── feed.xml                   # the RSS feed (generated)
├── requirements.txt
├── .env.example               # copy to .env and add your key
├── run_local.bat              # Windows fallback runner
└── .github/workflows/podcast.yml
```

---

## Setup

### 1. Google Cloud Text-to-Speech API key

- In the Google Cloud console, enable the **Cloud Text-to-Speech API** and create
  an API key.
- The pipeline reads the key from the `GOOGLE_TTS_API_KEY` environment variable,
  or from a `.env` file. **The key is never hard-coded or committed** — `.env`
  is gitignored.

Copy the template and fill it in:

```bash
cp .env.example .env
# edit .env and paste your key into GOOGLE_TTS_API_KEY
```

### 2. Enable GitHub Pages

The feed's episode URLs point at GitHub Pages. Enable it once:

- **Settings → Pages → Build and deployment → Deploy from a branch**
- Branch: **`main`**, folder: **`/ (root)`**, then **Save**.

Your feed will then be live at:

```
https://avivbz.github.io/AI-EDU-Podacast/feed.xml
```

> **Note on the URL / repo name.** The original brief mentioned a
> `publications-podcast` path, but GitHub Pages for a project repo serves at
> `https://<username>.github.io/<repo-name>/`. Since this repo is
> **`AI-EDU-Podacast`**, the default `SITE_BASE_URL` is
> `https://avivbz.github.io/AI-EDU-Podacast`. If you serve the feed from a
> different path (a custom domain, or a repo literally named
> `publications-podcast`), set the `SITE_BASE_URL` environment variable /
> repository variable to match — every URL in the feed is built from it.

### 3. Subscribe in Apple Podcasts

Apple Podcasts → **File → Add a Show by URL…** and paste the `feed.xml` URL
above. (Listing it in the public directory is optional and separate.)

---

## Running it

### Recommended: GitHub Actions (no PC required)

The workflow in [`.github/workflows/podcast.yml`](.github/workflows/podcast.yml)
runs automatically when you **push a new `.md` file to `input/`**, on a weekly
cron (Mondays 07:00 UTC), or on manual dispatch. It installs `ffmpeg`, runs the
pipeline, and commits the new MP3 + `feed.xml` back to `main`.

**One-time:** add your key as an Actions secret named `GOOGLE_TTS_API_KEY`:

- **Settings → Secrets and variables → Actions → New repository secret**
- Name: `GOOGLE_TTS_API_KEY`, Value: *your key*.

Then your workflow is simply: add a new digest to `input/`, commit, push — a
fresh episode appears in the feed a couple of minutes later.

### Locally (any OS)

```bash
pip install -r requirements.txt
# ensure ffmpeg is installed and on PATH
export GOOGLE_TTS_API_KEY=...        # or use a .env file
python generate_podcast.py
git add episodes/ feed.xml && git commit -m "New episode" && git push origin main
```

### Locally on Windows + Task Scheduler

1. Install [Python 3.11+](https://www.python.org/downloads/) (tick *"Add to
   PATH"*), [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) (add its `bin` to
   PATH), then `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` and paste your key.
3. Double-click **`run_local.bat`** to generate + push an episode.

To run it on a schedule with **Task Scheduler**:

- Open *Task Scheduler* → **Create Basic Task…**
- Name it e.g. *"AI Edu Podcast"*, choose a trigger (e.g. **Weekly**).
- Action: **Start a program** → Program/script: browse to `run_local.bat`.
- "Start in": the repo folder (so relative paths resolve).
- Finish. (Tick *"Run whether user is logged on or not"* in the task's
  properties if you want it to run headless.)

---

## Configuration knobs

All optional, via environment variables (see `.env.example`):

| Variable             | Default                                          | Purpose                                   |
|----------------------|--------------------------------------------------|-------------------------------------------|
| `GOOGLE_TTS_API_KEY` | *(required)*                                     | Google Cloud TTS API key.                 |
| `SITE_BASE_URL`      | `https://avivbz.github.io/AI-EDU-Podacast`       | Base URL used for all feed/enclosure URLs.|
| `TTS_VOICE`          | `en-US-Neural2-J`                                | Any English Neural2 voice.                |
| `TTS_LANGUAGE_CODE`  | `en-US`                                          | TTS language code.                        |

---

## Input format

The pipeline is tuned for the "current-awareness digest" format in
[`input/`](input/): a `## Included publications` section with `### N. Title`
items, each carrying `**Title:**`, `**Summary:**`, `**Main conclusions …:**`,
etc. It reads the title, publisher, author, summary, and conclusions for each
included item and skips the "Unverified / excluded" section. If the structure
isn't recognized, it falls back to narrating the whole (Markdown-stripped)
document.

The episode date is taken from an 8-digit date in the filename
(e.g. `..._20260709.md` → `2026-07-09`), then a `Compiled: …` line, then today.

---

## Validating the feed

The generated `feed.xml` is a valid RSS 2.0 + iTunes feed. You can confirm with:

- [Podbase](https://podba.se/validate/) or
- [Cast Feed Validator](https://castfeedvalidator.com/)

Paste your live feed URL (`https://avivbz.github.io/AI-EDU-Podacast/feed.xml`)
once Pages is enabled.
