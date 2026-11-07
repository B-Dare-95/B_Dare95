# -*- coding: utf-8 -*-
"""Drive the real Tab Designer bd_family_cleaner.py with stand-in WPF controls.

The stub window is built from the script's own XAML (so names and markup are
checked), every click handler runs, and Apply/Undo really change a mock
extension on disk. Run: python tests/test_window.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import types
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True   # Revit's IronPython writes no .pyc
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)
import test_engine as TE  # noqa: E402
from dlc_tabdesigner import engine as E  # noqa: E402

PASSED = TE.PASSED
FAILED = TE.FAILED
check = TE.check


# ------------------------------------------------------------- WPF stubs
class Event(object):
    def __init__(self):
        self.h = []

    def __iadd__(self, fn):
        self.h.append(fn)
        return self

    def fire(self):
        for fn in list(self.h):
            fn(None, None)


class Coll(list):
    def Add(self, x):
        self.append(x)

    @property
    def Count(self):
        return len(self)

    def Clear(self):
        del self[:]


class Ctl(object):
    def __init__(self):
        self.Children = Coll()
        self.Items = Coll()
        self.IsEnabled = True
        self.ToolTip = None
        self.Content = None
        self.Text = ""


class TextBlock(Ctl):
    pass


class TextBox(Ctl):
    def __init__(self):
        Ctl.__init__(self)
        self._t = ""
        self.TextChanged = Event()

    @property
    def Text(self):
        return self._t

    @Text.setter
    def Text(self, v):
        self._t = v
        if hasattr(self, "TextChanged"):
            self.TextChanged.fire()


class CheckBox(Ctl):
    def __init__(self):
        Ctl.__init__(self)
        self.IsChecked = False


class Selector(Ctl):
    def __init__(self):
        Ctl.__init__(self)
        self._i = -1
        self.SelectionChanged = Event()

    @property
    def SelectedIndex(self):
        return self._i

    @SelectedIndex.setter
    def SelectedIndex(self, v):
        changed = v != self._i
        self._i = v
        if changed:
            self.SelectionChanged.fire()


class ComboBox(Selector):
    pass


class ListBox(Selector):
    def __init__(self):
        Selector.__init__(self)

        class Items(Coll):
            def __setitem__(inner, i, v):
                list.__setitem__(inner, i, v)
                self._i = -1          # WPF drops the selection on replace

            def Clear(inner):
                del inner[:]
                self._i = -1
        self.Items = Items()


class Button(Ctl):
    def __init__(self):
        Ctl.__init__(self)
        self.Click = Event()


class Grid(Ctl):
    def __init__(self):
        Ctl.__init__(self)
        self.RowDefinitions = Coll()
        self.ColumnDefinitions = Coll()

    @staticmethod
    def SetRow(el, r):
        el.row = r

    @staticmethod
    def SetColumn(el, c):
        el.col = c


class Panelish(Ctl):
    pass


class Any(object):
    def __getattr__(self, name):
        return name

    def __call__(self, *a, **k):
        return a


class GridLength(object):
    Auto = "auto"

    def __init__(self, *a):
        self.a = a


TAGS = {"TextBox": TextBox, "CheckBox": CheckBox, "TextBlock": TextBlock,
        "ListBox": ListBox, "Grid": Grid, "WrapPanel": Panelish,
        "Button": Button}
XNS = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
STATE = {"hook": None, "alerts": [], "answers": [], "reloads": 0}


class WPFWindow(object):
    def __init__(self, xaml, literal_string=False):
        root = ET.fromstring(xaml)
        for el in root.iter():
            name = el.get(XNS)
            if name:
                tag = el.tag.split("}")[-1]
                ctl = TAGS.get(tag, Ctl)()
                if el.get("IsChecked") is not None:
                    ctl.IsChecked = el.get("IsChecked") == "True"
                if el.get("Content") is not None and tag != "CheckBox":
                    ctl.Content = el.get("Content")
                setattr(self, name, ctl)
        self.closed = False

    def Close(self):
        self.closed = True

    def ShowDialog(self):
        STATE["hook"](self)


def alert(msg, **k):
    STATE["alerts"].append(msg)
    if k.get("exitscript"):
        raise SystemExit
    if k.get("yes"):
        return STATE["answers"].pop(0) if STATE["answers"] else True
    return True


def install():
    win = types.ModuleType("System.Windows")
    controls = types.ModuleType("System.Windows.Controls")
    controls.Orientation = Any()
    for n, v in dict(TextBlock=TextBlock, ComboBox=ComboBox, Button=Button,
                     Grid=Grid, Border=Panelish, StackPanel=Panelish,
                     ColumnDefinition=Panelish, RowDefinition=Panelish).items():
        setattr(controls, n, v)
    win.Controls = controls
    win.Thickness = win.CornerRadius = lambda *a: a
    win.GridLength = GridLength
    for n in ("GridUnitType", "FontWeights", "VerticalAlignment",
              "HorizontalAlignment", "TextWrapping", "TextAlignment"):
        setattr(win, n, Any())
    media = types.ModuleType("System.Windows.Media")
    media.SolidColorBrush = lambda c: ("brush", c)
    media.Color = types.SimpleNamespace(
        FromRgb=lambda r, g, b: (r, g, b),
        FromArgb=lambda a, r, g, b: (a, r, g, b))
    media.Brushes = Any()
    clr = types.ModuleType("clr")
    clr.AddReference = lambda n: None
    forms = types.SimpleNamespace(WPFWindow=WPFWindow, alert=alert)
    pyrevit = types.ModuleType("pyrevit")
    pyrevit.forms = forms
    loader = types.ModuleType("pyrevit.loader")
    sessionmgr = types.ModuleType("pyrevit.loader.sessionmgr")

    def reload_pyrevit():
        STATE["reloads"] += 1
    sessionmgr.reload_pyrevit = reload_pyrevit
    loader.sessionmgr = sessionmgr
    sys.modules.update({
        "System": types.ModuleType("System"), "System.Windows": win,
        "System.Windows.Controls": controls, "System.Windows.Media": media,
        "clr": clr, "pyrevit": pyrevit, "pyrevit.loader": loader,
        "pyrevit.loader.sessionmgr": sessionmgr})


def load(script_path):
    spec = importlib.util.spec_from_file_location("tab_designer", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def texts(grid):
    return [c.Text for c in grid.Children if isinstance(c, TextBlock)]


def combos(grid):
    return [c for c in grid.Children if isinstance(c, ComboBox)]


# ------------------------------------------------------------- tests
def test_window_apply_then_undo():
    install()
    root = tempfile.mkdtemp()
    local = tempfile.mkdtemp()
    os.environ["LOCALAPPDATA"] = local
    ext = TE.make_ext(root)
    original = TE.snapshot(root)
    mod = load(TE.designer_script(ext))
    check(mod.BACKUPS.startswith(local), "backups in LOCALAPPDATA")
    seen = {}

    def session(win):
        check(win.tab_name.Text == "SDC", "tab name prefilled")
        check(ext in win.where.Text, "shows where it found the extension")
        check(win.rename_ext.IsEnabled is False and
              "already named" in win.rename_ext.Content,
              "ext checkbox idle while name unchanged")
        win.tab_name.Text = "DLC"
        check(win.rename_ext.IsEnabled and u"SDC.extension → "
              u"DLC.extension" in win.rename_ext.Content,
              "ext checkbox follows the name: %s" % win.rename_ext.Content)
        check(len(win.panel_list.Items) == 5 and
              win.panel_list.Items[2].Tag == "Rooms", "panel list")
        win.panel_list.SelectedIndex = 2
        check(win.panel_title.Text == "Rooms", "Rooms selected")
        check(len(combos(win.tools)) == 5, "5 size dropdowns")
        check(len(win.preview.Children) == 5, "today: 5 large columns")
        win.btn_suggest.Click.fire()
        check(win.panel_list.SelectedIndex == 2, "selection kept")
        check(len(win.preview.Children) == 3,
              "after suggest: 3 columns (large + 2 stacks), got %d"
              % len(win.preview.Children))
        check(texts(win.tools)[2] == "Room Serial", "main tool listed first")
        # put Renumber Rooms into More
        names = [t for t in texts(win.tools)[2:]]
        idx = names.index("Renumber Rooms")
        cb = combos(win.tools)[idx]
        cb.SelectedIndex = cb.Items.index(E.MODE_LABELS["MORE"])
        check(any("More" in t.Text for card in win.preview.Children
                  for sp in [card.Child] for t in sp.Children),
              "preview shows the More menu")
        # move Room Gaps to the far left with the arrows
        for _ in range(5):
            names = texts(win.tools)[2:]
            i = names.index("Room Gaps")
            ups = [b for b in win.tools.Children if isinstance(b, Button)
                   and getattr(b, "row", 0) == i + 1 and b.Content == u"▲"]
            if not ups or not ups[0].IsEnabled:
                break
            ups[0].Click.fire()
        check(texts(win.tools)[2] == "Room Gaps", "arrows reorder")
        # designer row is locked
        win.panel_list.SelectedIndex = 4
        locked = [c for c in combos(win.tools) if not c.IsEnabled]
        check(len(locked) == 1 and "can't move itself" in locked[0].ToolTip,
              "designer can't be resized")
        win.rename_ext.IsChecked = True
        STATE["answers"] = [True]          # confirm Apply
        win.btn_apply.Click.fire()
        seen["closed"] = win.closed
        seen["reload"] = win.do_reload
    STATE["hook"] = session
    mod.main()
    check(seen.get("closed") and seen.get("reload"), "apply closes window")
    check(STATE["reloads"] == 1, "pyRevit refreshed once")
    confirm = [a for a in STATE["alerts"] if a.startswith("Apply this")]
    check(confirm and u"Tab SDC → DLC" in confirm[0], "confirm lists rename")
    done = STATE["alerts"][-1]
    check(done.startswith("Done.") and "pyRevit will now refresh" in done,
          "result message")
    tab = os.path.join(root, "DLC.extension", "DLC.tab")
    bad, rib = TE.ribbon(tab)
    check(bad == [], "pyRevit rules on disk: %s" % bad)
    check(E.entry_name(rib["Rooms"][0][0]) == "Room Gaps",
          "Room Gaps leads the small tools: %s" % rib["Rooms"])

    # second run from the new location: undo
    mod2 = load(TE.designer_script(os.path.join(root, "DLC.extension")))

    def session2(win):
        check(win.tab_name.Text == "DLC", "reopens as DLC")
        STATE["answers"] = [True]
        win.btn_undo.Click.fire()
        seen["closed2"] = win.closed
    STATE["hook"] = session2
    mod2.main()
    check(seen.get("closed2") and STATE["reloads"] == 2,
          "undo closes and refreshes")
    now = TE.snapshot(root)
    panel_bundles = [k for k in now if k.endswith(".panel/bundle.yaml")
                     or k.endswith(".panel" + os.sep + "bundle.yaml")]
    check(dict((k, v) for k, v in now.items() if k not in panel_bundles) ==
          dict((k, v) for k, v in original.items() if k not in panel_bundles),
          "undo restored every tool file exactly")
    for k in panel_bundles:
        txt = open(os.path.join(root, k), encoding="utf-8").read()
        check(E.strip_invisible(E.yaml_title(txt)) ==
              E.base(os.path.basename(os.path.dirname(k))),
              "after undo %s re-keyed for refresh" % k)
    shutil.rmtree(root)
    shutil.rmtree(local)


def swatch_buttons(win):
    return [b for b in win.swatches.Children if isinstance(b, Button)]


def hexes(win):
    return [b.Background[1] for b in swatch_buttons(win)
            if isinstance(getattr(b, "Background", None), tuple)]


def test_window_title_colours():
    install()
    root = tempfile.mkdtemp()
    local = tempfile.mkdtemp()
    os.environ["LOCALAPPDATA"] = local
    ext = TE.make_ext(root)
    mod = load(TE.designer_script(ext))
    mod.pick_custom_color = lambda cur: "#123ABC"
    STATE["alerts"] = []
    seen = {}

    def rgb(h):
        h = h.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    def session(win):
        win.panel_list.SelectedIndex = 0
        btns = swatch_buttons(win)
        check(len(btns) == len(E.PALETTE) + 2, "10 swatches + Custom + None")
        check([b.Content for b in btns[-2:]] == [u"Custom\u2026", u"None"],
              "custom and none buttons")
        check(win.preview_strip_text.Text == "Coordination", "strip label")
        check(win.preview_strip.Background[1] == rgb("#E2E8F0"),
              "no colour yet -> grey strip")
        btns[0].Click.fire()                         # Red
        check(win.design.panels[0].color == "#E53935", "red picked")
        check(win.preview_strip.Background[1] == rgb("#E53935"),
              "strip turns red")
        check(win.preview_strip_text.Foreground[1] == rgb("#FFFFFF"),
              "white text on red")
        red = swatch_buttons(win)[0]
        check(red.BorderThickness == (3,) and "(current)" in red.ToolTip,
              "chosen swatch highlighted")
        dot = win.panel_list.Items[0].Children[0]
        check(dot.Background[1] == rgb("#E53935"), "list dot red")
        check(win.panel_list.SelectedIndex == 0, "selection kept")
        # Rooms: yellow -> dark text
        win.panel_list.SelectedIndex = 2
        swatch_buttons(win)[2].Click.fire()
        check(win.preview_strip_text.Foreground[1] == rgb("#1F2937"),
              "dark text on yellow")
        # Doors: custom colour
        win.panel_list.SelectedIndex = 1
        [b for b in swatch_buttons(win) if b.Content == u"Custom\u2026"][0] \
            .Click.fire()
        check(win.design.panels[1].color == "#123ABC", "custom colour")
        check(rgb("#123ABC") in hexes(win), "custom colour shown as swatch")
        # Tools: set then None
        win.panel_list.SelectedIndex = 4
        swatch_buttons(win)[4].Click.fire()
        [b for b in swatch_buttons(win) if b.Content == "None"][0].Click.fire()
        check(win.design.panels[4].color is None, "None clears")
        STATE["answers"] = [True]
        win.btn_apply.Click.fire()
        seen["ok"] = win.closed
    STATE["hook"] = session
    mod.main()
    check(seen.get("ok"), "applied")
    tab = os.path.join(ext, "SDC.tab")

    def bundle(panel):
        import yaml
        return yaml.safe_load(open(os.path.join(tab, panel, "bundle.yaml"),
                                   encoding="utf-8"))
    co = bundle("Coordination.panel")
    check(co["background"] == {"title": "#E53935"},
          "only the title strip coloured: %s" % co.get("background"))
    check(E.strip_invisible(co["title"]) == "Coordination",
          "title kept alongside colour")
    check(bundle("Doors.panel")["background"]["title"] == "#123ABC",
          "custom written")
    ro = bundle("Rooms.panel")["background"]
    check(ro["title"] == "#FDD835" and ro["panel"] == "#123456",
          "Rooms: your old whole-panel colour kept, title set: %s" % ro)
    check("background" not in bundle("Tools.panel"), "None -> no colour")
    check(TE.ribbon(tab)[0] == [], "ribbon still valid")

    # reopen: colours read back; auto colours follows the example
    mod2 = load(TE.designer_script(ext))

    def session2(win):
        check([p.color for p in win.design.panels] ==
              ["#E53935", "#123ABC", "#FDD835", None, None],
              "colours read back: %s" % [p.color for p in win.design.panels])
        win.btn_colors.Click.fire()
        check([p.color for p in win.design.panels] ==
              ["#E53935", "#1E88E5", "#FDD835", "#43A047", "#8E24AA"],
              "auto: Coordination red, Doors blue, Rooms yellow, Sheet "
              "Manager green, Tools purple")
        check(win.panel_list.Items[1].Children[0].Background[1] ==
              rgb("#1E88E5"), "list dots updated")
    STATE["hook"] = session2
    mod2.main()
    shutil.rmtree(root)
    shutil.rmtree(local)


def test_window_cancel_and_errors():
    install()
    root = tempfile.mkdtemp()
    local = tempfile.mkdtemp()
    os.environ["LOCALAPPDATA"] = local
    ext = TE.make_ext(root)
    snap = TE.snapshot(root)
    mod = load(TE.designer_script(ext))
    STATE["reloads"] = 0
    STATE["alerts"] = []

    def session(win):
        win.tab_name.Text = "A/B"
        win.btn_apply.Click.fire()                 # bad name
        win.tab_name.Text = "DLC"
        STATE["answers"] = [False]                 # say No to confirm
        win.btn_apply.Click.fire()
        win.btn_undo.Click.fire()                  # nothing to undo
        win.btn_reset.Click.fire()
    STATE["hook"] = session
    mod.main()
    check(any("can't contain" in a for a in STATE["alerts"]), "bad name told")
    check(any("Nothing to undo" in a for a in STATE["alerts"]),
          "nothing to undo told")
    check(STATE["reloads"] == 0 and TE.snapshot(root) == snap,
          "cancelled run changes nothing")
    shutil.rmtree(root)
    shutil.rmtree(local)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                FAILED.append("%s crashed: %s" % (name, ex))
    print("window: %d assertions passed, %d failed" % (PASSED[0], len(FAILED)))
    for f in FAILED:
        print("  FAIL: " + f)
    sys.exit(1 if FAILED else 0)
