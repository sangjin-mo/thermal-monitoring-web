"""
roi.py - ROI 설정 및 온도 통계 추출

roi_config.json에서 ROI 좌표를 불러와 .npy 온도 행렬에서
해당 영역의 온도 통계값을 계산합니다.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

# 프로젝트 루트 기준 경로
ROI_CONFIG_PATH = "roi_config.json"
DATASET_DIR = "thermal_dataset"

# Thermal 이미지 vs .npy 해상도 차이 보정
DISPLAY_W = 640
DISPLAY_H = 480


@dataclass
class RoiResult:
    roi_thermal: np.ndarray
    max_temp: float
    mean_temp: float
    hot_temp_95: float
    roi_bounds: tuple  # (x1, y1, x2, y2) - thermal image 기준
    over_temp_pixels: int = 0       # 기준 온도 초과 픽셀 수
    max_hotspot_size: int = 0       # 가장 큰 초과 클러스터 크기 (connected component)
    hotspot_centroids: list = field(default_factory=list)  # [(x, y, temp), ...] in 640x480 좌표계


@dataclass
class RoiConfig:
    x1: int = 0
    y1: int = 0
    x2: int = 640
    y2: int = 480
    baseline_temp: float = 35.0
    warning_delta: float = 15.0
    critical_delta: float = 25.0


def load_roi_config(config_path: str = ROI_CONFIG_PATH) -> RoiConfig:
    """roi_config.json 에서 ROI 설정 불러오기"""
    if not os.path.isfile(config_path):
        print(f"[roi] {config_path} not found, using default (full frame)")
        return RoiConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    roi = cfg.get("thermal_roi", {})
    return RoiConfig(
        x1=int(roi.get("x1", 0)),
        y1=int(roi.get("y1", 0)),
        x2=int(roi.get("x2", 640)),
        y2=int(roi.get("y2", 480)),
        baseline_temp=float(cfg.get("baseline_temp", 35.0)),
        warning_delta=float(cfg.get("warning_delta", 15.0)),
        critical_delta=float(cfg.get("critical_delta", 25.0)),
    )


def _scale_roi_to_npy(
    roi: RoiConfig, npy_shape: tuple
) -> tuple:
    """
    Thermal 이미지 좌표(640x480)를 .npy 행렬 좌표로 변환.
    .npy shape = (H, W) 이므로 (height, width) 순서에 주의.
    """
    npy_h, npy_w = npy_shape
    scale_x = npy_w / DISPLAY_W
    scale_y = npy_h / DISPLAY_H

    nx1 = int(roi.x1 * scale_x)
    ny1 = int(roi.y1 * scale_y)
    nx2 = int(roi.x2 * scale_x)
    ny2 = int(roi.y2 * scale_y)

    nx1 = max(0, min(nx1, npy_w))
    ny1 = max(0, min(ny1, npy_h))
    nx2 = max(0, min(nx2, npy_w))
    ny2 = max(0, min(ny2, npy_h))

    return ny1, ny2, nx1, nx2  # numpy 슬라이싱 순서: y1:y2, x1:x2


def extract_roi_from_npy(npy_path: str, config: Optional[RoiConfig] = None) -> RoiResult:
    """
    .npy 파일에서 ROI 영역 온도 통계 추출.

    Args:
        npy_path: .npy 파일 경로
        config: ROI 설정 (None이면 roi_config.json 자동 로드)

    Returns:
        RoiResult (roi_thermal, max_temp, mean_temp, hot_temp_95, roi_bounds)
    """
    if config is None:
        config = load_roi_config()

    thermal = np.load(npy_path).astype(np.float64)

    if thermal.ndim != 2:
        raise ValueError(f"Expected 2D thermal array, got shape {thermal.shape}")

    y1, y2, x1, x2 = _scale_roi_to_npy(config, thermal.shape)

    # 유효성 검사 - ROI가 너무 작으면 전체 프레임 사용
    if y2 <= y1 or x2 <= x1:
        print(f"[roi] WARNING: ROI too small ({config.x1},{config.y1})-({config.x2},{config.y2}), using full frame")
        roi = thermal
    else:
        roi = thermal[y1:y2, x1:x2]

    # NaN 제거
    valid = roi[~np.isnan(roi)]
    if len(valid) == 0:
        return RoiResult(
            roi_thermal=roi,
            max_temp=0.0,
            mean_temp=0.0,
            hot_temp_95=0.0,
            roi_bounds=(config.x1, config.y1, config.x2, config.y2),
        )

    # 국소 발열 클러스터 분석
    # baseline + warning_delta 기준 초과 픽셀 수 + 가장 큰 연결 클러스터 크기
    over_threshold = config.baseline_temp + config.warning_delta
    hotspot_mask = roi > over_threshold
    over_pixels = int(np.sum(hotspot_mask))

    MIN_HOTSPOT = 3  # 노이즈 필터링: 3픽셀 이상만 실제 발열로 인정
    max_cluster = 0
    centroids = []

    if over_pixels > 0:
        hotspot_uint8 = hotspot_mask.astype(np.uint8)
        _, labels, stats, centroids_raw = cv2.connectedComponentsWithStats(
            hotspot_uint8, connectivity=8
        )
        # stats[0]은 배경(label 0) 전체 영역이므로 제외
        if len(stats) > 1:
            max_cluster = int(stats[1:, cv2.CC_STAT_AREA].max())

        # ROI 내부 좌표 -> thermal 이미지(640x480) 좌표로 변환
        scale_back_x = DISPLAY_W / thermal.shape[1]
        scale_back_y = DISPLAY_H / thermal.shape[0]

        for label_id in range(1, len(stats)):
            area = int(stats[label_id, cv2.CC_STAT_AREA])
            if area < MIN_HOTSPOT:
                continue
            cx, cy = centroids_raw[label_id]
            # ROI 오프셋 적용 후 thermal 이미지 좌표계로 변환
            if roi is not thermal:
                cx += x1
                cy += y1
            tx = round(cx * scale_back_x)
            ty = round(cy * scale_back_y)
            cluster_mask = (labels == label_id) & hotspot_mask
            cluster_max = float(np.nanmax(roi[hotspot_mask & (labels == label_id)]))
            centroids.append((tx, ty, cluster_max))

    return RoiResult(
        roi_thermal=roi,
        max_temp=float(np.nanmax(valid)),
        mean_temp=float(np.nanmean(valid)),
        hot_temp_95=float(np.nanpercentile(valid, 95)),
        roi_bounds=(config.x1, config.y1, config.x2, config.y2),
        over_temp_pixels=over_pixels,
        max_hotspot_size=max_cluster,
        hotspot_centroids=centroids,
    )


# ------------------------------------------------------------
# 테스트
# ------------------------------------------------------------
if __name__ == "__main__":
    from _encoding import setup_encoding
    setup_encoding()

    print("=== ROI Test ===\n")
    config = load_roi_config()
    print(f"ROI bounds: ({config.x1}, {config.y1}) - ({config.x2}, {config.y2})")
    print(f"Baseline: {config.baseline_temp}C")
    print(f"Warning delta: {config.warning_delta}C")
    print(f"Critical delta: {config.critical_delta}C")

    # 최신 .npy 파일 찾기
    if os.path.isdir(DATASET_DIR):
        npy_files = sorted(
            [f for f in os.listdir(DATASET_DIR) if f.endswith("_thermal.npy")]
        )
        if npy_files:
            npy_path = os.path.join(DATASET_DIR, npy_files[-1])
            print(f"\nTesting with: {npy_path}")
            result = extract_roi_from_npy(npy_path, config)
            print(f"  Max temp: {result.max_temp:.1f}C")
            print(f"  Mean temp: {result.mean_temp:.1f}C")
            print(f"  95th percentile: {result.hot_temp_95:.1f}C")
            print(f"  ROI shape: {result.roi_thermal.shape}")
            print(f"  Over-threshold pixels: {result.over_temp_pixels}")
            print(f"  Max hotspot cluster size: {result.max_hotspot_size}")
        else:
            print("\nNo .npy files found in thermal_dataset/")
    else:
        print(f"\n'{DATASET_DIR}' directory not found")
