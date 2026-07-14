"""
metadata.py - CSV 메타데이터 생성 및 업데이트

정상 JPG-NPY 파일쌍을 기준으로 metadata.csv를 생성/업데이트합니다.
이미 CSV에 있는 레코드는 건너뜁니다.

사용법 (import):
    from metadata import run_metadata
    result = run_metadata(log_callback=print)
"""

import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from thermal_utils import extract_from_jpeg

SAVE_DIR = "thermal_dataset"
CONFIG_PATH = "experiment_config.json"

CSV_HEADER = [
    "image_id", "timestamp", "image_path", "thermal_path",
    "min_temp", "max_temp", "mean_temp",
    "experiment_id", "condition", "target_temp",
    "distance_cm", "angle_deg", "ambient_temp", "notes",
]


class MetadataResult:
    def __init__(self):
        self.total_pairs = 0
        self.existing = 0
        self.new = 0
        self.messages: list[str] = []


def _log(msg: str, log_callback=None, messages: list[str] | None = None):
    if log_callback:
        log_callback(msg)
    else:
        print(msg)
    if messages is not None:
        messages.append(msg)


def run_metadata(
    save_dir: str = SAVE_DIR,
    config_path: str = CONFIG_PATH,
    log_callback=None,
) -> MetadataResult:
    result = MetadataResult()

    if not os.path.isdir(save_dir):
        _log(f"'{save_dir}' folder not found.", log_callback, result.messages)
        return result

    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    files = os.listdir(save_dir)
    jpgs = {f.replace(".jpg", ""): f
            for f in files if f.endswith(".jpg") and "_visual" not in f}
    npys = {f.replace("_thermal.npy", ""): f
            for f in files if f.endswith("_thermal.npy")}
    paired = sorted(set(jpgs.keys()) & set(npys.keys()))

    csv_path = os.path.join(save_dir, "metadata.csv")
    existing_ids: set[str] = set()
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            existing_ids = {row[0] for row in reader if row}

    new_ids = sorted(set(paired) - existing_ids)

    result.total_pairs = len(paired)
    result.existing = len(existing_ids)
    result.new = len(new_ids)

    _log(f"Pairs: {result.total_pairs}  Existing: {result.existing}  "
         f"New: {result.new}", log_callback, result.messages)

    if not new_ids:
        _log("No new records to add.", log_callback, result.messages)
        return result

    write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(CSV_HEADER)

        count = 0
        for base in new_ids:
            jpg_path = os.path.join(save_dir, jpgs[base])
            npy_path = os.path.join(save_dir, npys[base])
            thermal = np.load(npy_path)

            try:
                _, cap_meta = extract_from_jpeg(jpg_path)
            except Exception:
                cap_meta = {"timestamp": "", "distance_cm": 0, "ambient_temp": 0.0}

            row = [
                base,
                cap_meta.get("timestamp", ""),
                jpgs[base],
                npys[base],
                round(float(np.nanmin(thermal)), 2),
                round(float(np.nanmax(thermal)), 2),
                round(float(np.nanmean(thermal)), 2),
                config.get("experiment_id", ""),
                config.get("condition", ""),
                config.get("target_temp", ""),
                cap_meta.get("distance_cm", ""),
                config.get("angle_deg", ""),
                round(float(cap_meta.get("ambient_temp", 0)), 2),
                config.get("notes", ""),
            ]
            writer.writerow(row)
            count += 1

        _log(f"Added {count} records.", log_callback, result.messages)

    return result


if __name__ == "__main__":
    run_metadata()
