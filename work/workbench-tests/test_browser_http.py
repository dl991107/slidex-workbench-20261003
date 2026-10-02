import json
import threading
import uuid
from test_server import _load_backend, _running, _exchange


def test_real_http_browser_routes_auth_replay_and_limits(monkeypatch):
    backend = _load_backend()
    seen = []
    def discover(endpoint):
        seen.append('discover')
        return {'websocket':'ws://127.0.0.1:9222/devtools/browser/test',
                'targets':[{'id':'a','title':'Test','url':'https://example.invalid/?secret=hidden'}]}
    def runner(record,event):
        seen.append('run')
        return {'status':'passed','provider':'geetest','secret':'hidden'}
    bridge = backend.BrowserBridge(discover=discover,runner=runner)
    monkeypatch.setattr(backend,'BrowserBridge',lambda:bridge)
    with _running(backend,None) as server:
        assert not seen
        body = json.dumps({'endpoint':'http://127.0.0.1:9222'})
        assert _exchange(server,body,path='/api/browser/connect',token='wrong')[0]==403
        assert not seen
        status,data,raw = _exchange(server,body,path='/api/browser/connect')
        assert status==200 and b'hidden' not in raw
        request = json.dumps({'target':data['targets'][0]['id'],'request_id':str(uuid.uuid4())})
        first = _exchange(server,request,path='/api/browser/run')
        replay = _exchange(server,request,path='/api/browser/run')
        assert first[0]==replay[0]==200 and first[1]==replay[1]
        assert seen.count('run')==1 and b'hidden' not in first[2]
        assert _exchange(server,'{}',path='/api/browser/run')[0]==400
        assert _exchange(server,'{}',path='/api/browser/connect',transmit=False,content_length=16385)[0]==413


def test_real_http_cancel_cannot_cancel_another_operation(monkeypatch):
    backend = _load_backend()
    started = threading.Event()
    def discover(endpoint):
        return {'websocket':'ws://127.0.0.1:9222/devtools/browser/test',
                'targets':[{'id':'a','title':'Test','url':'https://example.invalid/'}]}
    def runner(record,event):
        started.set()
        assert event.wait(3)
        return {'status':'cancelled'}
    bridge = backend.BrowserBridge(discover=discover,runner=runner)
    monkeypatch.setattr(backend,'BrowserBridge',lambda:bridge)
    with _running(backend,None) as server:
        _,data,_ = _exchange(server,json.dumps({'endpoint':'http://127.0.0.1:9222'}),path='/api/browser/connect')
        request_id = str(uuid.uuid4())
        request = json.dumps({'target':data['targets'][0]['id'],'request_id':request_id})
        result = []
        thread = threading.Thread(target=lambda:result.append(_exchange(server,request,path='/api/browser/run')))
        thread.start()
        try:
            assert started.wait(2)
            assert _exchange(server,'{}',path='/api/shutdown')[0]==409
            wrong = json.dumps({'request_id':str(uuid.uuid4())})
            assert _exchange(server,wrong,path='/api/browser/cancel')[0]==409
            assert not bridge.cancel_event.is_set()
            right = json.dumps({'request_id':request_id})
            assert _exchange(server,right,path='/api/browser/cancel')[0]==200
        finally:
            if bridge.cancel_event:
                bridge.cancel_event.set()
            thread.join(3)
        assert result[0][1]['result']['status']=='cancelled'
