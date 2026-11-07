# -*- coding: utf-8 -*-
"""Engine tests on a mock of the real DLC tab. Run: python tests/test_engine.py"""
import hashlib
import os
import shutil
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
from dlc_tabdesigner import engine as E  # noqa: E402

REAL_BUTTON = os.path.join(HERE, "..", "SDC.tab", "Tools.panel",
                           "Tab Designer.pushbutton")
PASSED = [0]
FAILED = []


def check(cond, msg):
    if cond:
        PASSED[0] += 1
    else:
        FAILED.append(msg)


def w(path, text=""):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w") as fh:
        fh.write(text)


def button(panel, name, kb=1, title=None):
    d = os.path.join(panel, name + ".pushbutton")
    w(os.path.join(d, "bd_family_cleaner.py"), "x = 1\n" * (kb * 170))
    w(os.path.join(d, "icon.png"), "png")
    if title:
        w(os.path.join(d, "bundle.yaml"), 'title: "%s"\n' % title)
    return d


def make_ext(root):
    """The tab from the screenshot (22 Oct 2026)."""
    ext = os.path.join(root, "SDC.extension")
    tab = os.path.join(ext, "SDC.tab")
    w(os.path.join(ext, "lib", "dlc_stairxfer", "engine.py"), "# lib\n")
    w(os.path.join(ext, ".hidden"), "keep me\n")
    w(os.path.join(ext, "installer.ps1"), "$p = 'X\\SDC.extension\\SDC.tab'\n")
    w(os.path.join(tab, "bundle.yaml"),
      "layout:\n  - Coordination\n  - Doors\n  - Rooms\n  - Sheet Manager\n"
      "  - Tools\n")
    co = os.path.join(tab, "Coordination.panel")
    button(co, "Delete Duplicates", 3, "Delete\\nDuplicates")
    button(co, "Find Link Duplicates", 9, "Find Link\\nDuplicates")
    button(co, "Reset Colours", 2, "Reset\\nColours")
    button(co, "Stair Transfer", 30, "Stair\\nTransfer")
    w(os.path.join(co, "bundle.yaml"),
      "layout:\n  - Delete Duplicates\n  - Find Link Duplicates\n"
      "  - Reset Colours\n  - Stair Transfer\n")
    do = os.path.join(tab, "Doors.panel")
    button(do, "Fill Hardware", 4, "Fill\\nHardware")
    b = button(do, "Write Door Data", 12, "Write\\nDoor Data")
    w(os.path.join(b, "notes.py"), 'P = "SDC_Door_Number"\n')
    ro = os.path.join(tab, "Rooms.panel")
    for n, kb in (("Room Doctor", 6), ("Room Fixer", 7), ("Room Gaps", 5),
                  ("Renumber Rooms", 3), ("Room Serial", 10)):
        button(ro, n, kb)
    # title styles seen in real bundles: block scalar and localised map
    w(os.path.join(ro, "Room Serial.pushbutton", "bundle.yaml"),
      "title: |-\n  Room\n  Serial\ntooltip: Serial numbers\n")
    w(os.path.join(ro, "Room Doctor.pushbutton", "bundle.yaml"),
      "title:\n  ar: Tabib\n  en_us: Room Doctor\nauthor: DLC\n")
    w(os.path.join(ro, "bundle.yaml"),
      "layout:\n  - Room Doctor\n  - Room Fixer\n  - Room Gaps\n"
      "  - Renumber Rooms\n  - Room Serial\nbackground: \"#123456\"\n")
    sm = os.path.join(tab, "Sheet Manager.panel")
    button(sm, "Export Sheets", 8, "Export\\nPDF + DWG")
    button(sm, "Create Sheets", 6, "Create\\nSheets")
    to = os.path.join(tab, "Tools.panel")
    button(to, "Element Info", 2, "Element Info")
    shutil.copytree(REAL_BUTTON, os.path.join(to, "Tab Designer.pushbutton"))
    return ext


