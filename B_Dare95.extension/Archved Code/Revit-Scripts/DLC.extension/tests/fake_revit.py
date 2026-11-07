# -*- coding: utf-8 -*-
"""
Minimal fake of the Revit API + pyRevit, just enough to import and drive
DLC Stair Transfer's bd_family_cleaner.py outside Revit.

Fidelity rules (the ones that matter for this tool):
  * Stairs reject top-below-base at Regenerate, like Revit does.
  * CopyElements maps levels by NAME; when the target has no level of that
    name it CREATES one (worst case for us) - the tool must clean it up.
  * Railing copy can be told to fail, to test the retry path.
  * Parameters on a missing level id raise.
"""
import sys
import types


# --------------------------------------------------------------------- ids
class ElementId(object):
    def __init__(self, v):
        self.Value = int(v) if not hasattr(v, "_bic") else v._bic

    def __eq__(self, o):
        return isinstance(o, ElementId) and o.Value == self.Value

    def __ne__(self, o):
        return not self.__eq__(o)

    def __hash__(self):
        return hash(self.Value)

    def __repr__(self):
        return "Id(%s)" % self.Value


ElementId.InvalidElementId = ElementId(-1)


class XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def DistanceTo(self, o):
        return ((self.X - o.X) ** 2 + (self.Y - o.Y) ** 2 +
                (self.Z - o.Z) ** 2) ** 0.5


class Transform(object):
    """Translation-only transform (links never tilt)."""

    def __init__(self, dx=0.0, dy=0.0, dz=0.0):
        self.d = (dx, dy, dz)

    @staticmethod
    def CreateTranslation(v):
        return Transform(v.X, v.Y, v.Z)

    def Multiply(self, right):
        return Transform(*[a + b for a, b in zip(self.d, right.d)])

    def OfPoint(self, p):
        return XYZ(p.X + self.d[0], p.Y + self.d[1], p.Z + self.d[2])

    @property
    def Inverse(self):
        return Transform(*[-a for a in self.d])


class _Enum(object):
    def __getattr__(self, name):
        return name


BuiltInParameter = _Enum()


class _BIC(object):
    def __init__(self, n):
        self._bic = n


class _BICEnum(object):
    def __getattr__(self, name):
        return _BIC(name)


BuiltInCategory = _BICEnum()


# ------------------------------------------------------------- elements
class _NameProp(object):
    @staticmethod
    def GetValue(el):
        return el._name


class Element(object):
    Name = _NameProp()
    _next = [1000]

    def __init__(self, name="", eid=None):
        if eid is None:
            Element._next[0] += 1
            eid = Element._next[0]
        self.Id = ElementId(eid)
        self._name = name
        self.params = {}
        self.Category = None
        self.doc = None

    def get_Parameter(self, bip):
        return self.params.get(bip)

    def GetTypeId(self):
        return getattr(self, "type_id", ElementId.InvalidElementId)


class Param(object):
    def __init__(self, owner, bip, value, kind):
        self.owner, self.bip, self.v, self.kind = owner, bip, value, kind
        self.IsReadOnly = False
        self.HasValue = True

    def AsDouble(self):
        return float(self.v)

    def AsElementId(self):
        return self.v

    def Set(self, value):
        if self.kind == "id" and value != ElementId.InvalidElementId:
            if self.owner.doc.GetElement(value) is None:
                raise Exception("level not in document")
        self.v = value
        return True


class Level(Element):
    def __init__(self, name, elev, eid=None):
        Element.__init__(self, name, eid)
        self.ProjectElevation = float(elev)


class ElementType(Element):
    pass


class StairsType(ElementType):
    def __init__(self, name, max_riser):
        ElementType.__init__(self, name)
        self.MaxRiserHeight = max_riser


class RevitLinkInstance(Element):
    def __init__(self, name, link_doc, xform):
        Element.__init__(self, name)
        self._ldoc, self._x = link_doc, xform

    def GetLinkDocument(self):
        return self._ldoc

    def GetTotalTransform(self):
        return self._x


