# -*- coding: utf-8 -*-
"""
PreDist Dataset（Fraunhofer IEE，93 个集中供热换热站）数据清点脚本
====================================================================

只读原始数据目录，只写本目录（勘探/）下的结果文件。
可重复运行，默认全量重建：

    python build_profile.py              # 全量清点 + 生成报告
    python build_profile.py --report     # 不重读 CSV，仅用已有结果重生成 data_inventory.md

输出：
    substation_profile.csv            每站一行（含逐特征缺失率 miss_* 列）
    null_profile_by_substation.csv    站 × 特征 缺失率矩阵（附表）
    feature_presence_by_manufacturer.csv  每个特征在多少站出现（M1/M2）
    feature_value_quality.csv         站 × 特征 数值质量（缺失率/极值/零值率/物理越界）
    fault_events_enriched.csv         故障事件 + 训练窗口覆盖率 + 可用性判定
    normal_events_enriched.csv        正常事件 + 训练窗口覆盖率 + 可用性判定
    fault_label_distribution.csv      Fault label / Monitoring potential 分布
    disturbance_type_distribution.csv disturbance type 分布
    known_anomalies.csv               README 末尾“已知异常表”结构化
    profile_summary.json              报告所需的全部汇总数字
    data_inventory.md                 中文数据清点与质量报告
    build_log.txt                     运行日志
"""

import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# 路径与常量（硬编码，保证可重跑）
# ----------------------------------------------------------------------------
BASE = Path(r"C:\Users\lzh\Desktop\AI\供热管道\数据")
OUT = Path(r"C:\Users\lzh\Desktop\AI\供热管道\工作站\勘探")
OUT.mkdir(parents=True, exist_ok=True)

MANS = [("manufacturer 1", "M1"), ("manufacturer 2", "M2")]

USABLE_MISS_THRESHOLD = 0.20      # 非空率 >= 80% 视为可用特征
TEMP_LO, TEMP_HI = -30.0, 150.0   # 温度类特征物理合理区间（°C）
INSIDE_TOL = pd.Timedelta(days=1) # 训练窗口“落在数据范围内”的容差
MIN_TRAIN_DAYS = 30.0             # 训练窗口最短天数（可训练性红线）
MIN_COVERAGE = 0.80               # 窗口时间覆盖率红线
MIN_USABLE_FEAT = 8               # 建模站最少可用特征数

LOG_PATH = OUT / "build_log.txt"
_log_fh = None


def log(msg=""):
    print(msg, flush=True)
    if _log_fh is not None:
        _log_fh.write(str(msg) + "\n")
        _log_fh.flush()


# ----------------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------------
def parse_dates(s):
    """混合时间格式解析（M2 存在 .310497 之类小数秒），无法解析记为 NaT。"""
    return pd.to_datetime(s, format="mixed", errors="coerce")


