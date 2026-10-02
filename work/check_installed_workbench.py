"""Check local app startup only; never call a browser connection or run route."""
import http.client
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

APP=Path('/Applications/Slidex工作台.app')
process=subprocess.Popen([str(APP/'Contents/MacOS/launch'),'--no-open'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
try:
    origin=json.loads(process.stdout.readline())['url']
    port=urlsplit(origin).port
    def request(method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
        try:
            connection.request(method,path,body=body,headers=headers or {})
            response=connection.getresponse()
            return response.status,response.read()
        finally:
            connection.close()
    status,raw=request('GET','/')
    assert status==200 and '连接现有 Chrome for Testing'.encode() in raw
    token=re.search(rb'name="workbench-token" content="([a-f0-9]{64})"',raw).group(1).decode()
    status,raw=request('GET','/api/status')
    data=json.loads(raw)
    assert status==200 and data['backend']=='浏览器适配器' and data['busy'] is False
    assert request('GET','/app.js')[0]==200 and request('GET','/style.css')[0]==200
    headers={'Origin':origin,'X-Workbench-Token':token,'Content-Type':'application/json'}
    assert request('POST','/api/shutdown','{}',headers)[0]==200
    assert process.wait(timeout=5)==0
    print(json.dumps({'installed_app_started':True,'local_ui_served':True,'status':data,
                      'clean_shutdown':True,'browser_connections_attempted':0},ensure_ascii=False))
finally:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