def designer_script(ext_dir):
    for root, dirs, files in os.walk(ext_dir):
        if root.endswith("Tab Designer.pushbutton"):
            return os.path.join(root, "bd_family_cleaner.py")
    raise AssertionError("designer not found")


def snapshot(root):
    out = {}
    for d, ds, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root)] = hashlib.sha1(
                open(p, "rb").read()).hexdigest()
        if not fs and not ds:
            out[os.path.relpath(d, root) + "/"] = "dir"
    return out


# ------------------------------------------------- pyRevit ribbon rules
ITEM = set(E.ITEM_KINDS) | {".stack"}


def layout(d):
    f = os.path.join(d, "bundle.yaml")
    if not os.path.exists(f):
        return None
    return (yaml.safe_load(open(f)) or {}).get("layout")


def ribbon(tab):
    """Render the tab like pyRevit would; return (problems, {panel: cols})."""
    bad, out = [], {}
    for pn in sorted(os.listdir(tab)):
        pdir = os.path.join(tab, pn)
        if E.kind(pn) != ".panel":
            continue
        kids = [k for k in os.listdir(pdir) if E.kind(k) in ITEM]
        lay = layout(pdir)
        names = lay if lay is not None else sorted(E.base(k) for k in kids)
        if lay is not None:
            listed = [E.entry_name(x) for x in lay]
            for k in kids:
                if E.base(k) not in listed:
                    bad.append("%s: %s would vanish" % (pn, k))
        cols = []
        for n in names:
            m = [k for k in kids if E.base(k) == E.entry_name(n)]
            if not m:
                bad.append("%s: layout lists missing %s" % (pn, n))
                continue
            k = m[0]
            if E.kind(k) == ".stack":
                sd = os.path.join(pdir, k)
                sk = [x for x in os.listdir(sd) if E.kind(x) in ITEM]
                if len(sk) not in (2, 3):
                    bad.append("%s/%s has %d items" % (pn, k, len(sk)))
                sl = layout(sd) or sorted(E.base(x) for x in sk)
                for x in sk:
                    if E.base(x) not in [E.entry_name(y) for y in sl]:
                        bad.append("%s/%s: %s would vanish" % (pn, k, x))
                    if E.kind(x) == ".pulldown":
                        for y in os.listdir(os.path.join(sd, x)):
                            if E.kind(y) in ITEM and E.kind(y) not in \
                                    E.PUSH_KINDS:
                                bad.append("%s: %s in a pulldown" % (pn, y))
                        if not os.path.exists(os.path.join(sd, x,
                                                           "icon.png")):
                            bad.append("pulldown without icon")
                cols.append(sl)
            else:
                cols.append([n])
        out[E.base(pn)] = cols
    return bad, out


def ctx_for(ext_dir):
    return E.find_context(designer_script(ext_dir))


def modes(design):
    return dict((p.label, [(i.label, i.mode) for i in p.items])
                for p in design.panels)


# ------------------------------------------------------------- tests
def test_context_from_own_location():
    root = tempfile.mkdtemp()
    ext = make_ext(root)
    ctx = ctx_for(ext)
    check(ctx.ext_dir == ext and ctx.tab_name == "SDC" and
          ctx.ext_name == "SDC", "found ext/tab from the button")
    check(ctx.root == root, "root = folder holding the extension")
    try:
        E.find_context(os.path.join(root, "loose", "bd_family_cleaner.py"))
        FAILED.append("outside an extension should fail")
    except E.DesignerError as ex:
        check("must sit inside" in str(ex), "clear message")
    shutil.rmtree(root)