def to_py(o):
    """把 numpy / pandas 类型转为可 json 序列化的 python 类型。"""
    if isinstance(o, dict):
        return {str(k): to_py(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [to_py(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d %H:%M:%S")
    if o is pd.NaT:
        return None
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def safe_round(x, n=4):
    try:
        if x is None or (isinstance(x, float) and not math.isfinite(x)):
            return None
        return round(float(x), n)
    except Exception:
        return None


def fmt_num(x, n=2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:,.{n}f}"


def fmt_pct(x, n=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{100.0 * x:.{n}f}%"


def station_file_id(p: Path):
    return int(p.stem.split("_")[1])


def read_meta(mdir: Path):
    """读取一个厂商目录下的标签/配置/特征说明文件。"""
    meta = {}

    faults = pd.read_csv(mdir / "faults.csv", sep=";")
    faults["substation ID"] = pd.to_numeric(faults["substation ID"], errors="coerce").astype("Int64")
    for col in ["Report date", "Possible anomaly start", "Possible anomaly end",
                "Training start", "Training end"]:
        faults[col] = parse_dates(faults[col])
    faults["efd_bool"] = faults["efd_possible"].map({True: True, False: False, "True": True, "False": False})
    faults["monitoring_num"] = pd.to_numeric(faults["Monitoring potential"], errors="coerce")
    meta["faults"] = faults

    normal = pd.read_csv(mdir / "normal_events.csv", sep=";")
    normal["substation ID"] = pd.to_numeric(normal["substation ID"], errors="coerce").astype("Int64")
    for col in ["Event start", "Event end", "Training start", "Training end"]:
        normal[col] = parse_dates(normal[col])
    meta["normal_events"] = normal

    dist = pd.read_csv(mdir / "disturbances.csv", sep=";")
    dist["substation ID"] = pd.to_numeric(dist["substation ID"], errors="coerce").astype("Int64")
    dist["Event start"] = parse_dates(dist["Event start"])
    meta["disturbances"] = dist

    cfg = pd.read_csv(mdir / "configuration_types.csv", sep=";")
    cfg["substation ID"] = pd.to_numeric(cfg["substation ID"], errors="coerce").astype("Int64")
    meta["config"] = cfg

    fd = pd.read_csv(mdir / "feature_descriptions.csv", sep=";")
    if "unit" not in fd.columns:
        fd["unit"] = ""
    meta["feature_desc"] = fd
    return meta


def read_known_anomalies():
    """解析 README 末尾已知异常表。"""
    rows = []
    readme = (BASE / "README.md").read_text(encoding="utf-8")
    for line in readme.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 5:
            continue
        if cells[0].lower().startswith("manufacturer") or set(cells[0]) <= {"-", " "}:
            continue
        if not cells[0].isdigit():
            continue
        rows.append({
            "manufacturer": f"M{cells[0]}",
            "substation_id": int(cells[1]),
            "from": cells[2],
            "to": cells[3],
            "description": cells[4],
        })
    return rows


# ----------------------------------------------------------------------------
# 窗口覆盖率
# ----------------------------------------------------------------------------
def window_coverage(ts_arr, s, e, med_sec):
    """返回 (窗口内行数, 期望行数, 覆盖率)；参数不合法返回 (None, None, None)。"""
    if ts_arr is None or med_sec is None or not np.isfinite(med_sec) or med_sec <= 0:
        return None, None, None
    if pd.isna(s) or pd.isna(e):
        return None, None, None
    if e < s:
        return 0, 0, 0.0
    s64 = np.datetime64(s.to_datetime64())
    e64 = np.datetime64(e.to_datetime64())
    a = int(np.searchsorted(ts_arr, s64, side="left"))
    b = int(np.searchsorted(ts_arr, e64, side="right"))
    n = b - a
    expected = (e - s).total_seconds() / float(med_sec) + 1.0
    cov = n / expected if expected > 0 else 0.0
    return n, float(expected), float(cov)


# ----------------------------------------------------------------------------
# 主计算
# ----------------------------------------------------------------------------
def compute():
    global _log_fh
    _log_fh = open(LOG_PATH, "w", encoding="utf-8")
    t0 = time.time()
    log("=" * 78)
    log("PreDist 数据清点：开始")
    log(f"数据目录: {BASE}")
    log(f"输出目录: {OUT}")
    log("=" * 78)

    known_anomalies = read_known_anomalies()
    pd.DataFrame(known_anomalies).to_csv(OUT / "known_anomalies.csv", index=False, encoding="utf-8-sig")
    log(f"README 已知异常表解析到 {len(known_anomalies)} 条")

    meta_by_man = {}
    feature_units = {}       # (man, feature) -> unit
    feature_has_desc = defaultdict(set)  # man -> 有说明的列名
    for mdir_name, man in MANS:
        mdir = BASE / mdir_name
        meta_by_man[man] = read_meta(mdir)
        m = meta_by_man[man]
        for _, r in m["feature_desc"].iterrows():
            col = str(r["column"]).strip()
            feature_units[(man, col)] = str(r["unit"]) if pd.notna(r["unit"]) else None
            feature_has_desc[man].add(col)
        log(f"[{man}] 站配置文件 {len(m['config'])} 行, faults {len(m['faults'])} 条, "
            f"normal_events {len(m['normal_events'])} 条, disturbances {len(m['disturbances'])} 条")

    # ---------------- 逐站扫描 ----------------
    profile_rows = []          # 每站一行
    station_ctx = {}           # (man, sid) -> dict
    feature_presence = defaultdict(int)     # (man, feature) -> 站数
    station_features = defaultdict(list)    # man -> 有文件的站 id
    feature_quality_rows = []  # 站 × 特征 数值质量
    hash_grid = defaultdict(list)           # 时间戳指纹 -> [(man, sid)]
    man_station_meta = defaultdict(lambda: {
        "n_files": 0, "total_rows": 0, "t_start": None, "t_end": None,
        "intervals": [], "dups": 0, "ooo": 0, "max_gap_h": [],
        "span_days": [], "time_cov": [], "bad_ts": 0,
    })

    for mdir_name, man in MANS:
        mdir = BASE / mdir_name
        files = sorted((mdir / "operational_data").glob("substation_*.csv"), key=station_file_id)
        log(f"\n[{man}] 开始扫描 {len(files)} 个 CSV ...")
        for k, f in enumerate(files, 1):
            sid = station_file_id(f)
            station_ctx[(man, sid)] = {}
            df = pd.read_csv(f, sep=";", low_memory=False)
            ts = parse_dates(df["timestamp"])
            raw_cols = [c for c in df.columns if c != "timestamp"]
            for c in raw_cols:
                feature_presence[(man, c)] += 1
            station_features[man].append(sid)

            # --- 时间戳质量 ---
            n_rows = len(df)
            n_bad_ts = int(ts.isna().sum())
            dup_ts = int(ts.duplicated().sum())
            ooo = int((ts.diff() < pd.Timedelta(0)).sum())
            t = pd.to_datetime(ts.dropna()).sort_values()
            if len(t) >= 2:
                span_days = (t.iloc[-1] - t.iloc[0]).total_seconds() / 86400.0
                diffs = t.diff().dropna()
                pos = diffs[diffs > pd.Timedelta(0)]
                med_sec = float(pos.median().total_seconds()) if len(pos) else None
                max_gap_h = float(diffs.max().total_seconds() / 3600.0) if len(diffs) else None
            else:
                span_days, med_sec, max_gap_h = 0.0, None, None
            time_cov = None
            if med_sec and span_days > 0:
                expected = span_days * 86400.0 / med_sec + 1.0
                time_cov = min(1.0, n_rows / expected)
            ts_hash = None
            if len(t):
                ts_hash = hashlib.md5(t.values.tobytes()).hexdigest()
                hash_grid[ts_hash].append((man, sid))
            ts_arr = t.values.astype("datetime64[ns]") if len(t) else None

            # --- 逐特征缺失率 ---
            miss = df[raw_cols].isna().mean()
            null_rates = {c: float(miss[c]) for c in raw_cols}

            # --- 数值 / 类别列划分 ---
            num_cols = [c for c in raw_cols if pd.api.types.is_numeric_dtype(df[c])]
            cat_cols = [c for c in raw_cols if c not in num_cols]
            converted = {}
            for c in list(cat_cols):
                ser = df[c]
                nv = ser.notna().sum()
                if nv == 0:
                    continue
                conv = pd.to_numeric(ser, errors="coerce")
                if conv.notna().sum() / nv >= 0.99:
                    converted[c] = conv
            num_df = df[num_cols].copy()
            for c, v in converted.items():
                num_df[c] = v
            all_num = list(num_df.columns)
            numeric_ok = set(num_cols) | set(converted)
            cat_only = [c for c in raw_cols if c not in numeric_ok]

            nunique = df[raw_cols].nunique(dropna=True)
            all_nan_feats = [c for c in raw_cols if null_rates[c] >= 0.999]
            avail_feats = [c for c in raw_cols
                           if null_rates[c] <= USABLE_MISS_THRESHOLD and nunique.get(c, 0) >= 2]
            full_feats = [c for c in raw_cols if null_rates[c] <= USABLE_MISS_THRESHOLD]
            high_miss = [c for c in raw_cols if null_rates[c] > 0.5]
            very_high_miss = [c for c in raw_cols if null_rates[c] > 0.8]
            worst_feat = max(null_rates.items(), key=lambda kv: kv[1]) if null_rates else ("", None)

            # --- 数值统计（向量化）---
            if all_num:
                stats = num_df.agg(["min", "max", "mean"]).T
                notna_cnt = num_df.notna().sum()
                zero_rate = (num_df == 0).sum() / notna_cnt.replace(0, np.nan)
            else:
                stats = pd.DataFrame(columns=["min", "max", "mean"])
                zero_rate = pd.Series(dtype=float)

            temp_cols = [c for c in all_num if ("temperature" in c.lower() or c.lower().endswith("_temp"))]
            if temp_cols:
                out_cnt = ((num_df[temp_cols] < TEMP_LO) | (num_df[temp_cols] > TEMP_HI)).sum()
            else:
                out_cnt = pd.Series(dtype=int)

            for c in raw_cols:
                kind = "numeric" if c in numeric_ok else "categorical"
                row = {
                    "manufacturer": man,
                    "substation_id": sid,
                    "feature": c,
                    "kind": kind,
                    "null_rate": null_rates[c],
                    "n_valid": int(df[c].notna().sum()),
                }
                if c in all_num:
                    row["min"] = float(stats.loc[c, "min"]) if pd.notna(stats.loc[c, "min"]) else None
                    row["max"] = float(stats.loc[c, "max"]) if pd.notna(stats.loc[c, "max"]) else None
                    row["mean"] = float(stats.loc[c, "mean"]) if pd.notna(stats.loc[c, "mean"]) else None
                    row["zero_rate"] = float(zero_rate.get(c, np.nan)) if np.isfinite(zero_rate.get(c, np.nan)) else None
                    row["out_of_range_temp"] = int(out_cnt.get(c, 0)) if c in temp_cols else None
                else:
                    vc = df[c].value_counts(dropna=True)
                    row["top_value"] = str(vc.index[0]) if len(vc) else None
                    row["top_share"] = float(vc.iloc[0] / vc.sum()) if len(vc) else None
                    row["n_unique"] = int(nunique.get(c, 0))
                row["unit"] = feature_units.get((man, c))
                feature_quality_rows.append(row)

            # --- 表计质量（能量/流量/功率）---
            meter_feats = [c for c in raw_cols if c.startswith("p_net_meter_")]
            meter_info = {}
            for c in meter_feats:
                if c not in all_num:
                    continue
                ser = num_df[c]
                nv = int(ser.notna().sum())
                zr = float((ser == 0).sum() / nv) if nv else None
                # 累积量表：非递增比例
                non_inc = None
                if c in ("p_net_meter_energy", "p_net_meter_volume") and nv > 2:
                    d = ser.dropna().diff().dropna()
                    non_inc = float((d <= 0).mean()) if len(d) else None
                meter_info[c] = {
                    "null_rate": null_rates[c], "zero_rate": zr, "non_increasing_rate": non_inc,
                    "min": float(ser.min()) if nv else None, "max": float(ser.max()) if nv else None,
                }

            rec = {
                "manufacturer": man,
                "substation_id": sid,
                "configuration_type": None,
                "row_count": n_rows,
                "t_start": t.iloc[0] if len(t) else None,
                "t_end": t.iloc[-1] if len(t) else None,
                "时间跨度天数": span_days,
                "采样间隔中位数(分钟)": med_sec / 60.0 if med_sec else None,
                "时间戳重复数": dup_ts,
                "时间戳乱序数": ooo,
                "最大连续缺失间隔(小时)": max_gap_h,
                "时间覆盖率": time_cov,
                "可用特征数量": len(avail_feats),
                "非空率>=80%特征数": len(full_feats),
                "全空特征数": len(all_nan_feats),
                "全空特征列表": "|".join(all_nan_feats),
                "缺失率>50%特征数": len(high_miss),
                "缺失率>80%特征数": len(very_high_miss),
                "特征平均缺失率": float(np.mean([null_rates[c] for c in raw_cols])) if raw_cols else None,
                "最大单特征缺失率": float(worst_feat[1]) if worst_feat[1] is not None else None,
                "最大单特征缺失率_特征": worst_feat[0],
                "n_features": len(raw_cols),
                "n_bad_timestamp": n_bad_ts,
                "n_1min_intervals": 0,
                "features": raw_cols,
            }
            if med_sec:
                # “1 分钟粒度”：M2 部分文件开头 24h 存在 ±1s 抖动的 1 分钟间隔
                secs = diffs.dt.total_seconds()
                rec["n_1min_intervals"] = int(((secs >= 55) & (secs <= 65)).sum())
            rec["n_nonzero_second_rows"] = int((t.dt.second != 0).sum()) if len(t) else 0
            for c in raw_cols:
                rec["miss_" + c] = null_rates[c]
            profile_rows.append(rec)
            outdoor_stats = None
            if "outdoor_temperature" in df.columns:
                o = df["outdoor_temperature"]
                outdoor_stats = {
                    "nunique": int(o.nunique()), "min": float(o.min()) if o.notna().any() else None,
                    "max": float(o.max()) if o.notna().any() else None,
                    "null_rate": float(o.isna().mean()),
                }
            station_ctx[(man, sid)] = {
                "ts_arr": ts_arr, "med_sec": med_sec,
                "t_min": t.iloc[0] if len(t) else None,
                "t_max": t.iloc[-1] if len(t) else None,
                "span_days": span_days, "n_rows": n_rows,
                "usable_feats": len(avail_feats), "null_rates": null_rates,
                "meter": meter_info, "features": raw_cols,
                "outdoor": outdoor_stats,
                "n_1min": rec["n_1min_intervals"],
                "n_sec_jitter": rec["n_nonzero_second_rows"],
            }
            mm = man_station_meta[man]
            mm["n_files"] += 1
            mm["total_rows"] += n_rows
            mm["dups"] += dup_ts
            mm["ooo"] += ooo
            mm["bad_ts"] += n_bad_ts
            if len(t):
                mm["t_start"] = t.iloc[0] if mm["t_start"] is None else min(mm["t_start"], t.iloc[0])
                mm["t_end"] = t.iloc[-1] if mm["t_end"] is None else max(mm["t_end"], t.iloc[-1])
            if med_sec:
                mm["intervals"].append(med_sec / 60.0)
            mm["max_gap_h"].append(max_gap_h)
            mm["span_days"].append(span_days)
            if time_cov is not None:
                mm["time_cov"].append(time_cov)
            if k % 5 == 0 or k == len(files):
                log(f"  [{man}] {k}/{len(files)} 站完成  (累计 {time.time()-t0:.1f}s)")

    # ---------------- 配置类型、标签计数 ----------------
    for man in meta_by_man:
        cfg = meta_by_man[man]["config"].set_index("substation ID")["configuration_type"]
        for rec in profile_rows:
            if rec["manufacturer"] != man:
                continue
            sid = rec["substation_id"]
            rec["configuration_type"] = cfg.get(sid) if sid in cfg.index else None
            if pd.isna(rec["configuration_type"]):
                rec["configuration_type"] = None

    # 逐站标签计数
    for rec in profile_rows:
        man, sid = rec["manufacturer"], rec["substation_id"]
        m = meta_by_man[man]
        rec["fault_event_count"] = int((m["faults"]["substation ID"] == sid).sum())
        rec["normal_event_count"] = int((m["normal_events"]["substation ID"] == sid).sum())
        rec["total_disturbance_count"] = int((m["disturbances"]["substation ID"] == sid).sum())
        d = m["disturbances"]
        sub_d = d[d["substation ID"] == sid]
        rec["disturbance_fault_count"] = int((sub_d["type"] == "fault").sum())
        rec["disturbance_task_count"] = int((sub_d["type"] == "task").sum())
        rec["disturbance_activity_count"] = int((sub_d["type"] == "activity").sum())

    # ---------------- 事件表增强 ----------------
    def enrich(events, man):
        out = []
        for _, ev in events.iterrows():
            rec = {"manufacturer": man, "event_id": ev.get("Event ID"),
                   "substation_id": int(ev["substation ID"]) if pd.notna(ev["substation ID"]) else None}
            sid = rec["substation_id"]
            ctx = station_ctx.get((man, sid))
            rec["station_has_data"] = ctx is not None
            if ctx:
                rec["station_row_count"] = ctx["n_rows"]
                rec["station_t_start"] = ctx["t_min"]
                rec["station_t_end"] = ctx["t_max"]
                rec["station_span_days"] = round(ctx["span_days"], 2)
                rec["station_interval_min"] = ctx["med_sec"] / 60.0 if ctx["med_sec"] else None
                rec["station_usable_features"] = ctx["usable_feats"]
            if "Report date" in ev.index:
                rec["report_date"] = ev["Report date"]
                if ctx and pd.notna(ev["Report date"]):
                    rec["report_inside_data"] = bool(ctx["t_min"] <= ev["Report date"] <= ctx["t_max"])
                elif ctx:
                    rec["report_inside_data"] = None
            ts_arr = ctx["ts_arr"] if ctx else None
            med = ctx["med_sec"] if ctx else None

            # 训练窗口
            ts_s, ts_e = ev["Training start"], ev["Training end"]
            rec["train_start"] = ts_s
            rec["train_end"] = ts_e
            rec["train_nonnull"] = bool(pd.notna(ts_s) and pd.notna(ts_e))
            if rec["train_nonnull"]:
                rec["train_days"] = round((ts_e - ts_s).total_seconds() / 86400.0, 2)
            else:
                rec["train_days"] = None
            if rec["train_nonnull"] and ctx:
                rec["train_inside_span"] = bool(ts_s >= ctx["t_min"] - INSIDE_TOL and
                                                ts_e <= ctx["t_max"] + INSIDE_TOL)
            else:
                rec["train_inside_span"] = None
            n, exp, cov = window_coverage(ts_arr, ts_s, ts_e, med)
            rec["train_rows_in_window"], rec["train_expected_rows"], rec["train_coverage"] = n, exp, cov

            # 测试/异常窗口
            if "Possible anomaly start" in ev.index:
                a_s, a_e = ev["Possible anomaly start"], ev["Possible anomaly end"]
            else:
                a_s, a_e = ev["Event start"], ev["Event end"]
            rec["test_start"], rec["test_end"] = a_s, a_e
            rec["test_nonnull"] = bool(pd.notna(a_s) and pd.notna(a_e))
            if rec["test_nonnull"]:
                rec["test_days"] = round((a_e - a_s).total_seconds() / 86400.0, 2)
            else:
                rec["test_days"] = None
            if rec["test_nonnull"] and ctx:
                rec["test_inside_span"] = bool(a_s >= ctx["t_min"] - INSIDE_TOL and
                                               a_e <= ctx["t_max"] + INSIDE_TOL)
            else:
                rec["test_inside_span"] = None
            n2, exp2, cov2 = window_coverage(ts_arr, a_s, a_e, med)
            rec["test_rows_in_window"], rec["test_expected_rows"], rec["test_coverage"] = n2, exp2, cov2

            # 可用性判定
            flags = []
            if ctx is None:
                flags.append("station_missing")
            if not rec["train_nonnull"]:
                flags.append("no_training_window")
            if rec["train_nonnull"] and ctx:
                if not rec["train_inside_span"]:
                    flags.append("window_outside_data")
                if rec["train_days"] is not None and rec["train_days"] < MIN_TRAIN_DAYS:
                    flags.append("train_too_short")
                if cov is not None and cov < MIN_COVERAGE:
                    flags.append("data_coverage_low")
                if ctx["usable_feats"] < MIN_USABLE_FEAT:
                    flags.append("too_few_usable_features")
            rec["issues"] = "|".join(flags)
            rec["usable_for_modeling"] = bool(len(flags) == 0)
            # 记 efd / label
            if "efd_bool" in ev.index:
                rec["efd_possible"] = ev["efd_bool"] if pd.notna(ev["efd_bool"]) else None
            if "Fault label" in ev.index:
                rec["fault_label"] = ev["Fault label"]
                rec["monitoring_potential"] = ev["Monitoring potential"]
                rec["problem_en"] = ev["Problem EN"]
            out.append(rec)
        return pd.DataFrame(out)

    faults_enr = []
    normal_enr = []
    for man in ["M1", "M2"]:
        m = meta_by_man[man]
        faults_enr.append(enrich(m["faults"], man))
        normal_enr.append(enrich(m["normal_events"], man))
    faults_enr = pd.concat(faults_enr, ignore_index=True)
    normal_enr = pd.concat(normal_enr, ignore_index=True)

    # ---------------- 写 CSV ----------------
    prof_df = pd.DataFrame(profile_rows)
    # 列顺序：先指定列，再把 miss_* 逐特征列附在后面
    base_cols = [
        "manufacturer", "substation_id", "configuration_type", "row_count", "t_start", "t_end",
        "时间跨度天数", "采样间隔中位数(分钟)", "时间戳重复数", "时间戳乱序数",
        "最大连续缺失间隔(小时)", "时间覆盖率", "特征平均缺失率", "最大单特征缺失率",
        "最大单特征缺失率_特征", "缺失率>50%特征数", "缺失率>80%特征数",
        "可用特征数量", "非空率>=80%特征数", "全空特征数", "全空特征列表",
        "n_features", "n_bad_timestamp", "n_1min_intervals", "fault_event_count", "normal_event_count",
        "total_disturbance_count", "disturbance_fault_count", "disturbance_task_count",
        "disturbance_activity_count",
    ]
    miss_cols = [c for c in prof_df.columns if c.startswith("miss_")]
    out_cols = base_cols + sorted(miss_cols)
    prof_df = prof_df[out_cols].sort_values(["manufacturer", "substation_id"]).reset_index(drop=True)
    prof_df.to_csv(OUT / "substation_profile.csv", index=False, encoding="utf-8-sig")
    log(f"\n写出 substation_profile.csv : {prof_df.shape[0]} 行 × {prof_df.shape[1]} 列")

    # 缺失率矩阵（宽表）
    feature_order = []
    for man in ["M1", "M2"]:
        for c in sorted([k[1] for k in feature_presence if k[0] == man]):
            if c not in feature_order:
                feature_order.append(c)
    matrices = []
    for rec in profile_rows:
        row = {"manufacturer": rec["manufacturer"], "substation_id": rec["substation_id"]}
        for c in feature_order:
            row[c] = rec.get("miss_" + c)
        matrices.append(row)
    null_mat = pd.DataFrame(matrices).sort_values(["manufacturer", "substation_id"]).reset_index(drop=True)
    null_mat.to_csv(OUT / "null_profile_by_substation.csv", index=False, encoding="utf-8-sig")
    log(f"写出 null_profile_by_substation.csv : {null_mat.shape[0]} 行 × {null_mat.shape[1]} 列")

    # 特征存在性
    presence_rows = []
    for man in ["M1", "M2"]:
        n_st = len(station_features[man])
        for c in sorted([k[1] for k in feature_presence if k[0] == man]):
            presence_rows.append({
                "manufacturer": man, "feature": c,
                "n_stations_with_column": feature_presence[(man, c)],
                "n_stations_total": n_st,
                "share": feature_presence[(man, c)] / n_st,
                "unit": feature_units.get((man, c)),
                "in_feature_descriptions": c in feature_has_desc[man],
            })
    presence_df = pd.DataFrame(presence_rows)
    presence_df.to_csv(OUT / "feature_presence_by_manufacturer.csv", index=False, encoding="utf-8-sig")
    log(f"写出 feature_presence_by_manufacturer.csv : {presence_df.shape[0]} 行")

    # 逐特征数值质量
    fq = pd.DataFrame(feature_quality_rows)
    fq["null_rate"] = fq["null_rate"].astype(float)
    fq = fq.sort_values(["manufacturer", "substation_id", "feature"]).reset_index(drop=True)
    fq.to_csv(OUT / "feature_value_quality.csv", index=False, encoding="utf-8-sig")
    log(f"写出 feature_value_quality.csv : {fq.shape[0]} 行")

    faults_enr.to_csv(OUT / "fault_events_enriched.csv", index=False, encoding="utf-8-sig")
    normal_enr.to_csv(OUT / "normal_events_enriched.csv", index=False, encoding="utf-8-sig")
    log(f"写出 fault_events_enriched.csv / normal_events_enriched.csv : "
        f"{len(faults_enr)} / {len(normal_enr)} 行")

    # ---------------- 汇总统计 ----------------
    summary = {}
    summary["generated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    summary["data_dir"] = str(BASE)
    summary["known_anomalies"] = known_anomalies

    # 厂商级
    man_summary = {}
    for man in ["M1", "M2"]:
        mm = man_station_meta[man]
        man_summary[man] = {
            "n_stations_with_file": mm["n_files"],
            "n_config_rows": int(len(meta_by_man[man]["config"])),
            "n_fault_rows": int(len(meta_by_man[man]["faults"])),
            "n_normal_rows": int(len(meta_by_man[man]["normal_events"])),
            "n_disturbance_rows": int(len(meta_by_man[man]["disturbances"])),
            "total_rows": int(mm["total_rows"]),
            "t_start": to_py(mm["t_start"]),
            "t_end": to_py(mm["t_end"]),
            "dup_ts_total": int(mm["dups"]),
            "ooo_total": int(mm["ooo"]),
            "bad_ts_total": int(mm["bad_ts"]),
            "interval_counter": dict(Counter([round(x, 3) for x in mm["intervals"]])),
            "span_days_min": safe_round(min(mm["span_days"])),
            "span_days_max": safe_round(max(mm["span_days"])),
            "span_days_median": safe_round(float(np.median(mm["span_days"]))),
            "max_gap_h_max": safe_round(max([x for x in mm["max_gap_h"] if x is not None])),
            "max_gap_h_median": safe_round(float(np.median([x for x in mm["max_gap_h"] if x is not None]))),
            "time_cov_median": safe_round(float(np.median(mm["time_cov"]))),
            "station_ids": sorted(station_features[man]),
            "missing_station_ids": sorted(set(int(x) for x in meta_by_man[man]["config"]["substation ID"].dropna())
                                          - set(station_features[man])),
        }
    summary["manufacturers"] = man_summary
    summary["n_stations_total"] = sum(v["n_stations_with_file"] for v in man_summary.values())
    summary["total_rows"] = sum(v["total_rows"] for v in man_summary.values())

    # 特征集合差异
    f1 = set(k[1] for k in feature_presence if k[0] == "M1")
    f2 = set(k[1] for k in feature_presence if k[0] == "M2")
    summary["feature_sets"] = {
        "M1_only": sorted(f1 - f2),
        "M2_only": sorted(f2 - f1),
        "common": sorted(f1 & f2),
        "union": sorted(f1 | f2),
    }
    summary["feature_presence"] = {
        man: {c: feature_presence[(man, c)] for c in sorted([k[1] for k in feature_presence if k[0] == man])}
        for man in ["M1", "M2"]
    }

    # 标签统计
    label = {}
    for man in ["M1", "M2"]:
        faults = meta_by_man[man]["faults"]
        efd_counts = faults["efd_bool"].value_counts(dropna=False)
        label[man] = {
            "n_faults": int(len(faults)),
            "efd_true": int(efd_counts.get(True, 0)),
            "efd_false": int(efd_counts.get(False, 0)),
            "efd_missing": int(efd_counts.get(np.nan, 0)),
            "fault_label_top": [[str(k), int(v)] for k, v in faults["Fault label"].value_counts(dropna=False).head(15).items()],
            "monitoring_value_counts": [[str(k), int(v)] for k, v in
                                        faults["Monitoring potential"].astype(str).value_counts(dropna=False).items()],
            "monitoring_numeric": {
                "min": safe_round(faults["monitoring_num"].min()),
                "median": safe_round(faults["monitoring_num"].median()),
                "max": safe_round(faults["monitoring_num"].max()),
                "unknown_count": int(faults["Monitoring potential"].astype(str).str.lower().eq("unknown").sum()),
            },
            "problem_top": [[str(k), int(v)] for k, v in faults["Problem EN"].value_counts(dropna=False).head(10).items()],
            "normal_events": int(len(meta_by_man[man]["normal_events"])),
            "disturbance_type": {str(k): int(v) for k, v in
                                 meta_by_man[man]["disturbances"]["type"].value_counts(dropna=False).items()},
        }
    summary["labels"] = label

    # 单独导出标签/干扰分布（表格版）
    lab_rows = []
    for m in ["M1", "M2"]:
        fl = meta_by_man[m]["faults"]["Fault label"].value_counts()
        for k, v in fl.items():
            lab_rows.append([m, "Fault label", str(k), int(v)])
        mv = meta_by_man[m]["faults"]["Monitoring potential"].astype(str).value_counts()
        for k, v in mv.items():
            lab_rows.append([m, "Monitoring potential", str(k), int(v)])
        pc = meta_by_man[m]["faults"]["Problem EN"].astype(str).str.strip().str.lower().value_counts()
        for k, v in pc.items():
            lab_rows.append([m, "Problem EN(lower)", str(k), int(v)])
    pd.DataFrame(lab_rows, columns=["manufacturer", "category", "value", "count"]).to_csv(
        OUT / "fault_label_distribution.csv", index=False, encoding="utf-8-sig")
    dist_rows = []
    for m in ["M1", "M2"]:
        for k, v in meta_by_man[m]["disturbances"]["type"].value_counts().items():
            dist_rows.append([m, str(k), int(v)])
    pd.DataFrame(dist_rows, columns=["manufacturer", "type", "count"]).to_csv(
        OUT / "disturbance_type_distribution.csv", index=False, encoding="utf-8-sig")

    # normal events 每站覆盖
    ne_cov = []
    for man in ["M1", "M2"]:
        ne = meta_by_man[man]["normal_events"]
        cnt = ne["substation ID"].value_counts()
        for sid in station_features[man]:
            ne_cov.append({"manufacturer": man, "substation_id": int(sid),
                           "normal_event_count": int(cnt.get(sid, 0))})
    summary["normal_event_station_coverage"] = {
        man: {
            "n_stations": len(station_features[man]),
            "n_with_0": int(sum(1 for x in ne_cov if x["manufacturer"] == man and x["normal_event_count"] == 0)),
            "n_with_1": int(sum(1 for x in ne_cov if x["manufacturer"] == man and x["normal_event_count"] == 1)),
            "n_with_2plus": int(sum(1 for x in ne_cov if x["manufacturer"] == man and x["normal_event_count"] >= 2)),
            "max_per_station": int(max([x["normal_event_count"] for x in ne_cov if x["manufacturer"] == man] or [0])),
            "stations_with_zero": sorted([x["substation_id"] for x in ne_cov
                                          if x["manufacturer"] == man and x["normal_event_count"] == 0]),
        }
        for man in ["M1", "M2"]
    }

    # 训练窗口统计
    def win_stats(df, col_days="train_days"):
        v = df[col_days].dropna().astype(float)
        return {
            "n_nonnull": int(len(v)),
            "min_days": safe_round(v.min()) if len(v) else None,
            "median_days": safe_round(v.median()) if len(v) else None,
            "max_days": safe_round(v.max()) if len(v) else None,
            "n_lt_7d": int((v < 7).sum()),
            "n_lt_30d": int((v < 30).sum()),
            "n_lt_90d": int((v < 90).sum()),
            "n_lt_365d": int((v < 365).sum()),
            "n_ge_365d": int((v >= 365).sum()),
            "total_days": safe_round(v.sum()),
        }

    summary["training_windows"] = {
        "faults": {
            man: win_stats(faults_enr[faults_enr["manufacturer"] == man])
            for man in ["M1", "M2"]
        },
        "faults_all": win_stats(faults_enr),
        "normal_events": {
            man: win_stats(normal_enr[normal_enr["manufacturer"] == man])
            for man in ["M1", "M2"]
        },
        "normal_events_all": win_stats(normal_enr),
    }

    # 可建模站-事件对 funnel
    def funnel(df):
        n_all = len(df)
        s1 = df[df["train_nonnull"]]
        s2 = s1[s1["station_has_data"]]
        s3 = s2[s2["train_inside_span"] == True]  # noqa: E712
        s4 = s3[s3["train_coverage"] >= MIN_COVERAGE]
        s5 = s4[s4["train_days"] >= MIN_TRAIN_DAYS]
        s6 = s5[s5["station_usable_features"] >= MIN_USABLE_FEAT]
        return {
            "total_events": n_all,
            "has_training_window": len(s1),
            "station_has_data": len(s2),
            "window_inside_data_span": len(s3),
            "coverage_ge_0.8": len(s4),
            "train_days_ge_30": len(s5),
            "usable_features_ge_8": len(s6),
            "usable_final": int(df["usable_for_modeling"].sum()),
            "usable_final_efd_true": int(((df["usable_for_modeling"]) &
                                          (df.get("efd_possible") == True)).sum()) if "efd_possible" in df else None,
        }

    summary["event_funnel"] = {
        "faults": {man: funnel(faults_enr[faults_enr["manufacturer"] == man]) for man in ["M1", "M2"]},
        "faults_all": funnel(faults_enr),
        "normal_events": {man: funnel(normal_enr[normal_enr["manufacturer"] == man]) for man in ["M1", "M2"]},
        "normal_events_all": funnel(normal_enr),
    }

    # 事件问题分布
    summary["event_issue_counts"] = {
        kind: {man: dict(Counter([x for s in sub["issues"].fillna("") for x in s.split("|") if x]))
               for man, sub in [("M1", df[df["manufacturer"] == "M1"]), ("M2", df[df["manufacturer"] == "M2"])]}
        for kind, df in [("faults", faults_enr), ("normal_events", normal_enr)]
    }
    # efd 与训练窗口一致性
    f_all = faults_enr
    summary["efd_consistency"] = {
        "efd_true_without_training": int(((f_all.get("efd_possible") == True) & (~f_all["train_nonnull"])).sum()),  # noqa: E712
        "efd_false_with_training": int(((f_all.get("efd_possible") == False) & (f_all["train_nonnull"])).sum()),  # noqa: E712
    }

    # 数据质量：逐站
    dq = []
    for rec in profile_rows:
        man, sid = rec["manufacturer"], rec["substation_id"]
        ctx = station_ctx[(man, sid)]
        dq.append({
            "manufacturer": man, "substation_id": sid,
            "row_count": rec["row_count"],
            "span_days": safe_round(rec["时间跨度天数"]),
            "interval_min": safe_round(rec["采样间隔中位数(分钟)"]),
            "max_gap_h": safe_round(rec["最大连续缺失间隔(小时)"]),
            "time_coverage": safe_round(rec["时间覆盖率"]),
            "usable_features": rec["可用特征数量"],
            "all_nan_features": rec["全空特征列表"],
            "fault_events": rec["fault_event_count"],
            "normal_events": rec["normal_event_count"],
            "disturbances": rec["total_disturbance_count"],
        })
    dq_df = pd.DataFrame(dq)

    summary["gaps"] = {
        "top20_max_gap": dq_df.sort_values("max_gap_h", ascending=False)
        .head(20)[["manufacturer", "substation_id", "max_gap_h", "span_days", "row_count"]]
        .to_dict(orient="records"),
        "n_stations_gap_gt_7d": int((dq_df["max_gap_h"] > 24 * 7).sum()),
        "n_stations_gap_gt_30d": int((dq_df["max_gap_h"] > 24 * 30).sum()),
        "n_stations_gap_gt_365d": int((dq_df["max_gap_h"] > 24 * 365).sum()),
        "stations_gap_gt_30d": dq_df[dq_df["max_gap_h"] > 24 * 30]
        .sort_values("max_gap_h", ascending=False)
        [["manufacturer", "substation_id", "max_gap_h", "span_days"]].to_dict(orient="records"),
    }

    # 时间覆盖率低的站
    summary["short_series"] = {
        "n_span_lt_90d": int((dq_df["span_days"] < 90).sum()),
        "n_span_lt_180d": int((dq_df["span_days"] < 180).sum()),
        "stations_span_lt_180d": dq_df[dq_df["span_days"] < 180]
        .sort_values("span_days")[["manufacturer", "substation_id", "span_days", "row_count", "fault_events", "normal_events"]]
        .to_dict(orient="records"),
    }

    # 特征缺失严重度（按出现该列的站取平均）
    fq_present = fq.copy()
    feat_miss = (fq_present.groupby(["manufacturer", "feature"])
                 .agg(mean_null=("null_rate", "mean"), n_stations=("null_rate", "size"),
                      median_null=("null_rate", "median"))
                 .reset_index())
    summary["worst_features"] = {
        man: feat_miss[feat_miss["manufacturer"] == man].sort_values("mean_null", ascending=False)
        .head(15)[["feature", "mean_null", "median_null", "n_stations"]].to_dict(orient="records")
        for man in ["M1", "M2"]
    }
    summary["worst_features_all"] = (feat_miss.sort_values("mean_null", ascending=False)
                                     .head(20)[["manufacturer", "feature", "mean_null", "median_null", "n_stations"]]
                                     .to_dict(orient="records"))

    # 全空特征（站×特征）
    allnan = fq[fq["null_rate"] >= 0.999][["manufacturer", "substation_id", "feature"]]
    summary["all_nan_features"] = {
        "n_pairs": int(len(allnan)),
        "by_feature": allnan.groupby("feature").size().sort_values(ascending=False).head(20).to_dict(),
        "by_station": allnan.groupby(["manufacturer", "substation_id"]).size().sort_values(ascending=False).head(20)
        .reset_index().to_dict(orient="records"),
    }

    # 温度物理区间
    temp_fq = fq[fq["feature"].str.contains("temperature", case=False, na=False)
                 | fq["feature"].str.endswith("_temp", na=False)].copy()
    temp_fq["out"] = temp_fq["out_of_range_temp"].fillna(0).astype(int)
    summary["temperature_quality"] = {
        "n_pairs": int(len(temp_fq)),
        "n_pairs_with_out_of_range": int((temp_fq["out"] > 0).sum()),
        "total_out_of_range_values": int(temp_fq["out"].sum()),
        "n_valid_values": int(temp_fq["n_valid"].sum()),
        "worst": temp_fq.sort_values("out", ascending=False).head(20)
        [["manufacturer", "substation_id", "feature", "n_valid", "out", "min", "max"]].to_dict(orient="records"),
        "outdoor": temp_fq[temp_fq["feature"] == "outdoor_temperature"]
        .sort_values("min")[["manufacturer", "substation_id", "n_valid", "null_rate", "min", "max"]]
        .head(15).to_dict(orient="records"),
    }

    # 表计长期为 0 / 全空
    meter_rows = []
    for (man, sid), ctx in station_ctx.items():
        for c, info in ctx["meter"].items():
            meter_rows.append({"manufacturer": man, "substation_id": sid, "feature": c, **info})
    meter_df = pd.DataFrame(meter_rows)
    meter_bad = meter_df[((meter_df["zero_rate"] > 0.95) | (meter_df["null_rate"] > 0.95))]
    summary["meter_quality"] = {
        "n_pairs": int(len(meter_df)),
        "n_zero_rate_gt_0.95": int((meter_df["zero_rate"] > 0.95).sum()),
        "n_null_rate_gt_0.95": int((meter_df["null_rate"] > 0.95).sum()),
        "n_bad_pairs": int(len(meter_bad)),
        "bad_pairs": meter_bad.sort_values(["null_rate"], ascending=False).head(40).to_dict(orient="records"),
        "zero_rate_by_feature": meter_df.groupby("feature")["zero_rate"].mean().dropna().round(4).to_dict(),
        "null_rate_by_feature": meter_df.groupby("feature")["null_rate"].mean().dropna().round(4).to_dict(),
        "non_increasing_by_feature": meter_df.groupby("feature")["non_increasing_rate"].mean().dropna().round(4).to_dict(),
    }

    # 时间戳网格重复（同厂商下时间戳完全一致的站组）
    grid_groups = []
    for h, lst in hash_grid.items():
        if len(lst) > 1:
            grid_groups.append({"n": len(lst), "stations": [f"{m}#{s}" for m, s in lst]})
    summary["identical_timestamp_grids"] = sorted(grid_groups, key=lambda g: -g["n"])

    # 重复表头 outdoor_temperature.1
    dup_header = fq[fq["feature"] == "outdoor_temperature.1"][["manufacturer", "substation_id"]]
    summary["duplicate_outdoor_columns"] = dup_header.to_dict(orient="records")

    # faults vs disturbances 一致性
    cons = []
    for man in ["M1", "M2"]:
        faults = meta_by_man[man]["faults"]
        dist = meta_by_man[man]["disturbances"]
        dist_f = dist[dist["type"] == "fault"]
        n_f = faults.groupby("substation ID").size()
        n_d = dist_f.groupby("substation ID").size()
        for sid in sorted(set(n_f.index) | set(n_d.index)):
            cons.append({"manufacturer": man, "substation_id": int(sid),
                         "faults_csv": int(n_f.get(sid, 0)), "disturbance_fault": int(n_d.get(sid, 0))})
    cons_df = pd.DataFrame(cons)
    cons_df["diff"] = cons_df["faults_csv"] - cons_df["disturbance_fault"]
    summary["fault_vs_disturbance"] = {
        "n_station_pairs": int(len(cons_df)),
        "n_mismatch": int((cons_df["diff"] != 0).sum()),
        "mismatch_rows": cons_df[cons_df["diff"] != 0].sort_values("diff").to_dict(orient="records"),
    }

    # 事件报告日期是否在数据范围内
    fr = faults_enr[faults_enr["station_has_data"]]
    summary["event_data_coverage"] = {
        "faults_report_outside_data": int((fr["report_inside_data"] == False).sum()),  # noqa: E712
        "faults_with_no_station_data": int((~faults_enr["station_has_data"]).sum()),
        "faults_test_window_outside_data": int((faults_enr["test_inside_span"] == False).sum()),  # noqa: E712
        "normal_test_window_outside_data": int((normal_enr["test_inside_span"] == False).sum()),  # noqa: E712
    }

    # 每站可用事件数
    usable_by_station = (faults_enr[faults_enr["usable_for_modeling"]]
                         .groupby(["manufacturer", "substation_id"]).size().rename("usable_faults"))
    ne_usable = (normal_enr[normal_enr["usable_for_modeling"]]
                 .groupby(["manufacturer", "substation_id"]).size().rename("usable_normals"))
    per_station_events = dq_df.set_index(["manufacturer", "substation_id"]).join(
        usable_by_station, how="left").join(ne_usable, how="left").fillna({"usable_faults": 0, "usable_normals": 0})
    summary["usable_events_by_station"] = per_station_events.reset_index().to_dict(orient="records")

    # 训练窗口按厂商 + efd 分布细节
    summary["faults_by_industry"] = {}
    for man in ["M1", "M2"]:
        sub = faults_enr[faults_enr["manufacturer"] == man]
        summary["faults_by_industry"][man] = {
            "n": int(len(sub)),
            "train_days_median": safe_round(sub["train_days"].median()),
            "n_train_lt_30": int((sub["train_days"] < 30).sum()),
            "n_train_lt_90": int((sub["train_days"] < 90).sum()),
            "efd_true": int((sub.get("efd_possible") == True).sum()),  # noqa: E712
            "efd_true_and_usable": int(((sub.get("efd_possible") == True) & sub["usable_for_modeling"]).sum()),  # noqa: E712
        }

    # 配置文件与数据文件对齐
    summary["config_vs_files"] = {}
    for man in ["M1", "M2"]:
        cfg_ids = set(int(x) for x in meta_by_man[man]["config"]["substation ID"].dropna())
        file_ids = set(station_features[man])
        summary["config_vs_files"][man] = {
            "config_ids": sorted(cfg_ids),
            "file_ids": sorted(file_ids),
            "in_config_no_file": sorted(cfg_ids - file_ids),
            "in_file_no_config": sorted(file_ids - cfg_ids),
            "config_empty": sorted([int(x) for x in
                                    meta_by_man[man]["config"]["substation ID"][
                                        meta_by_man[man]["config"]["configuration_type"].isna()].dropna()]),
        }

    # 时间戳分隔符/格式异常计数
    summary["timestamp_parsing"] = {
        man: {
            "bad_timestamp_total": man_summary[man]["bad_ts_total"],
        } for man in ["M1", "M2"]
    }

    # 逐站 profile 精简
    # 大间隙明细（>24h），用于定位“整段/大段缺失”
    gap_rows = []
    for (man, sid), ctx in station_ctx.items():
        arr = ctx["ts_arr"]
        if arr is None or len(arr) < 2:
            continue
        d = np.diff(arr).astype("timedelta64[s]").astype(float) / 3600.0
        for i in np.where(d > 24.0)[0]:
            gap_rows.append({
                "manufacturer": man, "substation_id": sid,
                "gap_hours": float(d[i]),
                "gap_start": pd.Timestamp(arr[i]),
                "gap_end": pd.Timestamp(arr[i + 1]),
            })
    gap_df = pd.DataFrame(gap_rows)
    if len(gap_df):
        gap_df = gap_df.sort_values("gap_hours", ascending=False)
    summary["gap_intervals"] = {
        "n_gt_24h": int(len(gap_df)),
        "n_gt_7d": int((gap_df["gap_hours"] > 168).sum()) if len(gap_df) else 0,
        "n_gt_30d": int((gap_df["gap_hours"] > 720).sum()) if len(gap_df) else 0,
        "top": gap_df.head(40).to_dict(orient="records") if len(gap_df) else [],
    }

    # 表计整段缺失（缺失率>30%）的站
    meter_null_rows = []
    for (man, sid), ctx in station_ctx.items():
        for c, info in ctx["meter"].items():
            if info["null_rate"] > 0.3:
                meter_null_rows.append({"manufacturer": man, "substation_id": sid, "feature": c,
                                        "null_rate": info["null_rate"], "zero_rate": info["zero_rate"]})
    summary["meter_quality"]["high_null"] = meter_null_rows
    summary["meter_quality"]["top_non_increasing"] = (
        meter_df.sort_values("non_increasing_rate", ascending=False)
        .head(15)[["manufacturer", "substation_id", "feature", "non_increasing_rate", "zero_rate", "null_rate"]]
        .to_dict(orient="records"))

    # 室外温度传感器异常（长期近似常数 / 范围过窄 / 大量缺失）
    out_rows = []
    for (man, sid), ctx in station_ctx.items():
        o = ctx.get("outdoor")
        if not o:
            continue
        rng = (o["max"] - o["min"]) if (o["min"] is not None and o["max"] is not None) else None
        out_rows.append({
            "manufacturer": man, "substation_id": sid, "nunique": o["nunique"],
            "min": o["min"], "max": o["max"], "range": rng, "null_rate": o["null_rate"],
            "suspect_constant": bool(o["nunique"] <= 20 or (rng is not None and rng < 5)),
        })
    out_df = pd.DataFrame(out_rows)
    summary["outdoor_sensor"] = {
        "n_stations": int(len(out_df)),
        "n_suspect": int(out_df["suspect_constant"].sum()) if len(out_df) else 0,
        "suspect": out_df[out_df["suspect_constant"]].sort_values("range").to_dict(orient="records"),
        "lowest_range": out_df.sort_values("range").head(10).to_dict(orient="records"),
        "highest_null": out_df.sort_values("null_rate", ascending=False).head(10).to_dict(orient="records"),
    }

    # 重复表头 outdoor_temperature.1 两站的对比
    dup_cmp = []
    for sid in [21, 57]:
        f = BASE / "manufacturer 2" / "operational_data" / f"substation_{sid}.csv"
        d = pd.read_csv(f, sep=";", usecols=["timestamp", "outdoor_temperature", "outdoor_temperature.1"])
        a, b = d["outdoor_temperature"], d["outdoor_temperature.1"]
        both = a.notna() & b.notna()
        dup_cmp.append({
            "manufacturer": "M2", "substation_id": sid,
            "null_rate_col1": float(a.isna().mean()), "null_rate_col2": float(b.isna().mean()),
            "corr": float(a[both].corr(b[both])) if both.sum() > 2 else None,
            "mean_abs_diff": float((a[both] - b[both]).abs().mean()) if both.sum() else None,
            "max_abs_diff": float((a[both] - b[both]).abs().max()) if both.sum() else None,
            "n_both": int(both.sum()),
        })
    summary["duplicate_outdoor_compare"] = dup_cmp

    # 1 分钟粒度行（M2 特定 9 站开头 24h）
    minute_rows = [{"manufacturer": rec["manufacturer"], "substation_id": rec["substation_id"],
                    "n_1min": rec["n_1min_intervals"]} for rec in profile_rows if rec["n_1min_intervals"] > 0]
    summary["one_minute_rows"] = {
        "n_stations": len(minute_rows),
        "total": int(sum(r["n_1min"] for r in minute_rows)),
        "stations": minute_rows,
    }
    summary["timestamp_second_jitter"] = {
        man: int(sum(rec["n_nonzero_second_rows"] for rec in profile_rows
                     if rec["manufacturer"] == man))
        for man in ["M1", "M2"]
    }

    # 长缺口（>7 天）按起始月份分布：用于识别“夏季断供/采集中断”模式
    if len(gap_df):
        long_gaps = gap_df[gap_df["gap_hours"] > 168].copy()
        long_gaps["start_month"] = pd.to_datetime(long_gaps["gap_start"]).dt.month
        summary["long_gap_month_profile"] = {
            "n": int(len(long_gaps)),
            "by_month": {int(k): int(v) for k, v in long_gaps["start_month"].value_counts().sort_index().items()},
            "n_start_may_oct": int(long_gaps["start_month"].isin([5, 6, 7, 8, 9, 10]).sum()),
        }
    else:
        summary["long_gap_month_profile"] = {"n": 0, "by_month": {}, "n_start_may_oct": 0}

    # 时间覆盖率低的站（<0.9）
    summary["low_time_coverage"] = {
        "n_lt_0.9": int((prof_df["时间覆盖率"] < 0.9).sum()),
        "n_lt_0.5": int((prof_df["时间覆盖率"] < 0.5).sum()),
        "stations": prof_df[prof_df["时间覆盖率"] < 0.9]
        .sort_values("时间覆盖率")[["manufacturer", "substation_id", "时间覆盖率", "row_count",
                                    "时间跨度天数", "最大连续缺失间隔(小时)"]]
        .to_dict(orient="records"),
    }

    summary["profile"] = prof_df.drop(columns=[c for c in prof_df.columns if c.startswith("miss_")]).to_dict(orient="records")
    summary["n_features"] = {
        man: len([k for k in feature_presence if k[0] == man]) for man in ["M1", "M2"]
    }
    summary["n_feature_desc"] = {man: len(feature_has_desc[man]) for man in ["M1", "M2"]}

    with open(OUT / "profile_summary.json", "w", encoding="utf-8") as fh:
        json.dump(to_py(summary), fh, ensure_ascii=False, indent=1)
    log(f"写出 profile_summary.json")
    log(f"\n全部计算完成，用时 {time.time()-t0:.1f}s")
    _log_fh.close()
    _log_fh = None
    return summary


# ----------------------------------------------------------------------------
# 报告生成（读取已算好的 CSV / JSON，便于快速迭代）
# ----------------------------------------------------------------------------
def md_table(rows, cols, headers=None, align=None):
    headers = headers or cols
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            if v is None:
                v = "—"
            if isinstance(v, float):
                v = f"{v:,.2f}"
            cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def generate_report():
    S = json.loads((OUT / "profile_summary.json").read_text(encoding="utf-8"))
    prof = pd.read_csv(OUT / "substation_profile.csv", encoding="utf-8-sig")
    fq = pd.read_csv(OUT / "feature_value_quality.csv", encoding="utf-8-sig")
    faults = pd.read_csv(OUT / "fault_events_enriched.csv", encoding="utf-8-sig")
    normals = pd.read_csv(OUT / "normal_events_enriched.csv", encoding="utf-8-sig")
    presence = pd.read_csv(OUT / "feature_presence_by_manufacturer.csv", encoding="utf-8-sig")
    known = pd.read_csv(OUT / "known_anomalies.csv", encoding="utf-8-sig")
    report_render(S, prof, fq, faults, normals, presence, known)


def report_render(S, prof, fq, faults, normals, presence, known):
    import re

    man = S["manufacturers"]
    lab = S["labels"]
    man_names = {"M1": "M1（厂商 1）", "M2": "M2（厂商 2）"}

    # ---------- 预处理 ----------
    faults = faults.copy()
    normals = normals.copy()
    for df in (faults, normals):
        df["usable"] = df["usable_for_modeling"].astype(str).str.lower().isin(["true", "1"])
        for c in ("train_start", "train_end", "test_start", "test_end", "report_date",
                  "station_t_start", "station_t_end"):
            if c in df.columns:
                df[c] = pd.to_datetime(df[c], format="mixed", errors="coerce")
    prof = prof.copy()
    for c in ("t_start", "t_end"):
        prof[c] = pd.to_datetime(prof[c], format="mixed", errors="coerce")
    faults["efd"] = faults["efd_possible"].map(
        lambda v: "是" if str(v).lower() == "true" else ("否" if str(v).lower() == "false" else "—"))
    faults["train_cov"] = pd.to_numeric(faults["train_coverage"], errors="coerce")
    faults["tdays"] = pd.to_numeric(faults["train_days"], errors="coerce")

    def fnum(x, n=1):
        if x is None or (isinstance(x, float) and not math.isfinite(x)) or pd.isna(x):
            return "—"
        return f"{float(x):,.{n}f}"

    def fpct(x, n=1):
        if x is None or pd.isna(x):
            return "—"
        return f"{100.0 * float(x):.{n}f}%"

    def fd(x):
        if x is None or pd.isna(x):
            return "—"
        return pd.Timestamp(x).strftime("%Y-%m-%d")

    def fdt(x):
        if x is None or pd.isna(x):
            return "—"
        return pd.Timestamp(x).strftime("%Y-%m-%d %H:%M")

    def table(rows, headers):
        out = ["| " + " | ".join(headers) + " |",
               "|" + "|".join([":---"] * len(headers)) + "|"]
        for r in rows:
            out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
        return "\n".join(out)

    f_ok = faults[faults.usable].copy()
    f_bad = faults[~faults.usable].copy()
    n_ok = normals[normals.usable].copy()

    L = []
    def add(*lines):
        L.extend(lines)

    add("# PreDist 数据集清点与质量报告",
        "",
        "> **数据来源**：Fraunhofer IEE *PreDist Dataset*（Zenodo DOI: 10.5281/zenodo.17522255）——"
        "93 个集中供热换热站运行时间序列 + 故障/干扰/正常事件标签。",
        f"> **数据目录**：`{S['data_dir']}`（只读，本报告未改动任何原始文件）  ",
        f"> **生成脚本**：`勘探/build_profile.py`（全量重跑约 41 秒）  ",
        f"> **生成时间**：{S['generated_at']}  ",
        "> **口径**：缺失率 = NaN 占比（含整行时间戳缺失另算）；时间覆盖率的详细定义见第 7 节。",
        "",
        "---",
        "")

    # ============================================================
    # 0. 摘要
    # ============================================================
    n_rows = S["total_rows"]
    efd_all = dict(Counter(faults["efd"].values))
    usable_f = S["event_funnel"]["faults_all"]["usable_final"]
    usable_n = S["event_funnel"]["normal_events_all"]["usable_final"]
    stations_gap30 = S["gaps"]["n_stations_gap_gt_30d"]
    short180 = S["short_series"]["n_span_lt_180d"]
    add("## 0. 结论摘要（TL;DR）", "",
        f"- **规模**：{S['n_stations_total']} 个站（M1 35 + M2 58），{n_rows:,} 行，"
        f"时间范围 {min(man['M1']['t_start'], man['M2']['t_start'])[:10]} ~ {max(man['M1']['t_end'], man['M2']['t_end'])[:10]}；"
        "所有站中位采样间隔均为 10 分钟（M2 有 9 站开头 24 h 为 1 分钟粒度，见 5.6）。",
        f"- **标签**：faults.csv 共 {len(faults)} 条故障报告（M1 {len(faults[faults.manufacturer=='M1'])} / "
        f"M2 {len(faults[faults.manufacturer=='M2'])}），efd_possible=True {efd_all.get('是',0)} 条、False {efd_all.get('否',0)} 条；"
        f"normal_events 共 {len(normals)} 条（M1 {len(normals[normals.manufacturer=='M1'])} / M2 {len(normals[normals.manufacturer=='M2'])}）。",
        f"- **可建模站-事件对**：故障侧 **{usable_f} 条**（M1 {S['event_funnel']['faults']['M1']['usable_final']} / "
        f"M2 {S['event_funnel']['faults']['M2']['usable_final']}，占全部故障报告 {usable_f/len(faults):.0%}）；"
        f"正常侧 **{usable_n} 条**（M1 {S['event_funnel']['normal_events']['M1']['usable_final']} / "
        f"M2 {S['event_funnel']['normal_events']['M2']['usable_final']}）。",
        f"- **不可用站**：M2#1、#38、#42、#48、#51 跨度仅 33.6~54.7 天且无 faults/normal 标签；"
        f"M2 共 {short180} 站时间跨度不足 180 天（占 M2 {short180/58:.0%}）。另外 **M2#33、#58 虽然有 2.4~2.5 万行数据，但所有特征缺失率都在 31.2%~79.2%**，"
        f"按“非空率≥80%”口径可用特征为 0（需放宽阈值/低频重采样才能用）。M1 有 {stations_gap30} 站存在 >30 天的连续数据缺口。",
        "",
        "**最会坑建模的 3 件事**：",
        "",
        "1. **M1 的“大段缺失”不是个别现象**：11 个 M1 站有 >30 天缺口，其中 M1#10 有一条 **4.6 年**（2015-05-29→2020-01-08）"
        "的缺口，时间覆盖率只有 34.3%；M1#14 缺口 1 年、M1#12 缺口 239 天。直接按时间插值/滑窗会把缺口当成连续序列。",
        "2. **表计（能量/体积）不是单调累计量，不能直接 `diff()`**：能量表 35.2%、体积表 34.7% 的相邻步长为非递增（计数器归零、"
        "长时间不变、设备更换），且 **M2 的单位是 Wh/ml/W，M1 是 kWh/m3/kW/l/h（相差 1000 倍）**，同名特征不可跨厂商直接拼接。",
        "3. **训练窗口与特征集合都不齐**：73 条故障中 19 条没有 Training 窗口（M1 5 / M2 14）；训练窗口 <30 天的有 4 条；"
        "M1 与 M2 只有 25 个同名特征（M1 26 列 / M2 49 列），且 M2 站间特征差异极大（多个特征只有 1~2 个站有）。"
        "此外 disturbances 的 fault 条数（155）≠ faults.csv（73），**不能把 disturbances 当故障标签表用**。",
        "")

    # ============================================================
    # 1. 总体概况
    # ============================================================
    add("---", "", "## 1. 总体概况", "")
    rows = []
    for m in ("M1", "M2"):
        x = man[m]
        rows.append([m, x["n_stations_with_file"], x["n_config_rows"], x["n_fault_rows"],
                     x["n_normal_rows"], x["n_disturbance_rows"], f"{x['total_rows']:,}",
                     x["t_start"][:10], x["t_end"][:10]])
    add("### 1.1 厂商级规模", "",
        table(rows, ["厂商", "有运行数据文件的站数", "configuration_types 行数", "faults 条数",
                     "normal_events 条数", "disturbances 条数", "总行数", "数据起始", "数据结束"]), "")
    rows = []
    for m in ("M1", "M2"):
        x = man[m]
        ints = ", ".join(f"{k} 分钟×{v} 站" for k, v in sorted(x["interval_counter"].items(), key=lambda kv: float(kv[0])))
        rows.append([m, x["span_days_min"], x["span_days_median"], x["span_days_max"],
                     ints, fnum(x["max_gap_h_median"]), fnum(x["max_gap_h_max"]),
                     fpct(x["time_cov_median"]), x["dup_ts_total"], x["ooo_total"], x["bad_ts_total"]])
    add("### 1.2 时间跨度、采样与时间戳质量", "",
        table(rows, ["厂商", "最短跨度(天)", "跨度中位(天)", "最长跨度(天)", "中位采样间隔",
                     "各站最大缺口的中位(h)", "最大缺口(h)", "时间覆盖率中位", "重复时间戳", "乱序时间戳", "无法解析时间戳"]), "",
        f"- 全量 {n_rows:,} 行中，时间戳重复 {man['M1']['dup_ts_total']+man['M2']['dup_ts_total']} 个、"
        f"乱序 {man['M1']['ooo_total']+man['M2']['ooo_total']} 个、无法解析 {man['M1']['bad_ts_total']+man['M2']['bad_ts_total']} 个 → 时间戳本身是干净的。",
        f"- M2 有 {S['one_minute_rows']['n_stations']} 个站的文件**开头 24 小时是 1 分钟粒度**（共 {S['one_minute_rows']['total']:,} 个 1 分钟间隔，"
        f"且时间戳带 ±1~2 秒抖动），其余时间为 10 分钟；M2 时间戳秒数非 0 的行共 {S['timestamp_second_jitter']['M2']:,} 行"
        f"（M1 为 {S['timestamp_second_jitter']['M1']} 行）→ 跨厂商/跨站对齐前必须先按 10 分钟 floor 或重采样。",
        f"- 长缺口（>7 天）共 {S['long_gap_month_profile']['n']} 个，其中 {S['long_gap_month_profile']['n_start_may_oct']} 个"
        f"起始于 5–10 月（夏季供暖停机/采集中断），建模时按“季节断点”处理比插值更合理。",
        "")

    add("### 1.3 与 README / 任务书口径的差异（重要）", "",
        "- README 写“93 个站，M1、M2 两个厂商”，但任务书说 “M1 35 站、M2 61 站”。实测：**M1 35 + M2 58 = 93**。",
        "- `manufacturer 2/configuration_types.csv` 只有 **58 行**，`operational_data` 也只有 **58 个文件**；"
        "**#22、#30、#32 三个站既无配置行也无运行数据**（#30 还出现在 disturbances 的 fault 记录里，#22 还出现在 README 已知异常表里）。",
        "- 结论：本项目能用的站数上限是 **93**，不是 96；引用“M2 61 站”会与数据对不上。",
        "")

    # ============================================================
    # 2. 特征集合差异
    # ============================================================
    add("---", "", "## 2. M1 / M2 特征集合差异", "")
    fs = S["feature_sets"]
    pres = presence.copy()
    add("### 2.1 数量对比", "",
        table([
            ["特征列总数（不含 timestamp）", S["n_features"]["M1"], S["n_features"]["M2"]],
            ["feature_descriptions 覆盖列数", S["n_feature_desc"]["M1"], S["n_feature_desc"]["M2"]],
            ["两厂商公共特征", len(fs["common"]), len(fs["common"])],
            ["仅 M1 有", len(fs["M1_only"]), 0],
            ["仅 M2 有", 0, len(fs["M2_only"])],
        ], ["项目", "M1", "M2"]), "",
        f"- 说明：M2 的 49 列里有 1 列是 `outdoor_temperature` 的重复表头（pandas 自动改名 `outdoor_temperature.1`，见 5.6），"
        f"`feature_descriptions.csv` 只描述了 48 列；且其中 `s_hc1.2_dhw_control unit_mode` 列名**含空格**。",
        "")

    def pres_rows(features, cols=("M1", "M2")):
        out = []
        for c in features:
            r = [c]
            for m in cols:
                q = pres[(pres.manufacturer == m) & (pres.feature == c)]
                r.append(f"{int(q.n_stations_with_column.iloc[0])}/{int(q.n_stations_total.iloc[0])}" if len(q) else "0/58")
            u1 = pres[(pres.manufacturer == "M1") & (pres.feature == c)]
            u2 = pres[(pres.manufacturer == "M2") & (pres.feature == c)]
            unit = None
            for q in (u1, u2):
                if len(q) and isinstance(q.unit.iloc[0], str) and q.unit.iloc[0]:
                    unit = q.unit.iloc[0]
                    break
            r.append(unit or "—")
            out.append(r)
        return out

    add("### 2.2 两厂商公共特征（25 列，按站数给出具备该列的站数）", "",
        table(pres_rows(fs["common"]), ["特征", "M1 具备站数", "M2 具备站数", "单位"]), "",
        "> 注意：**“公共列”不等于“高覆盖列”**。例如 `s_hc1.1_return_temperature` 在 M2 只有 2/58 站、在 M1 有 6/35 站；"
        "建模时必须以“本站实际有该列 + 非空率 ≥80%”为准，而不是以并集特征为准。", "")

    add("### 2.3 仅 M1 有的特征", "",
        table(pres_rows(fs["M1_only"], cols=("M1",)), ["特征", "M1 具备站数", "单位"]), "")

    add("### 2.4 仅 M2 有的特征", "",
        table(pres_rows(fs["M2_only"], cols=("M2",)), ["特征", "M2 具备站数", "单位"]), "")

    # 高覆盖核心特征
    core = []
    for c in fs["union"]:
        q1 = pres[(pres.manufacturer == "M1") & (pres.feature == c)]
        q2 = pres[(pres.manufacturer == "M2") & (pres.feature == c)]
        s1 = q1.share.iloc[0] if len(q1) else 0
        s2 = q2.share.iloc[0] if len(q2) else 0
        if s1 >= 0.8 and s2 >= 0.8:
            core.append([c, f"{int(q1.n_stations_with_column.iloc[0])}/35", f"{int(q2.n_stations_with_column.iloc[0])}/58"])
    add("### 2.5 两厂商覆盖率均 ≥80% 的“核心特征”（可直接做跨厂商特征）", "",
        table(core, ["特征", "M1 具备站数", "M2 具备站数"]), "")

    # ============================================================
    # 3. 标签统计
    # ============================================================
    add("---", "", "## 3. 标签统计", "")
    add("### 3.1 faults.csv 总览", "")
    rows = []
    for m in ("M1", "M2"):
        sub = faults[faults.manufacturer == m]
        rows.append([m, len(sub), int((sub.efd == "是").sum()), int((sub.efd == "否").sum()),
                     int((sub.train_start.notna() & sub.train_end.notna()).sum()), sub.substation_id.nunique(),
                     int((sub.monitoring_potential.astype(str).str.lower() == "unknown").sum())])
    add(table(rows, ["厂商", "故障报告数", "efd=True", "efd=False", "完整 Training 窗口", "涉及站数", "Monitoring=unknown"]), "",
        f"- 合计 {len(faults)} 条故障报告，覆盖 {faults.groupby(['manufacturer','substation_id']).ngroups} 个“厂商-站”组合"
        f"（M1 {faults[faults.manufacturer=='M1'].substation_id.nunique()} 个站 / M2 {faults[faults.manufacturer=='M2'].substation_id.nunique()} 个站）；"
        f"其余 {S['n_stations_total'] - faults.groupby(['manufacturer','substation_id']).ngroups} 个“厂商-站”组合**没有任何故障报告**"
        "（不等于没有故障，见 README 说明）。",
        "- `efd_possible=False` 的 18 条全部没有 Training start/end；但有 1 条 `efd_possible=True` 的记录 Training start 有值、Training end 为空"
        "（M1 事件 69，站 #26，2020-03-10）→ 训练窗口不完整，已被判为不可用。", "")

    add("### 3.2 Fault label 分布（两厂商合计，Top 15）", "")
    fl = faults["fault_label"].value_counts()
    rows = [[i + 1, k, v, fpct(v / len(faults))] for i, (k, v) in enumerate(fl.head(15).items())]
    add(table(rows, ["#", "Fault label", "条数", "占比"]), "",
        "- 补充：M1 最常见：Control unit: Incorrect parameterisation（11 条）、Failure of the heating circuit pump（4 条）；"
        "M2 最常见：Leakage（8 条）、Incorrect setting of the differential pressure regulator（6 条）。", "")

    add("### 3.3 Monitoring potential 分布（两厂商合计）", "")
    mv = faults["monitoring_potential"].astype(str).str.strip()

    def mon_key(v):
        try:
            return (0, float(v))
        except Exception:
            return (1, 0.0)
    mvc = Counter(mv.values)
    ordered = sorted(mvc.items(), key=lambda kv: mon_key(kv[0]))
    rows = []
    for k, v in ordered:
        note = {"1.75": "最低（泄漏类，通常只能事后发现）", "4": "最高（参数/控制类，可提前发现）",
                "unknown": "未知（标签缺失）"}.get(k, "")
        rows.append([k, v, fpct(v / len(faults)), note])
    add(table(rows, ["Monitoring potential", "条数", "占比", "备注"]), "",
        f"- 数值范围 1.75–4.0；unknown {int((mv.str.lower()=='unknown').sum())} 条。"
        "**Monitoring potential 低（≤2.1）的事件不适合做早期故障检测的监督标签**，建议单独分组评估。", "")

    add("### 3.4 Problem 类别（不区分大小写合并）", "")
    pm = faults["problem_en"].astype(str).str.strip().str.lower()
    pmc = pm.value_counts()
    rows = [[k, v, fpct(v / len(faults))] for k, v in pmc.items()]
    add(table(rows, ["Problem EN（小写合并）", "条数", "占比"]), "")

    add("### 3.5 normal_events 每站覆盖情况", "")
    nc = S["normal_event_station_coverage"]
    rows = []
    for m in ("M1", "M2"):
        x = nc[m]
        rows.append([m, x["n_stations"], x["n_with_0"], x["n_with_1"], x["n_with_2plus"], x["max_per_station"]])
    add(table(rows, ["厂商", "站数", "0 条事件", "1 条事件", "≥2 条事件", "单站最多"]), "",
        f"- M1 无 normal event 的站（{nc['M1']['n_with_0']} 个）：{'、'.join('#%d' % s for s in nc['M1']['stations_with_zero'])}。",
        f"- M2 无 normal event 的站（{nc['M2']['n_with_0']} 个）：{'、'.join('#%d' % s for s in nc['M2']['stations_with_zero'])}。",
        f"- normal event 的测试窗口（Event start→end）中位数 {fnum(normals['test_days'].median())} 天"
        f"（范围 {fnum(normals['test_days'].min())}~{fnum(normals['test_days'].max())} 天），全部落在站数据范围内。", "")

    add("### 3.6 disturbances 的 type 分布，及与 faults.csv 的不一致", "")
    rows = []
    for m in ("M1", "M2"):
        d = lab[m]["disturbance_type"]
        rows.append([m, d.get("fault", 0), d.get("task", 0), d.get("activity", 0), sum(d.values())])
    add(table(rows, ["厂商", "fault", "task", "activity", "合计"]), "",
        f"- **disturbances 中的 fault 记录（{sum(lab[m]['disturbance_type'].get('fault',0) for m in ('M1','M2'))} 条）远多于 faults.csv（{len(faults)} 条）**："
        "前者是运维系统里的故障/维护流水，后者才是人工确认、带训练窗口与故障类别的“事件报告”。"
        "**建模标签必须用 faults.csv，disturbances 只能用来排除维护时段/选正常段。**",
        "- 38 个“站-厂商”组合的两表数量不一致，典型例子：", "")
    mis = S["fault_vs_disturbance"]["mismatch_rows"]
    mis_sorted = sorted(mis, key=lambda r: r["diff"])[:10]
    add(table([[r["manufacturer"], f"#{r['substation_id']}", r["faults_csv"], r["disturbance_fault"], r["diff"]]
               for r in mis_sorted],
              ["厂商", "站", "faults.csv 条数", "disturbances 中 fault 条数", "差值"]),
        "", f"- 极端例：M2#30 在 disturbances 中有 9 条 fault，但 faults.csv 中 0 条；M2#50 为 13 vs 3；M1#7 为 9 vs 3。", "")

    # ============================================================
    # 4. 训练窗口
    # ============================================================
    add("---", "", "## 4. 训练窗口长度统计与可训练性", "")
    tw = S["training_windows"]
    rows = []
    for label, key in (("faults M1", ("faults", "M1")), ("faults M2", ("faults", "M2")),
                       ("faults 合计", ("faults_all", None)),
                       ("normal M1", ("normal_events", "M1")), ("normal M2", ("normal_events", "M2")),
                       ("normal 合计", ("normal_events_all", None))):
        st = tw[key[0]] if key[1] is None else tw[key[0]][key[1]]
        rows.append([label, st["n_nonnull"], fnum(st["min_days"]), fnum(st["median_days"]), fnum(st["max_days"]),
                     st["n_lt_7d"], st["n_lt_30d"], st["n_lt_90d"], st["n_ge_365d"]])
    add("### 4.1 Training start→end 天数分布", "",
        table(rows, ["事件类别", "有窗口条数", "最短(天)", "中位(天)", "最长(天)", "<7 天", "<30 天", "<90 天", "≥365 天"]), "",
        f"- 结论：normal_events 的训练窗口全部 ≥74 天（无 <30 天），**问题集中在 fault 侧**："
        f"{S['training_windows']['faults_all']['n_lt_30d']} 条故障训练窗口 <30 天（M1 {S['training_windows']['faults']['M1']['n_lt_30d']} / "
        f"M2 {S['training_windows']['faults']['M2']['n_lt_30d']}），另有 {S['training_windows']['faults_all']['n_lt_90d']} 条 <90 天。", "")

    bad_short = faults[(faults.tdays < 30) & faults.tdays.notna()].sort_values("tdays")
    add("### 4.2 训练窗口 <30 天的故障事件（直接影响可训练性）", "",
        table([[r.manufacturer, f"#{int(r.substation_id)}", int(r.event_id), fnum(r.tdays), fpct(r.train_cov),
                r.efd, r.fault_label] for r in bad_short.itertuples()],
              ["厂商", "站", "事件 ID", "训练天数", "窗口覆盖率", "efd", "Fault label"]), "")

    def funnel_rows(key, label):
        x = S["event_funnel"][key]
        return x
    fM1, fM2, fAll = S["event_funnel"]["faults"]["M1"], S["event_funnel"]["faults"]["M2"], S["event_funnel"]["faults_all"]
    nM1, nM2, nAll = S["event_funnel"]["normal_events"]["M1"], S["event_funnel"]["normal_events"]["M2"], S["event_funnel"]["normal_events_all"]
    add("### 4.3 训练窗口可用性漏斗（可建模站-事件对）", "",
        table([
            ["全部事件", fM1["total_events"], fM2["total_events"], fAll["total_events"], nM1["total_events"], nM2["total_events"], nAll["total_events"]],
            ["① 有非空 Training 窗口", fM1["has_training_window"], fM2["has_training_window"], fAll["has_training_window"], nM1["has_training_window"], nM2["has_training_window"], nAll["has_training_window"]],
            ["② 站有运行数据", fM1["station_has_data"], fM2["station_has_data"], fAll["station_has_data"], nM1["station_has_data"], nM2["station_has_data"], nAll["station_has_data"]],
            ["③ 窗口落在站数据范围内（容差 1 天）", fM1["window_inside_data_span"], fM2["window_inside_data_span"], fAll["window_inside_data_span"], nM1["window_inside_data_span"], nM2["window_inside_data_span"], nAll["window_inside_data_span"]],
            ["④ 窗口时间覆盖率 ≥80%", fM1["coverage_ge_0.8"], fM2["coverage_ge_0.8"], fAll["coverage_ge_0.8"], nM1["coverage_ge_0.8"], nM2["coverage_ge_0.8"], nAll["coverage_ge_0.8"]],
            ["⑤ 训练天数 ≥30 天", fM1["train_days_ge_30"], fM2["train_days_ge_30"], fAll["train_days_ge_30"], nM1["train_days_ge_30"], nM2["train_days_ge_30"], nAll["train_days_ge_30"]],
            ["⑥ 站可用特征 ≥8 个", fM1["usable_features_ge_8"], fM2["usable_features_ge_8"], fAll["usable_features_ge_8"], nM1["usable_features_ge_8"], nM2["usable_features_ge_8"], nAll["usable_features_ge_8"]],
            ["**最终可用**", f"**{fM1['usable_final']}**", f"**{fM2['usable_final']}**", f"**{fAll['usable_final']}**",
             f"**{nM1['usable_final']}**", f"**{nM2['usable_final']}**", f"**{nAll['usable_final']}**"],
        ], ["漏斗阶段", "故障 M1", "故障 M2", "故障 合计", "正常 M1", "正常 M2", "正常 合计"]), "",
        "定义：可用 = ①训练窗口非空 且 ②站有数据 且 ③窗口在数据范围内 且 ④覆盖率≥80% 且 ⑤≥30 天 且 ⑥站可用特征（非空率≥80% 且非常数）≥8 个。"
        "1 天容差用于兼容 M2 训练起点与数据起点相差数秒/数分钟的情况。", "",
        f"- 故障侧：**{fAll['usable_final']} / {fAll['total_events']} 条可用**（M1 {fM1['usable_final']}/{fM1['total_events']}、M2 {fM2['usable_final']}/{fM2['total_events']}）；"
        f"这 {fAll['usable_final']} 条全部是 `efd_possible=True`（efd=True 且最终可用也是 {fAll['usable_final']} 条）→ **可监督样本 = 43 条**。",
        f"- 正常侧：**{nAll['usable_final']} / {nAll['total_events']} 条可用**；M2 的 30 条全部可用，M1 损失 7 条（3 条窗口越界、2 条覆盖率不足、2 条可用特征 <8）。", "")

    add("### 4.4 训练窗口的构造规律与“窗口污染”", "")
    delta = (faults["report_date"] - faults["train_end"]).dt.total_seconds() / 86400.0
    n_win = int(faults["train_start"].notna().sum())
    start_eq = (faults["train_start"] - faults["station_t_start"]).abs() <= pd.Timedelta(days=1)
    add(f"- 规律 1：**Training end = Report date − 14 天**（差值中位数 {fnum(delta.median())} 天，"
        f"{int((delta.round(0)==14).sum())}/{int(delta.notna().sum())} 条严格 14 天）→ 故障前最后两周被排除在训练集之外。",
        f"- 规律 2：大多数事件 Training start = 该站数据起点（{int(start_eq.sum())}/{n_win} 条有窗口的事件在起点 1 天内），"
        "所以故障前可用历史长度 ≈ 从“站上线”到“故障前 2 周”；M2 短序列站因此只有几十天~几个月训练数据。", "")

    # 训练窗口与其它事件的重叠（污染）
    def overlaps(a1, a2, b1, b2):
        if pd.isna(a1) or pd.isna(a2) or pd.isna(b1) or pd.isna(b2):
            return False
        return a1 <= b2 and b1 <= a2

    contam = 0
    contam_examples = []
    for i, r in faults.iterrows():
        if pd.isna(r.train_start) or pd.isna(r.train_end):
            continue
        others = faults[(faults.manufacturer == r.manufacturer) & (faults.substation_id == r.substation_id)
                        & (faults.event_id != r.event_id)]
        hit = others[(others.report_date >= r.train_start) & (others.report_date <= r.train_end)]
        if len(hit):
            contam += 1
            if len(contam_examples) < 8:
                contam_examples.append([r.manufacturer, f"#{int(r.substation_id)}", int(r.event_id),
                                        fd(r.train_start), fd(r.train_end),
                                        "、".join(str(int(x)) for x in hit.event_id)])
    self_overlap = 0
    for i, r in faults.iterrows():
        if overlaps(r.train_start, r.train_end, r.test_start, r.test_end):
            self_overlap += 1
    n_contam = 0
    for i, r in normals.iterrows():
        if pd.isna(r.train_start) or pd.isna(r.train_end):
            continue
        fs = faults[(faults.manufacturer == r.manufacturer) & (faults.substation_id == r.substation_id)]
        if len(fs[(fs.report_date >= r.train_start) & (fs.report_date <= r.train_end)]):
            n_contam += 1
    add(f"- **窗口污染**：{contam}/{n_win} 条故障事件的训练窗口内**包含同站其它故障的报告日期**；"
        f"{n_contam}/{len(normals)} 条 normal event 的训练窗口内包含同站故障的报告日期；"
        f"另有 {self_overlap} 条故障的训练窗口与自身异常窗口重叠。"
        "说明一张“干净训练集”不能只按 Training start/end 切——同站多故障（如 M1#7 有 3 条、M1#21 有 4 条、M1#24 有 3 条、M2#10 有 4 条）"
        "时，必须先把其它故障的异常/维护时段从训练窗口里排除，否则存在标签泄漏。", "")
    if contam_examples:
        add(table(contam_examples, ["厂商", "站", "事件 ID", "训练起点", "训练终点", "窗口内包含的其它故障事件 ID"]), "")

    # ============================================================
    # 5. 数据质量红线
    # ============================================================
    add("---", "", "## 5. 数据质量红线", "")
    add("### 5.1 README 末尾“已知异常表”与本数据核对", "")
    rows = []
    for _, a in known.iterrows():
        m, sid = a["manufacturer"], int(a["substation_id"])
        q = prof[(prof.manufacturer == m) & (prof.substation_id == sid)]
        if not len(q):
            rows.append([m, f"#{sid}", f"{a['from']} → {a['to']}", a["description"], "无运行数据文件", "—"])
            continue
        t0, t1 = q.t_start.iloc[0], q.t_end.iloc[0]

        def parse_one(s, is_start):
            s = str(s).strip()
            if s == "start":
                return t0
            if s == "end":
                return t1
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                return pd.Timestamp(s)
            if re.fullmatch(r"\d{4}-\d{2}", s):
                ts = pd.Timestamp(s + "-01")
                return ts if is_start else ts + pd.offsets.MonthEnd(0)
            return None
        a0 = parse_one(a["from"], True)
        a1 = parse_one(a["to"], False)
        status = "—"
        open_bounds = (str(a["from"]).strip() == "start") or (str(a["to"]).strip() == "end")
        if a0 is not None and a1 is not None:
            ov = min(a1, t1) - max(a0, t0)
            if ov.total_seconds() <= 0:
                status = "不在数据覆盖期内"
            elif open_bounds:
                status = "覆盖（半开放区间）"
            else:
                full = (a1 - a0).total_seconds() if (a1 - a0).total_seconds() > 0 else 1
                status = "全覆盖" if ov.total_seconds() >= full * 0.99 else "部分覆盖"
        rows.append([m, f"#{sid}", f"{a['from']} → {a['to']}", a["description"],
                     f"{fd(t0)} ~ {fd(t1)}", status])
    add(table(rows, ["厂商", "站", "异常时间段", "README 描述", "该站数据范围", "与数据重叠"]), "",
        "- 可复核项：M1#19 室外温度确为坏传感器（下限 -64 °C、上限 191.7 °C，见 5.4）；M1#33、M1#21、M1#1、M2#34、M2#41 的行为变化"
        "无法用单列阈值直接验证，按 README 建议在建模时**按时间段剔除或加掩码**。",
        "- **M2#22 在 README 异常表里，但本数据包没有 M2#22 的运行数据**（配置、数据文件都没有）——这条异常无法处理，M2#22/#30/#32 应从站清单中排除。", "")

    add("### 5.2 大段缺失（时间戳整体缺失）", "")
    add("- **没有任何站的整条时间序列完全缺失**（93 个文件都有数据，且不存在“整列全空”的站×特征组合）；"
        "但存在两类“整段不可用”：① 时间轴大段缺口（见下）；② 有行但所有特征高缺失（M2#33、#58，见 5.3）。", "")
    add(f"- >24 小时间隙 **{S['gap_intervals']['n_gt_24h']} 个**，>7 天 **{S['gap_intervals']['n_gt_7d']} 个**，"
        f">30 天 **{S['gap_intervals']['n_gt_30d']} 个**；有 >7 天间隙的站 {S['gaps']['n_stations_gap_gt_7d']} 个，"
        f">30 天间隙的站 {S['gaps']['n_stations_gap_gt_30d']} 个（全部为 M1）。", "")
    rows = []
    for g in S["gap_intervals"]["top"][:15]:
        rows.append([g["manufacturer"], f"#{int(g['substation_id'])}",
                     fd(g["gap_start"]), fd(g["gap_end"]), fnum(g["gap_hours"] / 24.0)])
    add("Top 15 连续缺失区间：", "",
        table(rows, ["厂商", "站", "缺口起点", "缺口终点", "缺口长度(天)"]), "")

    ltc = S["low_time_coverage"]
    add(f"- 时间覆盖率（=实际行数 / 理论 10 分钟行数）<90% 的站：{ltc['n_lt_0.9']} 个；<50% 的站：{ltc['n_lt_0.5']} 个。", "")
    rows = [[r["manufacturer"], f"#{int(r['substation_id'])}", fpct(r["时间覆盖率"]), f"{int(r['row_count']):,}",
             fnum(r["时间跨度天数"], 0), fnum(r["最大连续缺失间隔(小时)"] / 24.0)] for r in ltc["stations"]]
    add(table(rows, ["厂商", "站", "时间覆盖率", "行数", "时间跨度(天)", "最大缺口(天)"]), "",
        "- 说明：时间覆盖率低只代表“时间轴上有空洞”，不代表这些站完全不可用——例如 M1#10 可切成多段（主体为 2012-2015 与 2020 两段）使用；"
        "但**任何跨缺口的滑窗/插值都会得到假数据**。", "")

    add("### 5.3 特征缺失程度", "")
    # M2#33/#58：所有特征缺失率都高，按 80% 口径无可用特征
    zero_avail = prof[prof["可用特征数量"] == 0]
    if len(zero_avail):
        detail = []
        for _, z in zero_avail.iterrows():
            q = fq[(fq.manufacturer == z["manufacturer"]) & (fq.substation_id == z["substation_id"])]
            detail.append(f"{z['manufacturer']}#{int(z['substation_id'])}（行数 {int(z['row_count']):,}，"
                          f"特征缺失率 {fpct(q['null_rate'].min())}~{fpct(q['null_rate'].max())}，"
                          f"若放宽到 50% 非空率则有 {int((q['null_rate'] <= 0.5).sum())}/{int(len(q))} 个特征可用）")
        add(f"- **特别注意：有 {len(zero_avail)} 个站“所有特征都不足 80% 非空”**：" + "；".join(detail) + "。"
            "这两站的 10 分钟行是存在的，但每条记录中相当大比例的特征列是 NaN（疑似采集/导出降采样或部分通道失效），"
            "在 80% 口径下可用特征 = 0，不能直接进多特征模型。", "")
    fq2 = fq.copy()
    g = (fq2.groupby(["manufacturer", "feature"])
         .agg(mean_null=("null_rate", "mean"), median_null=("null_rate", "median"),
              n_stations=("null_rate", "size"), n_valid=("n_valid", "sum")).reset_index())
    top_all = g.sort_values("mean_null", ascending=False).head(6)
    wide = g[g.n_stations >= 10].sort_values("mean_null", ascending=False).head(6)
    add("按“出现该列的站的平均缺失率”排序（含只在 1~2 个站出现的稀有列）：", "",
        table([[r.manufacturer, r.feature, fpct(r.mean_null), fnum(r.median_null * 100), int(r.n_stations)]
               for r in top_all.itertuples()],
              ["厂商", "特征", "站均缺失率", "中位缺失率(%)", "出现站数"]), "",
        "只看出现在 ≥10 个站的特征（更能代表训练时的普遍缺失）：", "",
        table([[r.manufacturer, r.feature, fpct(r.mean_null), fnum(r.median_null * 100), int(r.n_stations)]
               for r in wide.itertuples()],
              ["厂商", "特征", "站均缺失率", "中位缺失率(%)", "出现站数"]), "",
        f"- **最严重的 3 个（全表口径）**：{top_all.iloc[0].feature}（{fpct(top_all.iloc[0].mean_null)}，仅 {int(top_all.iloc[0].n_stations)} 站）、"
        f"{top_all.iloc[1].feature}（{fpct(top_all.iloc[1].mean_null)}）、{top_all.iloc[2].feature}（{fpct(top_all.iloc[2].mean_null)}）。",
        f"- **覆盖面广且缺失严重**（建模真正需要警惕）："
        + "；".join(f"{r.feature}（{fpct(r.mean_null)}，{int(r.n_stations)} 站）" for r in wide.head(3).itertuples()) + "。",
        "- 全表没有一个“整列全空”的（站×特征）组合；但 M1 的 `p_net_*` 表计列站均缺失约 12.7%，"
        "是整段表计数据缺失（不是零散 NaN），见 5.5。", "")

    add("### 5.4 温度类特征物理合理性（-30 ~ 150 °C）", "")
    tq = S["temperature_quality"]
    add(f"- 共检查 {tq['n_pairs']} 个“站×温度特征”组合、{tq['n_valid_values']:,} 个有效温度值；"
        f"越界值 **{tq['total_out_of_range_values']}** 个（{tq['total_out_of_range_values']/max(tq['n_valid_values'],1)*100:.4f}%），"
        f"涉及 {tq['n_pairs_with_out_of_range']} 个组合：", "")
    rows = [[r["manufacturer"], f"#{int(r['substation_id'])}", r["feature"], f"{int(r['n_valid']):,}",
             int(r["out"]), fnum(r["min"]), fnum(r["max"])] for r in tq["worst"] if r["out"] and r["out"] > 0]
    add(table(rows, ["厂商", "站", "特征", "有效值数", "越界值数", "最小值(°C)", "最大值(°C)"]), "",
        "- 结论：越界几乎全部来自 **M1#19 的室外温度**（-64~191.7 °C，987 个越界值）——README 已注明“坏传感器”，"
        "必须删除该特征或至少截断到 2016-06 之后；M2#17 的 `s_dhw_lower_storage_temperature` 有 3 个 -230 °C 级野值；"
        "M2#20 的 `p_net_supply_temperature` 有 1 个 181 °C 野值。其余温度值均在物理区间内。", "")

    out_s = S["outdoor_sensor"]
    add(f"- **室外温度传感器异常（新增发现）**：{out_s['n_suspect']} 个 M2 站的室外温度长期近似常数（变化范围 <5 °C）：", "")
    rows = [[r["manufacturer"], f"#{int(r['substation_id'])}", int(r["nunique"]), fnum(r["min"]), fnum(r["max"]),
             fnum(r["range"])] for r in out_s["suspect"]]
    add(table(rows, ["厂商", "站", "不同取值个数", "最小(°C)", "最大(°C)", "极差(°C)"]), "",
        "- 其中 **M2#18（0.2~1.0 °C）、M2#61（-3.0~-2.3 °C）** 与 README 所指“室外温度不可用/不可信”一致；"
        "**M2#3、M2#47 是 README 未列出的新增异常**。M2#41 的室外温度实际为 -9.7~23.1 °C（变化合理），"
        "与 README 描述不符，建议人工复核（可能只是该站不用室外温度做控制）。", "")
    rows = [[r["manufacturer"], f"#{int(r['substation_id'])}", fpct(r["null_rate"]), int(r["nunique"]),
             fnum(r["min"]), fnum(r["max"])] for r in out_s["highest_null"][:5]]
    add("室外温度缺失率最高的 5 站：", "",
        table(rows, ["厂商", "站", "缺失率", "不同取值个数", "最小(°C)", "最大(°C)"]), "")

    add("### 5.5 能量/流量/功率表计质量", "")
    mq = S["meter_quality"]
    add(table([
        ["p_net_meter_energy", fpct(mq["zero_rate_by_feature"].get("p_net_meter_energy", 0)),
         fpct(mq["null_rate_by_feature"].get("p_net_meter_energy", 0)), "累积量（kWh / Wh）"],
        ["p_net_meter_volume", fpct(mq["zero_rate_by_feature"].get("p_net_meter_volume", 0)),
         fpct(mq["null_rate_by_feature"].get("p_net_meter_volume", 0)), "累积量（m3 / ml）"],
        ["p_net_meter_heat_power", fpct(mq["zero_rate_by_feature"].get("p_net_meter_heat_power", 0)),
         fpct(mq["null_rate_by_feature"].get("p_net_meter_heat_power", 0)), "瞬时功率（kW / W）"],
        ["p_net_meter_flow", fpct(mq["zero_rate_by_feature"].get("p_net_meter_flow", 0)),
         fpct(mq["null_rate_by_feature"].get("p_net_meter_flow", 0)), "瞬时流量（l/h / ml/h）"],
    ], ["表计特征", "平均零值率", "平均缺失率", "物理含义 / 单位"]), "",
        f"- **没有“长期为 0”的表计列**：没有任何（站×表计列）的零值率 >95%；零值率平均值最高的功率表也只有 "
        f"{fpct(mq['zero_rate_by_feature'].get('p_net_meter_heat_power', 0))}（多为夏季/待机时段），属正常工况。",
        f"- **但累积表计严重非单调**：`p_net_meter_energy` 的平均非递增步长比例 **{fpct(mq['non_increasing_by_feature'].get('p_net_meter_energy', 0))}**、"
        f"`p_net_meter_volume` **{fpct(mq['non_increasing_by_feature'].get('p_net_meter_volume', 0))}**。"
        "典型原因是计数器归零/设备更换/长时间读数不变。**不能直接 diff() 得增量，也不能把原值当连续特征喂模型**；"
        "建议：按 `diff()` 后丢弃负值和异常大值、或改用“站内归一化 + 重置点掩码”，或者直接用配套的 heat_power/flow 瞬时量。", "")

    units = [["p_net_meter_energy", "kWh", "Wh"], ["p_net_meter_volume", "m3", "ml"],
             ["p_net_meter_flow", "l/h", "ml/h"], ["p_net_meter_heat_power", "kW", "W"]]
    add("**同名特征的单位差异（跨厂商拼接必须换算）**：", "",
        table(units, ["特征", "M1 单位", "M2 单位"]), "",
        "M2 的能量/体积/功率数值量级与 M1 相差 1000 倍（如 M2 的能量列常见 1e9 量级）；"
        "若用同一套标准化参数直接拼两个厂商，M2 特征会主导方差。", "")

    add("**表计整段缺失的站（缺失率 >30%，不是零散 NaN）**：", "")
    rows = []
    seen = set()
    for r in mq["high_null"]:
        key = (r["manufacturer"], r["substation_id"])
        if key in seen:
            continue
        seen.add(key)
        feats = [x["feature"] for x in mq["high_null"] if x["manufacturer"] == r["manufacturer"] and x["substation_id"] == r["substation_id"]]
        rows.append([r["manufacturer"], f"#{int(r['substation_id'])}", fpct(r["null_rate"]), f"{len(feats)} 列"])
    add(table(rows, ["厂商", "站", "表计列缺失率", "涉及表计列数"]), "",
        "- 这些站的表计数据在时间轴上有整段缺失（对应 5.2 的缺口或表计通信中断）；建模前应按“表计可用时段”切数据，而不是插值补齐。", "")

    add("### 5.6 其他会坑建模的问题", "")
    add("- **重复表头**：M2#21、#57 的文件里有两个 `outdoor_temperature` 列（第二个被 pandas 存成 `outdoor_temperature.1`）。"
        "两列高度相关（M2#21 corr=0.994、#57 corr=0.9998），但 M2#57 的第二列缺失 18.6%、M2#21 的最大偏差 22.6 °C。"
        "**建议保留第一列、删除 `.1`，并核对极端偏差出现的时间段。**", "")
    add(f"- **时间戳**：重复/乱序/解析失败均为 0（干净）；但 M2 有 {S['timestamp_second_jitter']['M2']:,} 行时间戳秒数 ≠0（±1~7 秒抖动），"
        f"{S['one_minute_rows']['n_stations']} 个 M2 站开头 24 h 为 1 分钟粒度（合计 {S['one_minute_rows']['total']:,} 个 1 分钟间隔）。"
        "固定的“每 144 行 = 1 天”假设在 M2 会错位。", "")
    add(f"- **超短序列**：时间跨度 <180 天的 M2 站 {short180} 个（最短 33.6 天），其中 #1、#38、#42、#48、#51 连 60 天都不到且无 faults/normal 标签；"
        "M1 最短的是 #30（236.5 天）。**M2 的站均跨度中位数只有 183.1 天**（M1 为 1,708.5 天），两厂商不能按同一套“多年训练窗口”假设做实验。", "")
    add("- **配置表缺值**：M2#57 的 `configuration_type` 为空（其余 57 站有值）。"
        "M1 只有 2 类配置（SH + DHW 28 站、SH + DHW with sub-circuits 7 站）；"
        "M2 有 4 类（SH、SH + DHW、SH with buffer tank、SH with sub-circuits），跨厂商的“配置”变量不能直接对齐。", "")
    add("- **首月规则**：README 明确“每条时间序列的第一个月建议删除”（调试/参数频繁变动期）。本项目所有站的数据起点都在上表，"
        "切数据时应统一丢弃每站前 30 天；M2 多个短序列站丢首月后只剩 ~2–5 个月。", "")
    add("- **M2 的 9 个站共用同一时间戳网格**：M2#3、#5、#7、#10、#17、#40、#49、#55、#60 的时间戳完全一致"
        "（2015-10-13 12:39:01 ~ 2020-04-02，236,084 行，含同样的开头 1 分钟段）。这是打包/导出痕迹，**不代表这 9 个站数据重复**"
        "（文件大小与各项数值不同），但做“时间戳去重/索引对齐”时不要误判为重复文件。", "")
    add("- **两厂商的数据截止时间不同**：M2 所有 58 个站统一截止 **2020-04-02**（疑似导出截止日），M1 多数站截止 2020-07-28；"
        "且 M2 有 28 个站 2019-08 之后才上线（可用历史很短）。**跨厂商对照实验必须按各自可用时段切分，不能假设相同测试期。**", "")

    add("### 5.7 “必须剔除 / 特殊处理”清单（建模前逐条确认）", "")
    redline = [
        ["M2 #1、#38、#42、#48、#51", "时间跨度 33.6~54.7 天，无 faults.csv / normal_events 标签", "直接剔除（或只做无监督 demo，不能进监督集）"],
        ["M2 #33、#58", "有 2.4~2.5 万行但所有特征缺失率 31.2%~79.2%，80% 口径可用特征=0", "若要使用：只保留缺失率最低的特征、按“实际有值行”切数据/降采样，不能插值补全"],
        ["M2 跨度 <180 天的另外 23 站", "站均只有约 3–6 个月数据（多为 2019-08 之后上线）", "只做“短训练窗口”实验；不要与 M1 混在一起报指标"],
        ["M1 #10", "4.6 年缺口（2015-05-29→2020-01-08），覆盖率 34.3%", "切段处理（2012-2015、2020 两段），禁止跨缺口滑窗/插值"],
        ["M1 #14、#12、#7、#8、#11、#2、#4、#16、#21、#28", "各有 1 条 30~365 天的大缺口（多数在夏季）", "按缺口切段；训练/测试窗口不得跨越缺口"],
        ["M1 #19", "室外温度坏传感器：-64~191.7 °C，987 个越界值；缺失 19.5%", "删除室外温度特征或截断到 2016-06 之后"],
        ["M2 #18、#3、#47、#61", "室外温度长期近似常数（极差 <1 °C）", "删除室外温度特征（或仅保留“不可用”标记）"],
        ["M2 #21、#57", "重复表头 outdoor_temperature.1", "删除 .1 列；核对偏差时段"],
        ["M1 #15、#17、#18、#24；M2 #3、#13、#33、#58", "表计列整段缺失 31%~79%", "按“表计可用时段”切数据；不要前向填充掩盖缺失"],
        ["M1 #1、#19、#21、#33；M2 #22、#34、#41", "README 已知行为异常（见 5.1）", "按 README 时间段剔除/加掩码；#22 无数据，直接排除"],
        ["M2 #22、#30、#32", "配置表/数据文件均缺失（#30 的 disturbance 记录、#22 的异常表仍在）", "从站清单排除，并在标签对账时说明"],
        ["M1 / M2 长序列站", "能量/体积累计计数器频繁归零（平均非递增步长 35.2% / 34.7%）", "重置感知 diff，或改用 heat_power/flow"],
        ["所有 M2 站", "表计单位是 Wh/ml/W；时间戳秒抖动", "单位换算（÷1000）；按 10 分钟 floor 后对齐"],
        ["所有站", "首月调试期；fault 训练窗口可能含同站其它故障", "统一丢弃每站前 30 天；训练窗口内排除其它事件异常/维护时段"],
    ]
    add(table(redline, ["对象", "问题", "处理建议"]), "")

    # ============================================================
    # 6. 可用于建模的站-事件对
    # ============================================================
    add("---", "", "## 6. 可用于建模的站-事件对清单", "")
    add(f"**结论：故障侧可用 {usable_f} 条（覆盖 {f_ok.groupby(['manufacturer','substation_id']).ngroups} 个“厂商-站”组合），"
        f"正常侧可用 {usable_n} 条（覆盖 {n_ok.groupby(['manufacturer','substation_id']).ngroups} 个组合）。** "
        "这就是本项目监督/无监督实验的真实样本量上限。", "")
    add("### 6.1 可用故障事件清单（43 条）", "",
        "（按 厂商/站 排序；覆盖率 = 训练窗口内实际行数 / 理论 10 分钟行数，可能略 >100%，因为窗口起点常比数据起点早数秒~数分钟）", "")
    cols = ["厂商", "事件 ID", "站", "报告日期", "Fault label", "监控潜力", "训练起点", "训练终点", "训练天数", "覆盖率", "efd"]
    rows = []
    for r in f_ok.sort_values(["manufacturer", "substation_id", "event_id"]).itertuples():
        rows.append([r.manufacturer, int(r.event_id), f"#{int(r.substation_id)}", fd(r.report_date),
                     r.fault_label, str(r.monitoring_potential), fd(r.train_start), fd(r.train_end),
                     fnum(r.tdays), fpct(r.train_cov), r.efd])
    add(table(rows, cols), "")

    add("### 6.2 不可用故障事件及原因（30 条）", "")
    reason_cn = {"no_training_window": "无训练窗口", "window_outside_data": "窗口越界",
                 "train_too_short": "训练<30天", "data_coverage_low": "覆盖率<80%",
                 "station_missing": "站无数据", "too_few_usable_features": "可用特征<8"}
    rows = []
    for r in f_bad.sort_values(["manufacturer", "substation_id", "event_id"]).itertuples():
        issues = [x for x in str(r.issues).split("|") if x]
        txt = "、".join(reason_cn.get(x, x) for x in issues) or "—"
        rows.append([r.manufacturer, int(r.event_id), f"#{int(r.substation_id)}", fd(r.report_date),
                     r.efd, "—" if pd.isna(r.tdays) else fnum(r.tdays),
                     fpct(r.train_cov) if not pd.isna(r.train_cov) else "—", txt, r.fault_label])
    add(table(rows, ["厂商", "事件 ID", "站", "报告日期", "efd", "训练天数", "覆盖率", "不可用原因", "Fault label"]), "")

    add("### 6.3 按站的可建模事件分布", "")
    st = pd.DataFrame(S["usable_events_by_station"])
    st["total_usable"] = st["usable_faults"] + st["usable_normals"]
    has_f = st[st.usable_faults > 0]
    add(f"- 有 ≥1 条可用故障事件的站：**{len(has_f)} 个**（M1 {(has_f.manufacturer=='M1').sum()} / M2 {(has_f.manufacturer=='M2').sum()}）；"
        f"可用故障事件最多的站：" + "、".join(f"{r.manufacturer}#{int(r.substation_id)}({int(r.usable_faults)} 条)"
        for r in st.sort_values("usable_faults", ascending=False).head(6).itertuples()) + "。",
        f"- 有 ≥1 条可用 normal event 的站：**{int((st.usable_normals>0).sum())} 个**"
        f"（M1 {int(((st.manufacturer=='M1')&(st.usable_normals>0)).sum())} / M2 {int(((st.manufacturer=='M2')&(st.usable_normals>0)).sum())}）。",
        "", "按站明细（仅列出有可用事件的站）：", "")
    rows = []
    for r in st[(st.total_usable > 0)].sort_values(["manufacturer", "substation_id"]).itertuples():
        rows.append([r.manufacturer, f"#{int(r.substation_id)}", int(r.usable_faults), int(r.usable_normals),
                     int(r.row_count), fnum(r.span_days, 0)])
    add(table(rows, ["厂商", "站", "可用故障数", "可用正常数", "行数", "跨度(天)"]), "")

    # ============================================================
    # 7. 口径与产出
    # ============================================================
    add("---", "", "## 7. 产出文件、口径与复现", "")
    add("### 7.1 产出文件（均在本目录 `勘探/` 下）", "",
        table([
            ["substation_profile.csv", "每站一行：配置、行数、起止、跨度、采样间隔、重复/乱序时间戳、最大缺口、覆盖率、"
                                        "平均/最大缺失率、可用特征数、可用特征列表（另有逐特征 `miss_*` 缺失率列）、三类标签计数"],
            ["null_profile_by_substation.csv", "附表：站 × 特征 缺失率矩阵（空 = 该站没有此列）"],
            ["feature_presence_by_manufacturer.csv", "每个特征在 M1/M2 多少个站出现、单位、是否有 feature_description"],
            ["feature_value_quality.csv", "站 × 特征 数值质量：缺失率、min/max/mean、零值率、温度越界数、类别 Top 值"],
            ["fault_events_enriched.csv", "73 条故障事件 + 训练/异常窗口覆盖率 + 是否可用 + 原因（建模输入表）"],
            ["normal_events_enriched.csv", "65 条 normal event + 训练/测试窗口覆盖率 + 是否可用"],
            ["fault_label_distribution.csv", "Fault label / Monitoring potential 分布（脚本另存）"],
            ["disturbance_type_distribution.csv", "disturbance type 分布（脚本另存）"],
            ["known_anomalies.csv", "README 已知异常表结构化（9 条）"],
            ["profile_summary.json", "全部汇总数字（本报告的机器可读版本）"],
            ["build_profile.py", "清点脚本（全量重跑约 41 秒）"],
        ], ["文件", "内容"]), "",
        "> 说明：`fault_label_distribution.csv` 与 `disturbance_type_distribution.csv` 是标签/干扰分布的**长表版本**，可直接用于画图；"
        "报告第 3 节已给出汇总。", "")

    add("### 7.2 关键口径", "")
    add("- **缺失率**：该列 NaN 行数 / 总行数。时间戳整体缺失（数据空洞）不计入缺失率，单独用“最大连续缺失间隔/时间覆盖率”衡量。",
        "- **可用特征**：非空率 ≥80% 且至少有 2 个不同取值（排除常数/仅单值列）。",
        "- **采样间隔中位数**：相邻时间戳差分的正数中位数；M2 开头 1 分钟段不会改变中位数（仍为 10 分钟）。",
        "- **时间覆盖率**：实际行数 / (时间跨度 / 中位采样间隔 + 1)。可近似理解为“时间轴上已有数据的比例”。",
        "- **训练窗口可用（可建模站-事件对）**：Training start/end 非空 且 站有运行数据 且 窗口在数据范围内（1 天容差）"
        " 且 窗口时间覆盖率 ≥80% 且 训练天数 ≥30 且 站可用特征 ≥8。",
        "- **温度越界**：温度类特征取值 < -30 °C 或 > 150 °C。",
        "- **“各特征总缺失率”**：在 `substation_profile.csv` 中以逐特征 `miss_<特征名>` 列给出；"
        "另汇总为 `特征平均缺失率` / `最大单特征缺失率` 两列，逐特征明细在 `null_profile_by_substation.csv`。", "")

    add("### 7.3 复现", "", "```powershell",
        "# 全量重跑（读 93 个 CSV，约 41 秒；只写 勘探/ 目录）",
        "& 'C:\\Users\\lzh\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe' ^",
        "  'C:\\Users\\lzh\\Desktop\\AI\\供热管道\\工作站\\勘探\\build_profile.py'",
        "",
        "# 仅用已有中间结果重生成本报告（秒级）",
        "& 'C:\\Users\\lzh\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe' ^",
        "  'C:\\Users\\lzh\\Desktop\\AI\\供热管道\\工作站\\勘探\\build_profile.py' --report",
        "```", "")

    # ============================================================
    # 附录 A
    # ============================================================
    add("---", "", "## 附录 A：93 个站概览", "",
        "> 完整字段见 `substation_profile.csv`；这里只列关键列。`最大缺口` 为时间戳相邻最大间隔；"
        "`覆盖率` 为时间覆盖率；`可用特征` 为非空率≥80% 且非常数的特征数。", "")
    cfg_map = {"SH": "SH", "SH + DHW": "SH+DHW", "SH + DHW with sub-circuits": "SH+DHW+子回路",
               "SH with buffer tank": "SH+缓冲罐", "SH with sub-circuits": "SH+子回路"}
    rows = []
    for _, r in prof.sort_values(["manufacturer", "substation_id"]).iterrows():
        cfg = cfg_map.get(str(r["configuration_type"]), str(r["configuration_type"]) if isinstance(r["configuration_type"], str) else "—")
        rows.append([r["manufacturer"], int(r["substation_id"]), cfg, f"{int(r['row_count']):,}",
                     fd(r["t_start"]), fd(r["t_end"]), fnum(r["时间跨度天数"], 0),
                     fnum(r["采样间隔中位数(分钟)"]), fnum(r["最大连续缺失间隔(小时)"] / 24.0),
                     fpct(r["时间覆盖率"]), int(r["可用特征数量"]),
                     int(r["fault_event_count"]), int(r["normal_event_count"]), int(r["total_disturbance_count"])])
    add(table(rows, ["厂商", "站", "配置", "行数", "起始", "结束", "跨度(天)", "间隔(min)",
                     "最大缺口(天)", "覆盖率", "可用特征", "故障", "正常", "扰动"]), "",
        "> 注：M2#33、#58 的“可用特征=0”是因为所有特征非空率都低于 80%（见 5.3），不是文件为空；"
        "M2#22、#30、#32 不在表中是因为本数据包没有这三个站的运行数据（见 1.3）。", "")

    text = "\n".join(L)
    (OUT / "data_inventory.md").write_text(text, encoding="utf-8")
    log(f"写出 data_inventory.md : {len(text):,} 字符 / {len(L)} 行")


if __name__ == "__main__":
    if "--report" in sys.argv:
        generate_report()
        print("data_inventory.md 已重新生成")
    else:
        compute()
        generate_report()
        print("清点完成：见 勘探/data_inventory.md")
