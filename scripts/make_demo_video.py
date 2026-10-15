"""Record a narrated, captioned walkthrough of the local CONTRA app.

Requires Microsoft Edge or Chrome, ffmpeg and an OPENAI_API_KEY for voice.
The recorder starts an isolated local server with model calls disabled.
"""

import base64
import hashlib
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
import urllib.error
import urllib.request
import wave


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "demo"
WIDTH, HEIGHT, FPS = 1600, 820, 15
VOICE_MODEL = "gpt-4o-mini-tts"
VOICE_NAME = "cedar"
VOICE_STYLE = ("Warm, clear, natural English narration for a thoughtful product demo. "
               "Sound like a real presenter explaining a product to judges, not an announcer. "
               "Vary emphasis gently and leave a small pause at commas and sentence ends.")
random.seed(73)


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
        self.hold(random.uniform(.62, .88))

    def center(self, selector):
        expression = f"(() => {{ const e=document.querySelector({json.dumps(selector)}); if(!e)return null; const r=e.getBoundingClientRect(); return {{x:r.left+r.width/2,y:r.top+r.height/2}}; }})()"
        position = self.cdp.evaluate(expression)
        if not position:
            raise RuntimeError("Cannot locate " + selector)
        return position["x"], position["y"]

    def move(self, x, y, duration=1.0):
        x0, y0 = self.cursor
        distance = ((x - x0) ** 2 + (y - y0) ** 2) ** .5
        bend = random.uniform(-.13, .13) * min(distance, 430)
        cx1, cy1 = x0 + (x - x0) * random.uniform(.18, .36) + bend, y0 + (y - y0) * .16 - bend * .35
        cx2, cy2 = x0 + (x - x0) * random.uniform(.68, .86) - bend * .3, y0 + (y - y0) * .86 + bend
        count = max(5, round(duration * FPS))
        ease = random.uniform(1.35, 2.45)
        for index in range(1, count + 1):
            fraction = index / count
            early = fraction ** ease
            late = (1 - fraction) ** ease
            t = early / (early + late) if early + late else fraction
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
        if random.random() < .3:
            self.move(x + random.uniform(-13, 13), y + random.uniform(-9, 9), random.uniform(.34, .62))
            self.hold(random.uniform(.07, .16))
        self.move(x, y, random.uniform(.4, .87))
        self.hold(random.uniform(.13, .33))
        self.cdp.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
        self.frame()
        self.cdp.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
        self.hold(random.uniform(.16, .37))

    def type_text(self, value):
        for letter in value:
            self.cdp.command("Input.insertText", {"text": letter})
            self.frame()
            if letter in " ," and random.random() < .35:
                self.frame()

    def replace_text(self, value):
        self.cdp.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65, "modifiers": 2})
        self.cdp.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65, "modifiers": 2})
        self.hold(.3)
        self.cdp.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Backspace", "windowsVirtualKeyCode": 8})
        self.cdp.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Backspace", "windowsVirtualKeyCode": 8})
        self.type_text(value)

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


def voice_key():
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("OPENAI_API_KEY is required for narration")


def voice_clip(index, words):
    payload = {"model": VOICE_MODEL, "voice": VOICE_NAME, "input": words,
               "instructions": VOICE_STYLE, "response_format": "wav", "speed": 1.06}
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
    output = OUTPUT / f"voice-{index:02d}-{identity}.wav"
    if output.exists():
        return output
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech", data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + voice_key(), "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                content = response.read()
            if not content.startswith(b"RIFF"):
                raise RuntimeError("Voice response was not a WAV file")
            output.write_bytes(content)
            return output
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503) or attempt == 2:
                raise RuntimeError(f"Voice API returned HTTP {exc.code}") from exc
            time.sleep(2 ** attempt)
    raise RuntimeError("Voice generation failed")


def speech_duration(path):
    with wave.open(str(path), "rb") as clip:
        # Streaming speech WAVs can leave a placeholder frame count in the header.
        actual_frames = len(clip.readframes(clip.getnframes())) / (clip.getnchannels() * clip.getsampwidth())
        return actual_frames / clip.getframerate()


def subtitle_scenes(path):
    scenes = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip()):
        lines = block.splitlines()
        def seconds(value):
            hours, minutes, rest = value.split(":")
            sec, millis = rest.split(",")
            return int(hours) * 3600 + int(minutes) * 60 + int(sec) + int(millis) / 1000
        start, end = (seconds(value) for value in lines[1].split(" --> "))
        scenes.append((start, end, " ".join(lines[2:])))
    return scenes


