"""Exercise the real packaged GUI on a virtual desktop (CI only)."""
import argparse
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

SPECS=(("route-assertion-ledger","route_assertion_ledger"),)


def require(condition,message):
    if not condition:raise AssertionError(message)


def wait(app,predicate,timeout=8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.root.update()
        if predicate():return
        time.sleep(.015)
    raise AssertionError("desktop result timed out")


def geometry(app,w,h):
    root=app.root
    root.geometry(f"{w}x{h}+10+10")
    root.update_idletasks();root.update()
    root.update_idletasks()
    root_x,root_y=root.winfo_rootx(),root.winfo_rooty()
    controls=[*app.controls,app.details_button,app.save_button,app.clear_button]
    rows=[]
    for c in controls:
        if not c.winfo_ismapped():continue
        x,y=c.winfo_rootx()-root_x,c.winfo_rooty()-root_y
        width,height=c.winfo_width(),c.winfo_height()
        require(width>1 and height>=30 and x>=0 and y>=0 and x+width<=root.winfo_width() and y+height<=root.winfo_height(),
                f"{app.adapter.TITLE} control outside screen: {c.cget('text') if 'text' in c.keys() else c.winfo_class()} {x,y,width,height} in {w,h}")
        rows.append({"widget":c.winfo_class(),"width":width,"height":height})
    require(app.run_button.winfo_ismapped() and app.demo_button.winfo_ismapped() and app.save_button.winfo_ismapped(),"main actions must remain mapped")
    # Check each panel's mapped children remain within the panel, not merely
    # within the root window; clipping must not hide the last input or output.
    for panel in (app.inputs,app.results):
        px,py=panel.winfo_rootx(),panel.winfo_rooty()
        for child in panel.winfo_children():
            if not child.winfo_ismapped():continue
            x,y=child.winfo_rootx()-px,child.winfo_rooty()-py
            if not (x>=0 and y>=0 and x+child.winfo_width()<=panel.winfo_width()+1 and y+child.winfo_height()<=panel.winfo_height()+1):
                print("Panel geometry:",[(c.winfo_class(),c.cget("text") if "text" in c.keys() else "",c.winfo_rooty()-py,c.winfo_height(),c.winfo_reqheight()) for c in panel.winfo_children() if c.winfo_ismapped()],flush=True)
            require(x>=0 and y>=0 and x+child.winfo_width()<=panel.winfo_width()+1 and y+child.winfo_height()<=panel.winfo_height()+1,
                    f"{app.adapter.TITLE} panel child clipped in {w,h}: {child.winfo_class()} at {x,y} size {child.winfo_width(),child.winfo_height()} vs {panel.winfo_width(),panel.winfo_height()}")
    return {"window":[root.winfo_width(),root.winfo_height()],"controls":rows}


def screenshot(root,path):
    # Pillow is a test-only dependency of this CI runner, not shipped in kits.
    from PIL import ImageGrab
    x,y=root.winfo_rootx(),root.winfo_rooty()
    box=(x,y,x+root.winfo_width(),y+root.winfo_height())
    image=ImageGrab.grab(bbox=box)
    if image.size!=(root.winfo_width(),root.winfo_height()):
        raise RuntimeError("desktop screenshot bounds mismatch")
    image.save(path,"PNG")



def check_product(name,module,kit,evidence):
    package=kit/(name+".pyz")
    sys.path.insert(0,str(package))
    adapter=importlib.import_module(module+".desktop")
    ui=importlib.import_module(module+".desktop_ui")
    import tkinter as tk
    root=tk.Tk()
    if len(sys.argv)>2:root.tk.call("tk","scaling",float(sys.argv[2]))
    print("Tk scaling:",root.tk.call("tk","scaling"),"DPI:",root.winfo_fpixels("1i"),flush=True)
    app=ui.launch(adapter,root=root,run_loop=False)
    rows=[]
    try:
        require(app.run_button.instate(["disabled"]),"run enabled with missing inputs")
        for w,h in ((760,550),(1000,620),(1280,720)):
            rows.append({"initial":geometry(app,w,h)})
        geometry(app,1000,620)
        screenshot(root,evidence/(name+"-desktop-initial.png"))
        app.demo_button.invoke()
        wait(app,lambda:app.result is not None and not app.busy)
        require(app.result.state=="review" and app.result_mode=="Synthetic example","built-in example failed")
        require(app.detail.cget("text").startswith("First finding:"),"first actionable finding absent")
        expected=json.loads((kit/"example-report.json").read_text(encoding="utf-8"))
        require(app.result.data==expected,name+" example differs from packaged fixture; expected="+json.dumps(expected,sort_keys=True,ensure_ascii=True)[:1800]+" actual="+json.dumps(app.result.data,sort_keys=True,ensure_ascii=True)[:1800])
        for row,(w,h) in zip(rows,((760,550),(1000,620),(1280,720))):
            row["example"]=geometry(app,w,h)
        geometry(app,1000,620)
        screenshot(root,evidence/(name+"-desktop-example.png"))
        original=app.result
        app.theme_button.invoke();root.update()
        require(app.dark and app.result is original,"theme must preserve result")
        require(app.root.cget("bg")=="#121720","dark palette not applied")
        geometry(app,1000,620)
        screenshot(root,evidence/(name+"-desktop-dark.png"))
        app.theme_button.invoke();root.update()
        require(not app.dark and app.result is original,"light switch lost result")
        with tempfile.TemporaryDirectory(prefix="desktop-ui-qa-") as tmp:
            tmp=Path(tmp)
            report=tmp/"example.html"
            with patch("tkinter.filedialog.asksaveasfilename",return_value=str(report)):
                app.save_button.invoke()
            require(report.is_file() and b"SYNTHETIC EXAMPLE" in report.read_bytes(),"example export not labeled")
            before=report.read_bytes()
            with patch("tkinter.filedialog.asksaveasfilename",return_value=str(report)),patch("tkinter.messagebox.showerror") as error:
                app.save_button.invoke()
                require(error.called and report.read_bytes()==before,"existing output overwritten")
            app.details_button.invoke()
            root.update()
            popup=next((x for x in root.winfo_children() if isinstance(x,tk.Toplevel)),None)
            require(popup is not None and popup.winfo_ismapped(),"report popup failed")
            def children(w):
                return [c for child in w.winfo_children() for c in [child,*children(child)]]
            copy=next(c for c in children(popup) if c.winfo_class()=="TButton" and c.cget("text")=="Copy summary")
            copy.invoke();root.update()
            copied=root.clipboard_get()
            require("Synthetic example" in copied and app.result.title in copied,"copy summary missing example label")
            require(str(kit) not in copied and str(tmp) not in copied,"copy summary exposed path")
            popup.destroy();root.update()
            # Select actual included fixtures; never bypass the core.
            if name=="sheet-handoff-gate":
                app.set_value("files",(str(kit/"examples/clean.xlsx"),))
            elif name=="static-publish-gate":
                local=tmp/"dist";shutil.copytree(kit/"examples/clean-dist",local)
                app.set_value("root",str(local));app.set_value("mode","Create snapshot")
            else:
                for key,file in (("spec","spec.json"),("evidence","observations-passing.json"),("policy","policy.json")):
                    app.set_value(key,str(kit/"examples"/file))
            require(app.result is None and app.save_button.instate(["disabled"]),"stale example remained exportable")
            require(not app.run_button.instate(["disabled"]),"complete inputs did not enable run")
            app.keyboard_run();wait(app,lambda:app.result is not None and not app.busy)
            require(app.result.state=="pass" and app.result_mode=="Your inputs","actual input path failed")
            geometry(app,1000,620)
            screenshot(root,evidence/(name+"-desktop-passing.png"))
            actual=tmp/"actual.json"
            with patch("tkinter.filedialog.asksaveasfilename",return_value=str(actual)):
                app.save_button.invoke()
            require(json.loads(actual.read_text(encoding="utf-8"))==app.result.data,"exported actual result mismatch")
            if name=="static-publish-gate":
                require(app.result.snapshot is not None,"candidate snapshot absent")
                snapshot=tmp/"candidate.json"
                with patch("tkinter.filedialog.asksaveasfilename",return_value=str(snapshot)),patch("tkinter.messagebox.askyesno",return_value=True):
                    app.extra_button.invoke()
                require(json.loads(snapshot.read_text(encoding="utf-8"))==app.result.snapshot,"candidate snapshot export failed")
                with patch("tkinter.filedialog.asksaveasfilename",return_value=str(local/"unwanted.json")),patch("tkinter.messagebox.showerror") as error:
                    app.save_button.invoke()
                    require(error.called and not (local/"unwanted.json").exists(),"audit root was modified")
                require(not app.path_labels["manifest"].winfo_ismapped(),"unused manifest controls visible")
                app.set_value("mode","Verify snapshot")
                root.update()
                require(app.path_labels["manifest"].winfo_ismapped(),"required manifest controls hidden")
                require(app.run_button.instate(["disabled"]),"verification enabled without reviewed snapshot")
                app.set_value("manifest",str(snapshot))
                require(not app.run_button.instate(["disabled"]),"reviewed snapshot did not enable run")
                app.run_button.invoke();wait(app,lambda:app.result is not None and not app.busy)
                require(app.result.state=="pass","reviewed pin did not verify")
                p=local/"index.html";p.write_bytes(p.read_bytes().replace(b"Example",b"Changed"))
                app.run_button.invoke();wait(app,lambda:app.result is not None and not app.busy)
                require(app.result.state=="review" and "content_changed" in {x["code"] for x in app.result.data["issues"]},"same-size change missed")
            if name=="route-assertion-ledger":
                app.set_value("mode","Spec preflight");root.update()
                require(app.run_button.instate(["disabled"]),"preflight missing spec must disable run")
                require(not app.path_labels["evidence"].winfo_ismapped(),"irrelevant evidence controls visible")
                app.demo_button.invoke();wait(app,lambda:app.result is not None and not app.busy)
                require(app.result.data["mode"]=="spec_preflight" and app.result.data["duplicate_id_groups"]==1,"preflight example mismatch")
                app.set_value("specs",(str(kit/"examples/spec.json"),));root.update()
                require(not app.run_button.instate(["disabled"]),"preflight selected spec not enabled")
                app.run_button.invoke();wait(app,lambda:app.result is not None and not app.busy)
                require(app.result.state=="pass" and app.result.data["mode"]=="spec_preflight","real preflight failed")
                geometry(app,760,550);geometry(app,1000,620)
                screenshot(root,evidence/(name+"-desktop-preflight.png"))
                app.set_value("mode","Assertion coverage");root.update()
                require(app.result is None and app.save_button.instate(["disabled"]),"mode change retained stale report")
                require(app.path_labels["evidence"].winfo_ismapped(),"coverage inputs did not restore")
            app.clear_button.invoke();root.update()
            require(app.result is None and app.save_button.instate(["disabled"]),"clear retained old result")
            require(app.run_button.instate(["disabled"]),"clear did not disable run")
        return {"product":name,"geometry":rows,"real_example":True,"actual_inputs":True,"exports":True,"stale_result_invalidated":True,"screenshot_count":4 if name=="route-assertion-ledger" else 3}
    finally:
        app.close();sys.path.pop(0)


if __name__ == "__main__":
    import os
    import tkinter as tk
    if os.name != "nt":
        raise SystemExit("Native Windows required")
    with tempfile.TemporaryDirectory(prefix="EZTOOLGO 테스트 ") as tmp:
        target=Path(tmp)/"route-assertion-ledger"
        shutil.copytree(Path(__file__).parent/"windows_gui_fixtures",target)
        shutil.copyfile(sys.argv[1],target/"route-assertion-ledger.pyz")
        # Preserve original strict geometry, assertions, real inputs, report
        # exports, themes, mode switching and clipboard checks.
        with patch(__name__+".screenshot",lambda *a:None):
            result=check_product("route-assertion-ledger","route_assertion_ledger",target,Path(tmp))
            result.pop("screenshot_count",None)
        print(json.dumps(result,ensure_ascii=True))
