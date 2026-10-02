"""One bounded inference per process; input and output use stdin/stdout only."""
import json
import sys
import time

from server import MAX_BODY, validate_payload


def main():
    payload = validate_payload(json.loads(sys.stdin.buffer.read(MAX_BODY+1)))
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(payload['image'],dtype=np.uint8),cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('invalid image')
    height,width = image.shape[:2]
    from slidex.vision import SliderImageSolver
    from loguru import logger
    logger.remove()
    started = time.perf_counter()
    result = SliderImageSolver(allow_yolo_backend=False).solve(image,payload['piece'])
    return {'success':bool(result.success),'gap_x':result.gap_x,'gap_box':result.gap_box,
            'confidence':result.confidence,'method':result.method,
            'elapsed_ms':round((time.perf_counter()-started)*1000,2),
            'image_width':width,'image_height':height}


if __name__ == '__main__':
    try:
        print(json.dumps(main(),allow_nan=False))
    except Exception:
        print(json.dumps({'error':'inference_failed'}))
        sys.exit(1)
