"""Generate synthetic, labelled input. This is not station validation data."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .schemas import UNITS


def example_request(count: int = 60) -> dict:
    samples = []
    for i, timestamp in enumerate(pd.date_range("2017-11-18T00:00:00+00:00", periods=count, freq="30min")):
        wave = float(np.sin(i / 8))
        samples.append({"timestamp": timestamp.isoformat(), "values": {
            "outdoor_temperature": 5 + wave,
            "p_net_supply_temperature": 80 + wave,
            "p_net_return_temperature": 45 + wave,
            "p_net_meter_heat_power": 100 + 10 * wave,
            "p_net_meter_flow": 2500 + 200 * wave,
            "p_hc1_return_temperature": 35 + wave,
            "s_hc1_supply_temperature": 55 + wave,
            "s_hc1_supply_temperature_setpoint": 55.0,
        }})
    return {"stationId": "station-example-m1-7", "modelId": "station-nbm-m1-7",
            "modelVersion": "example-1", "timezone": "Etc/UTC", "units": UNITS.copy(), "samples": samples}


def main():
    parser = argparse.ArgumentParser(description="生成合成接口测试请求（不代表现场真实数据）")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(example_request(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("已生成合成测试请求；仅供接口验证。")


if __name__ == "__main__":
    main()
