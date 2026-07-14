# Robot Thermal Monitoring System

산업용 다관절 로봇의 이상 발열을 조기 감지하여 예방 정비(Predictive Maintenance)를 지원하는 시스템입니다.
FLIR A50 Bi-spectrum 카메라의 열화상 이미지를 분석하여 로봇의 과열 상태를 실시간 모니터링하고 Telegram으로 알림을 전송합니다.

## 시스템 개요

```
FLIR A50 → REST Snapshot → Temperature Matrix (.npy) → ROI 설정 → 온도 분석 → Threshold 판단 → Overlay → Telegram 알림
```

## 사용 장비

| 항목 | 내용 |
|------|------|
| 카메라 | FLIR A50 Bi-spectrum (Thermal + Visible) |
| Thermal 해상도 | 640 × 480 |
| RGB 해상도 | 2592 × 1944 |
| 데이터 수집 주기 | 10초 |

## 프로젝트 구조

```
project/
├── capture.py              # FLIR A50 이미지 캡처 (Thermal + RGB)
├── thermal_utils.py        # 열화상 온도 추출 유틸 (Planck 변환)
├── metadata.py             # CSV 메타데이터 생성/업데이트
├── checking.py             # 데이터셋 무결성 검사 및 복구
├── calibration.py          # Thermal-RGB Homography 캘리브레이션 도구
├── tools.py                # 통합 운영 도구 GUI (Capture + Check + Metadata)
├── roi_selector.py         # GUI ROI 영역 설정 도구 (드래그)
│
├── roi.py                  # ROI 온도 통계 + 핫스팟 클러스터 분석
├── threshold.py            # 상태 머신 (Normal/Warning/Critical)
├── overlay.py              # Thermal/RGB 오버레이 이미지 생성
├── notifier.py             # Telegram 알림 전송 모듈
├── pipeline.py             # 통합 분석 파이프라인
│
├── _encoding.py            # Windows UTF-8 인코딩 유틸 (내부)
├── test.py                 # Threshold 시뮬레이션 테스트
├── test_overlay.py         # 단일 이미지 오버레이 확인용
│
├── product_design.md       # 제품 설계 계획안
├── experiment_config.json  # 실험 설정
├── roi_config.json         # ROI 좌표 + 임계값 설정
├── requirements.txt        # 의존성 패키지
├── .env.example            # 환경변수 템플릿 (BOT_TOKEN, CHAT_ID)
├── docs/
│   └── 카메라_도면.png      # FLIR A50 카메라 도면
└── thermal_dataset/        # 수집된 데이터셋
    ├── *.jpg               # Thermal 원본 이미지
    ├── *_thermal.npy       # 픽셀별 온도 행렬
    ├── *_visual.jpg        # 가시광 이미지
    ├── metadata.csv        # 데이터셋 메타데이터
    └── overlay/            # 오버레이 출력 이미지
```

## 빠른 시작

```bash
# 0. conda 환경 활성화 (권장)
conda activate test

# 1. 의존성 설치
pip install -r requirements.txt

# 2. 환경변수 설정 (Telegram 알림용)
cp .env.example .env
# → .env 파일에 BOT_TOKEN, CHAT_ID 입력

# 3. 통합 운영 도구 (캡처, 무결성 검사, 메타데이터)
python tools.py

# 4. ROI 영역 설정 (GUI)
python roi_selector.py

# 5. 캘리브레이션 (Thermal ↔ RGB 매핑, 공장 설치 시 필수)
python calibration.py

# 6. 전체 파이프라인 실행
python pipeline.py

# 7. 단일 이미지 오버레이 확인
python test_overlay.py
```

## ✅ 완료된 작업

### 데이터 수집

| 모듈 | 설명 |
|------|------|
| `tools.py` | 통합 운영 GUI — Capture(Start/Stop), Dataset Check, Metadata Generation 버튼, 실시간 로그 |
| `capture.py` | FLIR A50에서 Thermal + RGB 이미지 수집 (`CaptureSession` 클래스, GUI/스크립트 겸용) |
| `thermal_utils.py` | Radiometric JPEG에서 exiftool로 Raw Thermal 추출, Planck 변환으로 실제 °C 환산 |
| `checking.py` | 데이터셋 무결성 검사 — NPY 누락 시 JPG에서 복구, 고아 NPY 정리 (`run_check()` 함수) |
| `metadata.py` | JPG-NPY 파일쌍 스캔 후 `metadata.csv` 자동 생성, 실험 설정 연동 (`run_metadata()` 함수) |
| `calibration.py` | OpenCV GUI로 Thermal ↔ RGB 대응점 지정, Homography 행렬 계산 |
| `roi_selector.py` | Thermal 이미지에 마우스 드래그로 ROI 지정, `roi_config.json` 자동 저장 |

### 분석 파이프라인

| 모듈 | 설명 |
|------|------|
| `roi.py` | `.npy`에서 ROI 영역 온도 통계(max, mean, 95th) 추출 + Threshold 초과 픽셀 클러스터 분석 |
| `threshold.py` | 95th percentile + 클러스터 크기 기반 상태 판정, 상태 변화 시 알림 쿨다운(10분) |
| `overlay.py` | Thermal/RGB 이미지에 ROI 박스 + 온도 정보 표시, Homography 기반 좌표 변환 |
| `pipeline.py` | 전체 파이프라인 통합: ROI → Threshold → Overlay → Telegram 알림 |

### 알림

