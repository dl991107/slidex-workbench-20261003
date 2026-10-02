"""User-initiated loopback discovery and a single bounded browser operation."""
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MESSAGES = {
    'passed':'Slidex 适配器收到成功反馈，请在原页面确认最终状态。',
    'failed':'Slidex 适配器收到失败反馈；本次不会自动重试。',
    'unknown':'结果未确认，请查看原页面；如页面已变化，请重新连接并选择。',
    'unsupported':'未找到可用的内置适配滑块，或图片、尺寸不满足识别条件；未执行拖动。',
    'cancelled':'本次任务已停止，请在原页面检查鼠标和页面状态。',
}


class BridgeError(Exception):
    def __init__(self,status,code,message):
        self.status,self.code,self.message = status,code,message


def normalize_endpoint(value):
    try:
        if not isinstance(value,str) or len(value)>100 or value.strip()!=value:
            raise ValueError()
        parsed = urlsplit(value)
        if (parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost'}
                or not parsed.port or parsed.username is not None or parsed.password is not None
                or parsed.path not in {'','/'} or parsed.query or parsed.fragment
                or '\\' in value or '?' in value or '#' in value):
            raise ValueError()
        return f'http://127.0.0.1:{parsed.port}'
    except (TypeError,ValueError):
        raise BridgeError(400,'invalid_endpoint','请输入本机调试地址，例如 http://127.0.0.1:9222。') from None


def read_json(endpoint,path):
    deadline = time.monotonic()+3
    try:
        port = urlsplit(endpoint).port
        with socket.create_connection(('127.0.0.1',port),timeout=3) as connection:
            connection.sendall(f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n'.encode())
            raw,body_offset,length = bytearray(),None,None
            while True:
                remaining = deadline-time.monotonic()
                if remaining<=0:
                    raise TimeoutError()
                connection.settimeout(remaining)
                chunk = connection.recv(8192)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw)>1024*1024+16384:
                    raise ValueError()
                if body_offset is None:
                    end = raw.find(b'\r\n\r\n')
                    if end<0:
                        if len(raw)>16384:
                            raise ValueError()
                        continue
                    headers = bytes(raw[:end]).split(b'\r\n')
                    if headers[0].split()[1]!=b'200':
                        raise ValueError()
                    lengths = [line.split(b':',1)[1].strip() for line in headers[1:] if line.lower().startswith(b'content-length:')]
                    if len(lengths)!=1 or not lengths[0].isdigit() or any(line.lower().startswith(b'transfer-encoding:') for line in headers[1:]):
                        raise ValueError()
                    length,body_offset = int(lengths[0]),end+4
                    if length>1024*1024:
                        raise ValueError()
                if len(raw)-body_offset>=length:
                    break
            if body_offset is None or len(raw)-body_offset!=length:
                raise ValueError()
            return json.loads(raw[body_offset:])
    except Exception:
        raise BridgeError(502,'connection_failed','无法连接调试端口，请确认 Testing 已开启远程调试，且端口填写正确。') from None


