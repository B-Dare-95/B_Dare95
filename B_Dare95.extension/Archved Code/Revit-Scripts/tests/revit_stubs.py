# -*- coding: utf-8 -*-
"""Minimal Revit API stand-ins for testing revit_io outside Revit.

They reproduce the failure modes that matter: InvalidElementId on host
segments, link segments pointing at a RevitLinkInstance, unloaded links,
missing parameters, read-only parameters, Set() returning False, and
ParameterBindings.Insert returning False.
"""
import sys
import types


class ElementId(object):
    def __init__(self, v):
        self.Value = int(getattr(v, 'value', v))

    def __eq__(self, o):
        return isinstance(o, ElementId) and o.Value == self.Value

    def __ne__(self, o):
        return not self.__eq__(o)

    def __hash__(self):
        return hash(self.Value)

    @property
    def IntegerValue(self):            # removed in Revit 2026
        raise AttributeError('IntegerValue removed in Revit 2026')


ElementId.InvalidElementId = ElementId(-1)


class _Enum(object):
    def __init__(self, name, value):
        self.name, self.value = name, value

    def __repr__(self):
        return self.name


class BuiltInCategory(object):
    OST_Rooms = _Enum('OST_Rooms', -2000160)
    OST_Walls = _Enum('OST_Walls', -2000011)
    OST_RoomSeparationLines = _Enum('OST_RoomSeparationLines', -2000066)
    OST_Columns = _Enum('OST_Columns', -2000100)
    OST_StructuralColumns = _Enum('OST_StructuralColumns', -2001330)
    OST_GenericModel = _Enum('OST_GenericModel', -2000151)


class BuiltInParameter(object):
    ROOM_NUMBER = 'ROOM_NUMBER'
    ROOM_NAME = 'ROOM_NAME'
    ROOM_AREA = 'ROOM_AREA'
    ROOM_PHASE = 'ROOM_PHASE'
    ROOM_LOWER_OFFSET = 'ROOM_LOWER_OFFSET'
    FUNCTION_PARAM = 'FUNCTION_PARAM'


class WallKind(object):
    Basic = 'Basic'
    Curtain = 'Curtain'
    Stacked = 'Stacked'


class SpatialElementBoundaryLocation(object):
    Finish = 'Finish'
    Center = 'Center'


class SpatialElementBoundaryOptions(object):
    def __init__(self):
        self.SpatialElementBoundaryLocation = 'Finish'


class XYZ(object):
    def __init__(self, x, y, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)


class Curve(object):
    def __init__(self, pts):
        self._pts = [XYZ(*p) for p in pts]

    def Tessellate(self):
        return list(self._pts)


class Category(object):
    def __init__(self, bic, name):
        self.Id = ElementId(bic.value)
        self.Name = name

    @staticmethod
    def GetCategory(doc, bic):
        return Category(bic, repr(bic))


class Parameter(object):
    def __init__(self, value=None, storage='double', read_only=False,
                 reject=False):
        self.value = value
        self.storage = storage
        self.IsReadOnly = read_only
        self.reject = reject

    @property
    def HasValue(self):
        return self.value is not None

    def AsDouble(self):
        return float(self.value or 0.0)

    def AsInteger(self):
        return int(self.value or 0)

    def AsString(self):
        return self.value

    def AsElementId(self):
        return self.value

    def Set(self, v):
        if self.reject:
            return False
        if self.IsReadOnly:
            raise Exception('read only')
        self.value = v
        return True


class Element(object):
    _next = [1000]

    def __init__(self, doc=None, category=None, name=''):
        Element._next[0] += 1
        self.Id = ElementId(Element._next[0])
        self.Document = doc
        self.Category = category
        self._name = name
        self.params = {}
        if doc is not None:
            doc.add(self)

    # Element.Name is reached through DB.Element.Name.GetValue in revit_io
    def get_Parameter(self, bip):
        return self.params.get(bip)

    def LookupParameter(self, name):
        return self.params.get(name)


class _NameAccessor(object):
    @staticmethod
    def GetValue(el):
        return el._name


Element.Name = _NameAccessor()


class WallType(Element):
    def __init__(self, doc, name, function=None, kind=WallKind.Basic):
        Element.__init__(self, doc, None, name)
        self.Kind = kind
        if function is not None:
            self.params['FUNCTION_PARAM'] = Parameter(function, 'int')


