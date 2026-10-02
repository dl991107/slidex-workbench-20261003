import base64
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / 'outputs/Slidex工作台.app/Contents/Resources/infer.py'


def run(payload):
    assert WORKER.is_file(), 'inference worker has not been implemented'
    return subprocess.run([sys.executable, str(WORKER)], input=json.dumps(payload),
                          text=True, capture_output=True, timeout=15)


def test_real_public_sample_output():
    image = ROOT / 'work/public-puzzle-samples/example4.png'
    completed = run({'image': base64.b64encode(image.read_bytes()).decode(), 'piece': None})
    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert set(result) == {'success','gap_x','gap_box','confidence','method','elapsed_ms','image_width','image_height'}
    assert result['image_width'] == 672 and result['image_height'] == 390
    assert result['success'] and abs(result['gap_x'] - 238) <= 3


def test_worker_invalid_image_masks_detail():
    completed = run({'image':base64.b64encode(b'PRIVATE_INPUT_TEXT').decode()})
    assert completed.returncode != 0
    assert json.loads(completed.stdout) == {'error':'inference_failed'}
    assert 'PRIVATE_INPUT_TEXT' not in completed.stdout + completed.stderr


def test_exif_orientation_dimensions_match_decoded_pixels():
    data = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB',(80,40),'white').save(data,format='JPEG',exif=exif)
    completed = run({'image':base64.b64encode(data.getvalue()).decode()})
    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert (result['image_width'],result['image_height']) == (40,80)


def test_real_worker_timeout_and_followup_recovery():
    spec = importlib.util.spec_from_file_location('workbench',WORKER.parent/'server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    payload = {'image':(ROOT/'work/public-puzzle-samples/example4.png').read_bytes(),'piece':None}
    with pytest.raises(TimeoutError):
        server.run_inference(payload,timeout=.001)
    result = server.run_inference(payload)
    assert result['success'] and abs(result['gap_x']-238) <= 3