def test_scan_shows_current_ribbon():
    root = tempfile.mkdtemp()
    d = E.Design(ctx_for(make_ext(root)))
    check([p.label for p in d.panels] ==
          ["Coordination", "Doors", "Rooms", "Sheet Manager", "Tools"],
          "panel order from tab layout")
    m = modes(d)
    check(all(mode == "BIG" for p in m.values() for _, mode in p),
          "today everything is large")
    check([l for l, _ in m["Coordination"]] ==
          ["Delete Duplicates", "Find Link Duplicates", "Reset Colours",
           "Stair Transfer"], "labels one line, layout order")
    check([l for l, _ in m["Sheet Manager"]] == ["Create Sheets",
                                                  "Export PDF + DWG"],
          "title used as label")
    tools = d.panels[-1].items
    me = [i for i in tools if i.locked]
    check(len(me) == 1 and me[0].label == "Tab Designer" and
          me[0].options() == ["BIG"], "designer locked as Large")
    shutil.rmtree(root)


def test_suggest_compacts_sensibly():
    root = tempfile.mkdtemp()
    d = E.Design(ctx_for(make_ext(root)))
    d.suggest_all()
    m = modes(d)
    check(m["Coordination"][0] == ("Stair Transfer", "BIG") and
          [x for _, x in m["Coordination"][1:]] == ["SMALL"] * 3,
          "Coordination: Stair Transfer large + 3 small %s" % m["Coordination"])
    check(m["Rooms"][0] == ("Room Serial", "BIG") and
          [x for _, x in m["Rooms"][1:]] == ["SMALL"] * 4, "Rooms %s"
          % m["Rooms"])
    check(all(x == "BIG" for _, x in m["Doors"]), "2-tool panel stays large")
    check(all(x == "BIG" for _, x in m["Tools"]), "Tools stays large")
    rooms = [p for p in d.panels if p.label == "Rooms"][0]
    check([len(c) for c in E.preview(rooms)] == [1, 2, 2],
          "Rooms preview: large + 2+2 stacks %s" % E.preview(rooms))
    before = sum(E.width_estimate(p) for p in E.Design(d.ctx).panels)
    after = sum(E.width_estimate(p) for p in d.panels)
    check(after < before, "suggestion is narrower (%.1f -> %.1f)"
          % (before, after))
    shutil.rmtree(root)


def test_stack_sizes():
    check([E.stack_sizes(n) for n in range(1, 9)] ==
          [[1], [2], [3], [2, 2], [3, 2], [3, 3], [3, 2, 2], [3, 3, 2]],
          "groups of 3, never a lone 1")


