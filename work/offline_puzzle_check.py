"""Independent synthetic fixtures only; no remote pages or user CAPTCHA images."""
import json
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from loguru import logger
from slidex.vision import SliderImageSolver

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'offline-puzzle-test'
TYPES = ('clean', 'texture', 'distractor', 'whole_scene')


def png(image):
    ok, buf = cv2.imencode('.png', image)
    assert ok
    return buf.tobytes()


def fixture(kind, seed, scale):
    rng = np.random.default_rng(seed)
    h, w, size = 190, 400, 58
    x, y = int(rng.integers(170, 270)), int(rng.integers(50, 100))
    mask = np.zeros((size, size), np.uint8)
    cv2.rectangle(mask, (4, 12), (45, 53), 255, -1)
    cv2.circle(mask, (25, 12), 8, 255, -1)
    cv2.circle(mask, (45, 32), 8, 255, -1)
    cv2.circle(mask, (4, 32), 8, 0, -1)
    cv2.circle(mask, (25, 53), 8, 0, -1)
    background = np.full((h, w, 3), 220, np.uint8)
    if kind != 'clean':
        texture = rng.integers(90, 240, (24, 50, 3), dtype=np.uint8)
        background = cv2.resize(texture, (w, h), interpolation=cv2.INTER_CUBIC)
    original = background[y:y+size, x:x+size].copy()
    piece = np.zeros((size, size, 4), np.uint8)
    piece[:, :, :3] = np.where(mask[:, :, None] > 0, original, 0)
    piece[:, :, 3] = mask
    roi = background[y:y+size, x:x+size]
    roi[mask > 0] = 30
    if kind in ('distractor', 'whole_scene'):
        cv2.rectangle(background, (80, 55), (139, 114), (30, 30, 30), -1)
    if kind == 'whole_scene':
        start = background[y:y+size, 8:8+size]
        start[mask > 0] = original[mask > 0]
        cv2.drawContours(start, cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], -1, (255,255,255), 1)
    target_mask = np.zeros((h,w), np.uint8)
    target_mask[y:y+size, x:x+size] = mask
    target_mask = cv2.resize(target_mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    visible_x = int(np.where(target_mask >= 128)[1].min())
    background = cv2.resize(background, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    piece = cv2.resize(piece, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return background, piece, {'patch': x * scale, 'patch_y': y * scale, 'visible': visible_x}


def measure(solver, bg, piece=None):
    started = time.perf_counter()
    try:
        result = solver.solve(bg, piece).to_dict()
    except Exception as exc:
        result = {'success': False, 'error_code': type(exc).__name__, 'raised': True}
    result['measured_ms'] = round((time.perf_counter()-started)*1000, 3)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    logger.remove()
    solver = SliderImageSolver(allow_yolo_backend=False)
    rows, gallery, groups = [], [], defaultdict(list)
    for kind in TYPES:
        for seed in range(10):
            for scale in (0.75, 1.0, 1.5):
                bg, piece, truth = fixture(kind, seed, scale)
                for mode in ('image_only', 'with_piece'):
                    expected = truth['patch' if mode == 'with_piece' else 'visible']
                    result = measure(solver, png(bg), png(piece) if mode == 'with_piece' else None)
                    found = result.get('gap_x')
                    error = abs(found-expected) if found is not None else None
                    row = {'kind': kind, 'seed': seed, 'scale': scale, 'mode': mode,
                           'expected_x': expected, 'error_px': error,
                           'error_base_px': error/scale if error is not None else None,
                           'correct': bool(result['success'] and error is not None and error <= 3*scale),
                           **result}
                    rows.append(row)
                    groups[f'{kind}/{mode}'].append(row)
                    if seed == 0 and scale == 1:
                        picture = bg.copy()
                        cv2.line(picture, (round(expected),0), (round(expected),189), (0,180,0), 2)
                        if found is not None:
                            cv2.line(picture, (found,0), (found,189), (0,0,255), 2)
                        canvas = np.full((250,400,3), 255, np.uint8)
                        canvas[40:230] = picture
                        cv2.putText(canvas, f'{kind} / {mode}', (5,18), 0, .48, (0,0,0), 1)
                        cv2.putText(canvas, f'correct={row["correct"]} error={error} px', (5,36), 0, .42, (0,0,0), 1)
                        gallery.append(canvas)
                if seed == 0 and scale == 1:
                    cv2.imwrite(str(OUT/f'{kind}.png'), bg)
                    cv2.imwrite(str(OUT/f'{kind}-piece.png'), piece)
    summary = {}
    for name, cases in groups.items():
        times = [c['measured_ms'] for c in cases]
        summary[name] = {'total': len(cases), 'correct': sum(c['correct'] for c in cases),
                         'reported_success_but_wrong': sum(c['success'] and not c['correct'] for c in cases),
                         'refused': sum(not c['success'] and not c.get('raised',False) for c in cases),
                         'exceptions': sum(c.get('raised',False) for c in cases),
                         'median_ms': round(float(np.median(times)),3),
                         'p95_ms': round(float(np.percentile(times,95)),3)}
    blank = np.full((190,400,3), 220, np.uint8)
    line_only = blank.copy()
    cv2.line(line_only, (220,20), (220,170), (20,20,20), 2)
    boundaries = []
    for name, source in [('missing',None), ('empty_bytes',b''), ('corrupt_bytes',b'broken'),
                         ('blank',png(blank)), ('line_without_gap',png(line_only))]:
        result = measure(solver, source)
        boundaries.append({'case':name, 'expected':'reject',
                           'correct':not result['success'] and not result.get('raised',False), **result})
    cv2.imwrite(str(OUT/'comparison.png'), np.vstack([np.hstack(gallery[i:i+2]) for i in range(0,8,2)]))
    report = {'library':'slidex 0.6.28', 'input':'independent synthetic PNGs only',
              'yolo_backend':False, 'tolerance':'3 base-image pixels, scaled with image',
              'coordinate':{'image_only':'visible gap left edge from separately resized ground-truth mask',
                            'with_piece':'piece patch left edge, including transparent margin'},
              'summary':summary, 'boundary_cases':boundaries, 'cases':rows}
    (OUT/'results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'summary':summary,'boundary_cases':boundaries},indent=2))


if __name__ == '__main__':
    main()
