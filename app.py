# -*- coding: utf-8 -*-
"""
MultiSpan - mixed-resolution multi-monitor wallpaper splitter
Local app: stdlib HTTP server + Pillow + ffmpeg (imageio-ffmpeg binary).
UI opens in a browser window (pywebview wrapper planned for exe packaging).
"""
import ctypes, json, math, os, re, subprocess, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "out")
UP_DIR = os.path.join(BASE, "uploads")
CONFIG_PATH = os.path.join(BASE, "config.json")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(UP_DIR, exist_ok=True)

# ---------------------------------------------------------------- version / update check
APP_VERSION = "1.0.1"
 # 仓库地址——更新检查与跳转下载
UPDATE_API = "https://api.github.com/repos/unable616-hub/MultiSpan/releases/latest"
RELEASE_PAGE = "https://github.com/unable616-hub/MultiSpan/releases/latest"
UPDATE_READY = bool(re.match(r"https://api\.github\.com/repos/[^/\s]+/", UPDATE_API))


def _ver_tuple(v):
    """'v1.2.3' -> (1, 2, 3)；解析失败返回 (0,)。"""
    try:
        v = str(v).lower().lstrip("v").strip()
        parts = []
        for p in re.split(r"[.\-+_]", v):
            m = re.match(r"\d+", p)
            parts.append(int(m.group()) if m else 0)
        return tuple(parts) if parts else (0,)
    except Exception:
        return (0,)


def check_update():
    """查询 GitHub Releases 最新版本。任何失败都静默降级，不弹错。"""
    import urllib.request
    try:
        req = urllib.request.Request(
            UPDATE_API,
            headers={"User-Agent": "MultiSpan/" + APP_VERSION,
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8"))
        latest = str(data.get("tag_name", "")).strip()
        url = data.get("html_url") or RELEASE_PAGE
        has = bool(latest) and _ver_tuple(latest) > _ver_tuple(APP_VERSION)
        return {"ok": True, "current": APP_VERSION, "latest": latest,
                "has_update": has, "url": url}
    except Exception as e:
        return {"ok": False, "current": APP_VERSION, "latest": "",
                "has_update": False, "url": RELEASE_PAGE, "error": str(e)[:200]}

# ---------------------------------------------------------------- config profiles
def load_config():
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"profiles": [], "last_used": None}

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------- monitor detection
def make_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

class _POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class _DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", ctypes.c_ushort),
        ("dmDriverVersion", ctypes.c_ushort), ("dmSize", ctypes.c_ushort),
        ("dmDriverExtra", ctypes.c_ushort), ("dmFields", ctypes.c_ulong),
        ("dmPosition", _POINTL), ("dmDisplayOrientation", ctypes.c_ulong),
        ("dmDisplayFixedOutput", ctypes.c_ulong),
        ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", ctypes.c_ushort), ("dmBitsPerPel", ctypes.c_ulong),
        ("dmPelsWidth", ctypes.c_ulong), ("dmPelsHeight", ctypes.c_ulong),
        ("dmDisplayFlags", ctypes.c_ulong), ("dmDisplayFrequency", ctypes.c_ulong),
        ("dmICMMethod", ctypes.c_ulong), ("dmICMIntent", ctypes.c_ulong),
        ("dmMediaType", ctypes.c_ulong), ("dmDitherType", ctypes.c_ulong),
        ("dmReserved1", ctypes.c_ulong), ("dmReserved2", ctypes.c_ulong),
        ("dmPanningWidth", ctypes.c_ulong), ("dmPanningHeight", ctypes.c_ulong)]

class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong),
                ("szDevice", ctypes.c_wchar * 32)]

class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("DeviceName", ctypes.c_wchar * 32),
                ("DeviceString", ctypes.c_wchar * 128), ("StateFlags", ctypes.c_ulong),
                ("DeviceID", ctypes.c_wchar * 128), ("DeviceKey", ctypes.c_wchar * 128)]


def _edid_diag_inch(device_id):
    """Read physical diagonal from EDID (registry). device_id like DISPLAY\\GSM76E4\\5&..."""
    import winreg
    if not device_id or device_id.count("\\") < 1:
        return None
    prod = device_id.split("\\")[1]
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                              rf"SYSTEM\CurrentControlSet\Enum\DISPLAY\{prod}")
    except OSError:
        return None
    with root:
        i = 0
        while True:
            try:
                inst = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, inst + r"\Device Parameters") as dp:
                    edid, rtype = winreg.QueryValueEx(dp, "EDID")
                    if rtype == winreg.REG_BINARY and len(edid) >= 23:
                        hw, vh = edid[21], edid[22]   # max image size, cm
                        if hw and vh:
                            return math.hypot(hw, vh) / 2.54
            except OSError:
                continue
    return None


