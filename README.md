# Reddit Pain Analysis Exporter

This folder contains a Python script that discovers Reddit threads and extracts comments that match customer pain/frustration criteria.

Primary script:
- `reddit_export.py`

## What It Does

1. Discovers threads from a target subreddit (`USE_AUTO_DISCOVERY = True`) or uses manual URLs.
2. Scores thread relevance using pain/problem keyword signals.
3. Pulls comments from each thread.
4. Ranks comments for pain potential.
5. Applies strict pain/frustration validation.
6. Writes accepted comments and diagnostics to CSV/txt outputs.
7. Tracks unproductive threads and skips them in future runs.

## Requirements

- Python 3.9+
- `requests`

Install dependency:

```bash
python3 -m pip install requests
```

## Run

From `/Users/blakefuller/Desktop`:

```bash
python3 /Users/blakefuller/Desktop/RedditData_Output/reddit_export.py
```

Why run from Desktop: the script uses `OUTPUT_FOLDER = "RedditData_Output"` (relative path). Running from Desktop writes outputs into this folder.

## Key Config (in `reddit_export.py`)

- `SUBREDDIT`: target subreddit
- `TARGET_COMMENTS`: total accepted pain comments to collect
- `USE_AUTO_DISCOVERY`: `True` for auto thread discovery, `False` for `MANUAL_THREAD_URLS`
- `PREVIEW_MODE`: `True` to only discover and preview threads (no scraping)
- `DISCOVERY_LIMIT`: number of subreddit posts to scan for discovery
- `DISCOVERY_SORT`: discovery feed (`hot`, `new`, `top`)
- `MIN_COMMENTS_PER_THREAD`: discovery filter floor
- `PRE_RANK_MIN_SCORE`: pre-filter strength before strict classifier
- `STRICT_CLASSIFIER_MIN_SCORE`: strict acceptance threshold
- `ADAPTIVE_PRE_RANK_MIN_SCORE` / `ADAPTIVE_CLASSIFIER_MIN_SCORE`: fallback thresholds when behind target
- `MIN_SENTENCES`, `MIN_CHARS`, `MAX_CHARS`: comment structure/length filters

## Output Files

Main outputs are overwritten each run unless noted:

- `First_Last_RedditData_r_<subreddit>.csv`: accepted comments (core export)
- `First_Last_pain_analysis.csv`: accepted comments + scoring metadata
- `First_Last_rejected_comments.csv`: rejected candidates with reason
- `First_Last_validation_failures.csv`: validation/URL failures
- `discovered_thread_urls.txt`: ranked discovered threads (auto mode)
- `optimized_thread_urls.txt`: productive thread list for reuse
- `run_summary.txt`: run totals and category breakdown
- `rejected_threads.txt`: cumulative skip-list of threads with 0 accepted comments

## Typical Workflow

1. Set `PREVIEW_MODE = True` to inspect discovered threads.
2. Review `discovered_thread_urls.txt`.
3. Set `PREVIEW_MODE = False` and run full collection.
4. Review:
   - `run_summary.txt`
   - `First_Last_pain_analysis.csv`
   - `First_Last_rejected_comments.csv`
5. Tune thresholds and rerun.

## Tuning Tips

- If recall is too low (not enough accepted comments):
  - Lower `PRE_RANK_MIN_SCORE` slightly.
  - Lower `STRICT_CLASSIFIER_MIN_SCORE` slightly.
  - Increase `DISCOVERY_LIMIT`.
  - Lower `MIN_COMMENTS_PER_THREAD` slightly.

- If precision is too low (too much noise):
  - Raise `PRE_RANK_MIN_SCORE`.
  - Raise `STRICT_CLASSIFIER_MIN_SCORE`.
  - Raise `MIN_CHARS`.

- If runs are too slow:
  - Reduce `DISCOVERY_LIMIT`.
  - Keep `PREVIEW_MODE = True` while iterating on discovery.

## Notes

- Reddit may rate-limit requests; reruns can vary by time and subreddit activity.
- `rejected_threads.txt` is persistent and cumulative, so discovery behavior changes over time.