| 모듈 | 설명 |
|------|------|
| `notifier.py` | Telegram 이미지+캡션 전송, 실패 시 텍스트 폴백, `.env` 기반 토큰 관리 |
| `pipeline.py` | 상태 변화 감지 시 `notifier.py` 호출하여 자동 알림 |

### 판정 기준 상세

- **95th percentile** 온도가 `baseline + warning_delta` 초과 → Warning
- **95th percentile** 온도가 `baseline + critical_delta` 초과 → Critical
- **1~2픽셀 크기의 국소 과열** → 센서 노이즈로 간주, 무시
- **3픽셀 이상 연결된 과열 클러스터** → 실제 발열로 판정 (`cv2.connectedComponentsWithStats` 사용)

## 🚧 현재 작업 중

- **DB 설계** — 온도 이력(test.py 히스토리)을 저장할 DB 스키마 설계 (동료 작업 대기)
- **웹 대시보드** — 실시간 온도 트렌드, ROI 오버레이, 알림 상태 표시 (동료 작업 대기)
- **실시간 모니터링 루프** — DB + 대시보드 완료 후 `pipeline.py`를 실시간 모드로 전환 예정
- **공장 라인 실증 테스트** — 실제 로봇 발열 데이터 확보 시 검증

## 📋 앞으로 작업할 내용

### Phase 1 — MVP (현재 단계)

| 작업 | 상태 | 설명 |
|------|------|------|
| ROI 설정 (GUI) | ✅ | `roi_selector.py` — 이미지 드래그로 ROI 지정 |
| 온도 분석 파이프라인 | ✅ | `roi.py` — max/mean/95th + 클러스터 분석 |
| Threshold 판단 로직 | ✅ | `threshold.py` — 클러스터 크기 기반 노이즈 필터링 |
| 상태 머신 | ✅ | Normal → Warning → Critical → Normal 상태 전이 |
| Telegram 알림 | ✅ | `notifier.py` — 이미지+캡션 전송, `.env` 토큰 관리 |
| Overlay 시각화 | ✅ | `overlay.py` — Thermal/RGB 이미지에 온도 정보 표시 |
| 통합 파이프라인 | ✅ | `pipeline.py` — ROI → Threshold → Overlay → 알림 |
| 통합 운영 GUI | ✅ | `tools.py` — Capture, Check, Metadata 한 화면에서 실행 |
| 이력 관리 | ⬜ | 온도 트렌드 DB 저장 — DB 설계 완료 후 진행 |
| 웹 대시보드 | ⬜ | 실시간 상태/트렌드/알림 표시 — 동료 작업 대기 |
| 실시간 모니터링 | ⬜ | DB + 대시보드 연동 후 `pipeline.py` 실시간 전환 |

### Phase 2 — 고도화

- Robot Detection AI 모델 적용
- 이상 탐지(Anomaly Detection) 모델
- 다중 카메라 지원
- RTSP 스트리밍 지원
- 다중 로봇 모니터링
- 카메라 제조사 확장

### Phase 3 — 예지보전

- 부품 단위 진단
- 예지보전 알고리즘
- 클라우드 연동
- AI 기반 이상 패턴 분석

## 기술 스택

| 구분 | 기술 |
|------|------|
| 언어 | Python 3.12 |
| 이미지 처리 | OpenCV, Pillow |
| 수치 연산 | NumPy |
| 데이터 포맷 | JPEG, NPY, CSV, JSON |
| 통신 | REST API (requests) |
| 알림 | Telegram Bot API |
| 메타데이터 추출 | exiftool |
| 카메라 | FLIR A50 (REST API) |

## 데이터 수집 방식

- 10초 주기로 FLIR A50 카메라에 REST API 요청
- 수집 데이터: Thermal JPEG (radiometric) + Visual JPEG + Temperature Matrix (.npy)
- `.npy` 파일은 픽셀별 실제 온도 정보(°C)를 포함하여 별도 변환 불필요
- 실시간 스트리밍 대신 Snapshot 방식 채택 (네트워크 품질/방화벽 제약 고려)

## 알림 규칙

| 상태 | 메시지 전송 | 전송 정보 |
|------|------------|-----------|
| 평시 (Normal) | 없음 | - |
| 과열 (Warning) | 전송 | 로봇ID, 상태, 최고 온도, 발생 시간, 과열 범위 이미지 |
| 경보 (Critical) | 전송 | 로봇ID, 상태, 최고 온도, 발생 시간, 과열 범위 이미지 |

- 상태 변화 시에만 메시지 전송 (Normal → Warning → Critical → Normal)
- 연속 발송 방지를 위한 쿨다운: 10분

## 🔒 보안 및 개인정보 규칙

> **이 프로젝트에서 취득한 모든 데이터와 개인정보는 외부에 공유할 수 없습니다.**

| 항목 | 규칙 |
|------|------|
| `thermal_dataset/` | 수집된 이미지, 온도 행렬, 메타데이터 절대 외부 유출 금지 |
| 카메라 IP / 네트워크 정보 | 외부 노출 금지 (내부용 사설 IP 사용 권장: 192.168 대역) |
| Telegram Bot Token / Chat ID | `.env` 파일로 분리, 코드에 하드코딩 금지 |
| `thermal_to_rgb.npy` | 캘리브레이션 데이터 — 공유 금지 |

### .gitignore 확인사항

```gitignore
/.vscode
/thermal_dataset
/thermal_to_rgb.npy
/__pycache__
/.obsidian
*.pyc
.env
```

## 라이선스

Private — All rights reserved.
