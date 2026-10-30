"""MultiSpan 桌面壳：pywebview 原生窗口 + 本地服务。
用户感知不到浏览器——双击 exe 弹出独立窗口。"""
import os
import sys
import threading
import time


def resource_base():
    """PyInstaller onefile 解包目录 / 源码目录，都能找到 web/。"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                        "MultiSpan")


def setup_logging():
    """--noconsole 模式没有控制台，报错落到 %LocalAppData%\\MultiSpan\\log.txt。"""
    if not getattr(sys, "frozen", False):
        return
    try:
        os.makedirs(data_dir(), exist_ok=True)
        log = open(os.path.join(data_dir(), "log.txt"),
                   "a", encoding="utf-8", buffering=1)
        log.write("\n===== MultiSpan 启动 %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        sys.stderr = log
        sys.stdout = log
    except Exception:
        pass


def start_server(port=8765):
    """启动本地服务；端口被占则跳过（复用已运行的实例）。返回是否新建。"""
    import app
    from http.server import ThreadingHTTPServer
    if getattr(sys, "frozen", False):
        # 单文件 exe 解压在临时目录，产出/配置必须落在稳定位置
        data = data_dir()
        os.makedirs(data, exist_ok=True)
        app.BASE = resource_base()                      # web/ 静态资源在解包目录
        app.OUT_DIR = os.path.join(data, "out")
        app.UP_DIR = os.path.join(data, "uploads")
        app.CONFIG_PATH = os.path.join(data, "config.json")
        os.makedirs(app.OUT_DIR, exist_ok=True)
        os.makedirs(app.UP_DIR, exist_ok=True)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    except OSError:
        return False                       # 已有实例在跑，直接复用
    if not getattr(sys, "frozen", False):
        app.BASE = resource_base()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return True


def set_dpi_early():
    """必须在 webview 初始化之前调用——进程 DPI 感知只能设一次，
    pywebview 会设成 system 级，之后显示器坐标就被 DPI 虚拟化（4K 读成 2560）。"""
    try:
        u = __import__("ctypes").windll.user32
        u.SetProcessDpiAwarenessContext.argtypes = [__import__("ctypes").c_void_p]
        u.SetProcessDpiAwarenessContext.restype = bool
        u.SetProcessDpiAwarenessContext(__import__("ctypes").c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            __import__("ctypes").windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def main():
    setup_logging()
    set_dpi_early()
    port = 8765
    url = f"http://127.0.0.1:{port}"
    sys.path.insert(0, resource_base())
    os.chdir(resource_base())
    start_server(port)
    import webview
    webview.create_window("MultiSpan", url, width=1060, height=860,
                          min_size=(860, 640))
    webview.start()


if __name__ == "__main__":
    main()
