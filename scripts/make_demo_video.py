"""Record a reproducible, captioned walkthrough of the local CONTRA app.

Requires Microsoft Edge or Chrome and ffmpeg. No browser automation package is used.
The recorder starts an isolated local server with model calls disabled.
"""

import base64
import json
import os
from pathlib import Path
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "demo"
WIDTH, HEIGHT, FPS = 1600, 820, 15
random.seed(41)


def executable():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError("ffmpeg is required") from exc


def browser_executable():
    paths = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ]
    found = next((path for path in paths if path.exists()), None)
    if not found:
        raise RuntimeError("Microsoft Edge or Chrome is required")
    return found


def wait_http(url, timeout=20):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.read()
        except Exception:
            time.sleep(.15)
    raise RuntimeError("Timed out waiting for " + url)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class CDP:
    def __init__(self, url):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        headers = bytearray()
        while b"\r\n\r\n" not in headers:
            headers.extend(self.sock.recv(4096))
        if b" 101 " not in headers.split(b"\r\n", 1)[0]:
            raise RuntimeError("WebSocket handshake failed")
        self.leftover = bytes(headers.split(b"\r\n\r\n", 1)[1])
        self.next_id = 1

    def read_exact(self, count):
        data = bytearray()
        if self.leftover:
            data.extend(self.leftover[:count])
            self.leftover = self.leftover[count:]
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise RuntimeError("Browser debugging connection ended")
            data.extend(chunk)
        return bytes(data)

    def receive(self):
        first, second = self.read_exact(2)
        length = second & 127
        if length == 126:
            length = int.from_bytes(self.read_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self.read_exact(8), "big")
        payload = self.read_exact(length)
        if first & 15 == 8:
            raise RuntimeError("Browser closed the debugging connection")
        return json.loads(payload)

    def command(self, method, params=None):
        command_id = self.next_id
        self.next_id += 1
        payload = json.dumps({"id": command_id, "method": method, "params": params or {}}).encode()
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend([0x80 | 126, *length.to_bytes(2, "big")])
        else:
            header.extend([0x80 | 127, *length.to_bytes(8, "big")])
        header.extend(mask)
        header.extend(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(header)
        while True:
            response = self.receive()
            if response.get("id") != command_id:
                continue
            if "error" in response:
                raise RuntimeError(f"{method}: {response['error']}")
            return response.get("result", {})

    def evaluate(self, expression):
        result = self.command("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        if "exceptionDetails" in result:
            raise RuntimeError("Browser JavaScript failed: " + expression[:150])
        return result.get("result", {}).get("value")

    def close(self):
        self.sock.close()


class Recorder:
    def __init__(self, cdp, ffmpeg):
        self.cdp = cdp
        self.frames = 0
        self.cursor = (1230.0, 740.0)
        self.captions = []
        self.video = OUTPUT / "CONTRA_hackathon_demo_source.mp4"
        self.encoder = subprocess.Popen([
            ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
            "-vcodec", "mjpeg", "-i", "pipe:0", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(self.video),
        ], stdin=subprocess.PIPE)

    @property
    def seconds(self):
        return self.frames / FPS

    def frame(self):
        result = self.cdp.command("Page.captureScreenshot", {
            "format": "jpeg", "quality": 82, "fromSurface": True,
            "captureBeyondViewport": False,
        })
        self.encoder.stdin.write(base64.b64decode(result["data"]))
        self.frames += 1

    def hold(self, seconds):
        for _ in range(max(1, round(seconds * FPS))):
            self.frame()

    def present(self, selector):
        return self.cdp.evaluate(f"!!document.querySelector({json.dumps(selector)})")

    def wait(self, selector, timeout=15):
        deadline = time.monotonic() + timeout
        while not self.present(selector):
            if time.monotonic() > deadline:
                raise RuntimeError("Element did not appear: " + selector)
            self.frame()
        self.hold(.5)

    def scroll(self, selector):
        expression = f"(() => {{ const e=document.querySelector({json.dumps(selector)}); if(!e)return false; e.scrollIntoView({{behavior:'smooth',block:'center'}}); return true; }})()"
        if not self.cdp.evaluate(expression):
            raise RuntimeError("Cannot scroll to " + selector)
        self.hold(1.15)

    def center(self, selector):
        expression = f"(() => {{ const e=document.querySelector({json.dumps(selector)}); if(!e)return null; const r=e.getBoundingClientRect(); return {{x:r.left+r.width/2,y:r.top+r.height/2}}; }})()"
        position = self.cdp.evaluate(expression)
        if not position:
            raise RuntimeError("Cannot locate " + selector)
        return position["x"], position["y"]

    def move(self, x, y, duration=1.0):
        x0, y0 = self.cursor
        bend = random.uniform(-45, 45)
        cx1, cy1 = x0 + (x - x0) * .3 + bend, y0 + (y - y0) * .17 - bend * .25
        cx2, cy2 = x0 + (x - x0) * .72 - bend * .3, y0 + (y - y0) * .82 + bend
        count = max(5, round(duration * FPS))
        for index in range(1, count + 1):
            fraction = index / count
            t = fraction * fraction * (3 - 2 * fraction)
            one = 1 - t
            px = one ** 3 * x0 + 3 * one ** 2 * t * cx1 + 3 * one * t ** 2 * cx2 + t ** 3 * x
            py = one ** 3 * y0 + 3 * one ** 2 * t * cy1 + 3 * one * t ** 2 * cy2 + t ** 3 * y
            self.cdp.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": px, "y": py})
            self.frame()
        self.cursor = (x, y)

    def click(self, selector, scroll=True):
        if scroll:
            self.scroll(selector)
        x, y = self.center(selector)
        self.move(x, y, random.uniform(.75, 1.25))
        self.hold(.35)
        self.cdp.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
        self.frame()
        self.cdp.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
        self.hold(.5)

    def type_text(self, value):
        for letter in value:
            self.cdp.command("Input.insertText", {"text": letter})
            self.frame()

    def scene(self, text, action, minimum=0):
        start = self.seconds
        action()
        if self.seconds - start < minimum:
            self.hold(minimum - (self.seconds - start))
        self.captions.append((start, self.seconds, text))
        print(f"{self.seconds:5.1f}s  {text}", flush=True)

    def close(self):
        self.encoder.stdin.close()
        if self.encoder.wait() != 0:
            raise RuntimeError("Video encoding failed")


def srt_time(value):
    milliseconds = round(value * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def finalize_video(ffmpeg):
    subtitles = OUTPUT / "CONTRA_hackathon_demo.srt"
    ass = OUTPUT / "CONTRA_hackathon_demo.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1600
PlayResY: 900
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,28,&H00FFFFFF,&H00FFFFFF,&H00111111,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,40,40,18,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for block in re.split(r"\n\s*\n", subtitles.read_text(encoding="utf-8").strip()):
        lines = block.splitlines()
        timing = lines[1].split(" --> ")
        def convert(value):
            hours, minutes, rest = value.split(":")
            seconds, milliseconds = rest.split(",")
            return f"{int(hours)}:{minutes}:{seconds}.{int(milliseconds) // 10:02}"
        events.append(
            f"Dialogue: 0,{convert(timing[0])},{convert(timing[1])},Default,,0,0,0,,"
            + r"\N".join(lines[2:])
        )
    ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    source = OUTPUT / "CONTRA_hackathon_demo_source.mp4"
    captioned = OUTPUT / "CONTRA_hackathon_demo.mp4"
    subprocess.run([
        ffmpeg, "-y", "-loglevel", "error", "-i", source.name,
        "-vf", "pad=1600:900:0:0:color=0x111111,ass=CONTRA_hackathon_demo.ass",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", captioned.name,
    ], cwd=OUTPUT, check=True)
    return captioned


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    ffmpeg = executable()
    port = free_port()
    environment = os.environ.copy()
    environment.update({
        "CONTRA_DB": str(OUTPUT / "recording.sqlite3"),
        "CONTRA_PORT": str(port), "CONTRA_LLM": "0", "CONTRA_EMBEDDINGS": "0",
        "CONTRA_PUBLIC": "0",
    })
    server = subprocess.Popen([sys.executable, "-m", "contra.server"], cwd=ROOT, env=environment,
                              stdout=(OUTPUT / "server.log").open("w"), stderr=subprocess.STDOUT)
    browser = None
    cdp = None
    recorder = None
    try:
        wait_http(f"http://127.0.0.1:{port}/health")
        with tempfile.TemporaryDirectory(prefix="contra-demo-browser-", ignore_cleanup_errors=True) as profile:
            debug_port = free_port()
            browser = subprocess.Popen([
                str(browser_executable()), "--headless=new", "--no-sandbox", "--disable-gpu",
                "--disable-extensions", "--disable-background-networking", "--disable-dev-shm-usage",
                "--no-first-run", "--no-default-browser-check", "--remote-allow-origins=*",
                f"--remote-debugging-port={debug_port}", f"--user-data-dir={profile}",
                f"--window-size={WIDTH},{HEIGHT}", "about:blank",
            ], stdout=subprocess.DEVNULL, stderr=(OUTPUT / "browser.log").open("w"))
            targets = json.loads(wait_http(f"http://127.0.0.1:{debug_port}/json"))
            target = next(item for item in targets if item["type"] == "page")
            cdp = CDP(target["webSocketDebuggerUrl"])
            cdp.command("Page.enable")
            cdp.command("Runtime.enable")
            cdp.command("Emulation.setDeviceMetricsOverride", {
                "width": WIDTH, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False,
            })
            cdp.command("Page.navigate", {"url": f"http://127.0.0.1:{port}/"})
            deadline = time.monotonic() + 15
            while not cdp.evaluate("!!document.querySelector('#guest')"):
                if time.monotonic() > deadline:
                    raise RuntimeError("Guest page did not load")
                time.sleep(.2)
            cdp.evaluate("""(() => {
              const style=document.createElement('style');
              style.textContent=`#demo-cursor{position:fixed;left:0;top:0;width:24px;height:29px;z-index:2147483647;pointer-events:none;transform:translate(1230px,740px);filter:drop-shadow(1px 2px 2px #0008)}#demo-cursor:before{content:'';position:absolute;inset:0;background:#141414;clip-path:polygon(0 0,0 25px,6px 19px,11px 28px,15px 26px,10px 17px,20px 17px)}#demo-cursor:after{content:'';position:absolute;inset:2px 4px 4px 2px;background:#fff;clip-path:polygon(0 0,0 20px,5px 15px,10px 23px,12px 22px,7px 13px,16px 13px)}#demo-title{position:fixed;inset:0;z-index:2147483646;background:linear-gradient(110deg,#0b0b0bee,#21120bee);display:flex;align-items:center;padding:0 11%;color:#fff;opacity:1;transition:opacity .7s ease;pointer-events:none}#demo-title.hidden{opacity:0}#demo-title h1{font:800 88px/1 'Segoe UI',sans-serif;letter-spacing:-5px;margin:0}#demo-title h1 span{color:#ff5a12}#demo-title p{font:400 24px/1.4 'Segoe UI',sans-serif;margin:23px 0 0;max-width:800px}#demo-title small{display:block;color:#ff935d;font:700 14px 'Segoe UI',sans-serif;letter-spacing:3px;margin-bottom:20px}`;
              document.head.appendChild(style);
              const cursor=document.createElement('div');cursor.id='demo-cursor';document.body.appendChild(cursor);
              document.addEventListener('mousemove',e=>{cursor.style.transform=`translate(${e.clientX}px,${e.clientY}px)`});
              const title=document.createElement('div');title.id='demo-title';title.innerHTML='<div><small>THE WORKING PRODUCT DEMO</small><h1>CONTRA<span>.</span></h1><p>When market signals and company filings disagree, what should one investor actually do?</p></div>';document.body.appendChild(title);
            })()""")
            recorder = Recorder(cdp, ffmpeg)
            recorder.scene("What happens when market signals and company filings disagree?", lambda: recorder.hold(5), 5)
            cdp.evaluate("document.querySelector('#demo-title').classList.add('hidden')")
            recorder.scene("CONTRA puts independent evidence and investor limits in one explainable view.",
                           lambda: recorder.click("#guest", scroll=False), 9)
            recorder.wait(".terminal-hero")
            recorder.scene("Three agents inspect a frozen snapshot. Every conclusion links back to its source.",
                           lambda: recorder.hold(9), 9)
            recorder.scene("Choose ALPHA.NS, a clearly labeled synthetic scenario with known outcomes.",
                           lambda: recorder.click('[data-scenario="ALPHA.NS"]'), 12)
            recorder.scene("The Conservative profile has a 10 percent single asset cap. Now run the analysis.",
                           lambda: (recorder.scroll("#investor"), recorder.hold(2), recorder.click("#run", scroll=False)), 12)
            recorder.wait(".recommendation")
            recorder.scene("Price momentum is positive. Filing evidence is negative. The result is conflicted.",
                           lambda: (recorder.scroll(".large-state"), recorder.hold(7)), 10)
            recorder.scene("CONTRA sizes the action from this investor's holdings and risk cap.",
                           lambda: (recorder.scroll(".recommendation"), recorder.hold(9)), 12)
            recorder.scene("Click a cited reason to inspect the exact frozen filing excerpt and its date.",
                           lambda: (recorder.click('.recommendation [data-evidence^="E-"]'), recorder.wait('.drawer[aria-hidden="false"]'), recorder.hold(5)), 12)
            recorder.scene("The report also records three concurrent agent intervals and their execution modes.",
                           lambda: (recorder.click('.drawer-close', scroll=False), recorder.scroll('.timeline'), recorder.hold(7)), 12)
            recorder.scene("Compare Growth using the same market snapshot and a different portfolio limit.",
                           lambda: recorder.click("#compare"), 12)
            recorder.wait(".recommendation")
            recorder.scene("The evidence stays fixed. The 30 percent cap changes the personal action.",
                           lambda: (recorder.scroll(".recommendation"), recorder.hold(8)), 12)
            recorder.scene("Ask the filings about operating margin. The answer is an exact stored passage.",
                           lambda: (recorder.click("#ask-input"), recorder.type_text("operating margin"), recorder.click("#ask-form .primary", scroll=False), recorder.wait("#ask-result .evidence-item"), recorder.hold(4)), 15)
            recorder.scene("When no excerpt supports a question, CONTRA abstains instead of guessing.",
                           lambda: (recorder.click("[data-question]"), recorder.hold(5)), 10)
            recorder.scene("Evaluation checks scenarios, citation integrity and measured execution.",
                           lambda: (recorder.click('[data-nav="/evaluation"]', scroll=False), recorder.wait('.metric-grid'), recorder.hold(7)), 12)
            recorder.scene("CONTRA is research software. It does not predict returns or execute trades.",
                           lambda: (recorder.scroll('.section-row'), recorder.hold(6)), 9)
            cdp.evaluate("document.querySelector('#demo-title').innerHTML='<div><small>EVIDENCE. CONTEXT. ACTION.</small><h1>CONTRA<span>.</span></h1><p>Explore the working product at contra-h0nw.onrender.com</p></div>';document.querySelector('#demo-title').classList.remove('hidden')")
            recorder.scene("Explore the working demo and inspect the public source code.", lambda: recorder.hold(5), 5)
            captions = list(recorder.captions)
            duration = recorder.seconds
            recorder.close()
            recorder = None
            cdp.close()
            cdp = None
            browser.terminate()
            try:
                browser.wait(timeout=5)
            except subprocess.TimeoutExpired:
                browser.kill()
            browser = None
        subtitles = OUTPUT / "CONTRA_hackathon_demo.srt"
        subtitles.write_text("\n\n".join(
            f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{textwrap.fill(text, width=47)}"
            for index, (start, end, text) in enumerate(captions, 1)
        ) + "\n", encoding="utf-8")
        captioned = finalize_video(ffmpeg)
        print(f"Done: {captioned} ({duration:.1f} seconds)", flush=True)
    finally:
        if recorder:
            try:
                recorder.encoder.stdin.close()
                recorder.encoder.terminate()
            except Exception:
                pass
        if cdp:
            cdp.close()
        if browser:
            browser.terminate()
        server.terminate()


if __name__ == "__main__":
    if "--finalize-only" in sys.argv:
        print(finalize_video(executable()))
    else:
        main()
