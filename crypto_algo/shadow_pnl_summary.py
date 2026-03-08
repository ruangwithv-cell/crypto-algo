from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Telegram-friendly shadow PnL summary text")
    p.add_argument("--csv-path", type=Path, required=True)
    p.add_argument("--state-json", type=Path, default=None)
    p.add_argument("--out-path", type=Path, required=True)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.csv_path.exists():
        msg = ["SHADOW PNL UPDATE", "status=initialized_no_pnl_row_yet"]
        if args.state_json and args.state_json.exists():
            import json

            st = json.loads(args.state_json.read_text())
            msg.append(f"shadow_nav={float(st.get('nav', 1.0)):.4f}")
            if st.get("last_day_ms"):
                from datetime import datetime, timezone

                d = datetime.fromtimestamp(int(st["last_day_ms"]) / 1000, tz=timezone.utc).date().isoformat()
                msg.append(f"last_day_utc={d}")
        args.out_path.parent.mkdir(parents=True, exist_ok=True)
        args.out_path.write_text("\n".join(msg) + "\n")
        print(args.out_path)
        return 0

    rows = []
    with args.csv_path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    if not rows:
        args.out_path.parent.mkdir(parents=True, exist_ok=True)
        args.out_path.write_text("SHADOW PNL UPDATE\nstatus=no_pnl_rows_yet\n")
        print(args.out_path)
        return 0

    x = rows[-1]
    msg = []
    msg.append("SHADOW PNL UPDATE")
    msg.append(f"day_utc={x['day_utc']}")
    msg.append(f"daily_return={float(x['daily_return']):+.2%}")
    msg.append(f"shadow_nav={float(x['shadow_nav']):.4f}")
    msg.append(f"price_component={float(x['price_component']):+.2%}")
    msg.append(f"funding_component={float(x['funding_component']):+.2%}")
    msg.append(f"positions_prev={x['n_positions_prev']} gross_prev={float(x['gross_prev']):.2%}")
    msg.append(f"positions_curr={x['n_positions_curr']} gross_curr={float(x['gross_curr']):.2%}")
    msg.append(f"symbols_used={x['symbols_used']}")
    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    args.out_path.write_text("\n".join(msg) + "\n")
    print(args.out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
