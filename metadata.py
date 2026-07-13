"""
metadata.py - CSV 메타데이터 생성 및 업데이트

정상 JPG-NPY 파일쌍을 기준으로 metadata.csv를 생성/업데이트합니다.
이미 CSV에 있는 레코드는 건너뜁니다.
"""

import os
import sys
import json
import csv
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from thermal_utils import extract_from_jpeg

SAVE_DIR = "thermal_dataset"
CONFIG_PATH = "experiment_config.json"

CSV_HEADER = [
    "image_id", "timestamp", "image_path", "thermal_path",
    "min_temp", "max_temp", "mean_temp",
    "experiment_id", "condition", "target_temp",
    "distance_cm", "angle_deg", "ambient_temp", "notes"
]


def scan_pairs():
    files = os.listdir(SAVE_DIR)
    # 써멀 JPG만 대상 (가시광 _visual.jpg 제외)
    jpgs = {f.replace(".jpg", ""): f for f in files if f.endswith(".jpg") and "_visual" not in f}
    npys = {f.replace("_thermal.npy", ""): f for f in files if f.endswith("_thermal.npy")}
    return sorted(set(jpgs.keys()) & set(npys.keys())), jpgs, npys


def load_existing_ids():
    csv_path = os.path.join(SAVE_DIR, "metadata.csv")
    if not os.path.exists(csv_path):
        return set()
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        return {row[0] for row in reader if row}


def main():
    if not os.path.isdir(SAVE_DIR):
        print(f"'{SAVE_DIR}' 폴더가 존재하지 않습니다.")
        return

    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

    paired, jpgs, npys = scan_pairs()
    existing = load_existing_ids()
    new_ids = sorted(set(paired) - existing)

    print(f"파일쌍: {len(paired)}개  CSV 기존: {len(existing)}개  신규: {len(new_ids)}개")

    if not new_ids:
        print("추가할 레코드가 없습니다.")
        return

    csv_path = os.path.join(SAVE_DIR, "metadata.csv")
    write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(CSV_HEADER)

        count = 0
        for base in new_ids:
            jpg_path = os.path.join(SAVE_DIR, jpgs[base])
            npy_path = os.path.join(SAVE_DIR, npys[base])
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

        print(f"추가 완료: {count}개")


if __name__ == "__main__":
    main()