class Stairs(Element):
    def __init__(self, name, base, base_off, top, top_off, risers, type_id):
        Element.__init__(self, name)
        P = BuiltInParameter
        self.params = {
            P.STAIRS_BASE_LEVEL_PARAM: Param(self, P.STAIRS_BASE_LEVEL_PARAM,
                                             base.Id, "id"),
            P.STAIRS_BASE_OFFSET: Param(self, P.STAIRS_BASE_OFFSET,
                                        base_off, "d"),
            P.STAIRS_TOP_LEVEL_PARAM: Param(
                self, P.STAIRS_TOP_LEVEL_PARAM,
                top.Id if top else ElementId.InvalidElementId, "id"),
            P.STAIRS_TOP_OFFSET: Param(self, P.STAIRS_TOP_OFFSET,
                                       top_off, "d"),
            P.STAIRS_DESIRED_NUMBER_OF_RISERS: Param(
                self, P.STAIRS_DESIRED_NUMBER_OF_RISERS, risers, "i"),
        }
        self.type_id = type_id
        self.MultistoryStairsId = ElementId.InvalidElementId
        self.railings = []
        self._height = 0.0

    # geometry from params
    def _z(self, which):
        P = BuiltInParameter
        lv = self.doc.GetElement(self.params[getattr(
            P, "STAIRS_%s_LEVEL_PARAM" % which)].v)
        off = self.params[getattr(P, "STAIRS_%s_OFFSET" % which)].v
        return None if lv is None else lv.ProjectElevation + off

    @property
    def Height(self):
        t = self._z("TOP")
        return self._height if t is None else t - self._z("BASE")

    @property
    def ActualRisersNumber(self):
        return int(self.params[
            BuiltInParameter.STAIRS_DESIRED_NUMBER_OF_RISERS].v)

    @property
    def ActualRiserHeight(self):
        return self.Height / self.ActualRisersNumber

    @property
    def LevelId(self):
        return self.params[BuiltInParameter.STAIRS_BASE_LEVEL_PARAM].v

    def GetAssociatedRailings(self):
        return list(self.railings)

    def ChangeTypeId(self, tid):
        self.type_id = tid


class Railing(Element):
    def __init__(self, host):
        Element.__init__(self, "rail")
        self.host = host
        self.LevelId = ElementId.InvalidElementId


class StairsRun(Element):
    def __init__(self, stairs):
        Element.__init__(self, "run")
        self._s = stairs

    def GetStairs(self):
        return self._s


class StairsLanding(StairsRun):
    pass


class MultistoryStairs(Element):
    def __init__(self, members):
        """members: list of (Stairs, [placement Level])"""
        Element.__init__(self, "ms")
        self._m = members
        for st, _ in members:
            st.MultistoryStairsId = self.Id

    def GetAllStairsIds(self):
        return _Set([s.Id for s, _ in self._m])

    def GetStairsPlacementLevels(self, st):
        for s, lv in self._m:
            if s.Id == st.Id:
                return _Set([l.Id for l in lv])
        raise ValueError("not a member")


class _Set(list):
    @property
    def Count(self):
        return len(self)


# ------------------------------------------------------------- document
class FakeDoc(object):
    def __init__(self, title):
        self.Title = title
        self.PathName = "C:/%s.rvt" % title
        self.IsFamilyDocument = False
        self.IsLinked = False
        self.els = {}
        self.deleted = []
        self.regen_count = 0
        self.Application = types.SimpleNamespace(Documents=[])

    def add(self, el):
        el.doc = self
        self.els[el.Id] = el
        return el

    def GetElement(self, eid):
        return self.els.get(eid)

    def Delete(self, eid):
        self.deleted.append(self.els.pop(eid))

    def Regenerate(self):
        self.regen_count += 1
        for el in list(self.els.values()):
            if isinstance(el, Stairs):
                t = el._z("TOP")
                if t is not None and t <= el._z("BASE"):
                    raise Exception("Top of stair is below its base")

    def levels(self):
        return [e for e in self.els.values() if isinstance(e, Level)]


class FilteredElementCollector(object):
    def __init__(self, d):
        self._d = d
        self._items = list(d.els.values())

    def OfClass(self, cls):
        self._items = [e for e in self._items if isinstance(e, cls)]
        return self

    def OfCategory(self, bic):
        self._items = [e for e in self._items
                       if getattr(e, "cat", None) == bic._bic]
        return self

    def WhereElementIsNotElementType(self):
        self._items = [e for e in self._items
                       if not isinstance(e, ElementType)]
        return self

    def WherePasses(self, f):
        self._items = [e for e in self._items if f.passes(e)]
        return self

    def GetElementCount(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)


class ElementLevelFilter(object):
    def __init__(self, lid):
        self.lid = lid

    def passes(self, e):
        return getattr(e, "LevelId", None) == self.lid


# ------------------------------------------------------------- copy
class CopyConfig(object):
    fail_with_railings = False
    calls = []


def _map_level(src_level, dst, z_shift):
    for l in dst.levels():
        if l._name == src_level._name:
            return l
    # Revit fallback (worst case): create the level
    return dst.add(Level(src_level._name, src_level.ProjectElevation + z_shift))