def inspect_browser(endpoint):
    version = read_json(endpoint,'/json/version')
    try:
        socket_url = urlsplit(version['webSocketDebuggerUrl'])
        if (not re.match(r'^(?:Headless)?Chrome/',version['Browser']) or socket_url.scheme!='ws'
                or socket_url.hostname not in {'127.0.0.1','localhost'}
                or socket_url.port!=urlsplit(endpoint).port or socket_url.username is not None
                or socket_url.password is not None or socket_url.query or socket_url.fragment
                or not re.fullmatch(r'/devtools/browser/[a-zA-Z0-9-]+',socket_url.path)):
            raise ValueError()
        websocket = f'ws://127.0.0.1:{socket_url.port}{socket_url.path}'
        listing = read_json(endpoint,'/json/list')
        if not isinstance(listing,list) or len(listing)>500:
            raise ValueError()
        targets = []
        for entry in listing:
            if not isinstance(entry,dict) or entry.get('type')!='page':
                continue
            url = entry.get('url','')
            parsed = urlsplit(url)
            if (parsed.scheme not in {'http','https'} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None):
                continue
            if not isinstance(entry.get('id'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',entry['id']):
                raise ValueError()
            targets.append({'id':entry['id'],'url':url,'title':str(entry.get('title',''))[:120]})
        return {'websocket':websocket,'targets':targets}
    except BridgeError:
        raise
    except Exception:
        raise BridgeError(502,'invalid_browser','该端口没有返回有效的 Chrome 调试信息。') from None


def run_worker(record,cancel_event,timeout=50,stop_grace=2):
    if cancel_event.is_set():
        return {'status':'cancelled'}
    env = {'PATH':'/usr/bin:/bin','PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'}
    process = subprocess.Popen([sys.executable,'-E','-s','-B',str(ROOT/'browser_task.py')],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        env=env,cwd=ROOT,start_new_session=True)
    started,cancelled_at = time.monotonic(),None
    data = json.dumps(record)
    try:
        while True:
            now = time.monotonic()
            if (cancel_event.is_set() or now-started>timeout) and cancelled_at is None:
                process.terminate()
                cancelled_at = now
            if cancelled_at is not None and now-cancelled_at>stop_grace:
                try:
                    os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if now-started>timeout+stop_grace+2:
                return {'status':'cancelled' if cancel_event.is_set() else 'unknown'}
            try:
                stdout,_ = process.communicate(input=data,timeout=.2)
                break
            except subprocess.TimeoutExpired:
                data = None
        if cancel_event.is_set():
            return {'status':'cancelled'}
        if cancelled_at is not None or process.returncode:
            return {'status':'unknown'}
        return json.loads(stdout)
    finally:
        try:
            os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
        for stream in (process.stdin,process.stdout,process.stderr):
            stream.close()
        process.wait(timeout=2)


class BrowserBridge:
    def __init__(self,discover=inspect_browser,runner=run_worker):
        self.discover,self.runner = discover,runner
        self.gate,self.state_lock = threading.Lock(),threading.Lock()
        self.targets,self.completed = {},{}
        self.active_id,self.cancel_event = None,None

    @property
    def busy(self):
        return self.gate.locked()

    def connect(self,payload):
        if not isinstance(payload,dict) or set(payload)!={'endpoint'}:
            raise BridgeError(400,'invalid_fields','连接请求需要 endpoint 字段。')
        endpoint = normalize_endpoint(payload['endpoint'])
        if not self.gate.acquire(blocking=False):
            raise BridgeError(409,'busy','有任务正在执行，请结束后再连接。')
        try:
            self.targets = {}
            discovery = self.discover(endpoint)
            visible = []
            for target in discovery['targets']:
                handle = secrets.token_hex(16)
                self.targets[handle] = {'id':target['id'],'url':target['url'],
                    'endpoint':endpoint,'websocket':discovery['websocket']}
                parsed = urlsplit(target['url'])
                visible.append({'id':handle,'title':target['title'],'url':f'{parsed.scheme}://{parsed.netloc}'})
            return {'ok':True,'targets':visible,'message':f'已读取 {len(visible)} 个网页标签。请选择后执行。'}
        except BridgeError:
            raise
        except Exception:
            raise BridgeError(502,'connection_failed','读取浏览器信息失败，请检查调试端口。') from None
        finally:
            self.gate.release()

    @staticmethod
    def request_id(payload,keys):
        try:
            if not isinstance(payload,dict) or set(payload)!=keys or str(uuid.UUID(payload['request_id']))!=payload['request_id']:
                raise ValueError()
            return payload['request_id']
        except (ValueError,TypeError,AttributeError,KeyError):
            raise BridgeError(400,'invalid_request','请求字段或 request_id 不正确。') from None

    def run(self,payload):
        request_id = self.request_id(payload,{'target','request_id'})
        handle = payload['target']
        if not isinstance(handle,str) or len(handle)>64:
            raise BridgeError(400,'invalid_target','请选择本次连接返回的标签页。')
        with self.state_lock:
            if request_id in self.completed:
                original,result = self.completed[request_id]
                if original!=handle:
                    raise BridgeError(409,'request_conflict','相同 request_id 不能用于不同页面。')
                return result
        if not self.gate.acquire(blocking=False):
            raise BridgeError(409,'busy','已有任务正在执行；本次不会重复执行。')
        started = time.monotonic()
        try:
            with self.state_lock:
                # A duplicate may have waited between the cache check and gate acquisition.
                if request_id in self.completed:
                    original,result = self.completed[request_id]
                    if original!=handle:
                        raise BridgeError(409,'request_conflict','相同 request_id 不能用于不同页面。')
                    return result
                self.active_id,self.cancel_event = request_id,threading.Event()
            record = self.targets.get(handle)
            if not record:
                raise BridgeError(410,'stale_target','页面选择已失效，请重新连接。')
            fresh = self.discover(record['endpoint'])
            if fresh['websocket']!=record['websocket'] or not any(
                target['id']==record['id'] and target['url']==record['url'] for target in fresh['targets']):
                raise BridgeError(409,'page_changed','浏览器或页面已经变化，请重新连接后选择。')
            try:
                raw = self.runner(dict(record),self.cancel_event)
                status = raw.get('status','unknown')
                if status not in MESSAGES:
                    status = 'unknown'
                provider = raw.get('provider','')
                if provider not in {'geetest','aliyun-nocaptcha'}:
                    provider = ''
            except Exception:
                status,provider = 'unknown',''
            if self.cancel_event.is_set():
                status = 'cancelled'
            result = {'ok':True,'result':{'status':status,'provider':provider,
                'elapsed_ms':round((time.monotonic()-started)*1000), 'message':MESSAGES[status]}}
            with self.state_lock:
                self.completed[request_id] = (handle,result)
                while len(self.completed)>64:
                    self.completed.pop(next(iter(self.completed)))
            return result
        except BridgeError:
            raise
        except Exception:
            raise BridgeError(502,'connection_failed','浏览器连接已中断，请重新连接。') from None
        finally:
            with self.state_lock:
                self.active_id,self.cancel_event = None,None
            self.gate.release()

    def cancel(self,payload):
        request_id = self.request_id(payload,{'request_id'})
        with self.state_lock:
            if self.active_id!=request_id or self.cancel_event is None:
                raise BridgeError(409,'not_running','该任务当前未运行。')
            self.cancel_event.set()
        return {'ok':True,'message':'已请求停止本次任务。'}
