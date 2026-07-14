"""
overlay.py - 과열 부위 시각화 (Thermal / RGB Overlay)

Thermal 이미지 또는 RGB 이미지 위에 ROI 박스 + 온도 정보를 표시합니다.
thermal_to_rgb.npy (Homography)가 있으면 RGB 이미지에 오버레이하고,
없으면 Thermal 이미지에 직접 그립니다.

출력 이미지는 thermal_dataset/overlay/ 디렉토리에 timestamp_overlay.jpg 로 저장됩니다.
"""

import os
from dataclasses import dataclass

import cv2
import numpy as np

DATASET_DIR = "thermal_dataset"
HOMOGRAPHY_PATH = "thermal_to_rgb.npy"
OVERLAY_DIR = os.path.join(DATASET_DIR, "overlay")

# 시각화 스타일
ROI_COLOR_NORMAL = (0, 255, 0)    # 초록
ROI_COLOR_WARNING = (0, 200, 255) # 주황
ROI_COLOR_CRITICAL = (0, 0, 255)  # 빨강
TEXT_COLOR = (255, 255, 255)
TEXT_BG = (0, 0, 0)
LINE_THICKNESS = 2
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _status_color(status: str) -> tuple:
    if status == "Critical":
        return ROI_COLOR_CRITICAL
    elif status == "Warning":
        return ROI_COLOR_WARNING
    return ROI_COLOR_NORMAL


def _load_homography() -> np.ndarray | None:
    """Homography 행렬 로드, 없으면 None"""
    if os.path.isfile(HOMOGRAPHY_PATH):
        return np.load(HOMOGRAPHY_PATH)
    return None


# ------------------------------------------------------------
# 표시 이미지 선택 및 ROI 좌표 변환
# ------------------------------------------------------------
def _prepare_canvas(
    thermal_jpg_path: str,
    visual_jpg_path: str,
    roi_bounds: tuple,
    homography: np.ndarray | None = None,
) -> tuple[np.ndarray, tuple, float, float]:
    """
    오버레이 대상 이미지와 ROI 박스 좌표를 준비.

    homography가 있으면 visual 이미지에 thermal ROI를 투영.
    없으면 thermal 이미지에 직접 그림.

    Returns:
        (canvas, (x1, y1, x2, y2), scale_x, scale_y)

        scale은 원본 좌표 -> 표시용 좌표 변환 비율 (thermal 이미지는 640x480 그대로 사용)
    """
    tx1, ty1, tx2, ty2 = roi_bounds

    if homography is not None and os.path.isfile(visual_jpg_path):
        canvas = cv2.imread(visual_jpg_path)
        if canvas is None:
            print(f"[overlay] WARNING: cannot read {visual_jpg_path}, falling back to thermal")
            homography = None

    if homography is None or canvas is None:
        canvas = cv2.imread(thermal_jpg_path)
        if canvas is None:
            raise FileNotFoundError(f"Cannot read thermal image: {thermal_jpg_path}")
        thermal_h, thermal_w = canvas.shape[:2]
        return canvas, roi_bounds, thermal_w / 640, thermal_h / 480

    # Homography 적용: thermal 좌표 -> visual 좌표
    vis_h, vis_w = canvas.shape[:2]

    corners_thermal = np.array([
        [tx1, ty1],
        [tx2, ty1],
        [tx2, ty2],
        [tx1, ty2],
    ], dtype=np.float32).reshape(-1, 1, 2)

    projected = cv2.perspectiveTransform(corners_thermal, homography)
    pts = projected.reshape(4, 2)

    vx1 = int(pts[:, 0].min())
    vy1 = int(pts[:, 1].min())
    vx2 = int(pts[:, 0].max())
    vy2 = int(pts[:, 1].max())

    # 클리핑
    vx1 = max(0, vx1)
    vy1 = max(0, vy1)
    vx2 = min(vis_w, vx2)
    vy2 = min(vis_h, vy2)

    return canvas, (vx1, vy1, vx2, vy2), 1.0, 1.0


