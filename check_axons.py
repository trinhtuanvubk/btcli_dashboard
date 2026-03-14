"""
Đọc toàn bộ axon từ current_metagraph.csv, curl thử từng axon.
Timeout -> trả về non-active; có response text -> in ra.
"""

import csv
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CURRENT_CSV = BASE_DIR / "current_metagraph.csv"
DEFAULT_TIMEOUT = 15  # giây (một số axon phản hồi chậm)
DEFAULT_SLEEP = 1.0  # giây giữa mỗi request (nhiều axon cùng 1 máy AWS → tránh rate limit)
RETRIES = 2  # số lần retry khi timeout / No route to host (mạng có thể tạm thời)
# Giả browser để server không chặn (nhiều axon chỉ chấp nhận request giống browser)
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/json,application/xhtml+xml,*/*",
}


def read_axons_from_metagraph(csv_path: Path | None = None) -> list[dict]:
    """Đọc toàn bộ axon từ file current_metagraph. Trả về list dict có coldkey_name, hotkey_name, uid, axon."""
    path = csv_path or CURRENT_CSV
    if not path.exists():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            axon = (row.get("axon") or "").strip()
            if axon:
                rows.append({
                    "coldkey_name": row.get("coldkey_name", ""),
                    "hotkey_name": row.get("hotkey_name", ""),
                    "uid": row.get("uid", ""),
                    "axon": axon,
                })
    return rows


def _fetch(url: str, timeout: int, use_https: bool = False) -> tuple[str, str]:
    """GET một URL. Trả về ('active', body) hoặc ('non-active', error_msg)."""
    try:
        ctx = None
        if use_https:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, method="GET", headers=REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return "active", body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return "active", body or f"(HTTP {e.code} {e.reason})"
    except (TimeoutError, urllib.error.URLError, OSError, Exception) as e:
        msg = str(e).strip()
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            msg = "(timeout)"
        elif "SSH-2.0" in msg or "OpenSSH" in msg:
            msg = "Port đang trả SSH, không phải HTTP — kiểm tra lại port trong metagraph."
        elif "no route to host" in msg.lower() or "errno 113" in msg.lower() or "network is unreachable" in msg.lower():
            msg = "No route to host — máy đang chạy script không có đường đi tới IP này (không phải do inbound đích). Thử chạy script từ máy/VPC cùng mạng với axon hoặc từ nơi ping được axon."
        return "non-active", msg


def check_axon(
    axon_addr: str,
    path: str = "/stats",
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = RETRIES,
    try_https: bool = True,
) -> tuple[str, str]:
    """
    Gửi GET tới http(s)://<axon><path>. Retry khi timeout/No route to host; thử HTTPS nếu HTTP lỗi.
    active: có bất kỳ HTTP response nào (2xx, 4xx, 5xx).
    non-active: sau hết retry vẫn không kết nối được.
    """
    base = axon_addr.rstrip("/")
    full_path = path
    # Thử HTTP (có retry)
    last_err = ""
    for attempt in range(retries + 1):
        url = f"http://{base}{full_path}"
        status, text = _fetch(url, timeout, use_https=False)
        if status == "active":
            return "active", text
        last_err = text
        if attempt < retries:
            time.sleep(1.5)
    # Thử HTTPS một lần (một số axon chỉ bật HTTPS)
    if try_https:
        url = f"https://{base}{full_path}"
        status, text = _fetch(url, timeout, use_https=True)
        if status == "active":
            return "active", text
    return "non-active", last_err


def main(
    csv_path: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    sleep_sec: float = DEFAULT_SLEEP,
    retries: int = RETRIES,
    try_https: bool = True,
    verbose: bool = True,
) -> None:
    """Đọc axons từ metagraph, curl từng cái và in kết quả."""
    rows = read_axons_from_metagraph(csv_path)
    if not rows:
        print("Không có axon nào trong current_metagraph (hoặc file không tồn tại).")
        return

    print(f"Tổng số axon: {len(rows)} (sleep {sleep_sec}s giữa mỗi request)\n")

    for i, r in enumerate(rows):
        axon = r["axon"]
        label = f"{r['coldkey_name']}/{r['hotkey_name']} uid={r['uid']} {axon}/stats"
        status, text = check_axon(axon, timeout=timeout, retries=retries, try_https=try_https)

        print(f"[{status.upper()}] {label}")
        if status == "active" and text:
            # In response text, giới hạn vài dòng nếu quá dài
            lines = text.strip().splitlines()
            if len(lines) <= 10:
                print(text.strip())
            else:
                print("\n".join(lines[:10]))
                print(f"... ({len(lines)} dòng total, cắt bớt)")
        elif status == "non-active" and verbose:
            print(f"  -> {text}")
        print()

        if sleep_sec > 0 and i < len(rows) - 1:
            time.sleep(sleep_sec)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Check axons từ current_metagraph.csv")
    parser.add_argument("--csv", type=Path, default=None, help="Đường dẫn CSV (mặc định: current_metagraph.csv)")
    parser.add_argument("--timeout", type=int, default=20, help="Timeout mỗi request (giây)")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP, help="Sleep giữa mỗi request (giây), 0 = tắt")
    parser.add_argument("--retries", type=int, default=RETRIES, help="Số lần retry khi timeout / No route to host")
    parser.add_argument("--no-https", action="store_true", help="Không thử HTTPS khi HTTP lỗi")
    parser.add_argument("-q", "--quiet", action="store_true", help="Chỉ in active/non-active, không in chi tiết lỗi")
    args = parser.parse_args()

    main(
        csv_path=args.csv,
        timeout=args.timeout,
        sleep_sec=args.sleep,
        retries=args.retries,
        try_https=not args.no_https,
        verbose=not args.quiet,
    )
