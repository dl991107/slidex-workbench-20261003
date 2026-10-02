"""One user-requested attempt. Attach to an exact existing target, then disconnect."""
import asyncio
import json
import math
import signal
import sys

from loguru import logger
logger.remove()
from playwright.async_api import async_playwright
from slidex.providers import ProviderRegistry
from slidex._trajectory import generate_trajectory


async def solve_page(page,expected_url,result_timeout=6):
    if page.url!=expected_url:
        return {'status':'unknown'}
    provider = await ProviderRegistry.auto_detect(page)
    if provider is None:
        return {'status':'unsupported'}
    tasks,result = set(),asyncio.get_running_loop().create_future()
    requests = set()
    scope = None
    dragged = False
    main_task = asyncio.current_task()

    async def inspect(response):
        try:
            answer = await asyncio.wait_for(provider.validate_response(response),2)
            if answer is not None and not result.done():
                result.set_result(bool(answer))
        except (Exception,asyncio.CancelledError):
            pass

    def received(response):
        if response.request not in requests:
            return
        task = asyncio.create_task(inspect(response))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def requested(request):
        try:
            if request.frame==scope and len(requests)<128:
                requests.add(request)
        except Exception:
            pass

    def changed(*_):
        if page.url!=expected_url:
            main_task.cancel()

    try:
        elements = await provider.locate_elements(page)
        button,track = await elements.slider_btn.bounding_box(),await elements.slider_track.bounding_box()
        if not button or not track:
            return {'status':'unsupported','provider':provider.name}
        max_travel = track['width']-button['width']
        if (elements.metadata or {}).get('slider_type')=='scale':
            distance = max_travel
        else:
            background,piece = await provider.extract_images(page,elements)
            if not background or not piece or max(len(background),len(piece))>8*1024*1024:
                return {'status':'unsupported','provider':provider.name}
            from server import decode_image
            import base64
            decode_image(base64.b64encode(background).decode())
            decode_image(base64.b64encode(piece).decode())
            distance,confidence = await provider.find_gap(background,piece)
            if distance is None or not math.isfinite(confidence) or confidence<.5:
                return {'status':'unsupported','provider':provider.name}
        if not math.isfinite(distance) or not 0<distance<=max_travel+2 or page.url!=expected_url:
            return {'status':'unsupported','provider':provider.name}
        scope = await elements.slider_btn.owner_frame()
        if scope is None:
            return {'status':'unsupported','provider':provider.name}
        page.on('request',requested)
        page.on('response',received)
        page.on('framenavigated',changed)
        dragged = True
        await provider.perform_slide(page,elements,int(distance),generate_trajectory(distance),extra_overshoot=False)
        try:
            answer = await asyncio.wait_for(result,result_timeout)
            return {'status':'passed' if answer else 'failed','provider':provider.name}
        except asyncio.TimeoutError:
            return {'status':'unknown','provider':provider.name}
    finally:
        if dragged:
            try:
                await asyncio.wait_for(page.mouse.up(),2)
            except Exception:
                pass
        page.remove_listener('response',received)
        page.remove_listener('request',requested)
        page.remove_listener('framenavigated',changed)
        await provider.cleanup_after_result(page)
        for task in list(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks,return_exceptions=True)


async def main(record):
    task = asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,task.cancel)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(record['websocket'],timeout=8000)
        # stop() of this Playwright client disconnects; never call browser/context/page.close().
        for context in browser.contexts:
            for page in context.pages:
                session = await context.new_cdp_session(page)
                try:
                    info = await session.send('Target.getTargetInfo')
                finally:
                    await session.detach()
                if info['targetInfo']['targetId']==record['id']:
                    return await solve_page(page,record['url'])
        return {'status':'unknown'}


if __name__=='__main__':
    try:
        record = json.loads(sys.stdin.read(32769))
        result = asyncio.run(main(record))
    except asyncio.CancelledError:
        result = {'status':'cancelled'}
    except Exception:
        result = {'status':'unknown'}
    print(json.dumps(result,allow_nan=False))