class Wall(Element):
    def __init__(self, doc, wtype, width, stacked_members=None):
        Element.__init__(self, doc, Category(BuiltInCategory.OST_Walls,
                                             'Walls'), '')
        self.WallType = wtype
        self._width = width
        self._members = stacked_members or []
        self.IsStackedWall = bool(stacked_members)

    @property
    def Width(self):
        if self.IsStackedWall:
            raise Exception('stacked walls have no single width')
        if self._width is None:
            raise Exception('no width')
        return self._width

    def GetStackedWallMemberIds(self):
        return [m.Id for m in self._members]


class Level(Element):
    def __init__(self, doc, name, elevation):
        Element.__init__(self, doc, None, name)
        self.Elevation = elevation


class BoundarySegment(object):
    def __init__(self, pts, element_id, link_element_id=None):
        self._curve = Curve(pts)
        self.ElementId = element_id
        self.LinkElementId = link_element_id or ElementId.InvalidElementId

    def GetCurve(self):
        return self._curve


class Room(Element):
    def __init__(self, doc, number, name, level, rect=None, phase=None,
                 area=None, loops=None, placed=True):
        Element.__init__(self, doc, Category(BuiltInCategory.OST_Rooms,
                                             'Rooms'), name)
        self.LevelId = level.Id
        self.rect = rect
        self.Location = object() if placed else None
        self.loops = loops or []
        self.params = {
            'ROOM_NUMBER': Parameter(number, 'str'),
            'ROOM_NAME': Parameter(name, 'str'),
            'ROOM_AREA': Parameter(area if area is not None else 0.0),
            'ROOM_PHASE': Parameter(phase.Id if phase else None, 'id'),
            'ROOM_LOWER_OFFSET': Parameter(0.0),
        }
        self.boundary_calls = []

    def GetBoundarySegments(self, opts):
        self.boundary_calls.append(opts.SpatialElementBoundaryLocation)
        return self.loops


class RevitLinkInstance(Element):
    def __init__(self, doc, link_doc, name='Link'):
        Element.__init__(self, doc, None, name)
        self._ldoc = link_doc

    def GetLinkDocument(self):
        return self._ldoc


class InstanceBinding(object):
    def __init__(self, cats=None):
        self.Categories = cats or CategorySet()


class CategorySet(object):
    def __init__(self):
        self.items = []

    def Insert(self, c):
        self.items.append(c)
        return True

    def Contains(self, c):
        return any(x.Id == c.Id for x in self.items)


class _Map(object):
    """Like Revit: binding a parameter adds it to every element of the
    bound categories (empty value)."""
    def __init__(self, doc=None):
        self.items = []         # [(definition, binding)]
        self.refuse = False
        self.doc = doc

    def _apply(self, d, b):
        if self.doc is None:
            return
        for el in self.doc.elements.values():
            cat = getattr(el, 'Category', None)
            if cat is not None and b.Categories.Contains(cat):
                el.params.setdefault(d.Name, Parameter(None))

    def Insert(self, d, b, group):
        if self.refuse:
            return False
        self.items.append((d, b))
        self._apply(d, b)
        return True

    def ReInsert(self, d, b, group):
        self.items = [(x, y) for x, y in self.items if x.Name != d.Name]
        self.items.append((d, b))
        self._apply(d, b)
        return True

    def ForwardIterator(self):
        return _Iter(self.items)


class _Iter(object):
    def __init__(self, items):
        self.items, self.i = items, -1

    def Reset(self):
        self.i = -1

    def MoveNext(self):
        self.i += 1
        return self.i < len(self.items)

    @property
    def Key(self):
        return self.items[self.i][0]

    @property
    def Current(self):
        return self.items[self.i][1]


class Definition(object):
    def __init__(self, name, spec, guid=None):
        self.Name, self.spec, self.guid = name, spec, guid

    def GetDataType(self):
        return self.spec


class SpecTypeId(object):
    Area = 'autodesk.spec.aec:area'

    class Boolean(object):
        YesNo = 'autodesk.spec:spec.bool'


class GroupTypeId(object):
    Data = 'autodesk.parameter.group:data'


class ExternalDefinitionCreationOptions(object):
    def __init__(self, name, spec):
        self.Name, self.spec = name, spec
        self.GUID = None
        self.Description = ''


