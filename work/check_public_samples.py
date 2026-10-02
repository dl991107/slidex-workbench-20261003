"""Evaluate published independent examples, without browser interaction."""
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
from loguru import logger
from slidex.vision import SliderImageSolver

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'work/public-puzzle-samples'
OUT=ROOT/'outputs/public-sample-test'
OUT.mkdir(exist_ok=True)
logger.remove()
solver=SliderImageSolver(allow_yolo_backend=False)
rows=[]
for number in (4,8):
    original=SRC/f'example{number}.png'
    reference=SRC/f'predict{number}.png'
    started=time.perf_counter()
    result=solver.solve(original.read_bytes()).to_dict()
    elapsed=(time.perf_counter()-started)*1000
    ref=cv2.imread(str(reference))
    blue=np.all(ref==np.array([255,42,4],dtype=np.uint8),axis=2)
    ys,xs=np.where(blue)
    assert len(xs)>0
    # Published blue annotation supplies an independent horizontal reference.
    reference_x=int(xs.min())
    error=abs(result['gap_x']-reference_x) if result['gap_x'] is not None else None
    row={'sample':number,'input_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
         'source':f'https://github.com/chenwei-zhao/captcha-recognizer/blob/main/images_example/example{number}.png',
         'reference_source':f'https://github.com/chenwei-zhao/captcha-recognizer/blob/main/images_predict/predict{number}.png',
         'reference_type':'author published model annotation, not measured website ground truth',
         'reference_x':reference_x,'horizontal_error_px':error,
         'within_3px_of_reference':bool(result['success'] and error is not None and error<=3),
         'measured_ms':round(elapsed,3),'result':result}
    rows.append(row)
    observed=cv2.imread(str(original))
    if result['gap_box'] is not None:
        x1,y1,x2,y2=result['gap_box']
        cv2.rectangle(observed,(x1,y1),(x2,y2),(0,0,255),2)
    h,w=observed.shape[:2]
    canvas=np.full((h+35,2*w,3),255,np.uint8)
    canvas[35:,:w]=ref
    canvas[35:,w:]=observed
    cv2.putText(canvas,'Author reference',(5,23),0,.6,(0,0,0),1)
    cv2.putText(canvas,'Slidex output',(w+5,23),0,.6,(0,0,0),1)
    cv2.imwrite(str(OUT/f'comparison-{number}.png'),canvas)
report={'library':'slidex 0.6.28','optional_yolo':False,'browser_used':False,'rows':rows}
(OUT/'results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