class ElementTransformUtils(object):
    @staticmethod
    def CopyElements(sdoc, ids, ddoc, xform, opts):
        ids = list(ids)
        CopyConfig.calls.append(len(ids))
        has_rail = any(isinstance(sdoc.GetElement(i), Railing) for i in ids)
        if has_rail and CopyConfig.fail_with_railings:
            raise Exception("railing host lost")
        out = []
        zs = xform.d[2]
        for i in ids:
            e = sdoc.GetElement(i)
            if isinstance(e, Stairs):
                P = BuiltInParameter
                b = sdoc.GetElement(e.params[P.STAIRS_BASE_LEVEL_PARAM].v)
                t = sdoc.GetElement(e.params[P.STAIRS_TOP_LEVEL_PARAM].v)
                nb = _map_level(b, ddoc, zs)
                nt = _map_level(t, ddoc, zs) if t else None
                n = Stairs("copy", nb, e.params[P.STAIRS_BASE_OFFSET].v,
                           nt, e.params[P.STAIRS_TOP_OFFSET].v,
                           e.ActualRisersNumber, e.type_id)
                n.doc = ddoc  # params validate against target
                ddoc.add(n)
                n._height = e._height
                out.append(n.Id)
            elif isinstance(e, Railing):
                r = ddoc.add(Railing(None))
                out.append(r.Id)
        return out


class CopyPasteOptions(object):
    def SetDuplicateTypeNamesHandler(self, h):
        self.h = h


class _Tx(object):
    def __init__(self, d, name=""):
        self.started = self.ended = False

    def Start(self):
        self.started = True

    def Commit(self):
        self.ended = True

    def RollBack(self):
        self.ended = True
        self.rolled = True

    def HasStarted(self):
        return self.started

    def HasEnded(self):
        return self.ended

    def GetFailureHandlingOptions(self):
        return types.SimpleNamespace(SetFailuresPreprocessor=lambda p: None)

    def SetFailureHandlingOptions(self, o):
        pass


# ------------------------------------------------------------- install
def install():
    DB = types.ModuleType("DB")
    for n, v in dict(
            ElementId=ElementId, XYZ=XYZ, Transform=Transform,
            BuiltInParameter=BuiltInParameter, BuiltInCategory=BuiltInCategory,
            Element=Element, Level=Level, ElementType=ElementType,
            RevitLinkInstance=RevitLinkInstance,
            FilteredElementCollector=FilteredElementCollector,
            ElementLevelFilter=ElementLevelFilter,
            ElementTransformUtils=ElementTransformUtils,
            CopyPasteOptions=CopyPasteOptions, Transaction=_Tx,
            SubTransaction=_Tx,
            IDuplicateTypeNamesHandler=object, IFailuresPreprocessor=object,
            DuplicateTypeAction=_Enum(), FailureSeverity=_Enum(),
            FailureProcessingResult=_Enum()).items():
        setattr(DB, n, v)

    class _Exit(Exception):
        pass

    class TemplateListItem(object):
        def __init__(self, item, checked=False, name_attr=None):
            self.item, self.checked = item, checked

    forms = types.SimpleNamespace(
        alert=lambda *a, **k: True, SelectFromList=None,
        CommandSwitchWindow=None, TemplateListItem=TemplateListItem)
    printed = []
    out = types.SimpleNamespace(
        print_md=lambda s: printed.append(s),
        print_table=lambda **k: printed.append(k),
        linkify=lambda i: "link%s" % i.Value)
    script = types.SimpleNamespace(get_output=lambda: out,
                                   exit=lambda: (_ for _ in ()).throw(_Exit()))
    revit = types.SimpleNamespace(doc=None, uidoc=None)

    pyrevit = types.ModuleType("pyrevit")
    pyrevit.revit, pyrevit.DB, pyrevit.forms, pyrevit.script = \
        revit, DB, forms, script

    arch = types.ModuleType("Autodesk.Revit.DB.Architecture")
    arch.Stairs, arch.MultistoryStairs = Stairs, MultistoryStairs
    arch.StairsRun, arch.StairsLanding = StairsRun, StairsLanding
    sel = types.ModuleType("Autodesk.Revit.UI.Selection")
    sel.ObjectType = _Enum()
    sel.ISelectionFilter = object
    exc = types.ModuleType("Autodesk.Revit.Exceptions")
    exc.OperationCanceledException = type("OCE", (Exception,), {})

    class _ListFactory(object):
        def __getitem__(self, t):
            class L(list):
                def Add(self, x):
                    self.append(x)
            return L
    gen = types.ModuleType("System.Collections.Generic")
    gen.List = _ListFactory()

    for name, mod in [("pyrevit", pyrevit),
                      ("Autodesk", types.ModuleType("Autodesk")),
                      ("Autodesk.Revit", types.ModuleType("Autodesk.Revit")),
                      ("Autodesk.Revit.DB", DB),
                      ("Autodesk.Revit.DB.Architecture", arch),
                      ("Autodesk.Revit.UI", types.ModuleType("UI")),
                      ("Autodesk.Revit.UI.Selection", sel),
                      ("Autodesk.Revit.Exceptions", exc),
                      ("System", types.ModuleType("System")),
                      ("System.Collections", types.ModuleType("SC")),
                      ("System.Collections.Generic", gen)]:
        sys.modules[name] = mod
    return types.SimpleNamespace(revit=revit, forms=forms, printed=printed,
                                 Exit=_Exit)
