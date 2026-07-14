from _encoding import setup_encoding
setup_encoding()

from roi import load_roi_config, extract_roi_from_npy
from threshold import evaluate_threshold
from overlay import create_overlay, save_overlay

base = '20260714131111_660581'
thermal_jpg = f'thermal_dataset/{base}.jpg'
visual_jpg = f'thermal_dataset/{base}_visual.jpg'
npy_path = f'thermal_dataset/{base}_thermal.npy'

config = load_roi_config()
result = extract_roi_from_npy(npy_path, config)

status = evaluate_threshold(
    result.hot_temp_95,
    config.baseline_temp,
    config.warning_delta,
    config.critical_delta,
    result.over_temp_pixels,
    result.max_hotspot_size,
)

print(f'ROI bounds (thermal 640x480): {result.roi_bounds}')
print(f'Max: {result.max_temp:.1f}C  Mean: {result.mean_temp:.1f}C  95th: {result.hot_temp_95:.1f}C')
print(f'Status: {status.value}')

overlay = create_overlay(
    thermal_jpg_path=thermal_jpg,
    visual_jpg_path=visual_jpg,
    roi_bounds=result.roi_bounds,
    max_temp=result.max_temp,
    mean_temp=result.mean_temp,
    hot_temp=result.hot_temp_95,
    status=status.value,
)

out = save_overlay(base, overlay)
print(f'Overlay saved: {out}')
