# -*- coding: utf-8 -*-
"""Tests for DLC Select By Parameter. Run: python3 test_selectby.py"""
import os
import sys
import random
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
BUTTON = os.path.join(HERE, "..", "DLC.extension", "DLC.tab", "Select.panel",
                      "Select By Parameter.pushbutton")
sys.path.insert(0, BUTTON)
sys.path.insert(0, HERE)

import dlc_selectby_engine as eng  # noqa: E402
import script as tool  # noqa: E402  (imports fine without Revit)
import fake_revit as fr  # noqa: E402


# ---------------------------------------------------------------------------
class FakeProvider(object):
    def __init__(self, scopes, cats, params, values):
        self._scopes = scopes
        self._cats = cats          # scope -> [(key, name, ids)]
        self._params = params      # list of names
        self._values = values      # param -> {id: value}
        self.value_calls = 0

    def available_scopes(self):
        return list(self._scopes)

    def categories(self, scope):
        return self._cats.get(scope, [])

    def parameter_names(self, ids):
        return list(self._params)

    def values(self, ids, name):
        self.value_calls += 1
        src = self._values.get(name, {})
        return dict((i, src.get(i)) for i in ids)


def simple_provider():
    cats = {
        "view": [(1, "Rooms", [10, 11, 12]), (2, "Doors", [20])],
        "model": [(1, "Rooms", [10, 11, 12, 13]), (2, "Doors", [20, 21]),
                  (3, "Walls", [])],
    }
    values = {"Level": {10: "L01", 11: "L01", 12: "L02", 13: "L10", 20: "L01", 21: None},
              "Name": {10: "Office", 11: "WC", 12: "Office", 13: "  "}}
    return FakeProvider(["model", "view"], cats, ["Name", "Level", "Level"], values)


# ---------------------------------------------------------------------------
class EngineBasics(unittest.TestCase):
    def test_natural_sort(self):
        vals = ["L10", "L2", "l1", "Room 9", "Room 10", "B1", "B01", ""]
        out = sorted(vals, key=eng.natural_key)
        self.assertEqual(out[:4], ["", "B1", "B01", "l1"])
        self.assertLess(out.index("L2"), out.index("L10"))
        self.assertLess(out.index("Room 9"), out.index("Room 10"))

    def test_natural_key_never_mixes_types(self):
        rnd = random.Random(7)
        alphabet = "ab01 9.-_"
        for _ in range(3000):
            a = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 8)))
            b = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 8)))
            eng.natural_key(a) < eng.natural_key(b)  # must not raise

    def test_normalize(self):
        self.assertEqual(eng.normalize_value(None), eng.EMPTY_LABEL)
        self.assertEqual(eng.normalize_value("   "), eng.EMPTY_LABEL)
        self.assertEqual(eng.normalize_value(" A "), u"A")
        self.assertEqual(eng.normalize_value(12), u"12")

    def test_search(self):
        self.assertTrue(eng.matches_search("Plumbing Fixtures", "fix plum"))
        self.assertFalse(eng.matches_search("Doors", "door x"))
        self.assertTrue(eng.matches_search("anything", "   "))
        self.assertTrue(eng.matches_search(u"Façade Panel", u"FAÇ"))

    def test_value_index(self):
        idx = eng.build_value_index({1: "L10", 2: "L2", 3: None, 4: "L2", 5: ""})
        self.assertEqual([e.value for e in idx], ["L2", "L10", eng.EMPTY_LABEL])
        self.assertEqual(idx[0].ids, [2, 4])
        self.assertEqual(idx[2].ids, [3, 5])
        self.assertEqual(idx[0].label, u"L2  (2)")

    def test_value_index_empty_label_text_collides(self):
        # a real value spelled "<empty>" merges with empties - documented, harmless
        idx = eng.build_value_index({1: "<empty>", 2: None})
        self.assertEqual(len(idx), 1)

    def test_build_categories_drops_empty_and_merges(self):
        cats = eng.build_categories([(1, "Rooms", [1, 2]), (2, "Walls", []),
                                     (1, "Rooms", [2, 3])])
        self.assertEqual([c.name for c in cats], ["Rooms"])
        self.assertEqual(cats[0].ids, [1, 2, 3])

    def test_unicode_labels(self):
        e = eng.CategoryEntry(1, u"Pièces", [1])
        self.assertEqual(e.label, u"Pièces  (1)")


