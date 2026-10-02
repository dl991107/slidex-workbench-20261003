"""Drive only in-memory synthetic pages; external page requests are blocked."""
import asyncio
import base64
import json
from offline_puzzle_check import OUT, fixture, png, measure
from playwright.async_api import async_playwright
from slidex.vision import SliderImageSolver
from slidex._drag import build_drag_events, dispatch_drag_timeline

BROWSER = '<USER_HOME>/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell'


async def main():
    rows = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, executable_path=BROWSER)
        try:
            page = await browser.new_page(viewport={'width':760,'height':540})
            page.set_default_timeout(5000)
            await page.route('**/*', lambda route: route.abort())
            solver = SliderImageSolver(allow_yolo_backend=False)
            for scale in (0.75,1.0,1.5):
                bg, piece, truth = fixture('distractor',4,scale)
                found = measure(solver,png(bg),png(piece))
                assert found['success']
                start = 8*scale
                await page.set_content('<style>body{font-family:sans-serif}#scene{position:relative;margin:25px}#piece{position:absolute;cursor:grab}#status{margin:25px}</style><h3>LOCAL GENERATED JIGSAW — OFFLINE</h3><div id="scene"><img id="bg"><img id="piece"></div><p id="status">Waiting</p>')
                await page.evaluate('''p=>{
                  const bg=document.querySelector('#bg'),piece=document.querySelector('#piece');
                  bg.src=p.bg;piece.src=p.piece;piece.style.left=p.start+'px';piece.style.top=p.top+'px';
                  let pressed=false,begin=0,left=p.start,moves=0;
                  piece.onmousedown=e=>{pressed=true;begin=e.clientX;moves=0;e.preventDefault()};
                  document.onmousemove=e=>{if(!pressed||e.buttons!==1)return;left=p.start+e.clientX-begin;piece.style.left=left+'px';moves++};
                  document.onmouseup=()=>{if(!pressed)return;pressed=false;window.result={left,moves,pass:Math.abs(left-p.target)<=p.tolerance};document.querySelector('#status').textContent=JSON.stringify(window.result)};
                }''',{'bg':'data:image/png;base64,'+base64.b64encode(png(bg)).decode(),
                      'piece':'data:image/png;base64,'+base64.b64encode(png(piece)).decode(),
                      'start':start,'top':truth['patch_y'],'target':truth['patch'],'tolerance':3*scale})
                await page.evaluate('Promise.all([...document.querySelectorAll("img")].map(img=>img.decode()))')
                box=await page.locator('#piece').bounding_box()
                sx,sy=box['x']+box['width']/2,box['y']+box['height']/2
                await page.mouse.move(sx,sy)
                await page.mouse.down()
                await page.mouse.move(sx+10,sy,steps=12)
                await page.mouse.up()
                assert (await page.evaluate('window.result'))['pass'] is False
                await page.locator('#piece').evaluate('(img,x)=>img.style.left=x+"px"',start)
                delta=found['gap_x']-start
                points=[(sx+delta*i/12,sy,25) for i in range(1,13)]
                cdp=await page.context.new_cdp_session(page)
                await asyncio.wait_for(dispatch_drag_timeline(cdp,build_drag_events(sx,sy,points,extra_overshoot=False)),10)
                actual=await page.evaluate('window.result')
                rows.append({'scale':scale,'initial_x':start,'expected_patch_x':truth['patch'],
                             'recognized_x':found['gap_x'],'method':found['method'],
                             'wrong_distance_rejected':True,**actual})
                await cdp.detach()
            await page.screenshot(path=str(OUT/'browser-result.png'))
        finally:
            await browser.close()
    (OUT/'browser-results.json').write_text(json.dumps(rows,indent=2))
    print(json.dumps(rows,indent=2))
    assert all(r['pass'] and r['moves']>=8 for r in rows)


asyncio.run(asyncio.wait_for(main(),30))
