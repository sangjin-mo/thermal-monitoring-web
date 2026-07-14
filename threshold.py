"""
threshold.py - Threshold 판단 및 상태 머신

ROI 온도 통계값을 받아 Normal / Warning / Critical 상태를 판정하고
상태 변화 시 알림 여부를 결정합니다.

판정 기준:
  1. 95th percentile 온도가 baseline + delta 초과
  2. 동시에 국소 과열 영역이 3픽셀 이상의 클러스터로 존재해야 함
     (1~2픽셀 크기는 센서 노이즈로 간주)
"""

import time
from dataclasses import dataclass, field
from enum import Enum

MIN_HOTSPOT_SIZE = 3  # 국소 과열로 인정하는 최소 픽셀 클러스터 크기


class Status(Enum):
    NORMAL = "Normal"
    WARNING = "Warning"
    CRITICAL = "Critical"


@dataclass
class MonitorState:
    status: Status = Status.NORMAL
    last_alarm_time: float = 0.0
    alarm_cooldown: float = 10 * 60  # 10분


def evaluate_threshold(
    hot_temp: float,
    baseline: float = 35.0,
    warning_delta: float = 15.0,
    critical_delta: float = 25.0,
    over_temp_pixels: int = 0,
    max_hotspot_size: int = 0,
) -> Status:
    """
    온도 통계 + 클러스터 크기 기반 상태 판정.

    1~2픽셀 크기의 과열은 노이즈로 간주하고,
    3픽셀 이상의 연결된 과열 클러스터가 있을 때만 실제 발열로 판단합니다.
    """
    hotspot_real = max_hotspot_size >= MIN_HOTSPOT_SIZE

    if hot_temp >= baseline + critical_delta and hotspot_real:
        return Status.CRITICAL
    elif hot_temp >= baseline + warning_delta and hotspot_real:
        return Status.WARNING
    else:
        return Status.NORMAL


def should_alarm(new_status: Status, state: MonitorState) -> bool:
    """
    알림 전송 여부 판단:
    1. 상태가 변경되었을 때만 전송
    2. 이전 알림 후 alarm_cooldown 이내면 전송하지 않음
    """
    if new_status == state.status:
        return False

    now = time.time()
    if state.last_alarm_time > 0 and (now - state.last_alarm_time) < state.alarm_cooldown:
        return False

    return True


def evaluate_with_state(
    hot_temp: float,
    max_temp: float,
    mean_temp: float,
    baseline: float,
    warning_delta: float,
    critical_delta: float,
    state: MonitorState,
    over_temp_pixels: int = 0,
    max_hotspot_size: int = 0,
) -> tuple[Status, bool]:
    """
    ROI 결과를 받아 상태 판정 + 알림 여부를 한 번에 반환.
    (pipeline에서 호출할 편의 함수)

    Returns:
        (new_status, do_alarm)
    """
    new_status = evaluate_threshold(
        hot_temp, baseline, warning_delta, critical_delta,
        over_temp_pixels, max_hotspot_size,
    )
    do_alarm = should_alarm(new_status, state)
    return new_status, do_alarm