def detect_monitors():
    make_dpi_aware()
    user32 = ctypes.windll.user32
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(_RECT), ctypes.c_ssize_t)
    res = []
    def cb(hmon, hdc, rect, lparam):
        mi = _MONITORINFOEXW(); mi.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            dm = _DEVMODEW(); dm.dmSize = ctypes.sizeof(_DEVMODEW)
            user32.EnumDisplaySettingsW(mi.szDevice, -1, ctypes.byref(dm))
            md = _DISPLAY_DEVICEW(); md.cb = ctypes.sizeof(md)
            user32.EnumDisplayDevicesW(mi.szDevice, 0, ctypes.byref(md), 0)
            w = mi.rcMonitor.right - mi.rcMonitor.left
            h = mi.rcMonitor.bottom - mi.rcMonitor.top
            diag = _edid_diag_inch(md.DeviceID)
            res.append({"device": mi.szDevice, "x": mi.rcMonitor.left, "y": mi.rcMonitor.top,
                        "width": w, "height": h, "refresh": dm.dmDisplayFrequency,
                        "primary": bool(mi.dwFlags & 1),
                        "diag_edid": round(diag, 1) if diag else None})
        return 1
    CB = MONITORENUMPROC(cb)
    user32.EnumDisplayMonitors(None, None, CB, 0)
    res.sort(key=lambda m: (m["x"], m["y"]))
    for i, m in enumerate(res):
        m["index"] = i + 1
    return res

# ---------------------------------------------------------------- geometry math
def phys_size_cm(width_px, height_px, diag_inch):
    d = math.hypot(width_px, height_px)
    factor = diag_inch * 2.54 / d
    return width_px * factor, height_px * factor

def ppi_of(width_px, height_px, diag_inch):
    pw, _ = phys_size_cm(width_px, height_px, diag_inch)
    return width_px / (pw / 2.54)

def build_layout(monitors_cfg):
    """
    monitors_cfg: [{width,height,diag,x,y,shift_cm}] sorted left->right.
    Infers vertical placement from Windows virtual-desktop y positions:
      - same top y    -> top aligned
      - same bottom y -> bottom aligned
      - otherwise     -> proportional offset (fine-tune via shift_cm)
    """
    ref = monitors_cfg[0]
    ref_bottom = ref["y"] + ref["height"]
    canvas_h = max(phys_size_cm(m["width"], m["height"], m["diag"])[1] for m in monitors_cfg)
    x_cursor = 0.0
    plan = []
    for m in monitors_cfg:
        pw, ph = phys_size_cm(m["width"], m["height"], m["diag"])
        if m["y"] == ref["y"]:
            cy = 0.0                      # top aligned
        elif m["y"] + m["height"] == ref_bottom:
            cy = canvas_h - ph            # bottom aligned
        else:
            dpi = ppi_of(m["width"], m["height"], m["diag"])
            cy = max(0.0, min((m["y"] - ref["y"]) / dpi * 2.54, canvas_h - ph))
        cy += m.get("shift_cm", 0.0)
        cy = max(0.0, min(cy, canvas_h - ph))
        plan.append({"width": m["width"], "height": m["height"],
                     "cx": x_cursor, "cy": cy, "pw": pw, "ph": ph})
        x_cursor += pw
    return {"canvas_w_cm": x_cursor, "canvas_h_cm": canvas_h, "monitors": plan}

def screen_labels(monitors_cfg):
    """Position-aware names: 左屏/右屏 (row), 上屏/下屏 (stack), 左上屏 (mixed)."""
    def rank_words(n, two, three, prefix):
        if n == 2: return two
        if n == 3: return three
        return [f"{prefix}{i+1}" for i in range(n)]
    xs = sorted(set(m["x"] for m in monitors_cfg))
    cys = sorted(set(m["y"] + m["height"] / 2 for m in monitors_cfg))
    hw = rank_words(len(xs), ["左", "右"], ["左", "中", "右"], "横")
    vw = rank_words(len(cys), ["上", "下"], ["上", "中", "下"], "纵")
    labels = []
    for m in monitors_cfg:
        if len(xs) == 1:                      # vertical stack
            name = vw[cys.index(m["y"] + m["height"] / 2)] + "屏"
        elif len({m2["y"] for m2 in monitors_cfg}) == 1 or len(cys) == len(monitors_cfg):
            name = hw[xs.index(m["x"])] + "屏"   # horizontal row (top- or bottom-aligned)
        else:                                  # mixed: e.g. two stacked + one beside
            name = hw[xs.index(m["x"])] + vw[cys.index(m["y"] + m["height"] / 2)] + "屏"
        labels.append(name)
    return labels


