"""
test.py - Threshold 판단 및 상태 머신 테스트

※ 현재는 실제 온도 데이터가 없으므로 임의값을 기반으로 동작합니다.
   추후 capture.py에서 수집한 .npy 데이터와 연동 예정입니다.
"""

import io
import sys
import time
from enum import Enum
from dataclasses import dataclass, field
from collections import deque

# Windows cp949 인코딩 문제 방지
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# ============================================================
# 임시 설정값 (실제 운영 시 experiment_config.json 등에서 로드)
# ============================================================
BASELINE_TEMP = 35.0        # 기준 온도 (C)
WARNING_DELTA = 15.0        # baseline + 15C → Warning
CRITICAL_DELTA = 25.0       # baseline + 25C → Critical
ALARM_COOLDOWN = 10 * 60    # 알림 쿨다운 10분 (초 단위)
ROBOT_ID = "Robot-01"

# ------------------------------------------------------------
# 임시 온도 시나리오 (실제 데이터로 교체 예정)
# ------------------------------------------------------------
# 실제 운영 시: thermal_dataset/*.npy 파일에서 np.load() 하거나
# capture.py에서 실시간 수집한 온도 행렬의 ROI 통계값을 사용합니다.
SIMULATED_READINGS = [
    # (시점, hot_temp_95th_percentile, max_temp, mean_temp)
    ("13:00", 36.0, 37.2, 34.5),   # 정상
    ("13:10", 36.5, 38.1, 34.8),   # 정상
    ("13:20", 50.2, 55.3, 42.1),   # 과열 경계 (baseline+15=50 → 50.2 > 50 → Warning)
    ("13:30", 52.1, 57.8, 43.5),   # 과열 지속
    ("13:40", 53.0, 58.2, 44.0),   # 과열 지속 (쿨다운 중이므로 알림 없음)
    ("13:50", 60.5, 66.1, 48.3),   # 경보 (baseline+25=60 → 60.5 > 60 → Critical)
    ("14:00", 61.2, 67.5, 49.1),   # 경보 지속 (쿨다운 중)
    ("14:10", 38.0, 40.1, 35.2),   # 정상 복귀 (Critical → Normal 알림)
]


# ============================================================
# 상태 머신
# ============================================================
class Status(Enum):
    NORMAL = "Normal"
    WARNING = "Warning"
    CRITICAL = "Critical"


@dataclass
class MonitorState:
    status: Status = Status.NORMAL
    last_alarm_time: float = 0.0
    history: deque = field(default_factory=lambda: deque(maxlen=100))


# ============================================================
# Threshold 판단
# ============================================================
def evaluate_threshold(hot_temp: float) -> Status:
    """95th percentile 온도 기준 상태 판정"""
    if hot_temp >= BASELINE_TEMP + CRITICAL_DELTA:
        return Status.CRITICAL
    elif hot_temp >= BASELINE_TEMP + WARNING_DELTA:
        return Status.WARNING
    else:
        return Status.NORMAL


# ============================================================
# 알림 판단 (상태 변화 + 쿨다운)
# ============================================================
def should_alarm(new_status: Status, state: MonitorState) -> bool:
    """
    알림 전송 여부 판단:
    1. 상태가 변경되었을 때만 전송
    2. 이전 알림 후 ALARM_COOLDOWN 이내면 전송하지 않음
    """
    if new_status == state.status:
        return False

    now = time.time()
    if state.last_alarm_time > 0 and (now - state.last_alarm_time) < ALARM_COOLDOWN:
        return False

    return True


# ============================================================
# 알림 전송 (notifier 모듈 사용)
# ============================================================
from notifier import send_alarm as send_alarm_notifier, send_text, build_text_message


# ============================================================
# 이력 기록
# ============================================================
def log_reading(timestamp: str, hot_temp: float, max_temp: float,
                mean_temp: float, status: Status, history: deque):
    """온도 이력을 deque에 저장 (추후 CSV/DB 연동)"""
    history.append({
        "timestamp": timestamp,
        "hot_temp": hot_temp,
        "max_temp": max_temp,
        "mean_temp": mean_temp,
        "status": status.value,
    })


def print_history(history: deque):
    """이력 출력"""
    print("\n[Temperature History]")
    print(f"{'Time':<8} {'95th(C)':<10} {'max(C)':<10} {'mean(C)':<10} {'Status':<10}")
    print("-" * 50)
    for r in history:
        print(f"{r['timestamp']:<8} {r['hot_temp']:<10.1f} "
              f"{r['max_temp']:<10.1f} {r['mean_temp']:<10.1f} {r['status']:<10}")


# ============================================================
# 메인 시뮬레이션 루프
# ============================================================
def main():
    print("=" * 50)
    print("  Robot Thermal Monitoring - Threshold Test")
    print("  * Simulated data (not real sensor data)")
    print("=" * 50)
    print(f"  Baseline temp       : {BASELINE_TEMP}C")
    print(f"  Warning threshold   : {BASELINE_TEMP + WARNING_DELTA}C")
    print(f"  Critical threshold  : {BASELINE_TEMP + CRITICAL_DELTA}C")
    print(f"  Alarm cooldown      : {ALARM_COOLDOWN // 60} min")
    print("=" * 50)

    state = MonitorState()
    alarm_count = 0

    for timestamp, hot_temp, max_temp, mean_temp in SIMULATED_READINGS:
        # 1. Threshold 판단
        new_status = evaluate_threshold(hot_temp)

        # 2. 상태 변화 + 쿨다운 기반 알림 판단
        do_alarm = should_alarm(new_status, state)

        # 3. 상태 업데이트
        prev_status = state.status
        state.status = new_status

        # 4. 이력 기록
        log_reading(timestamp, hot_temp, max_temp, mean_temp, state.status, state.history)

        # 5. 출력
        transition = ""
        if do_alarm:
            transition = f"  <<< STATE CHANGE! ({prev_status.value} -> {new_status.value})"
            alarm_count += 1

        print(f"[{timestamp}] hot={hot_temp:.1f}C max={max_temp:.1f}C "
              f"mean={mean_temp:.1f}C -> {new_status.value}{transition}")

        # 6. 알림 발송 (상태 변화 시)
        if do_alarm:
            send_alarm_notifier(
                image_path="thermal_dataset/dummy_overlay.jpg",
                temp=hot_temp,
                status=new_status.value,
                robot_id=ROBOT_ID,
            )
            state.last_alarm_time = time.time()

        # 시뮬레이션 간격 (실제는 10초 주기)
        time.sleep(0.5)

    # 최종 이력 출력
    print_history(state.history)
    print(f"\nTotal alarms sent: {alarm_count}")


if __name__ == "__main__":
    main()
