# -*- coding: utf-8 -*-
"""Minimal Revit API stand-in that reproduces the behaviour the tool relies
on, including failure modes (views that refuse collectors, unplaced rooms,
parameters with no value, element-id parameters)."""


class ElementId(object):
    def __init__(self, value):
        self.Value = int(value)

    def __eq__(self, other):
        return isinstance(other, ElementId) and other.Value == self.Value

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.Value)

    def __repr__(self):
        return "ElementId(%d)" % self.Value


ElementId.InvalidElementId = ElementId(-1)


class BuiltInCategory(object):
    OST_Rooms = -2000160
    OST_Doors = -2000023
    OST_Walls = -2000011
    OST_Levels = -2000240
    OST_Grids = -2000220
    OST_Cameras = -2000500
    OST_TextNotes = -2000300
    OST_ProjectInformation = -2003101
    OST_Materials = -2000700
    # names like OST_InternalOrigin intentionally missing: must be ignored


class CategoryType(object):
    Model = "Model"
    Annotation = "Annotation"


class StorageType(object):
    String = "String"
    Integer = "Integer"
    Double = "Double"
    ElementId = "ElementId"
    None_ = "None"


class Category(object):
    def __init__(self, bic, name, ctype):
        self.Id = ElementId(bic)
        self.Name = name
        self.CategoryType = ctype


CATS = {
    "Rooms": Category(BuiltInCategory.OST_Rooms, "Rooms", CategoryType.Model),
    "Doors": Category(BuiltInCategory.OST_Doors, "Doors", CategoryType.Model),
    "Walls": Category(BuiltInCategory.OST_Walls, "Walls", CategoryType.Model),
    "Levels": Category(BuiltInCategory.OST_Levels, "Levels", CategoryType.Annotation),
    "Cameras": Category(BuiltInCategory.OST_Cameras, "Cameras", CategoryType.Model),
    "Text": Category(BuiltInCategory.OST_TextNotes, "Text Notes", CategoryType.Annotation),
}


class Definition(object):
    def __init__(self, name):
        self.Name = name


class Parameter(object):
    def __init__(self, name, storage, value=None, display=None, has_value=True):
        self.Definition = Definition(name)
        self.StorageType = storage
        self._value = value
        self._display = display
        self.HasValue = has_value and value is not None

    def AsString(self):
        return self._value if self.StorageType == StorageType.String else None

    def AsValueString(self):
        return self._display

    def AsInteger(self):
        return int(self._value)

    def AsDouble(self):
        return float(self._value)

    def AsElementId(self):
        return self._value


class Element(object):
    def __init__(self, eid, category, params=(), type_id=None, name=None):
        self.Id = ElementId(eid)
        self.Category = category
        self.Parameters = list(params)
        self._type_id = type_id or ElementId.InvalidElementId
        self._name = name

    def LookupParameter(self, name):
        for p in self.Parameters:
            if p.Definition.Name == name:
                return p
        return None

    def GetTypeId(self):
        return self._type_id


class _NameProp(object):
    @staticmethod
    def GetValue(element):
        return element._name


Element.Name = _NameProp()


class ElementType(Element):
    pass


class SpatialElement(Element):
    def __init__(self, eid, category, params=(), placed=True, **kw):
        Element.__init__(self, eid, category, params, **kw)
        self.Location = object() if placed else None


class View(object):
    def __init__(self, vid, visible_ids, usable=True, template=False):
        self.Id = ElementId(vid)
        self.visible = set(visible_ids)
        self.usable = usable
        self.IsTemplate = template


class _Collected(object):
    def __init__(self, elems):
        self._elems = elems

    def WhereElementIsNotElementType(self):
        return _Collected([e for e in self._elems if not isinstance(e, ElementType)])

    def ToElements(self):
        return list(self._elems)

    def GetElementCount(self):
        return len(self._elems)


def FilteredElementCollector(doc, view_id=None):
    doc.collector_calls += 1
    if view_id is None:
        return _Collected(list(doc.elements.values()))
    view = doc.views[view_id.Value]
    if not view.usable:
        raise Exception("The view is not a view that can be used by a collector")
    return _Collected([e for e in doc.elements.values() if e.Id.Value in view.visible])


