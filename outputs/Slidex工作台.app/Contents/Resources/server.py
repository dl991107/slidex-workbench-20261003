"""Local workbench. Browser connection and execution require explicit API calls."""
import argparse
import base64
import binascii
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from browser_bridge import BrowserBridge, BridgeError
MAX_BODY = 24 * 1024 * 1024
MAX_IMAGE = 8 * 1024 * 1024
MAX_PIXELS = 12_000_000
RESULT_FIELDS = ('success','gap_x','gap_box','confidence','method','elapsed_ms','image_width','image_height')
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class InputError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def decode_image(value):
    if not isinstance(value, str) or not value or len(value) > MAX_IMAGE * 4 // 3 + 4:
        raise InputError(400 if not value or not isinstance(value,str) else 413, 'invalid_image', '请选择有效图片，单张不超过 8 MB。')
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise InputError(400, 'invalid_base64', '图片数据格式不正确。') from None
    if len(data) > MAX_IMAGE:
        raise InputError(413, 'image_too_large', '单张图片不能超过 8 MB。')
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {'PNG','JPEG','WEBP'} or getattr(image,'n_frames',1) != 1:
                raise ValueError('unsupported format')
            if image.width * image.height > MAX_PIXELS or max(image.size) > 8192:
                raise InputError(413, 'image_dimensions', '图片不超过 1200 万像素，单边不超过 8192 像素。')
            image.verify()
    except InputError:
        raise
    except Exception:
        raise InputError(422, 'image_decode', '无法读取图片，请使用完整的 PNG、JPG 或 WebP 图片。') from None
    return data


def validate_payload(payload):
    if not isinstance(payload,dict) or set(payload) - {'image','piece'} or 'image' not in payload:
        raise InputError(400, 'invalid_fields', '请求缺少图片或包含不支持的字段。')
    return {'image':decode_image(payload['image']),
            'piece':decode_image(payload['piece']) if payload.get('piece') is not None else None}