def test_apply_rename_reapply_undo_cycle():
    root = tempfile.mkdtemp()
    bdir = tempfile.mkdtemp()
    ext = make_ext(root)
    original = snapshot(root)
    d = E.Design(ctx_for(ext))
    d.suggest_all()
    res = E.apply_design(d.ctx, d.panels, "DLC", True, False, bdir)
    new_ext = os.path.join(root, "DLC.extension")
    tab = os.path.join(new_ext, "DLC.tab")
    check(os.path.isdir(tab) and not os.path.exists(ext), "renamed both")
    check(res.renamed == [("SDC.tab", "DLC.tab"),
                          ("SDC.extension", "DLC.extension")], "renames")
    bad, rib = ribbon(tab)
    check(bad == [], "pyRevit rules after apply: %s" % bad)
    check(rib["Coordination"][0] == ["Stair Transfer"] and
          len(rib["Coordination"]) == 2 and len(rib["Coordination"][1]) == 3,
          "Coordination ribbon %s" % rib["Coordination"])
    check("Delete Duplicates[title:Delete Duplicates]" in
          rib["Coordination"][1], "2-line titles made 1-line when small")
    check(rib["Rooms"][0] == ["Room Serial"] and
          [len(c) for c in rib["Rooms"]] == [1, 2, 2], "Rooms %s" % rib["Rooms"])
    rb = yaml.safe_load(open(os.path.join(tab, "Rooms.panel", "bundle.yaml")))
    check(rb["background"] == "#123456", "other bundle keys kept")
    check(os.path.isfile(os.path.join(tab, "Tools.panel",
                                      "Tab Designer.pushbutton", "bd_family_cleaner.py")),
          "designer never moved")
    check(os.path.exists(os.path.join(new_ext, ".hidden")), "hidden kept")
    check(any("installer.ps1" in h[0] for h in res.name_refs) and
          not any("notes.py" in h[0] for h in res.name_refs),
          "old names found, SDC_ parameters ignored")
    check(os.path.exists(res.backup), "backup zip exists")
    after1 = snapshot(root)

    # re-open from the moved button: shows what was applied
    d2 = E.Design(ctx_for(new_ext))
    check(modes(d2) == modes(d), "re-scan reproduces the applied design")
    # re-apply unchanged -> identical
    E.apply_design(d2.ctx, d2.panels, "DLC", True, False, bdir)
    check(ribbon(tab) == (bad, rib), "re-apply is stable")
    # edit: Reset Colours into More, Room Gaps large, reorder
    d3 = E.Design(ctx_for(new_ext))
    co = d3.panels[0]
    rc = [i for i in co.items if i.label == "Reset Colours"][0]
    d3.set_mode(rc, "MORE")
    d3.index = 2
    rg = [i for i in d3.panel.items if i.label == "Room Gaps"][0]
    d3.set_mode(rg, "BIG")
    d3.move(rg, -10)                     # no-op past the end
    while d3.move(rg, -1):
        pass
    E.apply_design(d3.ctx, d3.panels, "DLC", True, False, bdir)
    bad3, rib3 = ribbon(tab)
    check(bad3 == [], "rules after edit %s" % bad3)
    check(rib3["Rooms"][0] == ["Room Gaps"], "moved to first: %s"
          % rib3["Rooms"])
    more = os.path.join(tab, "Coordination.panel", "DLC Stack 1.stack",
                        "More.pulldown")
    check(os.path.isdir(os.path.join(more, "Reset Colours.pushbutton")),
          "Reset Colours in More")
    check("Reset Colours[title:Reset Colours]" in
          yaml.safe_load(open(os.path.join(more, "bundle.yaml")))["layout"],
          "title fix carried into More")

    # undo x3 walks back to the original
    ctx = ctx_for(new_ext)
    check(len(E.undo_entries(bdir, ctx)) == 3, "3 applies to undo here")
    E.undo_last(bdir, ctx)
    E.undo_last(bdir, ctx_for(new_ext))
    check(snapshot(root) == after1, "two undos -> first apply state")
    name, safety = E.undo_last(bdir, ctx_for(new_ext))
    check(name == "SDC.extension" and snapshot(root) == original,
          "third undo -> exact original")
    check(os.path.exists(safety), "state before undo kept as a zip")
    try:
        E.undo_last(bdir, ctx_for(ext))
        FAILED.append("nothing left to undo")
    except E.DesignerError:
        PASSED[0] += 1
    shutil.rmtree(root)
    shutil.rmtree(bdir)


def test_copied_extension_is_independent():
    a = tempfile.mkdtemp()
    b = tempfile.mkdtemp()
    bdir = tempfile.mkdtemp()
    ext_a = make_ext(a)
    d = E.Design(ctx_for(ext_a))
    d.suggest_all()
    E.apply_design(d.ctx, d.panels, "DLC", True, False, bdir)
    # copy the restyled extension to another folder / PC
    shutil.copytree(os.path.join(a, "DLC.extension"),
                    os.path.join(b, "DLC.extension"))
    ctx_b = ctx_for(os.path.join(b, "DLC.extension"))
    check(ctx_b.root == b, "copy finds its own folder")
    check(E.undo_entries(bdir, ctx_b) == [],
          "undo history of folder A never touches the copy in B")
    db = E.Design(ctx_b)
    check(modes(db) == modes(d), "copy shows the same design")
    E.apply_design(ctx_b, db.panels, "DLC", True, False, bdir)
    check(ribbon(os.path.join(b, "DLC.extension", "DLC.tab"))[0] == [],
          "apply works in the copy")
    for x in (a, b, bdir):
        shutil.rmtree(x)


