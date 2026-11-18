"""训练一个站点的正常行为模型并保存（模型产物）。

示例:
  # 用 M1 站 7 最后一年数据训练，存成 models/M1_s7.pkl
  python scripts/train_station_model.py --mfr M1 --sid 7 --out models/M1_s7.pkl

  # 指定训练区间
  python scripts/train_station_model.py --mfr M2 --sid 21 --start 2019-01-01 --end 2019-12-01
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")
sys.path.insert(0, str(ROOT))

from src.inference import save_model, train_station_model  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mfr", required=True, choices=["M1", "M2"])
    ap.add_argument("--sid", required=True, type=int)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--features", default="phys2", choices=["raw", "phys", "phys2"])
    ap.add_argument("--no-cyclic", dest="cyclic", action="store_false", default=True)
    ap.add_argument("--adaptive", action="store_true", default=True)
    ap.add_argument("--no-adaptive", dest="adaptive", action="store_false")
    ap.add_argument("--quantile", type=float, default=0.99)
    ap.add_argument("--c-thr", type=int, default=None)
    ap.add_argument("--max-iter", type=int, default=100)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    t0 = time.time()
    model = train_station_model(
        args.mfr, args.sid, train_start=args.start, train_end=args.end,
        feature_mode=args.features, cyclic=args.cyclic, adaptive=args.adaptive, q=args.quantile,
        c_thr=args.c_thr, max_iter=args.max_iter,
    )
    path = save_model(model, args.out)
    print(f"模型已保存: {path}")
    print(f"  训练样本 {model.meta['n_train']} 行, 特征 {model.meta['n_features']} 个, "
          f"训练区间 {model.meta['train_start']} ~ {model.meta['train_end']}")
    print(f"  异常分数={model.score_kind}, 全局阈值={model.thr_global:.4f}, "
          f"工况自适应={'是' if model.adaptive and model.edges is not None else '否'}, C_thr={model.c_thr}")
    print(f"  耗时 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