def run_inference(payload, timeout=10):
    encoded = {key:base64.b64encode(value).decode() if value is not None else None for key,value in payload.items()}
    try:
        result = subprocess.run([sys.executable,'-B',str(ROOT/'infer.py')],
            input=json.dumps(encoded), capture_output=True, text=True, timeout=timeout,
            cwd=ROOT, env={'PATH':os.environ.get('PATH','/usr/bin:/bin'), 'PYTHONIOENCODING':'utf-8', 'PYTHONDONTWRITEBYTECODE':'1'})
    except subprocess.TimeoutExpired:
        raise TimeoutError('inference timeout') from None
    if result.returncode:
        raise RuntimeError('inference failed')
    return json.loads(result.stdout)


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, analyzer=run_inference, browser_bridge=None):
        if address[0] != '127.0.0.1':
            raise ValueError('loopback only')
        self.token, self.busy_lock, self.analyzer = secrets.token_hex(32), threading.Lock(), analyzer
        self.browser_bridge = browser_bridge if browser_bridge is not None else BrowserBridge()
        super().__init__(address, Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'

    def handle_error(self, request, client_address):
        pass  # Request data and traceback details are deliberately not logged.


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = 'SlidexWorkbench', ''
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass

    def send(self, status, data, mime='application/json; charset=utf-8'):
        body = data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):
            pass

    def error(self,status,code,message):
        self.send(status,{'ok':False,'error':{'code':code,'message':message}})

    def authorized(self,write=False):
        valid = self.headers.get_all('Host') == [f'127.0.0.1:{self.server.server_port}']
        origins = self.headers.get_all('Origin')
        valid &= origins in (None,[self.server.origin])
        valid &= self.headers.get('Sec-Fetch-Site') != 'cross-site'
        if write:
            valid &= origins == [self.server.origin]
            tokens = self.headers.get_all('X-Workbench-Token',[])
            valid &= len(tokens) == 1 and secrets.compare_digest(tokens[0].encode(),self.server.token.encode())
        if not valid:
            self.error(403,'forbidden','请从本机工作台窗口发起操作。')
        return valid

    def do_GET(self):
        if not self.authorized():
            return
        path = urlsplit(self.path).path
        if path == '/api/status':
            return self.send(200,{'version':'0.6.28','backend':'浏览器适配器','busy':self.server.busy_lock.locked() or self.server.browser_bridge.busy})
        assets = {'/':('index.html','text/html; charset=utf-8'),
                  '/app.js':('app.js','text/javascript; charset=utf-8'),
                  '/style.css':('style.css','text/css; charset=utf-8')}
        if path not in assets:
            return self.error(404,'not_found','页面不存在。')
        name,mime = assets[path]
        try:
            data = (ROOT/'web'/name).read_bytes()
            if path == '/':
                data = data.replace(b'__TOKEN__',self.server.token.encode())
            self.send(200,data,mime)
        except OSError:
            self.error(500,'asset_missing','界面文件不完整，请重新安装工作台。')

    def do_POST(self):
        if not self.authorized(write=True):
            return
        path = urlsplit(self.path).path
        browser_routes = {'/api/browser/connect':'connect','/api/browser/run':'run','/api/browser/cancel':'cancel'}
        if path not in {'/api/analyze','/api/shutdown',*browser_routes}:
            return self.error(404,'not_found','接口不存在。')
        try:
            lengths = self.headers.get_all('Content-Length',[])
            if len(lengths) != 1 or not lengths[0].isdigit() or self.headers.get('Transfer-Encoding'):
                raise InputError(400,'invalid_length','请求长度不正确。')
            size = int(lengths[0])
            if size > (16384 if path in browser_routes else MAX_BODY):
                raise InputError(413,'request_too_large','上传内容过大。')
            if self.headers.get_content_type() != 'application/json':
                raise InputError(400,'invalid_type','请求格式不正确。')
            try:
                payload = json.loads(self.rfile.read(size))
            except (ValueError,UnicodeError):
                raise InputError(400,'invalid_json','请求内容不完整。') from None
            if path in browser_routes:
                result = getattr(self.server.browser_bridge,browser_routes[path])(payload)
                return self.send(200,result)
            if path == '/api/shutdown':
                if payload != {}:
                    raise InputError(400,'invalid_fields','关闭请求格式不正确。')
                if not self.server.busy_lock.acquire(blocking=False):
                    raise InputError(409,'busy','识别进行中，请结束后再关闭。')
                if not self.server.browser_bridge.gate.acquire(blocking=False):
                    self.server.busy_lock.release()
                    raise InputError(409,'busy','浏览器任务进行中，请先停止或等待完成。')
                try:
                    self.send(200,{'ok':True})
                finally:
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            decoded = validate_payload(payload)
            if not self.server.busy_lock.acquire(blocking=False):
                raise InputError(409,'busy','已有识别任务进行中，请稍后重试。')
            try:
                raw = self.server.analyzer(decoded)
                result = {key:raw[key] for key in RESULT_FIELDS}
                self.send(200,{'ok':True,'result':result,'notice':'识别结果是候选位置，请结合图片核对；不代表网站验证通过。'})
            finally:
                self.server.busy_lock.release()
        except (InputError,BridgeError) as exc:
            self.error(exc.status,exc.code,exc.message)
        except (TimeoutError,socket.timeout):
            self.error(504,'timeout','识别或读取超时，请换较小图片后重试。')
        except Exception:
            self.error(500,'inference_failed','识别未完成，请检查图片后重试。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-open',action='store_true')
    parser.add_argument('--port-file',type=Path)
    args = parser.parse_args()
    with WorkbenchServer(('127.0.0.1',0)) as server:
        if args.port_file:
            args.port_file.write_text(json.dumps({'url':server.origin,'pid':os.getpid()}))
        print(json.dumps({'url':server.origin}),flush=True)
        if not args.no_open:
            import webbrowser
            webbrowser.open(server.origin)
        server.serve_forever(poll_interval=.2)


if __name__ == '__main__':
    main()
