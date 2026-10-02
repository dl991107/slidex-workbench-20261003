import asyncio
import base64
import json
from pathlib import Path

import cv2
import numpy as np
from playwright.async_api import async_playwright
from slidex.vision import SliderImageSolver
from slidex._drag import build_drag_events, dispatch_drag_timeline

ROOT = Path(__file__).resolve().parents[1]
BROWSER = '<USER_HOME>/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell'

async def main():
    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, executable_path=BROWSER)
        try:
            page = await browser.new_page(viewport={'width': 700, 'height': 420})
            await page.route('**/*', lambda route: route.abort())
            for target in (100, 180, 230):
                bg = np.full((150, 300, 3), 235, dtype=np.uint8)
                bg[40:84, target:target+40] = 45
                ok, png = cv2.imencode('.png', bg)
                assert ok
                image = base64.b64encode(png).decode()
                await page.set_content('''<style>body{font-family:sans-serif}#scene{position:relative;width:300px;height:150px;margin:40px}#piece{position:absolute;left:0;top:40px;width:40px;height:44px;background:#4caf50}#track{margin:40px;width:300px;height:40px;background:#ddd;position:relative}#btn{width:40px;height:40px;background:#4caf50;position:absolute;cursor:grab}</style><h3>LOCAL SYNTHETIC PUZZLE TEST</h3><div id="scene"><img id="bg"><div id="piece"></div></div><div id="track"><div id="btn"></div></div><p id="status">Waiting</p>''')
                await page.evaluate('''({image,target})=>{
                  document.querySelector('#bg').src='data:image/png;base64,'+image;
                  let start, moves=0, left=0, pressed=false;
                  const btn=document.querySelector('#btn'),piece=document.querySelector('#piece');
                  btn.onmousedown=e=>{if(!e.isTrusted)return;start=e.clientX;pressed=true;e.preventDefault()};
                  document.onmousemove=e=>{if(!pressed)return;if(e.buttons!==1){pressed=false;return}moves++;left=Math.max(0,Math.min(260,e.clientX-start));btn.style.left=piece.style.left=left+'px'};
                  document.onmouseup=()=>{if(!pressed)return;pressed=false;window.result={left,moves,pass:Math.abs(left-target)<=3&&moves>=8};document.querySelector('#status').textContent=JSON.stringify(window.result)};
                }''', {'image':image, 'target':target})
                # Solver reads the browser-rendered image, rather than the target variable.
                screenshot = await page.locator('#bg').screenshot()
                found = SliderImageSolver(allow_yolo_backend=False).solve(screenshot)
                assert found.success, found.to_dict()
                box = await page.locator('#btn').bounding_box()
                sx, sy = box['x']+20, box['y']+20
                pts = [(sx,sy,450)] + [(sx+found.gap_x*i/12,sy,25) for i in range(1,13)]
                session = await page.context.new_cdp_session(page)
                await dispatch_drag_timeline(session, build_drag_events(sx,sy,pts,extra_overshoot=False))
                actual = await page.evaluate('window.result')
                results.append({'expected_x':target,'recognized_x':found.gap_x,'method':found.method,**actual})
                assert actual['pass'], results[-1]
                await session.detach()
            await page.screenshot(path=str(ROOT/'outputs/local-puzzle-result.png'))
        finally:
            await browser.close()
    (ROOT/'outputs/local-results.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))

asyncio.run(main())
