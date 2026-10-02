import asyncio
import importlib
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

RESOURCE = Path(__file__).resolve().parents[2]/'outputs/Slidex工作台.app/Contents/Resources'
sys.path.insert(0,str(RESOURCE))


def test_unsupported_page_never_sends_input(monkeypatch):
    module = importlib.import_module('browser_task')
    class Page:
        url = 'https://example.invalid/test'
    async def detect(page):
        return None
    monkeypatch.setattr(module.ProviderRegistry,'auto_detect',detect)
    result = asyncio.run(module.solve_page(Page(),Page.url))
    assert result['status'] == 'unsupported'
    assert result['reason'] == 'no_provider'


@pytest.mark.parametrize('stage,reason',[
    ('bounds','bounds_unavailable'),('images','images_unavailable'),
    ('gap','gap_uncertain'),('distance','distance_invalid'),
    ('frame','frame_unavailable'),('page','page_changed'),
])
def test_pre_drag_failures_report_distinct_causes(monkeypatch,stage,reason):
    module = importlib.import_module('browser_task')
    from PIL import Image
    from io import BytesIO
    image = BytesIO()
    Image.new('RGB',(20,20)).save(image,format='PNG')
    class Box:
        def __init__(self,width): self.width=width
        async def bounding_box(self): return None if stage=='bounds' else {'width':self.width}
        async def owner_frame(self): return None if stage=='frame' else 'frame'
    class Page:
        url='https://example.invalid/test'
        def remove_listener(self,*args): pass
    class Provider:
        name='geetest'
        async def locate_elements(self,page):
            return SimpleNamespace(slider_btn=Box(30),slider_track=Box(300),metadata={})
        async def extract_images(self,page,*args):
            if stage=='page': page.url='https://example.invalid/changed'
            return (b'',b'') if stage=='images' else (image.getvalue(),image.getvalue())
        async def find_gap(self,*args):
            return (300 if stage=='distance' else 100,.1 if stage=='gap' else .9)
        async def cleanup_after_result(self,page): pass
        async def perform_slide(self,*args,**kwargs): pytest.fail('must not drag')
    async def detect(page): return Provider()
    monkeypatch.setattr(module.ProviderRegistry,'auto_detect',detect)
    result=asyncio.run(module.solve_page(Page(),Page.url))
    assert result == {'status':'unsupported','provider':'geetest','reason':reason}


def test_changed_url_stops_before_detection(monkeypatch):
    module = importlib.import_module('browser_task')
    class Page:
        url = 'https://example.invalid/new'
    async def detect(page):
        raise AssertionError('must not inspect changed page')
    monkeypatch.setattr(module.ProviderRegistry,'auto_detect',detect)
    result = asyncio.run(module.solve_page(Page(),'https://example.invalid/old'))
    assert result['status'] == 'unknown'


@pytest.mark.parametrize('answer',[True,False,None,'crash','old','other_frame'])
def test_feedback_timeout_and_drag_exception_cleanup(monkeypatch,answer):
    module = importlib.import_module('browser_task')
    calls,handlers = [],{}
    class Box:
        def __init__(self,width): self.width=width
        async def bounding_box(self): return {'width':self.width,'height':30,'x':0,'y':0}
        async def owner_frame(self): return 'selected-frame'
    class Mouse:
        async def up(self): calls.append('up')
    class Page:
        url='https://example.invalid/test'
        mouse=Mouse()
        def on(self,event,fn): handlers.setdefault(event,[]).append(fn)
        def remove_listener(self,event,fn):
            if fn in handlers.get(event,[]): handlers[event].remove(fn)
    class Provider:
        name='geetest'
        async def locate_elements(self,page):
            return SimpleNamespace(slider_btn=Box(30),slider_track=Box(300),metadata={'slider_type':'scale'})
        async def perform_slide(self,page,*args,**kwargs):
            calls.append('drag')
            if answer=='crash': raise RuntimeError('PRIVATE_EXCEPTION')
            if answer is not None:
                class Request: frame='other-frame' if answer=='other_frame' else 'selected-frame'
                request=Request()
                if answer!='old':
                    for fn in handlers['request']: fn(request)
                for fn in handlers['response']: fn(SimpleNamespace(request=request))
        async def validate_response(self,response): return answer
        async def cleanup_after_result(self,page): calls.append('cleanup')
    async def detect(page): return Provider()
    monkeypatch.setattr(module.ProviderRegistry,'auto_detect',detect)
    if answer=='crash':
        with pytest.raises(RuntimeError): asyncio.run(module.solve_page(Page(),Page.url,.02))
    else:
        result=asyncio.run(module.solve_page(Page(),Page.url,.02))
        assert result['status']==('passed' if answer is True else 'failed' if answer is False else 'unknown')
    assert calls==['drag','up','cleanup']
    assert all(not value for value in handlers.values())


def test_subprocess_timeout_stops_only_owned_process(monkeypatch):
    module=importlib.import_module('browser_bridge')
    real_popen=module.subprocess.Popen
    children=[]
    def launch_no_browser(command,**kwargs):
        process=real_popen([sys.executable,'-c','import time; time.sleep(30)'],**kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(module.subprocess,'Popen',launch_no_browser)
    import threading
    result=module.run_worker({},threading.Event(),timeout=.05,stop_grace=.2)
    assert result['status']=='unknown'
    assert children[0].poll() is not None


def test_exited_worker_with_live_child_cannot_hold_pipes_forever(monkeypatch):
    module=importlib.import_module('browser_bridge')
    real_popen=module.subprocess.Popen
    children=[]
    def launch_no_browser(command,**kwargs):
        code="import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])"
        process=real_popen([sys.executable,'-c',code],**kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(module.subprocess,'Popen',launch_no_browser)
    import threading
    import os
    import signal
    result=[]
    thread=threading.Thread(target=lambda:result.append(module.run_worker({},threading.Event(),timeout=.05,stop_grace=.1)))
    thread.start()
    try:
        thread.join(1.5)
        assert not thread.is_alive(), 'driver pipe outlived the hard timeout'
        assert result[0]['status']=='unknown'
    finally:
        for process in children:
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
        thread.join(3)