class ControllerFlow(unittest.TestCase):
    def setUp(self):
        self.p = simple_provider()
        self.c = eng.SelectController(self.p)

    def test_scope_order_and_default(self):
        self.assertEqual(self.c.scopes, ["view", "model"])
        self.assertEqual(self.c.scope, "view")
        self.assertEqual([x.name for x in self.c.categories], ["Doors", "Rooms"])

    def test_no_category_means_nothing(self):
        self.assertEqual(self.c.matched_ids(), [])
        self.assertFalse(self.c.can_apply())
        self.assertEqual(self.c.status_text(), u"Pick a category.")

    def test_category_only_selects_all(self):
        self.c.set_category(1)
        self.assertEqual(self.c.matched_ids(), [10, 11, 12])
        self.assertTrue(self.c.can_apply())
        self.assertIn(u"3 Rooms", self.c.status_text())

    def test_param_list_deduped_sorted_with_no_filter_first(self):
        self.c.set_category(1)
        self.assertEqual(self.c.param_choices(),
                         [eng.NO_FILTER_LABEL, "Level", "Name"])

    def test_single_and_multi_value(self):
        self.c.set_category(1)
        self.c.set_param("Level")
        self.assertEqual([v.value for v in self.c.values], ["L01", "L02"])
        self.assertFalse(self.c.can_apply())
        self.c.set_checked("L01", True)
        self.assertEqual(self.c.matched_ids(), [10, 11])
        self.c.set_checked("L02", True)
        self.assertEqual(self.c.matched_ids(), [10, 11, 12])
        self.assertIn(u"3 of 3", self.c.status_text())
        self.c.set_checked("L01", False)
        self.assertEqual(self.c.matched_ids(), [12])

    def test_value_search_and_check_visible(self):
        self.c.set_scope("model")
        self.c.set_category(1)
        self.c.set_param("Level")
        self.c.value_search = "l1"
        self.assertEqual([v.value for v in self.c.visible_values()], ["L10"])
        self.c.check_visible(True)
        self.assertEqual(self.c.checked, set(["L10"]))
        self.c.value_search = ""
        self.c.check_visible(True)
        self.assertEqual(self.c.matched_ids(), [10, 11, 12, 13])
        self.c.check_visible(False)
        self.assertEqual(self.c.matched_ids(), [])

    def test_empty_values_selectable(self):
        self.c.set_scope("model")
        self.c.set_category(1)
        self.c.set_param("Name")
        self.assertEqual(self.c.values[-1].value, eng.EMPTY_LABEL)
        self.c.set_checked(eng.EMPTY_LABEL, True)
        self.assertEqual(self.c.matched_ids(), [13])

    def test_no_filter_choice_resets(self):
        self.c.set_category(1)
        self.c.set_param("Level")
        self.c.set_checked("L01", True)
        self.c.set_param(eng.NO_FILTER_LABEL)
        self.assertIsNone(self.c.param)
        self.assertEqual(self.c.checked, set())
        self.assertEqual(self.c.matched_ids(), [10, 11, 12])

    def test_scope_switch_keeps_choices(self):
        self.c.set_category(1)
        self.c.set_param("Level")
        self.c.set_checked("L01", True)
        self.c.set_checked("L02", True)
        self.c.set_scope("model")
        self.assertEqual(self.c.category.key, 1)
        self.assertEqual(self.c.param, "Level")
        self.assertEqual(self.c.checked, set(["L01", "L02"]))
        self.assertEqual(self.c.matched_ids(), [10, 11, 12])

    def test_scope_switch_drops_values_not_present(self):
        self.c.set_scope("model")
        self.c.set_category(1)
        self.c.set_param("Level")
        self.c.set_checked("L10", True)
        self.c.set_scope("view")
        self.assertEqual(self.c.checked, set())
        self.assertFalse(self.c.can_apply())

    def test_scope_switch_category_missing(self):
        self.c.set_scope("model")
        self.c.set_category(3)  # Walls is empty -> dropped -> None
        self.assertIsNone(self.c.category)
        self.c.set_category(2)
        self.c.set_scope("view")
        self.assertEqual(self.c.category.key, 2)

    def test_category_switch_keeps_shared_param(self):
        self.c.set_scope("model")
        self.c.set_category(1)
        self.c.set_param("Level")
        self.c.set_checked("L01", True)
        self.c.set_category(2)
        self.assertEqual(self.c.param, "Level")
        self.assertEqual(self.c.matched_ids(), [20])

    def test_category_search(self):
        self.c.category_search = "roo"
        self.assertEqual([x.key for x in self.c.visible_categories()], [1])

    def test_bad_inputs(self):
        self.assertRaises(ValueError, self.c.set_scope, "selection")
        self.c.set_category(1)
        self.assertRaises(ValueError, self.c.set_param, "Nope")
        self.c.set_category(999)
        self.assertIsNone(self.c.category)
        self.assertEqual(self.c.matched_ids(), [])

    def test_matched_ids_are_subset_property(self):
        rnd = random.Random(3)
        for _ in range(300):
            ids = list(range(rnd.randint(1, 40)))
            vals = dict((i, rnd.choice(["A", "B", "C", None, ""])) for i in ids)
            p = FakeProvider(["model"], {"model": [(1, "X", ids)]}, ["P"], {"P": vals})
            c = eng.SelectController(p)
            c.set_category(1)
            c.set_param("P")
            pick = set(v.value for v in c.values if rnd.random() < 0.5)
            for v in pick:
                c.set_checked(v, True)
            got = set(c.matched_ids())
            want = set(i for i in ids if eng.normalize_value(vals[i]) in pick)
            self.assertEqual(got, want)
            self.assertEqual(sum(len(v.ids) for v in c.values), len(ids))

    def test_no_scopes(self):
        c = eng.SelectController(FakeProvider([], {}, [], {}))
        self.assertIsNone(c.scope)
        self.assertIn(u"open a model view", c.status_text())


