"""
Bot Telegram: mỗi 12 phút đọc current_metagraph.csv, check từng axon,
thêm cột status (active/non-active), ghi lại CSV và gửi báo cáo có 🟢/🔴.
"""

import csv
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
INTERVAL_MINUTES = 12
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


def format_report(rows: list[dict]) -> str:
    """Tạo nội dung báo cáo với 🟢 active, 🔴 non-active."""
    lines = ["<b>Axon status</b> (mỗi {} phút)\n".format(INTERVAL_MINUTES)]
    lines.append("<pre>")
    # Header
    lines.append("WALLET     HOTKEY  UID   AXON              STATUS")
    lines.append("-" * 55)
    for r in rows:
        wallet = (r["coldkey_name"] or "")[:10].ljust(10)
        hotkey = (r["hotkey_name"] or "")[:8].ljust(8)
        uid = str(r.get("uid", ""))[:4].ljust(4)
        axon = (r["axon"] or "")[:18].ljust(18)
        status = r.get("status", "")
        if status == "active":
            badge = "🟢 active"
        else:
            badge = "🔴 non-active"
        lines.append("{} {} {} {} {}".format(wallet, hotkey, uid, axon, badge))
    lines.append("</pre>")
    active_count = sum(1 for r in rows if r.get("status") == "active")
    non_active_count = len(rows) - active_count
    lines.append("\n🟢 {} active · 🔴 {} non-active".format(active_count, non_active_count))

    # Gửi thêm từng dòng non-active dạng ip:port/stats để copy
    non_active = [r for r in rows if r.get("status") != "active"]
    if non_active:
        lines.append("\n<b>Copy non-active:</b>")
        lines.append("<pre>")
        for r in non_active:
            axon = (r.get("axon") or "").strip()
            if axon:
                lines.append(axon + "/stats")
        lines.append("</pre>")
    return "\n".join(lines)


def main() -> None:
    print("Telegram axon bot: check mỗi {} phút, gửi tới chat {}".format(INTERVAL_MINUTES, CHAT_ID))
    while True:
        try:
            rows = run_check()
            if rows:
                msg = format_report(rows)
                # Telegram giới hạn 4096 ký tự
                if len(msg) > 4000:
                    msg = msg[:3950] + "\n… (cắt bớt)"
                send_telegram(msg)
                print("Sent report: {} axons, {} active".format(
                    len(rows),
                    sum(1 for r in rows if r.get("status") == "active"),
                ))
            else:
                print("No rows in current_metagraph.csv, skip send.")
        except Exception as e:
            print("Run error:", e)
            send_telegram("Axon check error: {}".format(str(e)[:500]))

        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