# ------------------------------------------------------------
# 오버레이 그리기
# ------------------------------------------------------------
def draw_overlay(
    canvas: np.ndarray,
    roi_bounds: tuple,
    max_temp: float,
    mean_temp: float,
    hot_temp: float,
    status: str,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> np.ndarray:
    """
    이미지 위에 ROI 박스 + 온도 정보 + 상태 표시를 그립니다.
    원본을 변경하지 않고 복사본을 반환합니다.
    """
    img = canvas.copy()
    h, w = img.shape[:2]
    color = _status_color(status)

    x1, y1, x2, y2 = roi_bounds
    x1_s = int(x1 * scale_x)
    y1_s = int(y1 * scale_y)
    x2_s = int(x2 * scale_x)
    y2_s = int(y2 * scale_y)

    # ROI 박스
    cv2.rectangle(img, (x1_s, y1_s), (x2_s, y2_s), color, LINE_THICKNESS)

    # 온도 텍스트
    lines = [
        f"Status : {status}",
        f"Max    : {max_temp:.1f}C",
        f"Mean   : {mean_temp:.1f}C",
        f"95th   : {hot_temp:.1f}C",
    ]

    font_scale = 0.6
    thickness = 1
    line_height = 22
    margin = 10

    # 텍스트 박스 위치 (ROI 위쪽, 공간 부족하면 그림 아래)
    text_x = x1_s
    text_y = y1_s - (len(lines) * line_height + margin)
    if text_y < margin:
        text_x = 10
        text_y = 30

    # 배경 박스
    max_text_w = 0
    for line in lines:
        (tw, th), _ = cv2.getTextSize(line, FONT, font_scale, thickness)
        max_text_w = max(max_text_w, tw)

    cv2.rectangle(
        img,
        (text_x - 4, text_y - th - margin),
        (text_x + max_text_w + 4, text_y + (len(lines) - 1) * line_height + 4),
        TEXT_BG,
        -1,
    )

    # 텍스트 그리기
    for i, line in enumerate(lines):
        cv2.putText(
            img, line,
            (text_x, text_y + i * line_height),
            FONT, font_scale, color if i == 0 else TEXT_COLOR, thickness,
        )

    return img


# ------------------------------------------------------------
# 메인 오버레이 함수
# ------------------------------------------------------------
def create_overlay(
    thermal_jpg_path: str,
    visual_jpg_path: str,
    roi_bounds: tuple,
    max_temp: float,
    mean_temp: float,
    hot_temp: float,
    status: str,
    homography: np.ndarray | None = None,
) -> np.ndarray:
    """
    오버레이 이미지 생성.

    Args:
        thermal_jpg_path: Thermal JPEG 경로
        visual_jpg_path: 가시광 JPEG 경로 (_visual.jpg)
        roi_bounds: Thermal 이미지 기준 ROI (x1, y1, x2, y2)
        max_temp, mean_temp, hot_temp: 온도 통계
        status: "Normal" / "Warning" / "Critical"
        homography: Homography 행렬 (None이면 자동 로드)

    Returns:
        오버레이가 적용된 BGR 이미지 배열
    """
    if homography is None:
        homography = _load_homography()

    canvas, canvas_roi, sx, sy = _prepare_canvas(
        thermal_jpg_path, visual_jpg_path, roi_bounds, homography
    )

    return draw_overlay(canvas, canvas_roi, max_temp, mean_temp, hot_temp, status, sx, sy)


def save_overlay(
    base_filename: str,
    overlay_img: np.ndarray,
    overlay_dir: str = OVERLAY_DIR,
) -> str:
    """오버레이 이미지를 overlay/ 디렉토리에 저장하고 경로를 반환"""
    os.makedirs(overlay_dir, exist_ok=True)
    out_path = os.path.join(overlay_dir, f"{base_filename}_overlay.jpg")
    cv2.imwrite(out_path, overlay_img)
    print(f"[overlay] saved: {out_path}")
    return out_path


# ------------------------------------------------------------
# 디스플레이 유틸
# ------------------------------------------------------------
def show_overlay(overlay_img: np.ndarray, window_name: str = "Overlay"):
    """오버레이 이미지를 창에 표시 (아무 키나 누르면 닫힘)"""
    max_w = 1200
    h, w = overlay_img.shape[:2]
    if w > max_w:
        scale = max_w / w
        overlay_img = cv2.resize(overlay_img, (max_w, int(h * scale)))

    cv2.imshow(window_name, overlay_img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


# ------------------------------------------------------------
# 테스트
# ------------------------------------------------------------
if __name__ == "__main__":
    from _encoding import setup_encoding
    setup_encoding()

    print("=== Overlay Test ===\n")

    # 최신 이미지 쌍 찾기
    if not os.path.isdir(DATASET_DIR):
        print(f"'{DATASET_DIR}' not found")
        sys.exit(1)

    files = os.listdir(DATASET_DIR)
    thermal_jpgs = sorted([f for f in files if f.endswith(".jpg") and "_visual" not in f])

    if not thermal_jpgs:
        print("No thermal images found")
        sys.exit(1)

    test_jpg = thermal_jpgs[-1]
    base = test_jpg.replace(".jpg", "")
    thermal_path = os.path.join(DATASET_DIR, test_jpg)
    visual_path = os.path.join(DATASET_DIR, f"{base}_visual.jpg")

    print(f"Thermal: {thermal_path}")
    print(f"Visual : {visual_path} (exists: {os.path.isfile(visual_path)})")

    H = _load_homography()
    print(f"Homography: {'found' if H is not None else 'not found (using thermal image)'}")

    # ROI 값 (roi.py에서 가져오거나 직접 지정)
    # 테스트용: Thermal 이미지 기준 중앙 영역
    test_roi = (140, 80, 330, 280)

    overlay = create_overlay(
        thermal_jpg_path=thermal_path,
        visual_jpg_path=visual_path,
        roi_bounds=test_roi,
        max_temp=55.3,
        mean_temp=42.1,
        hot_temp=50.2,
        status="Warning",
        homography=H,
    )

    save_overlay(base, overlay)
    print("Overlay image saved. Run with GUI to preview: cv2.imshow")
    # show_overlay(overlay)  # GUI 필요