# ---------------------------------------------------------------------------
class RevitProviderTests(unittest.TestCase):
    def make(self, view="plan", selected=(), settings=None):
        elems, plan, sheet = fr.sample_model()
        active = {"plan": plan, "sheet": sheet, "none": None}[view]
        doc = fr.Document(elems, active, {plan.Id.Value: plan, sheet.Id.Value: sheet})
        uidoc = fr.UIDocument([fr.ElementId(i) for i in selected])
        s = dict(tool.SETTINGS)
        s.update(settings or {})
        return tool.RevitProvider(fr.FakeDB, doc, uidoc, s), doc, uidoc

    def cats(self, provider, scope):
        return dict((n, sorted(ids)) for _k, n, ids in provider.categories(scope))

    def test_scopes(self):
        p, _d, _u = self.make()
        self.assertEqual(p.available_scopes(), ["view", "model"])
        p, _d, _u = self.make(selected=[101])
        self.assertEqual(p.available_scopes(), ["view", "model", "selection"])

    def test_sheet_view_disables_view_scope(self):
        p, _d, _u = self.make(view="sheet")
        self.assertEqual(p.available_scopes(), ["model"])
        c = eng.SelectController(p)
        self.assertEqual(c.scope, "model")

    def test_no_active_view(self):
        p, _d, _u = self.make(view="none")
        self.assertEqual(p.available_scopes(), ["model"])

    def test_model_categories(self):
        p, _d, _u = self.make()
        cats = self.cats(p, "model")
        self.assertEqual(sorted(cats), ["Doors", "Levels", "Rooms", "Walls"])
        self.assertEqual(cats["Rooms"], [101, 102, 103, 201, 202, 1001])  # 999 unplaced
        self.assertEqual(cats["Doors"], [301, 302, 303])  # door types excluded

    def test_unplaced_kept_when_setting_off(self):
        p, _d, _u = self.make(settings={"SKIP_UNPLACED_SPATIAL": False})
        self.assertIn(999, self.cats(p, "model")["Rooms"])

    def test_view_scope(self):
        p, _d, _u = self.make()
        cats = self.cats(p, "view")
        self.assertEqual(cats["Rooms"], [101, 102, 103])
        self.assertNotIn("Text Notes", cats)

    def test_selection_scope(self):
        p, _d, _u = self.make(selected=[101, 301, 602, 999])
        cats = self.cats(p, "selection")
        self.assertEqual(cats, {"Rooms": [101], "Doors": [301]})

    def test_collect_is_cached(self):
        p, doc, _u = self.make()
        before = doc.collector_calls
        p.categories("model")
        p.categories("model")
        self.assertEqual(doc.collector_calls, before + 1)

    def test_parameter_names_with_type(self):
        p, _d, _u = self.make()
        ids = self.cats(p, "model")["Doors"]
        names = p.parameter_names(ids)
        self.assertIn("Mark", names)
        self.assertIn("[Type] Fire Rating", names)
        self.assertIn("[Type] Type Mark", names)
        p2, _d, _u = self.make(settings={"INCLUDE_TYPE_PARAMETERS": False})
        ids = self.cats(p2, "model")["Doors"]
        self.assertFalse([n for n in p2.parameter_names(ids) if n.startswith("[Type]")])

    def test_sample_size_limits_reads(self):
        p, _d, _u = self.make(settings={"PARAM_SAMPLE_SIZE": 1})
        ids = self.cats(p, "model")["Walls"]
        self.assertEqual(p.parameter_names(ids), ["Comments"])

    def test_values_all_storage_types(self):
        p, _d, _u = self.make()
        rooms = self.cats(p, "model")["Rooms"]
        lv = p.values(rooms, "Level")       # ElementId, no display -> level name
        self.assertEqual(lv[101], "L01")
        self.assertEqual(lv[1001], "L10")
        area = p.values(rooms, "Area")      # Double with display units
        self.assertEqual(area[102], u"22.50 m²")
        dept = p.values(rooms, "Department")
        self.assertEqual(dept[103], "")
        self.assertIsNone(dept[202])
        doors = self.cats(p, "model")["Doors"]
        fire = p.values(doors, "Is Fire Door")  # Integer: display or fallback
        self.assertEqual((fire[301], fire[302], fire[303]), ("Yes", "No", "0"))
        tfr = p.values(doors, "[Type] Fire Rating")
        self.assertEqual((tfr[301], tfr[303]), ("60 min", ""))
        missing = p.values(doors, "Does Not Exist")
        self.assertEqual(set(missing.values()), set([None]))
        rooms_type = p.values(rooms, "[Type] Fire Rating")  # rooms have no type
        self.assertEqual(set(rooms_type.values()), set([None]))

    def test_end_to_end_select_and_zoom(self):
        p, _d, uidoc = self.make()
        c = eng.SelectController(p)
        c.set_scope("model")
        c.set_category(fr.BuiltInCategory.OST_Rooms)
        c.set_param("Level")
        self.assertEqual([v.value for v in c.values], ["L01", "L02", "L10"])
        c.set_checked("L01", True)
        c.set_checked("L10", True)
        ids = c.matched_ids()
        self.assertEqual(ids, [101, 102, 103, 1001])
        n, z = tool.apply_selection(p, uidoc, ids, tool.SETTINGS,
                                    fr.FakeList(), fr.ElementId)
        self.assertEqual(n, 4)
        self.assertEqual([i.Value for i in uidoc.Selection.ids], ids)
        self.assertEqual(z, 3)  # 1001 is on L10, not in the L01 plan
        self.assertEqual([i.Value for i in uidoc.shown[0]], [101, 102, 103])

    def test_zoom_skipped_when_nothing_visible_or_off(self):
        p, _d, uidoc = self.make()
        c = eng.SelectController(p)
        c.set_scope("model")
        c.set_category(fr.BuiltInCategory.OST_Rooms)
        n, z = tool.apply_selection(p, uidoc, [201, 202], tool.SETTINGS,
                                    fr.FakeList(), fr.ElementId)
        self.assertEqual((n, z, uidoc.shown), (2, 0, []))
        s = dict(tool.SETTINGS, ZOOM_TO_SELECTION=False)
        n, z = tool.apply_selection(p, uidoc, [101], s, fr.FakeList(), fr.ElementId)
        self.assertEqual((n, z, uidoc.shown), (1, 0, []))

    def test_zoom_failure_does_not_break_selection(self):
        elems, plan, _s = fr.sample_model()
        doc = fr.Document(elems, plan)
        uidoc = fr.UIDocument(fail_show=True)
        p = tool.RevitProvider(fr.FakeDB, doc, uidoc, tool.SETTINGS)
        p.categories("view")
        n, z = tool.apply_selection(p, uidoc, [101], tool.SETTINGS,
                                    fr.FakeList(), fr.ElementId)
        self.assertEqual((n, z), (1, 0))
        self.assertEqual(len(uidoc.Selection.set_calls), 1)

    def test_zoom_on_sheet_view_is_skipped(self):
        p, _d, uidoc = self.make(view="sheet")
        p.categories("model")
        n, z = tool.apply_selection(p, uidoc, [101], tool.SETTINGS,
                                    fr.FakeList(), fr.ElementId)
        self.assertEqual((n, z), (1, 0))


