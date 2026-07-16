"""
tools.py - 통합 모니터링 대시보드 GUI

환경 설정, 실시간 감지 화면, 로그 테이블을 하나의 GUI에서 제공합니다.
캡처 시작부터 분석, 알림까지 통합 수행합니다.

사용법:
    python tools.py
"""

import os
import sys
import glob
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog
from datetime import datetime
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageTk
import requests

from ..config import load_config, save_config
from ..capture.capture import CaptureSession
from ..analysis.roi import load_roi_config, extract_roi_from_npy, RoiResult
from ..analysis.threshold import (
    Status, MonitorState, evaluate_with_state,
)
from ..analysis.overlay import create_overlay, _load_homography
from ..analysis.notifier import send_alarm

DATASET_DIR = load_config().paths.dataset_dir
HOMOGRAPHY_PATH = load_config().paths.homography_path


class MonitoringDashboard:
    """통합 모니터링 대시보드 — 3섹션 레이아웃"""

    MAX_LOG_ROWS = 500
    DISPLAY_IMAGE_WIDTH = 560

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Robot Thermal Monitoring Dashboard")
        self.root.geometry("1060x820")
        self.root.minsize(900, 650)
        self.root.resizable(True, True)

        self._config = load_config()
        self._monitor_state = MonitorState()
        self._capture_session: Optional[CaptureSession] = None
        self._running = False
        self._tick_count = 0
        self._scan_timer_id: Optional[str] = None

        self._current_view = "thermal"
        self._current_overlay: Optional[np.ndarray] = None
        self._current_visual_overlay: Optional[np.ndarray] = None
        self._current_status: str = "Normal"
        self._current_roi_result: Optional[RoiResult] = None
        self._current_thermal_jpg: Optional[str] = None
        self._current_visual_jpg: Optional[str] = None

        self._processed_bases: set = set()
        self._camera_connected = False
        self._roi_running = False
        self._calib_running = False
        self._photo_ref: Optional[ImageTk.PhotoImage] = None

        self._build_ui()
        self._check_camera_connection()
        self._prime_processed_cache()

    # ════════════════════════════════════════════════════════════
    # UI 구성
    # ════════════════════════════════════════════════════════════
    def _build_ui(self):
        # ── Section 1: 환경 설정 ──────────────────────────────
        self._build_env_section()

        # ── Section 2: 감지 화면 (좌: 이미지, 우: 제어) ──────
        det_frame = ttk.LabelFrame(self.root, text="감지 화면", padding=10)
        det_frame.pack(fill="both", expand=True, padx=10, pady=(0, 5))

        det_paned = ttk.PanedWindow(det_frame, orient="horizontal")
        det_paned.pack(fill="both", expand=True)

        # Left panel: image
        img_frame = ttk.Frame(det_paned, width=580)
        det_paned.add(img_frame, weight=1)

        self._image_label = ttk.Label(img_frame, anchor="center", background="#1a1a1a")
        self._image_label.pack(fill="both", expand=True)

        # Right panel: controls
        ctrl_frame = ttk.Frame(det_paned, width=220)
        det_paned.add(ctrl_frame, weight=0)

        # View toggle
        view_frame = ttk.LabelFrame(ctrl_frame, text="View Mode", padding=8)
        view_frame.pack(fill="x", padx=5, pady=(5, 10))

        self._view_var = tk.StringVar(value="thermal")
        ttk.Radiobutton(view_frame, text="Thermal", variable=self._view_var,
                        value="thermal", command=self._on_view_changed).pack(anchor="w")
        ttk.Radiobutton(view_frame, text="Visual", variable=self._view_var,
                        value="visual", command=self._on_view_changed).pack(anchor="w")

        # Detection info
        info_frame = ttk.LabelFrame(ctrl_frame, text="Detection Info", padding=8)
        info_frame.pack(fill="x", padx=5, pady=(0, 10))

        self._status_label = ttk.Label(info_frame, text="Status: Normal",
                                       font=("", 11, "bold"))
        self._status_label.pack(anchor="w", pady=(0, 4))

        self._max_temp_label = ttk.Label(info_frame, text="Max: -- °C", font=("", 10))
        self._max_temp_label.pack(anchor="w")

        self._mean_temp_label = ttk.Label(info_frame, text="Mean: -- °C", font=("", 10))
        self._mean_temp_label.pack(anchor="w")

        self._hot_temp_label = ttk.Label(info_frame, text="95th: -- °C", font=("", 10))
        self._hot_temp_label.pack(anchor="w")

        self._hotspot_label = ttk.Label(info_frame, text="Hotspots: 0", font=("", 10))
        self._hotspot_label.pack(anchor="w")

        # Tool buttons
        tool_frame = ttk.LabelFrame(ctrl_frame, text="Tools", padding=8)
        tool_frame.pack(fill="x", padx=5)

        self._roi_btn = ttk.Button(tool_frame, text="Set ROI",
                                   command=self._launch_roi_selector)
        self._roi_btn.pack(fill="x", pady=(0, 6))

        self._calib_btn = ttk.Button(tool_frame, text="Calibrate",
                                     command=self._launch_calibration)
        self._calib_btn.pack(fill="x")

        # ── Section 3: 로그 화면 ──────────────────────────────
        self._build_log_section()

    def _build_env_section(self):
        env_frame = ttk.LabelFrame(self.root, text="환경 설정", padding=10)
        env_frame.pack(fill="x", padx=10, pady=(10, 5))

        # Row 0: Camera IP + connection status
        ttk.Label(env_frame, text="Camera IP:").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self._cam_ip_var = tk.StringVar(value=self._config.camera.ip)
        cam_ip_entry = ttk.Entry(env_frame, textvariable=self._cam_ip_var, width=18)
        cam_ip_entry.grid(row=0, column=1, sticky="w")

        self._cam_status_label = ttk.Label(env_frame, text="○ Disconnected",
                                           foreground="#888888")
        self._cam_status_label.grid(row=0, column=2, sticky="w", padx=(10, 0))

        # Row 1: Dataset dir + Browse
        ttk.Label(env_frame, text="Dataset:").grid(row=1, column=0, sticky="w",
                                                    padx=(0, 5), pady=(6, 0))
        self._dir_var = tk.StringVar(value=self._config.paths.dataset_dir)
        dir_entry = ttk.Entry(env_frame, textvariable=self._dir_var, width=40, state="readonly")
        dir_entry.grid(row=1, column=1, sticky="w", pady=(6, 0))

        browse_btn = ttk.Button(env_frame, text="Browse...", command=self._change_dataset_dir)
        browse_btn.grid(row=1, column=2, sticky="w", padx=(10, 0), pady=(6, 0))

        # Row 2: Interval + Start/Stop
        ttk.Label(env_frame, text="Interval (s):").grid(row=2, column=0, sticky="w",
                                                         padx=(0, 5), pady=(6, 0))
        self._interval_var = tk.StringVar(value=str(self._config.camera.capture_interval_sec))
        interval_entry = ttk.Entry(env_frame, textvariable=self._interval_var, width=6)
        interval_entry.grid(row=2, column=1, sticky="w", pady=(6, 0))

        self._monitor_btn = ttk.Button(env_frame, text="Start Monitoring",
                                       command=self._toggle_monitoring)
        self._monitor_btn.grid(row=2, column=2, sticky="w", padx=(10, 0), pady=(6, 0))

        # Row 3: Status bar
        self._status_bar_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self._status_bar_var,
                               relief="sunken", anchor="w", padding=3)
        status_bar.pack(fill="x", padx=10, pady=(0, 5))

    def _build_log_section(self):
        log_frame = ttk.LabelFrame(self.root, text="로그 화면", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        columns = ("time", "location", "temperature", "alert", "notified")
        self._log_tree = ttk.Treeview(log_frame, columns=columns, show="headings", height=12)

        self._log_tree.heading("time", text="Detection Time")
        self._log_tree.heading("location", text="Location")
        self._log_tree.heading("temperature", text="Temperature")
        self._log_tree.heading("alert", text="Alert Level")
        self._log_tree.heading("notified", text="Notified")

        self._log_tree.column("time", width=140, minwidth=100)
        self._log_tree.column("location", width=130, minwidth=80)
        self._log_tree.column("temperature", width=100, minwidth=80)
        self._log_tree.column("alert", width=100, minwidth=80)
        self._log_tree.column("notified", width=80, minwidth=60)

        self._log_tree.tag_configure("Critical", foreground="#ff0000",
                                     font=("Consolas", 9, "bold"))
        self._log_tree.tag_configure("Warning", foreground="#ff8800")
        self._log_tree.tag_configure("Normal", foreground="#888888")

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical",
                                  command=self._log_tree.yview)
        self._log_tree.configure(yscrollcommand=scrollbar.set)

        self._log_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ════════════════════════════════════════════════════════════
    # 환경 설정 메서드
    # ════════════════════════════════════════════════════════════
    def _check_camera_connection(self):
        ip = self._cam_ip_var.get().strip()
        if not ip:
            self._camera_connected = False
        else:
            try:
                r = requests.get(f"http://{ip}/api/image/current?imgformat=JPEG",
                                 timeout=5)
                self._camera_connected = r.status_code == 200
            except Exception:
                self._camera_connected = False

        if self._camera_connected:
            self._cam_status_label.configure(text="● Connected", foreground="#00aa00")
        else:
            self._cam_status_label.configure(text="○ Disconnected", foreground="#888888")

    def _change_dataset_dir(self):
        new_dir = filedialog.askdirectory(
            initialdir=os.path.abspath(self._config.paths.dataset_dir),
            title="Select Dataset Directory"
        )
        if new_dir:
            self._config.paths.dataset_dir = new_dir
            self._config.paths.overlay_dir = os.path.join(new_dir, "overlay")
            save_config(self._config)
            self._dir_var.set(new_dir)
            self._processed_bases.clear()
            self._prime_processed_cache()
            self._log_to_status(f"Dataset directory changed: {new_dir}")

    def _log_to_status(self, msg: str):
        self.root.after(0, lambda: self._status_bar_var.set(msg))

    # ════════════════════════════════════════════════════════════
    # 모니터링 시작/중지
    # ════════════════════════════════════════════════════════════
    def _toggle_monitoring(self):
        if self._running:
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _start_monitoring(self):
        cam_ip = self._cam_ip_var.get().strip()
        try:
            interval = float(self._interval_var.get())
            if interval <= 0:
                raise ValueError
        except ValueError:
            self._log_to_status("Invalid interval value. Must be > 0.")
            return

        self._config.camera.ip = cam_ip
        self._config.camera.capture_interval_sec = interval
        save_config(self._config)

        self._monitor_state = MonitorState()
        self._processed_bases.clear()
        self._prime_processed_cache()
        self._running = True
        self._tick_count = 0

        self._capture_session = CaptureSession(
            cam_ip=cam_ip,
            mode="both",
            interval=interval,
            save_dir=self._config.paths.dataset_dir,
            log_callback=None,
        )
        self._capture_session.start()

        self._monitor_btn.configure(text="Stop Monitoring")
        self._log_to_status(f"Monitoring started — {cam_ip}, interval={interval}s")
        self._monitoring_tick()

    def _stop_monitoring(self):
        self._running = False
        if self._scan_timer_id:
            self.root.after_cancel(self._scan_timer_id)
            self._scan_timer_id = None
        if self._capture_session:
            self._capture_session.stop()
            self._capture_session = None
        self._monitor_btn.configure(text="Start Monitoring")
        self._log_to_status("Monitoring stopped.")

    # ════════════════════════════════════════════════════════════
    # 모니터링 루프 (root.after)
    # ════════════════════════════════════════════════════════════
    def _monitoring_tick(self):
        if not self._running:
            return
        try:
            if self._tick_count % 10 == 0:
                self._check_camera_connection()

            new_pairs = self._scan_new_pairs()
            for pair in new_pairs:
                self._process_pair(pair)
                self._mark_processed(pair["base"])

            self._refresh_display()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._log_to_status(f"Tick error: {e}")

        self._tick_count += 1
        interval_ms = int(self._config.monitoring.process_interval_sec * 1000)
        self._scan_timer_id = self.root.after(interval_ms, self._monitoring_tick)

    # ════════════════════════════════════════════════════════════
    # 파일 스캔
    # ════════════════════════════════════════════════════════════
    def _scan_all_paired_bases(self) -> set:
        dataset_dir = self._config.paths.dataset_dir
        if not os.path.isdir(dataset_dir):
            return set()
        try:
            files = os.listdir(dataset_dir)
        except OSError:
            return set()
        thermal_jpgs = {f.replace(".jpg", ""): f for f in files
                        if f.endswith(".jpg") and "_visual" not in f}
        visual_jpgs = {f.replace("_visual.jpg", ""): f for f in files
                       if f.endswith("_visual.jpg")}
        return set(thermal_jpgs.keys()) & set(visual_jpgs.keys())

    def _prime_processed_cache(self):
        existing = self._scan_all_paired_bases()
        self._processed_bases = existing

    def _scan_new_pairs(self) -> list[dict]:
        dataset_dir = self._config.paths.dataset_dir
        if not os.path.isdir(dataset_dir):
            return []
        try:
            files = os.listdir(dataset_dir)
        except OSError:
            return []

        thermal_jpgs = {f.replace(".jpg", ""): f for f in files
                        if f.endswith(".jpg") and "_visual" not in f}
        npys = {f.replace("_thermal.npy", ""): f for f in files
                if f.endswith("_thermal.npy")}
        visual_jpgs = {f.replace("_visual.jpg", ""): f for f in files
                       if f.endswith("_visual.jpg")}

        bases = sorted(set(thermal_jpgs.keys()) & set(visual_jpgs.keys()))
        new_pairs = []
        for base in bases:
            if base in self._processed_bases:
                continue
            npy_path = os.path.join(dataset_dir, base + "_thermal.npy")
            if base not in npys:
                try:
                    from ..capture.thermal_utils import extract_from_jpeg
                    jpg_path = os.path.join(dataset_dir, thermal_jpgs[base])
                    thermal, _ = extract_from_jpeg(jpg_path)
                    np.save(npy_path, thermal)
                except Exception:
                    continue
            new_pairs.append({
                "base": base,
                "thermal_jpg": os.path.join(dataset_dir, thermal_jpgs[base]),
                "visual_jpg": os.path.join(dataset_dir, visual_jpgs[base]),
                "npy": npy_path,
            })
        return new_pairs

    def _mark_processed(self, base: str):
        self._processed_bases.add(base)
        max_cache = self._config.monitoring.max_processed_cache
        if len(self._processed_bases) > max_cache:
            retain = max_cache // 2
            self._processed_bases = set(sorted(self._processed_bases)[-retain:])

    # ════════════════════════════════════════════════════════════
    # 쌍 처리
    # ════════════════════════════════════════════════════════════
    def _process_pair(self, pair: dict):
        try:
            roi_config = load_roi_config()
            roi_result = extract_roi_from_npy(pair["npy"], roi_config)

            new_status, do_alarm = evaluate_with_state(
                hot_temp=roi_result.hot_temp_95,
                max_temp=roi_result.max_temp,
                mean_temp=roi_result.mean_temp,
                baseline=roi_config.baseline_temp,
                warning_delta=roi_config.warning_delta,
                critical_delta=roi_config.critical_delta,
                state=self._monitor_state,
                over_temp_pixels=roi_result.over_temp_pixels,
                max_hotspot_size=roi_result.max_hotspot_size,
            )

            self._monitor_state.status = new_status

            # Overlay 이미지 생성
            overlay = create_overlay(
                thermal_jpg_path=pair["thermal_jpg"],
                visual_jpg_path=pair["visual_jpg"],
                roi_bounds=roi_result.roi_bounds,
                max_temp=roi_result.max_temp,
                mean_temp=roi_result.mean_temp,
                hot_temp=roi_result.hot_temp_95,
                status=new_status.value,
                hotspot_centroids=roi_result.hotspot_centroids,
            )

            self._current_overlay = overlay
            self._current_visual_overlay = cv2.imread(pair["visual_jpg"])
            if self._current_visual_overlay is not None:
                self._current_visual_overlay = cv2.resize(
                    self._current_visual_overlay, (overlay.shape[1], overlay.shape[0]))

            self._current_thermal_jpg = pair["thermal_jpg"]
            self._current_visual_jpg = pair["visual_jpg"]
            self._current_roi_result = roi_result
            self._current_status = new_status.value

            # 위치 문자열
            if roi_result.hotspot_centroids:
                cx, cy, _ = roi_result.hotspot_centroids[0]
                loc_str = f"({cx}, {cy})"
            else:
                x1, y1, x2, y2 = roi_result.roi_bounds
                loc_str = f"ROI({(x1 + x2) // 2}, {(y1 + y2) // 2})"

            # 알림
            was_notified = False
            if do_alarm:
                was_notified = self._try_notify(roi_result, new_status)

            # 로그 추가
            self._add_log_row(
                datetime.now().strftime("%H:%M:%S"),
                loc_str,
                roi_result.max_temp,
                new_status.value,
                was_notified,
            )

            if do_alarm:
                self._log_to_status(
                    f"Alert: {new_status.value} | Max: {roi_result.max_temp:.1f}°C")

        except Exception as e:
            import traceback
            traceback.print_exc()

    # ════════════════════════════════════════════════════════════
    # 알림
    # ════════════════════════════════════════════════════════════
    def _try_notify(self, roi_result: RoiResult, new_status: Status) -> bool:
        try:
            overlay_dir = self._config.paths.overlay_dir
            os.makedirs(overlay_dir, exist_ok=True)
            overlay_path = os.path.join(overlay_dir, f"{datetime.now().strftime('%Y%m%d%H%M%S')}_overlay.jpg")
            cv2.imwrite(overlay_path, self._current_overlay)

            success = send_alarm(
                image_path=overlay_path,
                temp=roi_result.hot_temp_95,
                status=new_status.value,
                robot_id=self._config.identity.robot_id,
            )
            if success:
                self._monitor_state.last_alarm_time = time.time()
            return success
        except RuntimeError:
            return False
        except Exception:
            return False

    # ════════════════════════════════════════════════════════════
    # 이미지 표시
    # ════════════════════════════════════════════════════════════
    def _refresh_display(self):
        if self._current_view == "visual" and self._current_visual_overlay is not None:
            display_img = self._current_visual_overlay
        elif self._current_overlay is not None:
            display_img = self._current_overlay
        else:
            return

        self._photo_ref = self._cv2_to_tk(display_img, self.DISPLAY_IMAGE_WIDTH)
        self._image_label.configure(image=self._photo_ref)

        if self._current_roi_result:
            status = self._current_status
            color = {"Critical": "#ff0000", "Warning": "#ff8800"}.get(status, "#00aa00")
            self._status_label.configure(text=f"Status: {status}", foreground=color)
            self._max_temp_label.configure(
                text=f"Max: {self._current_roi_result.max_temp:.1f} °C")
            self._mean_temp_label.configure(
                text=f"Mean: {self._current_roi_result.mean_temp:.1f} °C")
            self._hot_temp_label.configure(
                text=f"95th: {self._current_roi_result.hot_temp_95:.1f} °C")
            self._hotspot_label.configure(
                text=f"Hotspots: {len(self._current_roi_result.hotspot_centroids)}")

    def _on_view_changed(self):
        self._current_view = self._view_var.get()
        self._refresh_display()

    @staticmethod
    def _cv2_to_tk(cv_img: np.ndarray, max_width: int) -> ImageTk.PhotoImage:
        h, w = cv_img.shape[:2]
        scale = max_width / w
        new_w, new_h = int(w * scale), int(h * scale)
        img = cv2.resize(cv_img, (new_w, new_h))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img)
        return ImageTk.PhotoImage(pil_img)

    # ════════════════════════════════════════════════════════════
    # 로그 테이블
    # ════════════════════════════════════════════════════════════
    def _add_log_row(self, timestamp: str, location: str, temp: float,
                     alert_level: str, was_notified: bool):
        def _insert():
            item_id = self._log_tree.insert("", 0, values=(
                timestamp, location, f"{temp:.1f}°C",
                alert_level, "Yes" if was_notified else "—",
            ), tags=(alert_level,))
            self._trim_log()
        self.root.after(0, _insert)

    def _trim_log(self):
        children = self._log_tree.get_children()
        if len(children) > self.MAX_LOG_ROWS:
            for item in children[self.MAX_LOG_ROWS:]:
                self._log_tree.delete(item)

    # ════════════════════════════════════════════════════════════
    # 외부 도구 실행 (ROI Selector / Calibration)
    # ════════════════════════════════════════════════════════════
    def _find_latest_thermal_jpg(self) -> str:
        dataset_dir = self._config.paths.dataset_dir
        if not os.path.isdir(dataset_dir):
            return ""
        jpgs = sorted(glob.glob(os.path.join(dataset_dir, "*.jpg")))
        thermal_jpgs = [j for j in jpgs if "_visual" not in j]
        return thermal_jpgs[-1] if thermal_jpgs else ""

    def _launch_roi_selector(self):
        if self._roi_running:
            return
        self._roi_running = True
        self._log_to_status("Launching ROI Selector...")

        def _run():
            try:
                img_path = self._find_latest_thermal_jpg()
                if not img_path:
                    self._log_to_status("No thermal image found for ROI selection.")
                    return
                old_argv = sys.argv
                sys.argv = ["roi_selector", img_path]
                try:
                    from ..tools.roi_selector import main as roi_main
                    roi_main()
                finally:
                    sys.argv = old_argv
            finally:
                self._roi_running = False
                self._config = load_config(force_reload=True)
                self.root.after(0, self._update_env_display)
                self._log_to_status("ROI Selector closed.")
        threading.Thread(target=_run, daemon=True).start()

    def _pick_calibration_image(self) -> str:
        """가장 hotspot이 많은 thermal 이미지, 없으면 가장 최근 이미지."""
        dataset_dir = self._config.paths.dataset_dir
        if not os.path.isdir(dataset_dir):
            return ""
        npy_files = sorted(glob.glob(os.path.join(dataset_dir, "*_thermal.npy")))
        if not npy_files:
            return self._find_latest_thermal_jpg()

        best_path = ""
        best_count = 0
        roi_config = load_roi_config()
        for npy_path in npy_files:
            try:
                result = extract_roi_from_npy(npy_path, roi_config)
                count = len(result.hotspot_centroids)
                if count > best_count:
                    best_count = count
                    best_path = npy_path.replace("_thermal.npy", ".jpg")
            except Exception:
                pass

        if best_count == 0 and npy_files:
            best_path = npy_files[-1].replace("_thermal.npy", ".jpg")

        return best_path

    def _launch_calibration(self):
        if self._calib_running:
            return
        self._calib_running = True
        self._log_to_status("Launching Calibration...")

        def _run():
            try:
                thermal_jpg = self._pick_calibration_image()
                if not thermal_jpg or not os.path.isfile(thermal_jpg):
                    self._log_to_status("No image found for calibration.")
                    return
                visual_jpg = thermal_jpg.replace(".jpg", "_visual.jpg")
                if not os.path.isfile(visual_jpg):
                    self._log_to_status(f"Visual image not found: {visual_jpg}")
                    return

                from ..tools.calibration import run_calibration
                run_calibration(thermal_jpg, visual_jpg)
            finally:
                self._calib_running = False
                self._config = load_config(force_reload=True)
                self.root.after(0, self._update_env_display)
                self._log_to_status("Calibration closed.")
        threading.Thread(target=_run, daemon=True).start()

    def _update_env_display(self):
        self._cam_ip_var.set(self._config.camera.ip)
        self._dir_var.set(self._config.paths.dataset_dir)
        self._interval_var.set(str(self._config.camera.capture_interval_sec))
        self._check_camera_connection()

    # ════════════════════════════════════════════════════════════
    # 종료 처리
    # ════════════════════════════════════════════════════════════
    def on_close(self):
        self._stop_monitoring()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = MonitoringDashboard(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
