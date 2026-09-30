"""Drive a real headless browser for real seconds, then screenshot and read the page.

Headless screenshots with --virtual-time-budget fast-forward the clock, so the game
finishes before jev can answer anything. This uses the devtools protocol instead: real
time passes, real requests go out.

    python pacman/tests/shot.py --seconds 25 --out shot.png
    python pacman/tests/shot.py --seconds 25 --width 900 --out narrow.png
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import aiohttp

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

REPORT_JS = """
(() => {
  const t = (id) => (document.getElementById(id) || {}).textContent;
  return JSON.stringify({
    score: t('score'), level: t('level-no'),
    decisions: t('stat-calls'), latency: t('stat-lat'),
    late: t('stat-late'), cost: t('stat-cost'),
    dirMeta: t('dir-meta'), danger: t('danger-label'),
    curtain: document.getElementById('curtain').hidden ? null : t('curtain-title'),
    gameSeconds: window.__game ? +(window.__game.tick / 60).toFixed(1) : null,
    lives: window.__game ? window.__game.lives : null,
    pelletsLeft: window.__game ? window.__game.pelletsLeft : null,
    errors: window.__errors || [],
  });
})()
"""


async def main(args):
    browser = EDGE if Path(EDGE).exists() else CHROME
    profile = tempfile.mkdtemp(prefix="pacshot-")
    proc = subprocess.Popen([
        browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        f"--remote-debugging-port={args.port}", f"--user-data-dir={profile}",
        f"--window-size={args.width},{args.height}", "--no-first-run",
        # Headless throttles rAF hard: without these the game clock runs at a tenth of
        # real time and a test game never gets anywhere.
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling",
        "--disable-frame-rate-limit",
        "--run-all-compositor-stages-before-draw",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        async with aiohttp.ClientSession() as http:
            port = await wait_for_port(profile)
            target = await wait_for_target(http, port)
            async with http.ws_connect(target, max_msg_size=0) as ws:
                cdp = Cdp(ws)
                await cdp.call("Page.enable")
                await cdp.call("Runtime.enable")
                await cdp.call("Log.enable")
                await cdp.call("Page.addScriptToEvaluateOnNewDocument", {
                    "source": "window.__errors=[];"
                              "addEventListener('error',e=>window.__errors.push(String(e.message)));"
                              "addEventListener('unhandledrejection',e=>window.__errors.push(String(e.reason)));",
                })
                try:
                    await cdp.call("Page.setWebLifecycleState", {"state": "active"})
                except RuntimeError:
                    pass
                await cdp.call("Page.navigate", {"url": args.url})
                await asyncio.sleep(args.seconds)
                if args.eval:
                    await cdp.call("Runtime.evaluate", {"expression": args.eval})
                    await asyncio.sleep(0.4)

                # On a page other than the game (the map, say) the report has nothing to read.
                result = (await cdp.call("Runtime.evaluate", {
                    "expression": REPORT_JS, "returnByValue": True,
                }))["result"]["result"]
                report = json.loads(result.get("value") or "{}")
                print(json.dumps(report, ensure_ascii=False, indent=2))
                for entry in cdp.console:
                    print(f"  console: {entry}")

                shot = await cdp.call("Page.captureScreenshot", {"format": "png"})
                Path(args.out).write_bytes(base64.b64decode(shot["result"]["data"]))
                print(f"saved {args.out}")
    finally:
        close_browser(proc)
        shutil.rmtree(profile, ignore_errors=True)


def close_browser(proc: subprocess.Popen) -> None:
    """Take the whole browser down, children included.

    Terminating only the process we launched leaves its renderers running, and a headless
    browser nobody is watching keeps the game going and the port taken. On Windows that
    means taskkill with /T; elsewhere terminate reaches the group.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


async def wait_for_port(profile: str) -> int:
    """The port this browser really took, read from its own profile.

    Asking for a fixed port and assuming we got it attaches us to whatever else is
    already listening there: a stale run of this same script leaves its browser behind,
    and then the screenshot comes from the wrong window. The browser writes the port it
    ended up with into DevToolsActivePort inside its user data directory, and that file
    is ours alone.
    """
    port_file = Path(profile) / "DevToolsActivePort"
    for _ in range(80):
        if port_file.exists():
            first = port_file.read_text(encoding="utf8").splitlines()
            if first and first[0].strip().isdigit():
                return int(first[0])
        await asyncio.sleep(0.25)
    raise RuntimeError("the browser never reported a debugging port")


async def wait_for_target(http: aiohttp.ClientSession, port: int) -> str:
    for _ in range(60):
        try:
            async with http.get(f"http://127.0.0.1:{port}/json/list") as r:
                targets = await r.json()
            for t in targets:
                if t.get("type") == "page":
                    return t["webSocketDebuggerUrl"]
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        await asyncio.sleep(0.25)
    raise RuntimeError("the browser never opened a debuggable page")


class Cdp:
    def __init__(self, ws):
        self.ws = ws
        self.id = 0
        self.console: list[str] = []

    async def call(self, method: str, params: dict | None = None) -> dict:
        self.id += 1
        await self.ws.send_json({"id": self.id, "method": method, "params": params or {}})
        while True:
            # Never wait for ever on an answer: a browser that has wandered off leaves this
            # script running, and with it the browser, which is how the port gets squatted.
            msg = json.loads(await asyncio.wait_for(self.ws.receive_str(), 60))
            if msg.get("method") in ("Log.entryAdded", "Runtime.consoleAPICalled"):
                self.note(msg)
            elif msg.get("id") == self.id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return {"result": msg.get("result", {})}

    def note(self, msg):
        p = msg.get("params", {})
        if "entry" in p:
            if p["entry"].get("level") in ("error", "warning"):
                self.console.append(f"{p['entry']['level']}: {p['entry'].get('text')}")
        else:
            args = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
            if p.get("type") in ("error", "warning"):
                self.console.append(f"{p['type']}: {args}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8770/")
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--out", default="shot.png")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--port", type=int, default=0, help="0 lets the browser pick a free one")
    ap.add_argument("--eval", default="", help="JavaScript to run just before the screenshot")
    asyncio.run(main(ap.parse_args()))
