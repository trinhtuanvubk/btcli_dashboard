import csv
import json
import re
from pathlib import Path

import bittensor as bt

OUTPUT_CSV = "metagraph_wallets.csv"


def load_hotkey_mapping(summary_path: Path) -> dict[str, tuple[str, str]]:
    """
    Read wallets_summary.json and return:
      hotkey_address -> (wallet_name, hotkey_name)
    """
    with summary_path.open() as f:
        data = json.load(f)

    mapping: dict[str, tuple[str, str]] = {}
    for wallet_name, info in data.items():
        hotkeys = info.get("hotkeys", {})
        for hotkey_name, hotkey_addr in hotkeys.items():
            mapping[hotkey_addr] = (wallet_name, hotkey_name)
    return mapping


def get_metagraph_rows(base_dir: Path | None = None) -> list[dict]:
    """
    Get list of (coldkey_name, hotkey_name, uid, axon) from metagraph.
    Returns list[dict] for web or CLI use.
    """
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent
    summary_path = base_dir / "wallets_82.json"

    hotkey_map = load_hotkey_mapping(summary_path)

    subtensor = bt.Subtensor(network="finney")
    metagraph = subtensor.metagraph(netuid=82)

    # Compute incentive-based rank for every UID (1 = highest incentive)
    incentives = metagraph.incentive.tolist()
    uid_rank: dict[int, int] = {}
    for rank, (uid_i, _inc) in enumerate(
        sorted(enumerate(incentives), key=lambda x: x[1], reverse=True), start=1
    ):
        uid_rank[uid_i] = rank

    rows: list[tuple[str, str, int, str, int, float]] = []
    for uid, axon in enumerate(metagraph.axons):
        hotkey_addr = axon.hotkey

        if hotkey_addr not in hotkey_map:
            continue

        wallet_name, hotkey_name = hotkey_map[hotkey_addr]
        axon_short = f"{axon.ip}:{axon.port}"
        rows.append((wallet_name, hotkey_name, uid, axon_short, uid_rank.get(uid, 0), incentives[uid]))

    try:
        subtensor.substrate.close()
    except Exception:
        pass
    del metagraph, subtensor

    def _num(s: str) -> int:
        m = re.search(r"\d+", s)
        return int(m.group(0)) if m else 0

    rows.sort(key=lambda r: (_num(r[0]), _num(r[1])))

    return [
        {"coldkey_name": r[0], "hotkey_name": r[1], "uid": r[2], "axon": r[3], "rank": r[4], "incentive": r[5]}
        for r in rows
    ]


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    rows_data = get_metagraph_rows(base_dir)

    # Write CSV
    csv_path = base_dir / OUTPUT_CSV
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["coldkey_name", "hotkey_name", "uid", "axon"])
        for r in rows_data:
            w.writerow([r["coldkey_name"], r["hotkey_name"], r["uid"], r["axon"]])
    print(f"Wrote {len(rows_data)} rows to {csv_path}")

    rows = [(r["coldkey_name"], r["hotkey_name"], r["uid"], r["axon"]) for r in rows_data]

    headers = ("WALLET", "HOTKEY", "UID", "AXON")
    col_widths = [
        max(len(str(x)) for x in ([h] + [r[i] for r in rows]))
        for i, h in enumerate(headers)
    ]

    def fmt_row(vals):
        return " | ".join(str(v).ljust(col_widths[i]) for i, v in enumerate(vals))

    print(fmt_row(headers))
    print("-+-".join("-" * w for w in col_widths))
    for r in rows:
        print(fmt_row(r))


if __name__ == "__main__":
    main()

