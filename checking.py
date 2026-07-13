"""checking.py - 데이터셋 무결성 검사 및 복구

- NPY가 누락된 JPG → 온도 행렬 자동 추출
- JPG가 없는 고아 NPY → 삭제
"""

import os
import sys
import numpy as np

# 프로젝트 루트를 path에 추가 (thermal_utils import를 위해)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from thermal_utils import extract_from_jpeg

SAVE_DIR = "thermal_dataset"


def scan_dataset():
    files = os.listdir(SAVE_DIR)
    # 써멀 JPG만 대상 (가시광 _visual.jpg 제외)
    jpgs = sorted([f for f in files if f.endswith(".jpg") and "_visual" not in f])
    npys = sorted([f for f in files if f.endswith("_thermal.npy")])
    jpg_bases = {f.replace(".jpg", ""): f for f in jpgs}
    npy_bases = {f.replace("_thermal.npy", ""): f for f in npys}
    return jpg_bases, npy_bases


def main():
    if not os.path.isdir(SAVE_DIR):
        print(f"'{SAVE_DIR}' 폴더가 존재하지 않습니다.")
        return

    print(f"=== '{SAVE_DIR}' 무결성 검사 ===")
    jpg_bases, npy_bases = scan_dataset()

    paired = set(jpg_bases.keys()) & set(npy_bases.keys())
    missing_npy = set(jpg_bases.keys()) - set(npy_bases.keys())
    orphan_npy = set(npy_bases.keys()) - set(jpg_bases.keys())

    print(f"JPG: {len(jpg_bases)}개  NPY: {len(npy_bases)}개  "
          f"정상: {len(paired)}개  NPY 누락: {len(missing_npy)}개  JPG 누락: {len(orphan_npy)}개")

    # 1. NPY 누락 → JPG에서 추출
    if missing_npy:
        print(f"\n▶ NPY 누락 복구 ({len(missing_npy)}개)")
        fixed, failed = 0, 0
        for base in sorted(missing_npy):
            jpg_path = os.path.join(SAVE_DIR, jpg_bases[base])
            npy_path = os.path.join(SAVE_DIR, base + "_thermal.npy")
            try:
                thermal, _ = extract_from_jpeg(jpg_path)
                np.save(npy_path, thermal)
                print(f"  ✓ {npy_path}  "
                      f"(min={np.nanmin(thermal):.1f}°C, max={np.nanmax(thermal):.1f}°C)")
                fixed += 1
            except Exception as e:
                print(f"  ✗ {jpg_bases[base]} — {e}")
                failed += 1
        print(f"복구: {fixed}개 성공, {failed}개 실패")

    # 2. JPG 누락 → 고아 NPY 삭제
    if orphan_npy:
        print(f"\n▶ JPG 누락 — 고아 NPY 삭제 ({len(orphan_npy)}개)")
        for base in sorted(orphan_npy):
            npy_path = os.path.join(SAVE_DIR, npy_bases[base])
            os.remove(npy_path)
            print(f"  ✗ 삭제됨: {npy_path}")

    # 최종 요약
    jpg_bases2, npy_bases2 = scan_dataset()
    paired2 = len(set(jpg_bases2.keys()) & set(npy_bases2.keys()))
    missing2 = len(set(jpg_bases2.keys()) - set(npy_bases2.keys()))
    orphan2 = len(set(npy_bases2.keys()) - set(jpg_bases2.keys()))

    print(f"\n=== 최종: JPG {len(jpg_bases2)}개  NPY {len(npy_bases2)}개  "
          f"정상 쌍 {paired2}개  NPY 누락 {missing2}개  JPG 누락 {orphan2}개 ===")

    if missing2 == 0 and orphan2 == 0:
        print("모든 파일이 정상입니다.")
        print("\n이제 metadata.py를 실행하세요 → python metadata.py")
    else:
        print("⚠ 불일치가 남아있습니다. 다시 실행해보세요.")


if __name__ == "__main__":
    main()
