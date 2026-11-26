"""Drive the Tk UI and capture screenshots (UI smoke test). Usage: python tools/ui_screenshot.py OUTDIR"""
import os, sys, tkinter as tk
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("APPDATA", os.path.join(sys.argv[1], "appdata"))
from PIL import ImageGrab
from leerbox.ui import app as A

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
root = tk.Tk()
A.ctypes = None
try:
    import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass
st = A.StudioApp(root)
root.geometry("1500x920+20+20")
steps = []
def shot(name):
    root.update(); root.lift(); root.attributes("-topmost", True)
    x, y = root.winfo_rootx(), root.winfo_rooty(); w, h = root.winfo_width(), root.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(os.path.join(out, name + ".png"))
    print("shot", name, w, h, st.status_var.get(), "|", st.size_var.get())
def seq():
    yield 1500, lambda: (st.select_font("fig:ansi_shadow"), st.add_effect("gradient"))
    yield 1200, lambda: shot("01_preview")
    yield 100, lambda: st.set_view("gallery")
    yield 3000, lambda: shot("02_gallery")
    yield 100, lambda: (st.text_in.delete("1.0", "end"), st.text_in.insert("1.0", "مرحبا بالعالم"), st.set_view("preview"), st.select_font("ras:Noto Naskh Arabic Bold"), st.ovars["raster_mode"].set("half"))
    yield 1500, lambda: shot("03_arabic")
    yield 100, lambda: (st.text_in.delete("1.0", "end"), st.text_in.insert("1.0", "LeerBox"), st.set_mode("unicode"))
    yield 1000, lambda: shot("04_unicode")
    yield 100, lambda: (st.set_mode("text"), st.curated_var.set("Retro terminal"), st.apply_curated(), st.nb.select(1))
    yield 1500, lambda: shot("05_curated_fx")
    yield 100, lambda: (st.add_compare(), st.select_font("fig:slant"), st.add_compare(), st.select_font("tlf:future"), st.add_compare(), st.set_view("compare"))
    yield 1500, lambda: shot("06_compare")
    yield 100, lambda: (st.set_mode("boxes"),)
    yield 1500, lambda: shot("07_boxes")
    img_path = os.path.join(out, "_portrait.png")
    def mk():
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
        import image_fixtures as F
        from PIL import Image
        w, h, d = F.portrait(240, 300)
        Image.frombytes("RGBA", (w, h), d).save(img_path)
        st.set_mode("image")
        ws = st.workspaces["image"]
        ws.load_path(img_path)
    yield 100, mk
    yield 2500, lambda: (st.workspaces["image"].fit(), shot("08_image_braille"))
    yield 100, lambda: st.workspaces["image"].set_params({**st.workspaces["image"].params, "mode": "truecolor", "cols": 90})
    yield 2500, lambda: (st.workspaces["image"].view.set("slider"), st.workspaces["image"].fit(), shot("09_image_slider"))
    yield 100, lambda: st.workspaces["image"].set_params({**st.workspaces["image"].params, "mode": "typographic", "cols": 120})
    yield 2500, lambda: (st.workspaces["image"].view.set("side"), st.workspaces["image"].fit(), shot("10_image_side"))
    def anim():
        from PIL import Image, ImageDraw
        fr = []
        for i in range(6):
            im = Image.new("RGB", (120, 80), (10, 10, 40)); ImageDraw.Draw(im).ellipse([5 + i * 15, 10, 45 + i * 15, 60], fill=(255, 200, 0)); fr.append(im)
        gp = os.path.join(out, "_anim.gif")
        fr[0].save(gp, save_all=True, append_images=fr[1:], duration=90, loop=0)
        st.set_mode("animation")
        a = st.workspaces["animation"]
        a.open_anim(gp)
        a.convert()
    yield 100, anim
    yield 3000, lambda: shot("11_animation")
    yield 500, lambda: (st.set_mode("text"), root.destroy())
it = seq()
def run():
    try:
        d, fn = next(it)
    except StopIteration:
        return
    def go():
        try: fn()
        except Exception as e: import traceback; traceback.print_exc()
        run()
    root.after(d, go)
run()
root.mainloop()
