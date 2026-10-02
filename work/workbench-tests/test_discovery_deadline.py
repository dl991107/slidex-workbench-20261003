import importlib
import pytest


def test_partial_headers_have_absolute_deadline(monkeypatch):
    module=importlib.import_module('browser_bridge')
    clock=[0]
    class SlowSocket:
        closed=False
        def __enter__(self): return self
        def __exit__(self,*args): self.closed=True
        def sendall(self,data): pass
        def settimeout(self,remaining): assert 0<remaining<=3
        def recv(self,size):
            clock[0]+=.8
            return b'x'
    connection=SlowSocket()
    monkeypatch.setattr(module.socket,'create_connection',lambda *args,**kwargs:connection)
    monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    with pytest.raises(module.BridgeError): module.read_json('http://127.0.0.1:9222','/json/version')
    assert clock[0]<4 and connection.closed


def test_discovery_reads_exact_bounded_json(monkeypatch):
    module=importlib.import_module('browser_bridge')
    body=b'{"Browser":"Chrome/Test"}'
    class Socket:
        parts=[b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n',body]
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def sendall(self,data): assert b'Host: 127.0.0.1:9222' in data
        def settimeout(self,remaining): pass
        def recv(self,size): return self.parts.pop(0)
    monkeypatch.setattr(module.socket,'create_connection',lambda *args,**kwargs:Socket())
    assert module.read_json('http://127.0.0.1:9222','/json/version')=={'Browser':'Chrome/Test'}
