"""
Bot Telegram: mỗi 12 phút đọc current_metagraph.csv, check từng axon,
thêm cột status (active/non-active), ghi lại CSV.
Chỉ gửi Telegram khi có UID đổi trạng thái (active ↔ non-active).
"""

import csv
import gc
import time
from pathlib import Path

import requests

from check_axons import (
    read_axons_from_metagraph,
    check_axon,
    DEFAULT_TIMEOUT,
    DEFAULT_SLEEP,
)

TOKEN = "8667840920:AAEKRsTYhdEDdV3tRRcUydt4soY7TYeEe3o"
CHAT_ID = "-5101231510"
INTERVAL_MINUTES = 2
BASE_DIR = Path(__file__).resolve().parent
CURRENT_CSV = BASE_DIR / "current_metagraph.csv"


def send_telegram(text: str, parse_mode: str = "HTML") -> None:
    url = "https://api.telegram.org/bot{}/sendMessage".format(TOKEN)
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode}
    try:
        r = requests.post(url, data=data, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"Telegram send error: {e}")


def run_check() -> list[dict]:
    """Đọc current_metagraph.csv, check từng axon, chỉ cập nhật cột status (active/non-active) rồi ghi lại."""
    rows = read_axons_from_metagraph(CURRENT_CSV)
    if not rows:
        return []

    for i, r in enumerate(rows):
        status, _ = check_axon(r["axon"], timeout=DEFAULT_TIMEOUT)
        r["status"] = status
        if DEFAULT_SLEEP > 0 and i < len(rows) - 1:
            time.sleep(DEFAULT_SLEEP)

    # Ghi lại cùng file 5 cột, chỉ cập nhật status
    fieldnames = ["coldkey_name", "hotkey_name", "uid", "axon", "status"]
    with CURRENT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    return rows


def format_state_change_alert(changed: list[dict]) -> str:
    """Tạo tin nhắn alert khi có UID đổi trạng thái."""
    lines = ["<b>⚠️ Axon state changed!</b>\n"]
    lines.append("<pre>")
    lines.append("UID   AXON               CHANGE")
    lines.append("-" * 45)
    for r in changed:
        uid = str(r.get("uid", ""))[:4].ljust(4)
        axon = (r["axon"] or "")[:18].ljust(18)
        prev = r["_prev_status"]
        curr = r["status"]
        if prev == "wait to check" and curr == "active":
            change = "🟡→🟢 active"
        elif prev == "wait to check" and curr == "non-active":
            change = "🟡→🔴 not start"
        elif curr == "active":
            change = "🔴→🟢 recovered"
        else:
            change = "🟢→🔴 DOWN"
        lines.append("{} {} {}".format(uid, axon, change))
    lines.append("</pre>")
    return "\n".join(lines)


def main() -> None:
    print("Telegram axon bot: check mỗi {} phút, gửi tới chat {}".format(INTERVAL_MINUTES, CHAT_ID))
    send_telegram("🤖 Axon bot started. Checking every {} minutes.".format(INTERVAL_MINUTES))
    # uid -> status của lần check trước
    prev_states: dict[str, str] = {}

    while True:
        try:
            rows = run_check()
            if not rows:
                print("No rows in current_metagraph.csv, skip.")
            else:
                changed = []
                for r in rows:
                    uid = str(r.get("uid", ""))
                    curr = r.get("status", "")
                    prev = prev_states.get(uid)
                    if prev is None or prev == curr:
                        pass  # UID mới hoặc không đổi, không alert
                    else:
                        r["_prev_status"] = prev
                        changed.append(r)
                    prev_states[uid] = curr

                active_count = sum(1 for r in rows if r.get("status") == "active")
                print("Check done: {}/{} active, {} changed".format(
                    active_count, len(rows), len(changed)
                ))

                if changed:
                    msg = format_state_change_alert(changed)
                    for i in range(0, len(msg), 4000):
                        send_telegram(msg[i:i+4000])
                    print("Sent alert for {} changed UIDs".format(len(changed)))
                else:
                    print("No state change, skip send.")

        except Exception as e:
            print("Run error:", e)
            send_telegram("Axon check error: {}".format(str(e)[:500]))
        finally:
            gc.collect()

        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