class Document(object):
    def __init__(self, elements, active_view, views=None):
        self.elements = dict((e.Id.Value, e) for e in elements)
        self.ActiveView = active_view
        self.views = dict(views or {})
        if active_view is not None:
            self.views[active_view.Id.Value] = active_view
        self.collector_calls = 0

    def GetElement(self, eid):
        return self.elements.get(eid.Value)


class Selection(object):
    def __init__(self, ids):
        self.ids = list(ids)
        self.set_calls = []

    def GetElementIds(self):
        return list(self.ids)

    def SetElementIds(self, ids):
        self.set_calls.append(list(ids))
        self.ids = list(ids)


class UIDocument(object):
    def __init__(self, selected=(), fail_show=False):
        self.Selection = Selection(selected)
        self.shown = []
        self.fail_show = fail_show

    def ShowElements(self, ids):
        if self.fail_show:
            raise Exception("No good view could be found")
        self.shown.append(list(ids))


class FakeDB(object):
    """Bundles the fake classes the way `from pyrevit import DB` would."""
    ElementId = ElementId
    BuiltInCategory = BuiltInCategory
    CategoryType = CategoryType
    StorageType = StorageType
    SpatialElement = SpatialElement
    Element = Element
    FilteredElementCollector = staticmethod(FilteredElementCollector)


class FakeList(object):
    """Stands in for System.Collections.Generic.List[T]."""
    def __getitem__(self, _t):
        return list


# ---------------------------------------------------------------------------
def sample_model():
    """3 levels, 6 placed rooms + 1 unplaced, 3 doors of 2 types, 2 walls,
    a level, a camera, a text note, a door type element."""
    S, I, D, E = (StorageType.String, StorageType.Integer,
                  StorageType.Double, StorageType.ElementId)
    lvl1 = Element(9001, CATS["Levels"], name="L01")
    lvl2 = Element(9002, CATS["Levels"], name="L02")
    lvl10 = Element(9010, CATS["Levels"], name="L10")

    def room(eid, name, number, lvl, dept, area, placed=True):
        params = [
            Parameter("Name", S, name),
            Parameter("Number", S, number),
            Parameter("Level", E, lvl.Id, display=None),
            Parameter("Department", S, dept),
            Parameter("Area", D, area, display=("%.2f m²" % area) if area else None),
        ]
        return SpatialElement(eid, CATS["Rooms"], params, placed=placed)

    rooms = [
        room(101, "Office", "101", lvl1, "Admin", 20.0),
        room(102, "Office", "102", lvl1, "Admin", 22.5),
        room(103, "Corridor", "103", lvl1, "", 40.0),
        room(201, "Office", "201", lvl2, "Sales", 20.0),
        room(202, "WC", "202", lvl2, None, 6.0),
        room(1001, "Lobby", "1001", lvl10, "Admin", 80.0),
        room(999, "Ghost", "999", lvl10, "Admin", 0.0, placed=False),
    ]
    dtype_a = ElementType(5001, CATS["Doors"], [Parameter("Fire Rating", S, "60 min"),
                                                Parameter("Type Mark", S, "D1")])
    dtype_b = ElementType(5002, CATS["Doors"], [Parameter("Fire Rating", S, "")])
    doors = [
        Element(301, CATS["Doors"], [Parameter("Mark", S, "D-01"),
                                     Parameter("Is Fire Door", I, 1, display="Yes")],
                type_id=dtype_a.Id),
        Element(302, CATS["Doors"], [Parameter("Mark", S, "D-02"),
                                     Parameter("Is Fire Door", I, 0, display="No")],
                type_id=dtype_a.Id),
        Element(303, CATS["Doors"], [Parameter("Mark", S, "D-03"),
                                     Parameter("Is Fire Door", I, 0, display=None)],
                type_id=dtype_b.Id),
    ]
    walls = [Element(401, CATS["Walls"], [Parameter("Comments", S, "x")]),
             Element(402, CATS["Walls"], [Parameter("Comments", S, None)])]
    other = [Element(601, CATS["Cameras"]), Element(602, CATS["Text"]),
             Element(603, None)]
    everything = [lvl1, lvl2, lvl10] + rooms + doors + walls + other + [dtype_a, dtype_b]
    plan_l01 = View(7001, [101, 102, 103, 301, 302, 401, 602, 9001])
    sheet = View(7002, [], usable=False)
    return everything, plan_l01, sheet