def source_rects(plan, src_w, src_h, mode="cover"):
    cw, ch = plan["canvas_w_cm"], plan["canvas_h_cm"]
    d = max(src_w / cw, src_h / ch) if mode == "cover" else min(src_w / cw, src_h / ch)
    map_w, map_h = cw * d, ch * d
    off_x, off_y = (src_w - map_w) / 2.0, (src_h - map_h) / 2.0
    rects = []
    for m in plan["monitors"]:
        x0 = max(0.0, min(off_x + m["cx"] * d, src_w - 1))
        y0 = max(0.0, min(off_y + m["cy"] * d, src_h - 1))
        x1 = max(x0 + 1, min(off_x + (m["cx"] + m["pw"]) * d, src_w))
        y1 = max(y0 + 1, min(off_y + (m["cy"] + m["ph"]) * d, src_h))
        rects.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                      "out_w": m["width"], "out_h": m["height"]})
    return rects, d

# ---------------------------------------------------------------- media processing
def get_ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def probe_media(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        from PIL import Image
        with Image.open(path) as im:
            return "image", im.width, im.height, {"duration": None}
    ff = get_ffmpeg()
    r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace")
    txt = r.stderr
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", txt)
    if not m:
        raise RuntimeError("无法解析媒体尺寸: " + txt[-500:])
    w, h = int(m.group(1)), int(m.group(2))
    kind = "gif" if ext == ".gif" else "video"
    dur = None
    md = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", txt)
    if md:
        dur = int(md.group(1)) * 3600 + int(md.group(2)) * 60 + float(md.group(3))
    return kind, w, h, {"duration": dur}

def crop_scale_filter(r):
    return (f"crop={math.floor(r['w']/2)*2}:{math.floor(r['h']/2)*2}:{round(r['x'])}:{round(r['y'])},"
            f"scale={r['out_w']}:{r['out_h']}:flags=lanczos,setsar=1")

def process_media(src, rects, tag, want_dynamic, want_static, log, out_dir=None, labels=None):
    """Returns list of {path,url,label,kind}. Static-image input -> png only."""
    kind, sw, sh, extra = probe_media(src)
    ff = get_ffmpeg()
    out_dir = out_dir or OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    labels = labels or [f"screen{i+1}" for i in range(len(rects))]
    outputs = []
    for i, r in enumerate(rects):
        pos = labels[i] if i < len(labels) else f"screen{i+1}"
        label = f"{pos}（{r['out_w']}×{r['out_h']}）"
        if kind == "image":
            from PIL import Image
            out = os.path.join(out_dir, f"{tag}-{pos}.png")
            with Image.open(src) as im:
                box = (round(r["x"]), round(r["y"]), round(r["x"] + r["w"]), round(r["y"] + r["h"]))
                crop = im.crop(box).resize((r["out_w"], r["out_h"]), Image.LANCZOS)
                crop.save(out, optimize=True)
            outputs.append({"path": out, "url": "/out/" + os.path.basename(out),
                            "label": label, "kind": "static"})
            continue
        # animated source (gif / video)
        if want_dynamic:
            out = os.path.join(out_dir, f"{tag}-{pos}.mp4")
            cmd = [ff, "-y", "-v", "error", "-i", src, "-vf", crop_scale_filter(r),
                   "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", out]
            log(f"dynamic screen{i+1}: {r['w']:.0f}x{r['h']:.0f}@({r['x']:.0f},{r['y']:.0f}) -> {r['out_w']}x{r['out_h']}")
            p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            if p.returncode != 0:
                raise RuntimeError(f"ffmpeg 动态处理 screen{i+1} 失败: {p.stderr[-600:]}")
            outputs.append({"path": out, "url": "/out/" + os.path.basename(out),
                            "label": label, "kind": "dynamic"})
        if want_static:
            dur = extra.get("duration") or 0
            ss = dur * 0.5 if dur else 0
            out = os.path.join(out_dir, f"{tag}-{pos}-static.png")
            cmd = [ff, "-y", "-v", "error", "-ss", f"{ss:.2f}", "-i", src,
                   "-frames:v", "1", "-vf", crop_scale_filter(r), out]
            p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            if p.returncode != 0:
                raise RuntimeError(f"ffmpeg 静帧处理 screen{i+1} 失败: {p.stderr[-600:]}")
            outputs.append({"path": out, "url": "/out/" + os.path.basename(out),
                            "label": label, "kind": "static"})
    return outputs

# ---------------------------------------------------------------- import / record
WE_EXTS_VIDEO = (".mp4", ".webm", ".mov", ".avi", ".mkv")
WE_EXTS_IMAGE = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

def import_we_folder(folder):
    """Read Wallpaper Engine project.json, resolve the entry file. Returns dict."""
    pj = os.path.join(folder, "project.json")
    if not os.path.isfile(pj):
        raise ValueError("文件夹里没有 project.json —— 请拖 WE 创意工坊壁纸的整个文件夹（如 workshop\\content\\431960\\<id>）")
    with open(pj, "r", encoding="utf-8", errors="replace") as f:
        proj = json.load(f)
    entry = proj.get("file", "")
    if not entry:
        raise ValueError("project.json 里没有 file 字段，无法识别本体文件")
    full = os.path.join(folder, entry)
    if not os.path.isfile(full):
        raise ValueError(f"本体文件不存在: {entry}")
    ext = os.path.splitext(entry)[1].lower()
    if ext in WE_EXTS_VIDEO:
        kind = "video"
    elif ext == ".gif":
        kind = "gif"
    elif ext in WE_EXTS_IMAGE:
        kind = "image"
    elif ext == ".pkg":
        kind = "pkg"
    elif ext == ".html":
        kind = "web"
    else:
        kind = "unknown"
    return {"kind": kind, "entry": entry, "path": full, "title": proj.get("title", "")}

def record_screen(monitor, seconds, out_path, log):
    """Record a monitor's region with ffmpeg gdigrab. monitor: dict with x,y,width,height."""
    make_dpi_aware()
    ff = get_ffmpeg()
    cmd = [ff, "-y", "-v", "error",
           "-f", "gdigrab", "-framerate", "30",
           "-offset_x", str(monitor["x"]), "-offset_y", str(monitor["y"]),
           "-video_size", f"{monitor['width']}x{monitor['height']}",
           "-i", "desktop", "-t", str(seconds),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", out_path]
    log(f"recording {monitor['width']}x{monitor['height']}@({monitor['x']},{monitor['y']}) for {seconds}s")
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"录屏失败: {p.stderr[-600:]}")
    return out_path

# ---------------------------------------------------------------- HTTP server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[http]", fmt % args)

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(BASE, "web", "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif path == "/api/monitors":
            self._send(200, {"monitors": detect_monitors()})
        elif path == "/api/config":
            self._send(200, load_config())
        elif path == "/api/version":
            self._send(200, {"version": APP_VERSION,
                             "update_ready": UPDATE_READY})
        elif path == "/api/check_update":
            self._send(200, check_update())
        elif path.startswith("/out/"):
            name = os.path.basename(unquote(path))
            fp = os.path.join(OUT_DIR, name)
            if not os.path.isfile(fp):
                self._send(404, {"error": "not found"}); return
            ext = os.path.splitext(name)[1].lower()
            ctype = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif",
                     ".mp4": "video/mp4", ".webm": "video/webm"}.get(ext, "application/octet-stream")
            with open(fp, "rb") as f:
                self._send(200, f.read(), ctype)
        else:
            self._send(404, {"error": "not found"})

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/config":
            try:
                body = self._read_json_body()
                cfg = load_config()
                action = body.get("action")
                if action == "save":
                    prof = body.get("profile", {})
                    if not prof.get("name"):
                        raise ValueError("配置需要名称")
                    prof["id"] = uuid.uuid4().hex[:8]
                    prof["saved_at"] = time.strftime("%Y-%m-%d %H:%M")
                    cfg["profiles"].append(prof)
                    cfg["last_used"] = prof["id"]
                    save_config(cfg)
                    self._send(200, {"ok": True, "id": prof["id"]})
                elif action == "set_last":
                    cfg["last_used"] = body.get("id")
                    save_config(cfg)
                    self._send(200, {"ok": True})
                elif action == "delete":
                    pid = body.get("id")
                    cfg["profiles"] = [p for p in cfg["profiles"] if p.get("id") != pid]
                    if cfg.get("last_used") == pid:
                        cfg["last_used"] = None
                    save_config(cfg)
                    self._send(200, {"ok": True})
                else:
                    raise ValueError("未知操作")
            except Exception as e:
                self._send(500, {"ok": False, "error": str(e)})
            return
        if path == "/api/open":
            try:
                body = self._read_json_body()
                target = body.get("path", "")
                if target.startswith(("http://", "https://")):
                    os.startfile(target)          # 打开浏览器（更新下载页等）
                    self._send(200, {"ok": True})
                    return
                if not os.path.isdir(target) and not os.path.isfile(target):
                    raise ValueError("路径不存在")
                os.startfile(target)
                self._send(200, {"ok": True})
            except Exception as e:
                self._send(500, {"ok": False, "error": str(e)})
            return
        if path == "/api/import":
            try:
                body = self._read_json_body()
                folder = body.get("path", "").strip().strip('"')
                if not folder:
                    raise ValueError("请填写壁纸文件夹路径")
                info = import_we_folder(folder)
                self._send(200, {"ok": True, **info})
            except Exception as e:
                self._send(500, {"ok": False, "error": str(e)})
            return
        if path == "/api/record_process":
            try:
                cfg = self._read_json_body()
                seconds = max(2, min(int(cfg.get("seconds", 10)), 60))
                mon_idx = int(cfg.get("monitor", 1)) - 1
                all_mons = detect_monitors()
                if mon_idx < 0 or mon_idx >= len(all_mons):
                    raise ValueError("显示器编号无效")
                rec_path = os.path.join(UP_DIR, f"rec-{time.strftime('%H%M%S')}.mp4")
                record_screen(all_mons[mon_idx], seconds, rec_path, lambda m: print("[record]", m))
                self._process_common(cfg, rec_path)
            except Exception as e:
                self._send(500, {"ok": False, "error": str(e)})
            return
        if path != "/api/process":
            self._send(404, {"error": "not found"}); return
        try:
            q = parse_qs(urlparse(self.path).query)
            filename = os.path.basename(q.get("filename", ["upload"])[0])
            ctype = self.headers.get("Content-Type", "")
            src_path = None
            if "application/json" in ctype:
                # JSON 模式：配置和 src_path 都在 body 里
                cfg = self._read_json_body()
                src_path = cfg.get("src_path")
            else:
                cfg = json.loads(self.headers.get("X-Config", "{}"))
            length = int(self.headers.get("Content-Length", "0"))
            if src_path and os.path.isfile(src_path):
                src = src_path          # 本地文件直接引用，免上传
            else:
                if length <= 0:
                    raise ValueError("空文件")
                src = os.path.join(UP_DIR, f"{uuid.uuid4().hex[:8]}-{filename}")
                with open(src, "wb") as f:
                    remaining = length
                    while remaining > 0:
                        chunk = self.rfile.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        f.write(chunk); remaining -= len(chunk)
            self._process_common(cfg, src)
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

    def _process_common(self, cfg, src):
        try:
            monitors = cfg["monitors"]          # [{width,height,diag,x,y,shift_cm}]
            mode = cfg.get("mode", "cover")
            want_dynamic = bool(cfg.get("dynamic", True))
            want_static = bool(cfg.get("static", False))
            plan = build_layout(monitors)
            kind, sw, sh, extra = probe_media(src)
            if kind == "image":
                want_dynamic = False            # 静态图只能出静态
            if not (want_dynamic or want_static):
                raise ValueError("请至少选择一种输出格式")
            rects, density = source_rects(plan, sw, sh, mode)
            # 产出目录：用户指定 > 原文件旁 multispan-output（本地直读时） > 默认 out
            out_dir = cfg.get("out_dir")
            if not out_dir and cfg.get("src_path"):
                out_dir = os.path.join(os.path.dirname(os.path.abspath(src)), "multispan-output")
            def log(msg): print("[process]", msg)
            outputs = process_media(src, rects, f"multispan-{time.strftime('%H%M%S')}",
                                    want_dynamic, want_static, log, out_dir,
                                    labels=screen_labels(monitors))
            final_dir = os.path.dirname(outputs[0]["path"]) if outputs else OUT_DIR
            self._send(200, {"ok": True, "kind": kind, "src": {"w": sw, "h": sh},
                             "density_px_per_cm": round(density, 2), "out_dir": final_dir,
                             "outputs": outputs})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

def main():
    make_dpi_aware()        # 录屏坐标需要物理像素
    port = 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"MultiSpan running at {url}  (Ctrl+C to stop)")
    import threading, webbrowser
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
