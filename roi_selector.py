"""
roi_selector.py - GUI ROI 영역 설정 도구

사용법:
    python roi_selector.py [thermal_image.jpg]

Thermal 이미지를 띄우고 마우스 드래그로 ROI 영역을 지정합니다.
선택 완료 후 S 키를 누르면 roi_config.json이 자동 업데이트됩니다.

조작:
    마우스 드래그 : ROI 영역 선택
    ESC / Q       : 종료 (변경사항 저장 안 함)
    S             : 현재 선택 영역을 roi_config.json에 저장 후 종료
    R             : 선택 영역 초기화
"""

import json
import os
import sys
import glob

import cv2
import numpy as np

DATASET_DIR = "thermal_dataset"
CONFIG_PATH = "roi_config.json"
DISPLAY_WIDTH = 800

# ROI 상태
roi_start = None   # (x, y) 드래그 시작점 (원본 이미지 좌표)
roi_end = None     # (x, y) 드래그 끝점 (원본 이미지 좌표)
final_roi = None   # 확정된 ROI (x1, y1, x2, y2) 원본 이미지 좌표
dragging = False
scale = 1.0


def resize_for_display(img, width):
    h, w = img.shape[:2]
    height = int(h * width / w)
    return cv2.resize(img, (width, height))


def mouse_callback(event, x, y, flags, param):
    global roi_start, roi_end, final_roi, dragging

    # 표시 좌표 -> 원본 좌표
    ox = int(x * scale)
    oy = int(y * scale)

    if event == cv2.EVENT_LBUTTONDOWN:
        roi_start = (ox, oy)
        roi_end = (ox, oy)
        final_roi = None
        dragging = True

    elif event == cv2.EVENT_MOUSEMOVE and dragging:
        roi_end = (ox, oy)

    elif event == cv2.EVENT_LBUTTONUP:
        dragging = False
        roi_end = (ox, oy)
        if roi_start and roi_end:
            x1 = min(roi_start[0], roi_end[0])
            y1 = min(roi_start[1], roi_end[1])
            x2 = max(roi_start[0], roi_end[0])
            y2 = max(roi_start[1], roi_end[1])
            if x2 - x1 > 5 and y2 - y1 > 5:
                final_roi = (x1, y1, x2, y2)
            else:
                final_roi = None


def get_roi_box():
    """현재 ROI 박스 좌표 반환 (원본 기준), 없으면 None"""
    if final_roi:
        return final_roi
    if roi_start and roi_end:
        x1 = min(roi_start[0], roi_end[0])
        y1 = min(roi_start[1], roi_end[1])
        x2 = max(roi_start[0], roi_end[0])
        y2 = max(roi_start[1], roi_end[1])
        if x2 - x1 > 2 and y2 - y1 > 2:
            return (x1, y1, x2, y2)
    return None


def load_existing_roi():
    """기존 roi_config.json에서 저장된 ROI 불러오기"""
    if not os.path.isfile(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    roi = cfg.get("thermal_roi", {})
    x1 = roi.get("x1")
    y1 = roi.get("y1")
    x2 = roi.get("x2")
    y2 = roi.get("y2")
    if None not in (x1, y1, x2, y2):
        return (int(x1), int(y1), int(x2), int(y2))
    return None


def save_roi(roi):
    """roi_config.json에 ROI 좌표 저장"""
    x1, y1, x2, y2 = roi

    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {}

    cfg["thermal_roi"] = {
        "_comment": "Thermal 이미지(640x480) 기준 관심 영역 [x1, y1, x2, y2]",
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
    }

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

    print(f"[roi_selector] ROI saved to {CONFIG_PATH}: ({x1},{y1})-({x2},{y2})")


def main():
    global scale

    # 이미지 선택
    if len(sys.argv) >= 2:
        img_path = sys.argv[1]
    else:
        jpg_files = sorted(glob.glob(os.path.join(DATASET_DIR, "*.jpg")))
        thermal_files = [f for f in jpg_files if "_visual" not in f]
        img_path = thermal_files[-1] if thermal_files else None

    if img_path is None:
        print("Thermal 이미지를 찾을 수 없습니다.")
        print("사용법: python roi_selector.py [thermal_image.jpg]")
        sys.exit(1)

    img = cv2.imread(img_path)
    if img is None:
        print(f"이미지를 불러올 수 없습니다: {img_path}")
        sys.exit(1)

    print(f"Loaded: {img_path}  ({img.shape[1]}x{img.shape[0]})")
    print("  Drag mouse to set ROI")
    print("  S = save & exit    R = reset    ESC/Q = quit without saving")

    # 기존 ROI 있으면 로드
    existing = load_existing_roi()
    if existing:
        global final_roi
        final_roi = existing
        print(f"  Loaded existing ROI: ({existing[0]},{existing[1]})-({existing[2]},{existing[3]})")

    img_disp = resize_for_display(img, DISPLAY_WIDTH)
    scale = img.shape[1] / img_disp.shape[1]

    cv2.namedWindow("ROI Selector - Thermal Image")
    cv2.setMouseCallback("ROI Selector - Thermal Image", mouse_callback)

    while True:
        disp = img_disp.copy()

        # 기존 ROI 또는 현재 드래그 중인 ROI 표시
        box = get_roi_box()
        if box:
            x1, y1, x2, y2 = box
            dx1 = int(x1 / scale)
            dy1 = int(y1 / scale)
            dx2 = int(x2 / scale)
            dy2 = int(y2 / scale)
            cv2.rectangle(disp, (dx1, dy1), (dx2, dy2), (0, 255, 0), 2)

            # 크기 표시
            w = x2 - x1
            h = y2 - y1
            cv2.putText(disp, f"{w}x{h} ({x1},{y1})-({x2},{y2})",
                        (dx1, dy1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # 안내 텍스트
        cv2.putText(disp, "Drag: set ROI | S: save | R: reset | Q: quit",
                    (10, disp.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        cv2.imshow("ROI Selector - Thermal Image", disp)
        key = cv2.waitKey(1)

        if key == ord("q") or key == 27:  # Q or ESC
            print("Quit without saving.")
            break
        elif key == ord("r"):  # Reset
            global roi_start, roi_end, dragging
            roi_start = None
            roi_end = None
            final_roi = None
            dragging = False
            print("ROI reset.")
        elif key == ord("s"):  # Save
            box = get_roi_box()
            if box:
                save_roi(box)
                break
            else:
                print("No ROI selected. Drag to select an area first.")

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
