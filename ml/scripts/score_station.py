"""用已训练的模型给一段数据打分并输出告警段。

适用于：① PreDist 里的站；② 国内热力站数据（先做字段映射）。

示例:
  # 给 PreDist 某个站的一段数据打分
  python scripts/score_station.py --model models/M1_s7.pkl --mfr M1 --sid 7 \
      --start 2017-11-19 --end 2017-11-27 --out reports/M1_s7_alarms.csv

  # 给国内 CSV 打分（自动 / 手动映射列名）
  python scripts/score_station.py --model models/M1_s7.pkl --csv 某热力站.csv \
      --time-col 时间 --map "供水温度=s_hc1_supply_temperature" \
      "回水温度=p_hc1_return_temperature" --out 告警.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import load_substation          # noqa: E402
from src.inference import load_model, map_columns  # noqa: E402


def segments(df: pd.DataFrame) -> pd.DataFrame:
    """把逐点告警合并成告警段。"""
    if not df["confirmed"].any():
        return pd.DataFrame(columns=["start", "end", "hours", "peak_score", "max_criticality"])
    flag = df["confirmed"].to_numpy()
    rows, start = [], None
    for i, v in enumerate(flag):
        if v and start is None:
            start = i
        elif not v and start is not None:
            rows.append((start, i - 1))
            start = None
    if start is not None:
        rows.append((start, len(flag) - 1))
    out = []
    for a, b in rows:
        chunk = df.iloc[a:b + 1]
        out.append({
            "start": df.index[a], "end": df.index[b],
            "hours": round((df.index[b] - df.index[a]).total_seconds() / 3600, 1),
            "peak_score": float(chunk["score"].max()),
            "max_criticality": int(chunk["criticality"].max()),
        })
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--mfr", choices=["M1", "M2"], default=None)
    ap.add_argument("--sid", type=int, default=None)
    ap.add_argument("--csv", default=None, help="外部 CSV（国内数据）")
    ap.add_argument("--time-col", default=None)
    ap.add_argument("--map", nargs="*", default=None, help="原始列名=标准列名 ...")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    model = load_model(args.model)

    if args.csv:
        df = pd.read_csv(args.csv)
        mapping = {}
        for item in (args.map or []):
            k, _, v = item.partition("=")
            mapping[k.strip()] = v.strip()
        df = map_columns(df, mapping, args.time_col)
        src = args.csv
    else:
        if not (args.mfr and args.sid):
            raise SystemExit("需要 --mfr/--sid 或 --csv")
        df = load_substation(args.mfr, args.sid)
        src = f"{args.mfr} 站 {args.sid}"

    if args.start or args.end:
        df = df.loc[args.start:args.end]
    if df.empty:
        raise SystemExit("数据为空")

    res = model.detect(df)
    seg = segments(res)

    print(f"数据源: {src}  区间 {df.index.min()} ~ {df.index.max()}  共 {len(df)} 点")
    print(f"告警点 {int(res['confirmed'].sum())} 个 / 确认告警段 {len(seg)} 个")
    if len(seg):
        print(seg.to_string(index=False))
    else:
        print("未触发确认告警（criticality 未达到 C_thr）")

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        res.to_csv(path, encoding="utf-8-sig")
        seg_path = path.with_name(path.stem + "_segments.csv")
        seg.to_csv(seg_path, index=False, encoding="utf-8-sig")
        print(f"逐点结果: {path}\n告警段:   {seg_path}")


if __name__ == "__main__":
    main()
