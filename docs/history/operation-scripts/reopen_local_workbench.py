"""Restart the identified workbench service; never call browser routes."""
import http.client
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

BASE=Path(__file__).resolve().parent
APP=Path('/Applications/Slidex工作台.app')
OLD_PID,OLD_PORT=56463,56043
old_origin=f'http://127.0.0.1:{OLD_PORT}'

def request(origin,method,path,body=None,headers=None):
    assert path in {'/','/app.js','/api/status','/api/shutdown'}
    parsed=urlsplit(origin)
    assert parsed.scheme=='http' and parsed.hostname=='127.0.0.1' and parsed.port
    connection=http.client.HTTPConnection('127.0.0.1',parsed.port,timeout=3)
    try:
        connection.request(method,path,body,headers or {})
        response=connection.getresponse()
        return response.status,response.read(512*1024)
    finally:
        connection.close()

command=subprocess.check_output(['/bin/ps','-p',str(OLD_PID),'-o','command='],text=True).strip()
assert command.startswith(str(APP/'Contents/Resources/runtime/bin/python3.12')+' ')
assert str(APP/'Contents/Resources/server.py') in command
status,raw=request(old_origin,'GET','/api/status')
assert status==200 and json.loads(raw)['backend']=='浏览器适配器'
assert json.loads(raw)['busy'] is False, 'Workbench busy; leave it running'
status,raw=request(old_origin,'GET','/')
assert status==200 and '连接现有 Chrome for Testing'.encode() in raw
token=re.search(rb'name="workbench-token" content="([a-f0-9]{64})"',raw).group(1).decode()
status,_=request(old_origin,'POST','/api/shutdown','{}',{
    'Origin':old_origin,'X-Workbench-Token':token,'Content-Type':'application/json'})
assert status==200, 'Old service did not accept shutdown'
del token

state=Path(tempfile.mkdtemp(prefix='workbench-reopen-',dir=BASE))
port_file=state/'endpoint.json'
with (state/'service.log').open('wb') as log:
    process=subprocess.Popen([str(APP/'Contents/MacOS/launch'),'--no-open','--port-file',str(port_file)],
        stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
for _ in range(50):
    if port_file.exists(): break
    assert process.poll() is None, 'New service exited'
    time.sleep(.1)
endpoint=json.loads(port_file.read_text())
assert endpoint['pid']==process.pid
origin=endpoint['url']
status,raw=request(origin,'GET','/api/status')
assert status==200 and json.loads(raw)['busy'] is False
status,raw=request(origin,'GET','/app.js')
assert status==200 and 'Unsupported · 本次未执行拖动'.encode() in raw
status,raw=request(origin,'GET','/')
assert status==200 and '结果说明'.encode() in raw
opened=subprocess.run(['/usr/bin/open',origin],check=False).returncode==0
(BASE/'current-workbench.json').write_text(json.dumps(endpoint))
print(json.dumps({'old_shutdown_accepted':True,'new_service_ready':True,'new_diagnostic_ui':True,
    'opened':opened,'url':origin,'browser_routes_called':0},ensure_ascii=False))