def test_refuses_before_changing_anything():
    root = tempfile.mkdtemp()
    bdir = tempfile.mkdtemp()
    ext = make_ext(root)
    os.makedirs(os.path.join(ext, "SDC.tab", "Doors.panel", "More.pulldown",
                             "Mine.pushbutton"))
    snap = snapshot(root)
    d = E.Design(ctx_for(ext))
    doors = [p for p in d.panels if p.label == "Doors"][0]
    d.set_mode([i for i in doors.items if i.label == "Fill Hardware"][0],
               "MORE")
    try:
        E.apply_design(d.ctx, d.panels, "DLC", True, False, bdir)
        FAILED.append("own More folder should block")
    except E.DesignerError as ex:
        check("Nothing was changed" in str(ex) and "More.pulldown" in str(ex),
              "explains the clash")
    check(snapshot(root) == snap and E.read_history(bdir) == [],
          "nothing changed, no backup recorded")
    for bad in ("", "  ", "A/B", "X:", "Tab."):
        check(E.check_name(bad) is not None, "name %r rejected" % bad)
    check(E.check_name("DLC Tools") is None, "spaces ok")
    # without MORE tools in Doors, your own More pulldown is just a tool
    d = E.Design(ctx_for(ext))
    check(E.check_panel([p for p in d.panels if p.label == "Doors"][0]) == [],
          "own More pulldown fine when More isn't used")
    os.makedirs(os.path.join(root, "DLC.extension"))
    d = E.Design(ctx_for(ext))
    try:
        E.apply_design(d.ctx, d.panels, "DLC", True, False, bdir)
        FAILED.append("existing DLC.extension should block")
    except E.DesignerError as ex:
        check("already exists" in str(ex), "existing target folder reported")
    try:
        d.set_mode(d.panels[-1].items[-1], "SMALL")
        FAILED.append("locked designer can't go small")
    except E.DesignerError:
        PASSED[0] += 1
    shutil.rmtree(root)
    shutil.rmtree(bdir)


def test_onedrive_lock_retry_and_midway_failure():
    root = tempfile.mkdtemp()
    bdir = tempfile.mkdtemp()
    ext = make_ext(root)
    original = snapshot(root)
    real_rename = os.rename
    fails = {"n": 2}

    def flaky(a, b):
        if fails["n"] > 0 and a.endswith(".tab"):
            fails["n"] -= 1
            raise OSError(13, "Access is denied (OneDrive)")
        return real_rename(a, b)
    os.rename = flaky
    try:
        d = E.Design(ctx_for(ext))
        d.suggest_all()
        E.apply_design(d.ctx, d.panels, "DLC", False, False, bdir)
    finally:
        os.rename = real_rename
    check(os.path.isdir(os.path.join(ext, "DLC.tab")),
          "brief lock retried and succeeded")
    E.undo_last(bdir, ctx_for(ext))
    check(snapshot(root) == original, "undo after lock test")

    def always(a, b):
        if a.endswith(".extension"):
            raise OSError(32, "used by another process")
        return real_rename(a, b)
    os.rename = always
    try:
        d = E.Design(ctx_for(ext))
        d.suggest_all()
        E.apply_design(d.ctx, d.panels, "DLC", True, False, bdir)
        FAILED.append("locked extension folder should fail")
    except E.DesignerError as ex:
        check("synced (OneDrive)" in str(ex), "friendly lock message")
    finally:
        os.rename = real_rename
    tab = os.path.join(ext, "DLC.tab")
    check(ribbon(tab)[0] == [], "half-way state is still a valid ribbon")
    E.undo_last(bdir, ctx_for(ext))
    check(snapshot(root) == original, "undo restores after a midway failure")
    shutil.rmtree(root)
    shutil.rmtree(bdir)