def tighten_video(ffmpeg):
    """Shorten quiet scene tails in both streams, then retime the external SRT."""
    original = OUTPUT / "CONTRA_hackathon_demo_uncut.mp4"
    original_srt = OUTPUT / "CONTRA_hackathon_demo_uncut.srt"
    destination = OUTPUT / "CONTRA_hackathon_demo.mp4"
    subtitles = OUTPUT / "CONTRA_hackathon_demo.srt"
    scenes = subtitle_scenes(original_srt)
    duration = scenes[-1][1]
    scan = subprocess.run([
        ffmpeg, "-hide_banner", "-i", str(original), "-vn", "-af",
        "silencedetect=noise=-38dB:d=1.1", "-f", "null", "-",
    ], capture_output=True, text=True, check=True).stderr
    starts = re.findall(r"silence_start:\s*([\d.]+)", scan)
    ends = re.findall(r"silence_end:\s*([\d.]+)", scan)
    cuts = []
    for raw_start, raw_end in zip(starts, ends):
        start, end = float(raw_start), float(raw_end)
        if end - start < 1.2:
            continue
        cut_start = round((start + .45) * FPS) / FPS
        cut_end = round((end - .65) * FPS) / FPS
        if cut_end - cut_start > .08:
            cuts.append((cut_start, cut_end))
    if not cuts:
        shutil.copy2(original, destination)
        shutil.copy2(original_srt, subtitles)
        return destination
    kept = []
    position = 0.0
    for start, end in cuts:
        kept.append((position, start))
        position = end
    kept.append((position, duration))
    filters = []
    for index, (start, end) in enumerate(kept):
        filters.append(f"[0:v]trim=start={start:.4f}:end={end:.4f},setpts=PTS-STARTPTS[v{index}]")
        filters.append(f"[0:a]atrim=start={start:.4f}:end={end:.4f},asetpts=PTS-STARTPTS[a{index}]")
    labels = "".join(f"[v{i}][a{i}]" for i in range(len(kept)))
    filters.append(f"{labels}concat=n={len(kept)}:v=1:a=1[v][a]")
    subprocess.run([
        ffmpeg, "-y", "-loglevel", "error", "-i", str(original),
        "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        str(destination),
    ], check=True)

    def retimed(value):
        removed = 0.0
        for start, end in cuts:
            if value >= end:
                removed += end - start
            elif value > start:
                return start - removed
        return value - removed

    subtitles.write_text("\n\n".join(
        f"{index}\n{srt_time(retimed(start))} --> {srt_time(retimed(end))}\n{textwrap.fill(words, width=80)}"
        for index, (start, end, words) in enumerate(scenes, 1)
    ) + "\n", encoding="utf-8")
    print(f"Removed {sum(end-start for start, end in cuts):.1f}s across {len(cuts)} long pauses", flush=True)
    return destination


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
    scenes = subtitle_scenes(subtitles)
    clips = [voice_clip(index, words) for index, (_, _, words) in enumerate(scenes, 1)]
    audio_filters = []
    for index, ((start, end, _), clip) in enumerate(zip(scenes, clips), 1):
        duration = speech_duration(clip)
        room = end - start - .42
        tempo = max(1.0, duration / room)
        if tempo > 1.22:
            raise RuntimeError(f"Narration scene {index} needs {duration:.1f}s but has only {room:.1f}s")
        delay = round((start + .18) * 1000)
        audio_filters.append(f"[{index}:a]atempo={tempo:.4f},adelay={delay}:all=1[a{index}]")
        print(f"Voice {index:02d}: {duration:.1f}s in a {end-start:.1f}s scene", flush=True)
    labels = "".join(f"[a{index}]" for index in range(1, len(clips) + 1))
    audio_filters.append(f"{labels}amix=inputs={len(clips)}:duration=longest:normalize=0,"
                         f"atrim=0:{scenes[-1][1]:.3f},loudnorm=I=-17:TP=-1.5:LRA=10[a]")
    subprocess.run([
        ffmpeg, "-y", "-loglevel", "error", "-i", source.name,
        *(part for clip in clips for part in ("-i", clip.name)),
        "-filter_complex", ";".join(audio_filters), "-map", "0:v", "-map", "[a]",
        "-vf", "pad=1600:900:0:0:color=0x111111,ass=CONTRA_hackathon_demo.ass",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart", captioned.name,
    ], cwd=OUTPUT, check=True)
    shutil.copy2(captioned, OUTPUT / "CONTRA_hackathon_demo_uncut.mp4")
    shutil.copy2(subtitles, OUTPUT / "CONTRA_hackathon_demo_uncut.srt")
    tighten_video(ffmpeg)
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
            recorder.scene("What happens when market signals and company filings disagree?", lambda: recorder.hold(5.5), 5.5)
            cdp.evaluate("document.querySelector('#demo-title').classList.add('hidden')")
            recorder.scene("CONTRA puts independent evidence and investor limits in one explainable view.",
                           lambda: recorder.click("#guest", scroll=False), 7.5)
            recorder.wait(".terminal-hero")
            recorder.scene("Three agents inspect a frozen snapshot. Every conclusion links back to its source.",
                           lambda: recorder.hold(6.5), 6.5)
            recorder.scene("Choose ALPHA.NS, a clearly labeled synthetic scenario with known outcomes.",
                           lambda: recorder.click('[data-scenario="ALPHA.NS"]'), 9.5)
            recorder.scene("The Conservative profile has a 10 percent single asset cap. Now run the analysis.",
                           lambda: (recorder.scroll("#investor"), recorder.hold(.8), recorder.click("#run", scroll=False)), 10)
            recorder.wait(".recommendation")
            recorder.scene("Price momentum is positive. Filing evidence is negative. The result is conflicted.",
                           lambda: (recorder.scroll(".large-state"), recorder.hold(5.5)), 8)
            recorder.scene("CONTRA sizes the action from this investor's holdings and risk cap.",
                           lambda: (recorder.scroll(".recommendation"), recorder.hold(6)), 8.5)
            recorder.scene("Click a cited reason to inspect the exact frozen filing excerpt and its date.",
                           lambda: (recorder.click('.recommendation [data-evidence^="E-"]'), recorder.wait('.drawer[aria-hidden="false"]'), recorder.hold(3.5)), 9)
            recorder.scene("The report also records three concurrent agent intervals and their execution modes.",
                           lambda: (recorder.click('.drawer-close', scroll=False), recorder.scroll('.timeline'), recorder.hold(4.5)), 9)
            recorder.scene("The fourth dimension separates foreign and domestic flows. These figures are synthetic market context.",
                           lambda: (recorder.scroll('.flow-card'), recorder.hold(4)), 7)
            recorder.scene("Now compare all three investors using the exact same market snapshot.",
                           lambda: (recorder.click("#all-investors"), recorder.wait(".investors-table"), recorder.scroll(".investors-table")), 10)
            recorder.scene("Conservative trims, Growth holds, and Starter stays out. The evidence is unchanged.",
                           lambda: recorder.hold(7), 9)
            recorder.scene("Ask the filings about operating margin. The answer is an exact stored passage.",
                           lambda: (recorder.click("#ask-input"), recorder.type_text("operating margin"), recorder.click("#ask-form .primary", scroll=False), recorder.wait("#ask-result .evidence-item"), recorder.hold(3)), 12.5)
            recorder.scene("When no excerpt supports a question, CONTRA abstains instead of guessing.",
                           lambda: (recorder.click("#ask-input"), recorder.replace_text("weather forecast"), recorder.click("#ask-form .primary", scroll=False), recorder.hold(2.5)), 10)
            recorder.scene("Evaluation checks scenarios, citation integrity and measured execution.",
                           lambda: (recorder.click('[data-nav="/evaluation"]', scroll=False), recorder.wait('.metric-grid'), recorder.hold(5)), 9.5)
            recorder.scene("CONTRA is research software. It does not predict returns or execute trades.",
                           lambda: (recorder.scroll('#degraded-checks'), recorder.hold(3.5)), 6)
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
            f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{textwrap.fill(text, width=80)}"
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
    if "--tighten-only" in sys.argv:
        print(tighten_video(executable()))
    elif "--finalize-only" in sys.argv:
        original_srt = OUTPUT / "CONTRA_hackathon_demo_uncut.srt"
        if original_srt.exists():
            shutil.copy2(original_srt, OUTPUT / "CONTRA_hackathon_demo.srt")
        print(finalize_video(executable()))
    else:
        main()
