"""
Web dashboard: left = current metagraph table,
right = coldkey/hotkey that disappeared since last run (max 30 rows, queue).
Refreshes get_metagraph_rows every 10 minutes.
Saves 2 CSVs: current_metagraph.csv, dead_metagraph.csv
"""

import csv
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from print_metagraph_table import get_metagraph_rows

app = FastAPI(title="Metagraph Dashboard")

BASE_DIR = Path(__file__).resolve().parent
CURRENT_CSV = BASE_DIR / "current_metagraph.csv"
DEAD_CSV = BASE_DIR / "dead_metagraph.csv"
DEAD_QUEUE_MAX = 30
REFRESH_INTERVAL_SEC = 5 * 60  # 10 minutes

# State (thread-safe: only background thread writes, main thread reads)
_current_rows: list[dict] = []
_previous_rows: list[dict] = []
_dead_queue: deque = deque(maxlen=DEAD_QUEUE_MAX)
_last_fetch: datetime | None = None
_lock = threading.Lock()


def _row_key(r: dict) -> tuple[str, str]:
    return (r["coldkey_name"], r["hotkey_name"])


FIELDNAMES_CURRENT = ["coldkey_name", "hotkey_name", "uid", "axon", "status", "rank", "incentive"]


def _read_status_from_csv() -> dict[tuple[str, str], str]:
    """Đọc cột status từ file. Row mới chưa có thì dashboard để 'wait to check'."""
    out = {}
    if not CURRENT_CSV.exists():
        return out
    with CURRENT_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row.get("coldkey_name", ""), row.get("hotkey_name", ""))
            if row.get("status"):
                out[key] = row["status"]
    return out


def _write_current_csv(rows: list[dict]) -> None:
    sorted_rows = sorted(rows, key=lambda r: int(r.get("rank") or 0))
    with CURRENT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES_CURRENT, extrasaction="ignore")
        w.writeheader()
        for r in sorted_rows:
            out = {k: r.get(k, "") for k in FIELDNAMES_CURRENT}
            try:
                out["incentive"] = f"{float(r.get('incentive', 0)):.6f}"
            except (ValueError, TypeError):
                pass
            w.writerow(out)


def _write_dead_csv(dead_list: list[dict]) -> None:
    with DEAD_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["coldkey_name", "hotkey_name", "uid", "axon", "disappeared_at"],
        )
        w.writeheader()
        w.writerows(dead_list)