def test_titles_in_every_yaml_style():
    root = tempfile.mkdtemp()
    d = E.Design(ctx_for(make_ext(root)))
    rooms = [p for p in d.panels if p.label == "Rooms"][0]
    labels = [i.label for i in rooms.items]
    check("Room Serial" in labels and "|-" not in labels,
          "block scalar title read: %s" % labels)
    check("Room Doctor" in labels, "localised title read (en_us)")
    check(E.yaml_title("title: >-\n  Long\n  Name\n") == "Long Name",
          "folded scalar")
    check(E.yaml_title('title: "A\\nB"') == "A\\nB" and
          E.one_line(E.yaml_title('title: "A\\nB"')) == "A B", "quoted \\n")
    check(E.yaml_title("tooltip: x\n") is None, "no title -> None")
    d.suggest_all()
    bdir = tempfile.mkdtemp()
    E.apply_design(d.ctx, d.panels, "SDC", False, False, bdir)
    tab = os.path.join(root, "SDC.extension", "SDC.tab")
    bad, rib = ribbon(tab)
    flat = [x for c in rib["Rooms"] for x in c]
    check(bad == [] and "Room Serial" in flat,
          "Room Serial large keeps its own title: %s" % rib["Rooms"])
    shutil.rmtree(root)
    shutil.rmtree(bdir)


def test_reapply_when_marker_files_vanished():
    # the reported error: 2nd run said "your own folder 'DLC Stack 1.stack'"
    # because the marker file inside it was gone
    root = tempfile.mkdtemp()
    bdir = tempfile.mkdtemp()
    ext = make_ext(root)
    d = E.Design(ctx_for(ext))
    d.suggest_all()
    co = d.panels[0]
    d.set_mode([i for i in co.items if i.label == "Reset Colours"][0], "MORE")
    E.apply_design(d.ctx, d.panels, "DLC", True, False, bdir)
    new_ext = os.path.join(root, "DLC.extension")
    tab = os.path.join(new_ext, "DLC.tab")
    first = ribbon(tab)
    removed = 0
    for r, ds, fs in os.walk(tab):
        if E.MARKER in fs:
            os.remove(os.path.join(r, E.MARKER))
            removed += 1
    check(removed >= 3, "markers removed (%d)" % removed)
    d2 = E.Design(ctx_for(new_ext))
    check(modes(d2) == modes(d), "still recognised as the applied design")
    try:
        E.apply_design(d2.ctx, d2.panels, "DLC", True, False, bdir)
        PASSED[0] += 1
    except E.DesignerError as ex:
        FAILED.append("second apply refused: %s" % ex)
    check(ribbon(tab) == first, "second apply gives the same ribbon")
    check(not [x for x in os.listdir(os.path.join(tab, "Coordination.panel"))
               if x.startswith("DLC Stack 2")], "no duplicate stacks")
    shutil.rmtree(root)
    shutil.rmtree(bdir)


def test_fix_refs_option():
    root = tempfile.mkdtemp()
    bdir = tempfile.mkdtemp()
    ext = make_ext(root)
    d = E.Design(ctx_for(ext))
    res = E.apply_design(d.ctx, d.panels, "DLC", True, True, bdir)
    new_ext = os.path.join(root, "DLC.extension")
    inst = open(os.path.join(new_ext, "installer.ps1")).read()
    check("DLC.extension\\DLC.tab" in inst and res.fixed_files >= 1,
          "names fixed: %s" % inst)
    notes = open(os.path.join(new_ext, "DLC.tab", "Doors.panel",
                              "Write Door Data.pushbutton", "notes.py")).read()
    check("SDC_Door_Number" in notes, "SDC_ parameter untouched")
    shutil.rmtree(root)
    shutil.rmtree(bdir)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                FAILED.append("%s crashed: %s" % (name, ex))
    print("engine: %d assertions passed, %d failed" % (PASSED[0], len(FAILED)))
    for f in FAILED:
        print("  FAIL: " + f)
    sys.exit(1 if FAILED else 0)