class Document(object):
    def __init__(self, title='Model', workshared=False):
        self.Title = title
        self.IsWorkshared = workshared
        self.elements = {}
        self.ParameterBindings = _Map(self)
        self.rooms_for_probe = []         # [(room, phase_id, rect)]
        self.probes = []

    def add(self, el):
        self.elements[el.Id.Value] = el

    def GetElement(self, eid):
        if eid is None:
            return None
        return self.elements.get(eid.Value)

    def GetRoomAtPoint(self, pt, phase):
        self.probes.append((pt.X, pt.Y, pt.Z))
        for room in self.elements.values():
            if not isinstance(room, Room) or room.rect is None:
                continue
            x0, y0, x1, y1 = room.rect
            if x0 < pt.X < x1 and y0 < pt.Y < y1:
                return room
        return None


class Phase(Element):
    pass


class _Groups(object):
    def __init__(self):
        self.groups = {}

    def get_Item(self, name):
        return self.groups.get(name)

    def Create(self, name):
        grp = _Group()
        self.groups[name] = grp
        return grp


class _Group(object):
    def __init__(self):
        self.Definitions = _Defs()


class _Defs(object):
    def __init__(self):
        self.defs = {}

    def get_Item(self, name):
        return self.defs.get(name)

    def Create(self, opt):
        d = Definition(opt.Name, opt.spec, opt.GUID)
        self.defs[opt.Name] = d
        return d


class _SPFile(object):
    def __init__(self):
        self.Groups = _Groups()


class Application(object):
    def __init__(self):
        self.SharedParametersFilename = r'C:\Firm\Firm_SharedParams.txt'
        self.opened = []
        self.fail_open = False
        self._spf = _SPFile()

    def OpenSharedParameterFile(self):
        if self.fail_open:
            raise Exception('cannot open shared parameter file')
        self.opened.append(self.SharedParametersFilename)
        return self._spf


class CheckoutStatus(object):
    OwnedByOtherUser = 'OwnedByOtherUser'
    OwnedByCurrentUser = 'OwnedByCurrentUser'
    NotOwned = 'NotOwned'


class _TooltipInfo(object):
    def __init__(self, owner):
        self.Owner = owner


class WorksharingUtils(object):
    owners = {}

    @staticmethod
    def GetCheckoutStatus(doc, eid):
        return (CheckoutStatus.OwnedByOtherUser
                if eid.Value in WorksharingUtils.owners
                else CheckoutStatus.NotOwned)

    @staticmethod
    def GetWorksharingTooltipInfo(doc, eid):
        return _TooltipInfo(WorksharingUtils.owners.get(eid.Value))


def install():
    """Register fake Autodesk.Revit.DB and System modules."""
    db = types.ModuleType('Autodesk.Revit.DB')
    for name, obj in list(globals().items()):
        if isinstance(obj, type):
            setattr(db, name, obj)
    autodesk = types.ModuleType('Autodesk')
    revit = types.ModuleType('Autodesk.Revit')
    revit.DB = db
    autodesk.Revit = revit
    sys.modules['Autodesk'] = autodesk
    sys.modules['Autodesk.Revit'] = revit
    sys.modules['Autodesk.Revit.DB'] = db
    system = types.ModuleType('System')
    system.Guid = lambda s: ('GUID', s)
    sys.modules['System'] = system
    return db


class FilteredElementCollector(object):
    def __init__(self, doc):
        self.items = list(doc.elements.values())

    def OfCategory(self, bic):
        cid = ElementId(bic.value)
        self.items = [e for e in self.items
                      if e.Category is not None and e.Category.Id == cid]
        return self

    def WhereElementIsNotElementType(self):
        return self

    def __iter__(self):
        return iter(self.items)


class _Selection(object):
    def __init__(self, ids):
        self.ids = ids

    def GetElementIds(self):
        return list(self.ids)


class UIDocument(object):
    def __init__(self, ids):
        self.Selection = _Selection(ids)


class View(object):
    def __init__(self, level=None):
        self.GenLevel = level


class Transaction(object):
    log = []

    def __init__(self, doc, name=''):
        self.doc, self.name, self._s, self._e = doc, name, False, False

    def Start(self):
        self._s = True
        Transaction.log.append(('start', self.name))

    def Commit(self):
        self._e = True
        Transaction.log.append(('commit', self.name))

    def RollBack(self):
        self._e = True
        Transaction.log.append(('rollback', self.name))

    def HasStarted(self):
        return self._s

    def HasEnded(self):
        return self._e


class SubTransaction(Transaction):
    def __init__(self, doc):
        Transaction.__init__(self, doc, 'sub')