def _load_dead_csv_into_queue() -> None:
    """Load existing dead_metagraph.csv into _dead_queue on startup so we don't overwrite it with empty."""
    global _dead_queue
    if not DEAD_CSV.exists():
        return
    with _lock:
        _dead_queue.clear()
        with DEAD_CSV.open(newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                if row.get("coldkey_name") or row.get("hotkey_name"):
                    _dead_queue.append(dict(row))


def _fetch_and_diff() -> None:
    global _current_rows, _previous_rows, _dead_queue, _last_fetch
    try:
        new_rows = get_metagraph_rows(BASE_DIR)
        status_by_key = _read_status_from_csv()
        for r in new_rows:
            r["status"] = status_by_key.get(_row_key(r)) or "wait to check"
            r.setdefault("rank", 0)
            r.setdefault("incentive", 0.0)
        current_keys = {_row_key(r) for r in new_rows}
        with _lock:
            for r in _previous_rows:
                if _row_key(r) not in current_keys:
                    entry = {
                        "coldkey_name": r["coldkey_name"],
                        "hotkey_name": r["hotkey_name"],
                        "uid": r["uid"],
                        "axon": r["axon"],
                        "disappeared_at": datetime.now().isoformat(),
                    }
                    _dead_queue.append(entry)
            _previous_rows = list(new_rows)
            _current_rows = list(new_rows)
            _last_fetch = datetime.now()
            current_snapshot = list(_current_rows)
            dead_snapshot = list(_dead_queue)
        _write_current_csv(current_snapshot)
        _write_dead_csv(dead_snapshot)
    except Exception as e:
        with _lock:
            _last_fetch = datetime.now()
        raise e


def _background_loop() -> None:
    while True:
        try:
            _fetch_and_diff()
        except Exception:
            pass
        time.sleep(REFRESH_INTERVAL_SEC)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Metagraph Dashboard</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      font-family: 'JetBrains Mono', 'Fira Code', monospace;
      background: #0d1117;
      color: #e6edf3;
      margin: 0;
      padding: 16px;
    }}
    h1 {{
      text-align: center;
      font-size: 1.5rem;
      margin-bottom: 8px;
    }}
    .meta {{
      text-align: center;
      color: #8b949e;
      font-size: 0.85rem;
      margin-bottom: 20px;
    }}
    .tables {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      max-width: 1400px;
      margin: 0 auto;
    }}
    .panel {{
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 8px;
      overflow: hidden;
    }}
    .panel h2 {{
      margin: 0;
      padding: 12px 16px;
      font-size: 1rem;
      background: #21262d;
      border-bottom: 1px solid #30363d;
    }}
    .panel.left h2 {{ color: #7ee787; }}
    .panel.right h2 {{ color: #ff7b72; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
    }}
    th, td {{
      padding: 8px 12px;
      text-align: left;
      border-bottom: 1px solid #21262d;
    }}
    th {{
      background: #21262d;
      color: #8b949e;
      font-weight: 600;
    }}
    tr:hover {{ background: #21262d; }}
    .count {{ color: #8b949e; font-weight: normal; }}
    .dead-time {{ font-size: 0.75rem; color: #8b949e; }}
    .status-active {{ color: #7ee787; font-weight: 600; }}
    .status-inactive {{ color: #ff7b72; font-weight: 600; }}
    .status-wait {{ color: #d29922; font-weight: 600; }}
    @media (max-width: 900px) {{
      .tables {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <h1>Metagraph Dashboard</h1>
  <p class="meta">Refreshes every 5 min · Last fetch: {last_fetch}</p>
  <div class="tables">
    <div class="panel left">
      <h2>On metagraph <span class="count">({current_len} rows)</span></h2>
      <table>
        <thead>
          <tr>
            <th>WALLET</th>
            <th>HOTKEY</th>
            <th>UID</th>
            <th>AXON</th>
            <th>STATUS</th>
            <th>RANK</th>
            <th>INCENTIVE</th>
          </tr>
        </thead>
        <tbody>
          {current_rows_html}
        </tbody>
      </table>
    </div>
    <div class="panel right">
      <h2>Disappeared (max 30) <span class="count">({dead_len} rows)</span></h2>
      <table>
        <thead>
          <tr>
            <th>WALLET</th>
            <th>HOTKEY</th>
            <th>UID</th>
            <th>AXON</th>
            <th>Disappeared at</th>
          </tr>
        </thead>
        <tbody>
          {dead_rows_html}
        </tbody>
      </table>
    </div>
  </div>
  <p class="meta" style="margin-top: 20px;">
    <a href="/" style="color: #58a6ff;">Reload</a> ·
    <a href="/api/state" style="color: #58a6ff;">API JSON</a>
  </p>
</body>
</html>
"""


def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _status_cell(s: str) -> str:
    if s == "active":
        return '<td class="status-active">🟢 active</td>'
    if s == "non-active":
        return '<td class="status-inactive">🔴 non-active</td>'
    return '<td class="status-wait">🟡 wait to check</td>'

def _fmt_incentive(val) -> str:
    try:
        return f"{float(val):.6f}"
    except (ValueError, TypeError):
        return str(val)

def _render_html(current: list[dict], dead: list[dict], last_fetch: str) -> str:
    sorted_current = sorted(current, key=lambda r: int(r.get("rank") or 0)) if current else []
    if sorted_current:
        current_rows_html = "\n".join(
            f'<tr><td>{_escape(r["coldkey_name"])}</td><td>{_escape(r["hotkey_name"])}</td>'
            f'<td>{r["uid"]}</td><td>{_escape(r["axon"])}</td>{_status_cell(r.get("status") or "wait to check")}'
            f'<td>{r.get("rank", "")}</td><td>{_fmt_incentive(r.get("incentive", 0))}</td></tr>'
            for r in sorted_current
        )
    else:
        current_rows_html = "<tr><td colspan=\"7\">No data yet</td></tr>"
    if dead:
        dead_rows_html = "\n".join(
            f'<tr><td>{_escape(r["coldkey_name"])}</td><td>{_escape(r["hotkey_name"])}</td>'
            f'<td>{r["uid"]}</td><td>{_escape(r["axon"])}</td>'
            f'<td class="dead-time">{_escape(r["disappeared_at"])}</td></tr>'
            for r in dead
        )
    else:
        dead_rows_html = "<tr><td colspan=\"5\">None</td></tr>"
    return HTML_TEMPLATE.format(
        last_fetch=last_fetch,
        current_len=len(current),
        dead_len=len(dead),
        current_rows_html=current_rows_html,
        dead_rows_html=dead_rows_html,
    )


@app.get("/", response_class=HTMLResponse)
def index():
    with _lock:
        current = list(_current_rows)
        dead = list(_dead_queue)
        last_fetch = _last_fetch.isoformat() if _last_fetch else "—"
    return _render_html(current, dead, last_fetch)


@app.get("/api/state")
def api_state():
    with _lock:
        return {
            "current": list(_current_rows),
            "dead": list(_dead_queue),
            "last_fetch": _last_fetch.isoformat() if _last_fetch else None,
        }


if __name__ == "__main__":
    import uvicorn

    _load_dead_csv_into_queue()
    print("Fetching metagraph (first run)...")
    try:
        _fetch_and_diff()
    except Exception as e:
        print(f"First run error: {e}")
    t = threading.Thread(target=_background_loop, daemon=True)
    t.start()
    print("Dashboard at http://127.0.0.1:1234 (refreshes every 10 min)")
    print("CSV: current_metagraph.csv, dead_metagraph.csv")
    uvicorn.run(app, host="0.0.0.0", port=20430)