# ---------------------------------------------------------------------------
class PackagingChecks(unittest.TestCase):
    def test_xaml_parses_and_names_match(self):
        root = ET.fromstring(tool.XAML.encode("utf-8"))
        xns = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
        names = set(el.get(xns) for el in root.iter() if el.get(xns))
        self.assertEqual(names, set(tool.XAML_NAMES))
        src = open(os.path.join(BUTTON, "bd_family_cleaner.py")).read()
        import re
        used = set(re.findall(r"self\.((?:rb|tb|lb|cb|btn|tx)_[a-z_]+)", src))
        self.assertTrue(used <= names, used - names)

    def test_settings_shape(self):
        for key in ("ZOOM_TO_SELECTION", "SKIP_UNPLACED_SPATIAL",
                    "INCLUDE_TYPE_PARAMETERS", "PARAM_SAMPLE_SIZE",
                    "EXCLUDED_CATEGORIES", "EXTRA_CATEGORIES", "DEFAULT_SCOPE"):
            self.assertIn(key, tool.SETTINGS)
        self.assertIn(tool.SETTINGS["DEFAULT_SCOPE"], eng.SCOPE_ORDER)

    def test_bundle_yaml_present(self):
        self.assertTrue(os.path.isfile(os.path.join(BUTTON, "bundle.yaml")))
        self.assertTrue(os.path.isfile(os.path.join(BUTTON, "icon.png")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
