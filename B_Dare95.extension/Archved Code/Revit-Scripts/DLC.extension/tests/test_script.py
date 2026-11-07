# -*- coding: utf-8 -*-
"""Script-layer tests against the fake Revit API. Run: python tests/test_script.py"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import fake_revit as F  # noqa: E402

env = F.install()
from dlc_stairxfer import engine as E  # noqa: E402

SCRIPT = os.path.join(ROOT, "DLC.tab", "Coordination.panel",
                      "Stair Transfer.pushbutton", "bd_family_cleaner.py")

PASSED = [0]
FAILED = []


def check(cond, msg):
    if cond:
        PASSED[0] += 1
    else:
        FAILED.append(msg)


def mm(v):
    return E.mm(v)


def near(a, b, tol=0.05):
    return abs(E.to_mm(a) - E.to_mm(b)) <= tol


# ----------------------------------------------------------------- models
def build(link_dz_mm=0.0):
    F.Element._next[0] = 1000
    F.CopyConfig.fail_with_railings = False
    F.CopyConfig.calls = []
    arch = F.FakeDoc("ARCH")
    A = {}
    for n, z in [("GF FFL", 0), ("L01 FFL", 3500), ("L02 FFL", 7000),
                 ("L03 FFL", 10500), ("ROOF FFL", 14000)]:
        A[n] = arch.add(F.Level(n, mm(z)))
    stype = arch.add(F.StairsType("Concrete 175", mm(180)))
    # pinned group: one reference stair on GF, repeated at L01 and L02
    ref = arch.add(F.Stairs("ref", A["GF FFL"], 0.0, A["L01 FFL"], 0.0, 20,
                            stype.Id))
    rail = arch.add(F.Railing(ref))
    ref.railings = [rail.Id]
    # unpinned last flight L03 -> ROOF, starting 0 / ending 0
    top = arch.add(F.Stairs("top", A["L03 FFL"], 0.0, A["ROOF FFL"], 0.0, 20,
                            stype.Id))
    ms = arch.add(F.MultistoryStairs(
        [(ref, [A["GF FFL"], A["L01 FFL"], A["L02 FFL"]]),
         (top, [A["L03 FFL"]])]))
    ms.cat = "OST_MultistoryStairs"

    st = F.FakeDoc("STR")
    S = {}
    for n, z in [("GF SSL", -150), ("L01 SSL", 3400), ("L02 SSL", 6920),
                 ("L03 SSL", 10400), ("ROOF SSL", 13750),
                 ("L01 FFL ref", 3500)]:   # a reference level that must be unticked
        S[n] = st.add(F.Level(n, mm(z + link_dz_mm)))
    xform = F.Transform(5.0, 7.0, mm(link_dz_mm))
    li = st.add(F.RevitLinkInstance("ARCH.rvt : 1", arch, xform))
    lt = st.add(F.ElementType("ARCH.rvt"))
    li.type_id = lt.Id
    st.Application.Documents = [st, arch]
    return arch, st, A, S, ms, ref, top, rail, xform


def load_script(str_doc, settings=None):
    env.revit.doc = str_doc
    env.revit.uidoc = None
    spec = importlib.util.spec_from_file_location("dlc_stair_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if settings:
        mod.SETTINGS.update(settings)
    return mod


EXPECT = [  # base, top, height (mm)
    ("GF SSL", "L01 SSL", 3550), ("L01 SSL", "L02 SSL", 3520),
    ("L02 SSL", "L03 SSL", 3480), ("L03 SSL", "ROOF SSL", 3350)]


# ----------------------------------------------------------------- tests
def test_collect_jobs_expands_multistorey():
    arch, st, A, S, ms, ref, top, rail, xf = build()
    m = load_script(st)
    src = m.Source(arch, xf, "ARCH")
    # pick a RUN of the reference stair -> must resolve to the whole ms
    jobs = m.collect_jobs([(src, F.StairsRun(ref)), (src, top), (src, ms)])
    check(len(jobs) == 4, "4 flights, got %d" % len(jobs))
    dzs = sorted(round(E.to_mm(j.dz)) for j in jobs)
    check(dzs == [0, 0, 3500, 7000], "dz set %s" % dzs)
    check(all(j.railing_ids == [rail.Id] for j in jobs if j.stairs is ref),
          "railings attached to reference flights")


def run_copy(link_dz_mm=0.0, settings=None, fail_rails=False):
    arch, st, A, S, ms, ref, top, rail, xf = build(link_dz_mm)
    m = load_script(st, settings)
    F.CopyConfig.fail_with_railings = fail_rails
    src = m.Source(arch, xf, "ARCH")
    jobs = m.collect_jobs([(src, ms)])
    strs = [S[n] for n in S if "SSL" in n]
    str_by_key = dict((m.eid_val(l.Id), l) for l in strs)
    recs = [E.LevelRec(m.eid_val(l.Id), l._name, l.ProjectElevation)
            for l in strs]
    arecs = [E.LevelRec(m.eid_val(l.Id), l._name, src.z(l.ProjectElevation))
             for l in arch.levels()]
    before = set(m.eid_val(l.Id) for l in st.levels())
    res = []
    opts = F.CopyPasteOptions()
    for j in sorted(jobs, key=lambda j: j.flight.base_elev + j.flight.dz):
        p = E.plan_flight(j.flight, arecs, recs, m.SETTINGS)
        check(p.ok, "plan ok %s" % p.error)
        new_st, note = m.copy_flight(j, p, opts, str_by_key, None)
        res.append((p, new_st, note))
    removed, kept = m.cleanup_new_levels(before, set(str_by_key.keys()))
    return st, S, res, removed, kept


def test_copy_rehosts_each_flight_slab_to_slab():
    st, S, res, removed, kept = run_copy()
    check(len(res) == 4, "4 stairs created")
    P = F.BuiltInParameter
    for (p, s, note), (b, t, h) in zip(res, EXPECT):
        bl = st.GetElement(s.params[P.STAIRS_BASE_LEVEL_PARAM].v)
        tl = st.GetElement(s.params[P.STAIRS_TOP_LEVEL_PARAM].v)
        check(bl is S[b], "base %s got %s" % (b, bl._name))
        check(tl is S[t], "top %s got %s" % (t, tl._name))
        check(near(s.params[P.STAIRS_BASE_OFFSET].v, 0), "base off 0")
        check(near(s.params[P.STAIRS_TOP_OFFSET].v, 0), "top off 0")
        check(near(s.Height, mm(h)), "height %s got %.1f"
              % (h, E.to_mm(s.Height)))
        check(s.ActualRisersNumber == 20, "risers kept 20")
        check(note == [], "no notes %s" % note)


def test_levels_created_by_copy_are_removed():
    st, S, res, removed, kept = run_copy()
    check(sorted(removed) == ["GF FFL", "L01 FFL", "L03 FFL", "ROOF FFL"],
          "removed %s" % removed)
    check(not [l for l in st.levels() if l._name.endswith(" FFL")],
          "every level the copy created is gone")
    check(kept == [], "nothing kept %s" % kept)
    check("L01 FFL ref" in [l._name for l in st.levels()],
          "pre-existing STR level untouched")


def test_link_moved_vertically():
    # link and STR both 25 m up in host frame: result identical
    st, S, res, removed, kept = run_copy(link_dz_mm=25000)
    for (p, s, note), (b, t, h) in zip(res, EXPECT):
        check(near(s.Height, mm(h)), "shifted frame height %s" % h)


def test_railing_failure_retries_without_rails():
    st, S, res, removed, kept = run_copy(fail_rails=True)
    check(len(res) == 4, "still 4 stairs")
    noted = [r for r in res if any("railings not copied" in n for n in r[2])]
    check(len(noted) == 3, "3 reference flights noted, got %d" % len(noted))
    check(F.CopyConfig.calls.count(1) >= 3, "retried with stair only")


def test_rehost_survives_order_conflict():
    # Base level moved ABOVE the copied top: setting top first must win
    arch, st, A, S, ms, ref, top, rail, xf = build()
    m = load_script(st)
    P = F.BuiltInParameter
    hi = st.add(F.Level("tmp hi", mm(20000)))
    lo = st.add(F.Level("tmp lo", mm(19000)))
    s = st.add(F.Stairs("x", lo, 0.0, hi, 0.0, 20, None))
    plan = E.FlightPlan()
    plan.base_level = E.LevelRec(m.eid_val(S["L02 SSL"].Id), "L02 SSL", 0)
    plan.top_level = E.LevelRec(m.eid_val(S["L03 SSL"].Id), "L03 SSL", 0)
    plan.base_offset = plan.top_offset = 0.0
    plan.source = E.FlightSource("k", "x", 0, 0, 0, 0, 20)
    sbk = {m.eid_val(S["L02 SSL"].Id): S["L02 SSL"],
           m.eid_val(S["L03 SSL"].Id): S["L03 SSL"]}
    m.apply_levels(s, plan, sbk)
    check(s.params[P.STAIRS_BASE_LEVEL_PARAM].v == S["L02 SSL"].Id and
          s.params[P.STAIRS_TOP_LEVEL_PARAM].v == S["L03 SSL"].Id,
          "levels applied despite order")
    # now the reverse: base must go first (new top below old base)
    s2 = st.add(F.Stairs("y", hi, 0.0, st.add(F.Level("tmp hh", mm(23000))),
                         0.0, 20, None))
    plan.base_level = E.LevelRec(m.eid_val(S["GF SSL"].Id), "GF SSL", 0)
    plan.top_level = E.LevelRec(m.eid_val(S["L01 SSL"].Id), "L01 SSL", 0)
    sbk = {m.eid_val(S["GF SSL"].Id): S["GF SSL"],
           m.eid_val(S["L01 SSL"].Id): S["L01 SSL"]}
    st.els.pop(s.Id)  # isolate regenerate checks to s2
    m.apply_levels(s2, plan, sbk)
    check(s2.params[P.STAIRS_TOP_LEVEL_PARAM].v == S["L01 SSL"].Id,
          "reverse order handled")


def test_main_end_to_end_open_doc_route():
    arch, st, A, S, ms, ref, top, rail, xf = build()
    m = load_script(st, {"STR_LEVEL_NAME_CONTAINS": "SSL"})
    m.forms.CommandSwitchWindow = type("C", (), {"show": staticmethod(
        lambda opts, **k: "Choose from open arch model")})

    def select(items, **k):
        title = k.get("title", "")
        if title == "Architecture model":
            return "ARCH"
        if title == "Stairs to copy":
            return [i for i in items if i.startswith("Multistorey")]
        if title.startswith("Structural"):
            names = [i.name for i in items if i.checked]
            check(not any("FFL ref" in n for n in names),
                  "reference FFL level unticked by name filter")
            check(all("mm)" in n for n in names), "labels show elevation")
            return [i.item for i in items if i.checked]
        raise AssertionError(title)
    m.forms.SelectFromList = type("S", (), {"show": staticmethod(select)})
    alerts = []
    m.forms.alert = lambda msg, **k: alerts.append(msg) or True
    n_before = len([e for e in st.els.values() if isinstance(e, F.Stairs)])
    m.main()
    made = [e for e in st.els.values() if isinstance(e, F.Stairs)]
    check(len(made) - n_before == 4, "main created 4 stairs")
    check(any("4 stair(s) created, 0 failed" in a for a in alerts),
          "final alert %s" % alerts[-1:])
    check(not any(l._name.endswith(" FFL") for l in st.levels()),
          "no stray FFL levels left")


def test_dry_run_changes_nothing():
    arch, st, A, S, ms, ref, top, rail, xf = build()
    m = load_script(st, {"DRY_RUN": True, "STR_LEVEL_NAME_CONTAINS": "SSL"})
    m.forms.CommandSwitchWindow = type("C", (), {"show": staticmethod(
        lambda opts, **k: "Choose from open arch model")})
    m.forms.SelectFromList = type("S", (), {"show": staticmethod(
        lambda items, **k: "ARCH" if k["title"] == "Architecture model" else
        ([i for i in items if i.startswith("Multi")]
         if k["title"] == "Stairs to copy" else
         [i.item for i in items if i.checked]))})
    m.forms.alert = lambda *a, **k: True
    count = len(st.els)
    m.main()
    check(len(st.els) == count, "dry run made no elements")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                FAILED.append("%s crashed: %s" % (name, ex))
    print("script: %d assertions passed, %d failed" % (PASSED[0], len(FAILED)))
    for f in FAILED:
        print("  FAIL: " + f)
    sys.exit(1 if FAILED else 0)
