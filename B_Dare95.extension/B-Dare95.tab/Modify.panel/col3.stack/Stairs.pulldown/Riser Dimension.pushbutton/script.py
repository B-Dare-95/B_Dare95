# -*- coding: utf-8 -*-
"""Stair Riser Chain Dimension

Pick a stair (host model or linked model) in a section or elevation view and
the tool places ONE multi-segment vertical dimension up the whole stair:

    plane 0 : the base of the lowest run
    plane 1 : the landing surface above it
    ...
    plane n : the surface the top run finishes on

Each segment then gets its own text:

    Prefix : "<N> EQ. RISERS @ <H>MM = "
    Suffix : "MM"

so a segment reads e.g.  11 EQ. RISERS @ 170MM = 1870 MM

The intermediate planes are taken from the base face of the run ABOVE each
landing rather than from the landing's own top face. Both sit at exactly the
same elevation, but a run's base face is the one kind of reference that reads
reliably out of stair geometry, host or linked.
"""

__title__ = "Stair Riser\nChain"
__author__ = "Mohamed Bedair"
__doc__ = ("Chain-dimension a stair's rise in section: base, each landing top, "
           "then the finish level, with 'N EQ. RISERS @ HMM = ' / 'MM' written "
           "into each segment's Prefix / Suffix.")

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from Autodesk.Revit.DB import (
    BoundingBoxIntersectsFilter,
    BuiltInCategory,
    BuiltInParameter,
    DimensionType,
    Element,
    ElementId,
    FilteredElementCollector,
    GeometryInstance,
    Level,
    Line,
    Options,
    Outline,
    PlanarFace,
    Reference,
    ReferenceArray,
    RevitLinkInstance,
    Solid,
    Transaction,
    ViewDetailLevel,
    ViewSection,
    ViewType,
    XYZ,
)
from Autodesk.Revit.DB.Architecture import Stairs, StairsRun
from Autodesk.Revit.UI import (
    TaskDialog,
    TaskDialogCommandLinkId,
    TaskDialogCommonButtons,
    TaskDialogResult,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from System import EventHandler
from System.Windows import RoutedEventHandler
from System.Windows.Controls import SelectionChangedEventHandler, TextChangedEventHandler
from System.Windows.Input import MouseButtonEventHandler
from System.Windows.Markup import XamlReader
from System.Windows.Threading import Dispatcher, DispatcherFrame


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
active_view = doc.ActiveView

FT_TO_MM = 304.8
TOL = 1.0e-9


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def eid_val(element_id):
    """ElementId numeric value - .Value (2025+) with .IntegerValue fallback."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def to_mm(feet):
    return feet * FT_TO_MM


def fmt_mm(value_mm):
    """275.0 -> '275', 274.6 -> '274.6'."""
    if abs(value_mm - round(value_mm)) < 0.05:
        return "{0:.0f}".format(round(value_mm))
    return "{0:.1f}".format(value_mm)


def alert(title, message):
    td = TaskDialog(title)
    td.MainInstruction = title
    td.MainContent = message
    td.Show()


def type_name(element):
    """Read an element type's name three ways - .Name is unreliable in IronPython."""
    name = None
    try:
        name = Element.Name.GetValue(element)
    except Exception:
        name = None
    if not name:
        try:
            name = element.Name
        except Exception:
            name = None
    if not name:
        try:
            param = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
            if param is not None:
                name = param.AsString()
        except Exception:
            name = None
    if not name:
        name = "<unnamed id {0}>".format(eid_val(element.Id))
    return name


LINEAR_STYLE_NAMES = ("linear", "linearfixed")


def collect_dimension_types():
    """Returns (linear_types, all_types, problems).

    Each list holds (name, DimensionType) pairs sorted by name. Style is compared
    by string so a mismatched enum identity cannot wipe out the whole list, and
    a type whose StyleType cannot be read is kept rather than dropped.
    """
    linear = []
    every = []
    problems = []

    collector = FilteredElementCollector(doc).OfClass(DimensionType)

    for dim_type in collector:
        name = type_name(dim_type)

        style_text = None
        try:
            style_text = str(dim_type.StyleType)
        except Exception as ex:
            problems.append("{0}: StyleType unreadable -> {1}".format(name, ex))

        every.append((name, dim_type))

        if style_text is None:
            linear.append((name, dim_type))
        elif style_text.strip().lower() in LINEAR_STYLE_NAMES:
            linear.append((name, dim_type))

    linear.sort(key=lambda pair: pair[0].lower())
    every.sort(key=lambda pair: pair[0].lower())
    return linear, every, problems


def bbox_corners(bbox):
    """The eight corners of a BoundingBoxXYZ, in the box's own coordinates."""
    lo = bbox.Min
    hi = bbox.Max
    points = []
    for x in (lo.X, hi.X):
        for y in (lo.Y, hi.Y):
            for z in (lo.Z, hi.Z):
                points.append(XYZ(x, y, z))
    # a bounding box can carry its own transform
    try:
        if bbox.Transform is not None and not bbox.Transform.IsIdentity:
            points = [bbox.Transform.OfPoint(p) for p in points]
    except Exception:
        pass
    return points


# ---------------------------------------------------------------------------
# Selection filters
#
# ObjectType.Element can only ever return the RevitLinkInstance itself, never a
# element inside it, so linked stairs need ObjectType.LinkedElement - and that
# mode cannot pick host elements. Hence two filters and two pick modes.
# ---------------------------------------------------------------------------

def is_stair_element(element):
    if element is None:
        return False
    if isinstance(element, Stairs) or isinstance(element, StairsRun):
        return True
    cat = element.Category
    if cat is None:
        return False
    cat_id = eid_val(cat.Id)
    return cat_id in (int(BuiltInCategory.OST_Stairs),
                      int(BuiltInCategory.OST_StairsRuns))


class HostStairFilter(ISelectionFilter):
    """Stairs in the active document."""

    def AllowElement(self, element):
        return is_stair_element(element)

    def AllowReference(self, reference, point):
        return True


class LinkedStairFilter(ISelectionFilter):
    """Stairs inside Revit links.

    In LinkedElement mode Revit hands AllowElement the RevitLinkInstance in some
    versions and the linked element in others, so accept both and do the real
    category test in AllowReference, where the linked id is always available.
    """

    def __init__(self, host_doc):
        self.host_doc = host_doc

    def AllowElement(self, element):
        if isinstance(element, RevitLinkInstance):
            return True
        return is_stair_element(element)

    def AllowReference(self, reference, point):
        try:
            link = self.host_doc.GetElement(reference.ElementId)
            if not isinstance(link, RevitLinkInstance):
                return False
            link_doc = link.GetLinkDocument()
            if link_doc is None:
                return False
            linked_id = reference.LinkedElementId
            if linked_id is None or linked_id == ElementId.InvalidElementId:
                return False
            return is_stair_element(link_doc.GetElement(linked_id))
        except Exception:
            # never let a filter exception kill the pick loop
            return False


def ask_source_mode():
    """Returns 'host', 'link' or None."""
    td = TaskDialog("Stair Riser Chain")
    td.MainInstruction = "Where is the stair?"
    td.MainContent = ("Revit uses a different pick mode for linked elements, "
                      "so this has to be chosen up front.")
    td.AddCommandLink(TaskDialogCommandLinkId.CommandLink1,
                      "Host model",
                      "Pick a stair in the current model.")
    td.AddCommandLink(TaskDialogCommandLinkId.CommandLink2,
                      "Linked model",
                      "Pick a stair inside a loaded Revit link.")
    td.CommonButtons = TaskDialogCommonButtons.Cancel
    td.DefaultButton = TaskDialogResult.Cancel

    result = td.Show()
    if result == TaskDialogResult.CommandLink1:
        return "host"
    if result == TaskDialogResult.CommandLink2:
        return "link"
    return None


# ---------------------------------------------------------------------------
# Run data
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Value resolution
#
# The Stairs API scatters these values around and moves them between releases:
# ActualTreadDepth is on Stairs, not StairsRun, and the built-in parameter names
# differ across 2024-2027. Each value is chased through a chain of sources and
# the source that answered is recorded so it can be reported.
# ---------------------------------------------------------------------------

def read_property(element, names):
    for name in names:
        try:
            value = getattr(element, name)
        except Exception:
            continue
        if value is not None:
            return value, "property {0}".format(name)
    return None, None


def read_builtin_param(element, names, as_int=False):
    for name in names:
        bip = getattr(BuiltInParameter, name, None)
        if bip is None:
            continue
        try:
            param = element.get_Parameter(bip)
        except Exception:
            continue
        if param is None or not param.HasValue:
            continue
        try:
            value = param.AsInteger() if as_int else param.AsDouble()
        except Exception:
            continue
        if value:
            return value, "parameter {0}".format(name)
    return None, None


def read_named_param(element, names, as_int=False):
    for name in names:
        try:
            param = element.LookupParameter(name)
        except Exception:
            continue
        if param is None or not param.HasValue:
            continue
        try:
            value = param.AsInteger() if as_int else param.AsDouble()
        except Exception:
            continue
        if value:
            return value, "parameter '{0}'".format(name)
    return None, None


def resolve_value(sources, as_int=False):
    """sources = [(element, [prop names], [bip names], [param names]), ...]

    Returns (value, source_description) or (None, None).
    """
    for element, props, bips, named in sources:
        if element is None:
            continue

        value, src = read_property(element, props)
        if value:
            return value, src

        value, src = read_builtin_param(element, bips, as_int)
        if value:
            return value, src

        value, src = read_named_param(element, named, as_int)
        if value:
            return value, src

    return None, None


def read_number(element, prop_names, bip_names=None):
    """Like resolve_value, but zero is a legitimate answer.

    resolve_value tests values for truth, which is right for a depth or a
    count but wrong for an elevation - a run based at 0.0 is perfectly normal.
    """
    for name in prop_names:
        try:
            value = getattr(element, name)
        except Exception:
            continue
        if value is not None:
            return float(value)

    for name in (bip_names or []):
        bip = getattr(BuiltInParameter, name, None)
        if bip is None:
            continue
        try:
            param = element.get_Parameter(bip)
        except Exception:
            continue
        if param is None or not param.HasValue:
            continue
        try:
            return param.AsDouble()
        except Exception:
            continue

    return None


def plan_distance(element, point):
    """Plan distance from an element's bounding box centre to a point."""
    if point is None:
        return 0.0
    try:
        bbox = element.get_BoundingBox(None)
        if bbox is None:
            return 0.0
        cx = (bbox.Min.X + bbox.Max.X) * 0.5
        cy = (bbox.Min.Y + bbox.Max.Y) * 0.5
        return XYZ(cx - point.X, cy - point.Y, 0.0).GetLength()
    except Exception:
        return 0.0


def stair_siblings(document, stairs, skip_run_id):
    """[(element, label)] for the landings and other runs of the same stair.

    The surface a run finishes on belongs to a different element - usually the
    landing above, sometimes the first tread of the next run. Rather than trying
    to identify which, every sibling is offered up and the elevation sweep in
    the elevation sweep picks whichever one has a face at the right height.
    """
    out = []
    if stairs is None:
        return out

    try:
        for landing_id in stairs.GetStairsLandings():
            element = document.GetElement(landing_id)
            if element is not None:
                out.append((element, "landing above the run"))
    except Exception:
        pass

    try:
        skip = eid_val(skip_run_id)
        for other_id in stairs.GetStairsRuns():
            if eid_val(other_id) == skip:
                continue
            element = document.GetElement(other_id)
            if element is not None:
                out.append((element, "start of the run above"))
    except Exception:
        pass

    return out


def elements_near(document, point, target_z, radius_ft):
    """[(element, label)] for floors and landings straddling a given level.

    The surface a flight finishes on is often not part of the stair at all -
    a floor slab, or a landing belonging to a different Stairs element. This
    is a bounded box query around the head of the run, not a document sweep.
    """
    found = []
    if point is None:
        return found

    try:
        low = XYZ(point.X - radius_ft, point.Y - radius_ft, target_z - 0.5)
        high = XYZ(point.X + radius_ft, point.Y + radius_ft, target_z + 0.5)
        box_filter = BoundingBoxIntersectsFilter(Outline(low, high))
    except Exception:
        return found

    wanted = [("OST_StairsLandings", "landing at the finish level"),
              ("OST_Floors", "floor at the finish level")]

    for cat_name, label in wanted:
        bic = getattr(BuiltInCategory, cat_name, None)
        if bic is None:
            continue
        try:
            collector = (FilteredElementCollector(document)
                         .OfCategory(bic)
                         .WhereElementIsNotElementType()
                         .WherePasses(box_filter))
            for element in collector:
                found.append((element, label))
        except Exception:
            continue

    return found


def find_level_at(document, elevation):
    """A Level datum at the given internal elevation, or None."""
    best = None
    best_gap = 0.05
    for level in FilteredElementCollector(document).OfClass(Level):
        try:
            gap = abs(level.Elevation - elevation)
        except Exception:
            continue
        if gap < best_gap:
            best_gap = gap
            best = level
    return best


class RunData(object):
    """One run of a stair, reduced to what the dimension chain needs.

    Everything positional comes from the run's own horizontal faces, never
    from BaseElevation / TopElevation - a parameter elevation is not
    guaranteed to share a basis with face.Origin.Z.
    """

    def __init__(self, run, index, stairs, link_instance):
        self.run = run
        self.index = index
        self.stairs = stairs
        self.link = link_instance
        self.error = None
        self.notes = []

        self.transform = None
        if link_instance is not None:
            self.transform = link_instance.GetTotalTransform()

        # -- counts and heights -------------------------------------------
        self.num_risers, _src = resolve_value(
            [(run, ["ActualRisersNumber", "ActualNumRisers"],
              ["STAIRS_RUN_ACTUAL_NUM_RISERS", "STAIRS_ACTUAL_NUM_RISERS"],
              ["Actual Number of Risers"]),
             (stairs, ["ActualRisersNumber", "ActualNumRisers"],
              ["STAIRS_ACTUAL_NUM_RISERS"],
              ["Actual Number of Risers"])],
            as_int=True)
        if self.num_risers is None:
            self.num_risers = 0

        self.riser_height_ft, self.height_source = resolve_value(
            [(run, ["ActualRiserHeight"],
              ["STAIRS_RUN_ACTUAL_RISER_HEIGHT", "STAIRS_ACTUAL_RISER_HEIGHT"],
              ["Actual Riser Height", "Riser Height"]),
             (stairs, ["ActualRiserHeight"],
              ["STAIRS_ACTUAL_RISER_HEIGHT"],
              ["Actual Riser Height", "Riser Height", "Maximum Riser Height"])])

        self.rise_ft, _src = resolve_value(
            [(run, ["Height"], ["STAIRS_RUN_HEIGHT"], ["Relative Height"])])

        # -- the run's own horizontal faces -------------------------------
        faces = horizontal_faces(run)
        if not faces:
            self.error = "no horizontal faces with references on this run"
            return

        faces.sort(key=lambda pair: pair[1])
        self.base_ref, self.base_z = faces[0]
        self.geom_top_ref, self.geom_top_z = faces[-1]

        if self.rise_ft is None or self.rise_ft < TOL:
            if self.num_risers > 0 and self.riser_height_ft:
                self.rise_ft = self.num_risers * self.riser_height_ft
            else:
                self.rise_ft = self.geom_top_z - self.base_z

        if self.riser_height_ft is None or self.riser_height_ft < TOL:
            if self.num_risers > 0:
                self.riser_height_ft = self.rise_ft / float(self.num_risers)
                self.height_source = "derived from rise / risers"
            else:
                self.error = "riser height unavailable and not derivable"
                return

        if self.num_risers < 1:
            self.num_risers = int(round(self.rise_ft / self.riser_height_ft))
            self.notes.append("riser count derived from rise / riser height")

        if self.num_risers < 1:
            self.error = "calculated riser count is less than 1"
            return

        # where this run finishes - one riser above its last tread when the
        # run ends with a riser
        self.finish_z = self.base_z + (self.num_risers * self.riser_height_ft)

        # how many risers the run's own solid actually reaches
        self.geom_risers = int(round(
            (self.geom_top_z - self.base_z) / self.riser_height_ft))

        # -- placement anchor ---------------------------------------------
        self.corners = []
        try:
            bbox = run.get_BoundingBox(None)
            if bbox is not None:
                local = bbox_corners(bbox)
                if self.transform is not None:
                    self.corners = [self.transform.OfPoint(p) for p in local]
                else:
                    self.corners = list(local)
        except Exception:
            self.corners = []

        self.top_point_local = None
        try:
            path = list(run.GetStairsPath())
            if path:
                self.top_point_local = path[-1].GetEndPoint(1)
        except Exception:
            self.top_point_local = None

    # -- derived values ---------------------------------------------------

    @property
    def riser_height_mm(self):
        return to_mm(self.riser_height_ft)

    @property
    def expected_mm(self):
        return self.num_risers * self.riser_height_mm

    def label(self):
        if self.error:
            return "Run {0}  -  {1}".format(self.index, self.error)
        return "Run {0}   |   {1} risers @ {2} mm   =   {3} mm".format(
            self.index,
            self.num_risers,
            fmt_mm(self.riser_height_mm),
            fmt_mm(self.expected_mm))


# ---------------------------------------------------------------------------
# Geometry - riser faces at the two ends of the run
# ---------------------------------------------------------------------------

def collect_solids(geometry_element, solids):
    for geo_obj in geometry_element:
        if isinstance(geo_obj, Solid):
            if geo_obj.Volume > 1.0e-6 and geo_obj.Faces.Size > 0:
                solids.append(geo_obj)
        elif isinstance(geo_obj, GeometryInstance):
            collect_solids(geo_obj.GetInstanceGeometry(), solids)


def horizontal_faces(element):
    """[(reference, z)] for every horizontal planar face carrying a reference."""
    found = []

    opts = Options()
    opts.ComputeReferences = True
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel = ViewDetailLevel.Fine

    geom = element.get_Geometry(opts)
    if geom is None:
        return found

    solids = []
    collect_solids(geom, solids)

    for solid in solids:
        for face in solid.Faces:
            if not isinstance(face, PlanarFace):
                continue
            if abs(face.FaceNormal.Z) < 0.999:
                continue
            face_ref = face.Reference
            if face_ref is None:
                continue
            found.append((face_ref, face.Origin.Z))

    return found


def top_surface_of(element):
    """Highest horizontal face on an element - a landing's walking surface."""
    faces = horizontal_faces(element)
    if not faces:
        return None, None
    faces.sort(key=lambda pair: pair[1])
    return faces[-1][0], faces[-1][1]


def finish_candidates(run_data, stairs, slack):
    """[(reference, z, label)] for the surface the last run finishes on.

    Only needed for the topmost run: every other run hands over to the run
    above it, whose base face sits on the landing and is reliably
    referenceable.
    """
    target = run_data.finish_z
    document = run_data.run.Document
    pool = []

    # landings of this stair, taken as whole elements rather than matched
    # on a parameter elevation
    if stairs is not None:
        try:
            for landing_id in stairs.GetStairsLandings():
                landing = document.GetElement(landing_id)
                if landing is None:
                    continue
                ref, z = top_surface_of(landing)
                if ref is not None:
                    pool.append((ref, z, "landing top surface",
                                 plan_distance(landing, run_data.top_point_local)))
        except Exception:
            pass

        # the stair solid itself carries the landing surfaces too
        for ref, z in horizontal_faces(stairs):
            pool.append((ref, z, "stair surface", 0.0))

    # floors and other stairs' landings sitting at the finish level
    for element, label in elements_near(document, run_data.top_point_local,
                                        target, 6.0):
        distance = plan_distance(element, run_data.top_point_local)
        for ref, z in horizontal_faces(element):
            pool.append((ref, z, label, distance))

    near = [c for c in pool if abs(c[1] - target) <= slack]
    near.sort(key=lambda c: (round(abs(c[1] - target), 6), c[3]))

    candidates = [(ref, z, label) for ref, z, label, _d in near[:5]]

    level = find_level_at(document, target)
    if level is not None:
        try:
            candidates.append((Reference(level), target,
                               "level '{0}'".format(type_name(level))))
        except Exception:
            pass

    # last resort - the run's own top tread, one riser short of the finish
    candidates.append((run_data.geom_top_ref, run_data.geom_top_z,
                       "top tread of the run (finish surface not found)"))
    return candidates


def build_chain(run_datas, stairs):
    """Turn the runs into an ordered list of dimension planes.

    plane 0 : base of the lowest run
    plane i : base of run i, which sits ON the landing above run i-1 - this
              is the whole trick. The landing's own top face is awkward to
              reference, but the next run's base face is at the identical
              elevation and is the same kind of face we already read
              successfully at the bottom of the stair.
    plane n : the surface the last run finishes on

    Returns (planes, segments, problems) where planes is
    [(reference, z, label)] bottom to top and segments is the RunData behind
    each gap between consecutive planes.
    """
    usable = [rd for rd in run_datas if not rd.error]
    problems = ["Run {0}: {1}".format(rd.index, rd.error)
                for rd in run_datas if rd.error]

    if not usable:
        return [], [], problems

    usable.sort(key=lambda rd: rd.base_z)

    slack = max(0.05, min([rd.riser_height_ft for rd in usable]) * 0.5)

    planes = [(usable[0].base_ref, usable[0].base_z, "base of the stair")]
    segments = []

    for i, run_data in enumerate(usable):

        nxt = usable[i + 1] if (i + 1) < len(usable) else None

        if nxt is not None and abs(nxt.base_z - run_data.finish_z) <= slack:
            planes.append((nxt.base_ref, nxt.base_z,
                           "landing top (base of run {0})".format(nxt.index)))
            segments.append(run_data)
            continue

        if nxt is not None:
            # a gap the runs do not explain - a landing thicker than one
            # riser, or runs that do not stack. Fall back to searching.
            problems.append(
                "Run {0}: run {1} starts {2} mm above this run's finish, not on it."
                .format(run_data.index, nxt.index,
                        fmt_mm(to_mm(nxt.base_z - run_data.finish_z))))

        found = None
        for ref, z, label in finish_candidates(run_data, stairs, slack):
            if (z - planes[-1][1]) > TOL:
                found = (ref, z, label)
                break

        if found is None:
            problems.append("Run {0}: no plane found above it - chain stops here."
                            .format(run_data.index))
            break

        planes.append(found)
        segments.append(run_data)

    if len(planes) < 2:
        return [], [], problems

    return planes, segments, problems


# ---------------------------------------------------------------------------
# WPF window
# ---------------------------------------------------------------------------

XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Stair Riser Chain Dimension"
        Height="580" Width="760"
        WindowStartupLocation="CenterScreen"
        WindowStyle="None" ResizeMode="NoResize"
        ShowInTaskbar="False" Background="#161616">

  <Window.Resources>

    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
    </Style>

    <Style x:Key="Caption" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Margin" Value="0,0,0,4"/>
    </Style>

    <Style TargetType="TextBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="CaretBrush" Value="#F1C21B"/>
      <Setter Property="BorderBrush" Value="#525252"/>
      <Setter Property="BorderThickness" Value="0,0,0,2"/>
      <Setter Property="Padding" Value="6,5"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Style.Triggers>
        <Trigger Property="IsFocused" Value="True">
          <Setter Property="BorderBrush" Value="#F1C21B"/>
        </Trigger>
      </Style.Triggers>
    </Style>

    <Style x:Key="Flat" TargetType="Button">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Background" Value="#393939"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Padding" Value="16,8"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" CornerRadius="3"
                    Background="{TemplateBinding Background}"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#525252"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Accent" TargetType="Button" BasedOn="{StaticResource Flat}">
      <Setter Property="Background" Value="#F1C21B"/>
      <Setter Property="Foreground" Value="#161616"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>

    <Style x:Key="Radio" TargetType="ToggleButton">
      <Setter Property="Foreground" Value="#A8A8A8"/>
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Padding" Value="14,7"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ToggleButton">
            <Border x:Name="Bd" CornerRadius="3"
                    Background="{TemplateBinding Background}"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ListBox">
      <Setter Property="Background" Value="#262626"/>
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="BorderBrush" Value="#393939"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Disabled"/>
    </Style>

    <Style TargetType="ListBoxItem">
      <Setter Property="Foreground" Value="#F4F4F4"/>
      <Setter Property="Padding" Value="8,5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListBoxItem">
            <Border x:Name="Bd" Background="Transparent"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#393939"/>
              </Trigger>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#F1C21B"/>
                <Setter Property="Foreground" Value="#161616"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

  </Window.Resources>

  <Border BorderBrush="#393939" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <!-- header -->
      <Border x:Name="HeaderBar" Grid.Row="0" Background="#262626" Padding="16,12">
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <StackPanel Grid.Column="0">
            <TextBlock Text="STAIR RISER CHAIN DIMENSION" FontSize="14" FontWeight="SemiBold"/>
            <TextBlock x:Name="SubTitle" Text="" Style="{StaticResource Caption}" Margin="0,3,0,0"/>
          </StackPanel>
          <Button x:Name="BtnClose" Grid.Column="1" Content="X" Width="32" Height="28"
                  Style="{StaticResource Flat}" Padding="0" Background="#262626"/>
        </Grid>
      </Border>

      <!-- body -->
      <Grid Grid.Row="1" Margin="16,14,16,10">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="300"/>
          <ColumnDefinition Width="16"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>

        <!-- left : dimension type -->
        <Grid Grid.Column="0">
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
          </Grid.RowDefinitions>
          <TextBlock Grid.Row="0" Text="DIMENSION TYPE" Style="{StaticResource Caption}"/>
          <TextBox Grid.Row="1" x:Name="TxtSearch" Margin="0,0,0,6"/>
          <ListBox Grid.Row="2" x:Name="LstTypes"/>
        </Grid>

        <!-- right : options -->
        <StackPanel Grid.Column="2">

          <TextBlock Text="RUNS ON THE STAIR YOU PICK   -   one segment each, bottom to top"
                     Style="{StaticResource Caption}"/>
          <ListBox x:Name="LstRuns" Height="86" Margin="0,0,0,12"
                   Focusable="False" IsHitTestVisible="False"/>

          <TextBlock Text="OFFSET FROM STAIR (MM)   -   negative places it on the other side"
                     Style="{StaticResource Caption}"/>
          <TextBox x:Name="TxtOffset" Text="500" Margin="0,0,0,12"/>

          <TextBlock Text="PREFIX TEMPLATE   ( {N} = riser count , {H} = riser height )"
                     Style="{StaticResource Caption}"/>
          <TextBox x:Name="TxtPrefix" Margin="0,0,0,12"/>

          <TextBlock Text="SUFFIX" Style="{StaticResource Caption}"/>
          <TextBox x:Name="TxtSuffix" Text="MM" Margin="0,0,0,12"/>

          <TextBlock Text="PREVIEW" Style="{StaticResource Caption}"/>
          <Border Background="#262626" BorderBrush="#393939" BorderThickness="1" Padding="10,8">
            <TextBlock x:Name="TxtPreview" Text="" Foreground="#F1C21B"
                       FontFamily="Consolas" FontSize="13" TextWrapping="Wrap"/>
          </Border>

        </StackPanel>
      </Grid>

      <!-- footer -->
      <Border Grid.Row="2" Background="#262626" Padding="16,12">
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <TextBlock x:Name="TxtStatus" Grid.Column="0" VerticalAlignment="Center"
                     Foreground="#A8A8A8" TextWrapping="Wrap" Margin="0,0,12,0"/>
          <StackPanel Grid.Column="1" Orientation="Horizontal">
            <Button x:Name="BtnCancel" Content="Cancel" Style="{StaticResource Flat}" Margin="0,0,8,0"/>
            <Button x:Name="BtnOk" Content="Start Chaining" Style="{StaticResource Accent}"/>
          </StackPanel>
        </Grid>
      </Border>

    </Grid>
  </Border>
</Window>
"""


def build_preview(run_info, prefix_template, suffix):
    if run_info is None or run_info.error:
        return ""
    prefix = (prefix_template
              .replace("{N}", str(run_info.num_risers))
              .replace("{H}", fmt_mm(run_info.riser_height_mm)))
    return "{0}{1} {2}".format(prefix, fmt_mm(run_info.expected_mm), suffix).strip()


def show_options_window(run_infos, preselect_index, dim_types, source_label):
    """Returns a dict with the user's choices, or None if cancelled."""

    window = XamlReader.Parse(XAML)

    sub_title = window.FindName("SubTitle")
    header_bar = window.FindName("HeaderBar")
    txt_search = window.FindName("TxtSearch")
    lst_types = window.FindName("LstTypes")
    lst_runs = window.FindName("LstRuns")
    txt_offset = window.FindName("TxtOffset")
    txt_prefix = window.FindName("TxtPrefix")
    txt_suffix = window.FindName("TxtSuffix")
    txt_preview = window.FindName("TxtPreview")
    txt_status = window.FindName("TxtStatus")
    btn_ok = window.FindName("BtnOk")
    btn_cancel = window.FindName("BtnCancel")
    btn_close = window.FindName("BtnClose")

    sub_title.Text = source_label
    txt_prefix.Text = "{N} EQ. RISERS @ {H}MM = "

    state = {"result": None, "type_map": []}

    # -- dimension types ---------------------------------------------------
    def fill_types(needle):
        lst_types.Items.Clear()
        state["type_map"] = []
        needle = (needle or "").strip().lower()
        for name, dim_type in dim_types:
            if needle and needle not in name.lower():
                continue
            state["type_map"].append(dim_type)
            lst_types.Items.Add(name)
        if lst_types.Items.Count > 0:
            lst_types.SelectedIndex = 0

    fill_types(None)

    # -- runs --------------------------------------------------------------
    for run_info in run_infos:
        lst_runs.Items.Add(run_info.label())

    def current_run():
        """The run the preview is drawn from - the first usable one."""
        for run_info in run_infos:
            if not run_info.error:
                return run_info
        return run_infos[0] if run_infos else None

    # -- preview -----------------------------------------------------------
    def refresh(sender=None, args=None):
        run_info = current_run()
        txt_preview.Text = build_preview(run_info, txt_prefix.Text, txt_suffix.Text)
        usable = len([r for r in run_infos if not r.error])
        if usable == 0:
            txt_status.Text = "No usable runs on this stair."
            btn_ok.IsEnabled = False
        else:
            txt_status.Text = ("These settings apply to every run you pick. "
                               "Press Esc in the view to finish.")
            btn_ok.IsEnabled = True

    # -- events ------------------------------------------------------------
    def on_search(sender, args):
        fill_types(txt_search.Text)

    txt_search.TextChanged += TextChangedEventHandler(on_search)
    txt_prefix.TextChanged += TextChangedEventHandler(refresh)
    txt_suffix.TextChanged += TextChangedEventHandler(refresh)

    def on_drag(sender, args):
        try:
            window.DragMove()
        except Exception:
            pass

    header_bar.MouseLeftButtonDown += MouseButtonEventHandler(on_drag)

    def on_ok(sender, args):
        if lst_types.SelectedIndex < 0:
            txt_status.Text = "Pick a dimension type."
            return
        try:
            offset_mm = float(txt_offset.Text)
        except ValueError:
            txt_status.Text = "Offset must be a number (mm)."
            return
        state["result"] = {
            "dim_type": state["type_map"][lst_types.SelectedIndex],
            "offset_mm": offset_mm,
            "prefix_template": txt_prefix.Text,
            "suffix": txt_suffix.Text,
        }
        window.Close()

    def on_cancel(sender, args):
        state["result"] = None
        window.Close()

    btn_ok.Click += RoutedEventHandler(on_ok)
    btn_cancel.Click += RoutedEventHandler(on_cancel)
    btn_close.Click += RoutedEventHandler(on_cancel)

    refresh()

    frame = DispatcherFrame()

    def on_closed(sender, args):
        frame.Continue = False

    window.Closed += EventHandler(on_closed)
    window.Show()
    Dispatcher.PushFrame(frame)

    return state["result"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():

    # -- view check - section and elevation views only ---------------------
    if active_view is None or active_view.IsTemplate:
        alert("Stair Riser Chain",
              "Open a section or elevation view and run the tool again.")
        return

    section_types = (ViewType.Section, ViewType.Elevation)

    if not isinstance(active_view, ViewSection) or active_view.ViewType not in section_types:
        alert("Stair Riser Chain",
              "This tool only runs in a section or elevation view.\n\n"
              "Current view is a {0}.".format(active_view.ViewType))
        return

    # the rise is measured along Z, so the view has to be upright
    up = active_view.UpDirection
    if abs(up.Z) < 0.99:
        alert("Stair Riser Chain",
              "This view is tilted, so a vertical dimension cannot be placed "
              "reliably. Use an upright section or elevation.")
        return

    # -- dimension types ---------------------------------------------------
    dim_types, all_types, problems = collect_dimension_types()

    if not dim_types:
        if all_types:
            # nothing matched the style filter, but types do exist - show them all
            # rather than blocking the user, and say why.
            dim_types = all_types
            report = ("No type reported a Linear style, so every dimension type in the "
                      "project is listed instead. Pick a linear one.")
            if problems:
                report += "\n\nProblems reading types:\n" + "\n".join(problems[:10])
            alert("Stair Riser Chain", report)
        else:
            report = "No DimensionType elements were found in this document at all."
            if problems:
                report += "\n\n" + "\n".join(problems[:10])
            alert("Stair Riser Chain", report)
            return

    # -- pick mode ---------------------------------------------------------
    mode = ask_source_mode()
    if mode is None:
        return

    if mode == "link":
        object_type = ObjectType.LinkedElement
        pick_filter = LinkedStairFilter(doc)
        prompt = "Select a stair run  -  Esc to finish"
    else:
        object_type = ObjectType.Element
        pick_filter = HostStairFilter()
        prompt = "Select a stair run  -  Esc to finish"

    settings = None
    created = 0
    log = []

    # -- pick / create loop, ends on Esc ------------------------------------
    while True:

        try:
            picked = uidoc.Selection.PickObject(object_type, pick_filter, prompt)
        except OperationCanceledException:
            break
        except Exception as ex:
            alert("Stair Riser Chain", "Selection failed:\n{0}".format(ex))
            break

        resolved = resolve_pick(picked, mode)
        if resolved["error"]:
            alert("Stair Riser Chain", resolved["error"])
            continue

        run_infos = resolved["run_infos"]
        preselect = resolved["preselect"]
        link_instance = resolved["link_instance"]

        # settings are asked once, then reused for every following pick
        if settings is None:
            choice = show_options_window(
                run_infos, preselect, dim_types, resolved["source_label"])
            if choice is None:
                return
            settings = {
                "dim_type": choice["dim_type"],
                "offset_mm": choice["offset_mm"],
                "prefix_template": choice["prefix_template"],
                "suffix": choice["suffix"],
            }

        placed, messages = create_chain_dimension(
            run_infos, resolved["stairs"], settings, link_instance)
        created += placed
        if messages:
            log.append("--- {0} ---".format(resolved["source_label"]))
            log.extend(messages)

    # -- session summary ----------------------------------------------------
    if created == 0 and not log:
        return

    lines = ["Segments dimensioned: {0}".format(created)]
    if log:
        lines.append("")
        lines.extend(log)

    alert("Stair Riser Chain", "\n".join(lines))


def resolve_pick(picked, mode):
    """Turn a picked reference into run data. Never raises."""
    out = {"error": None, "run_infos": None, "preselect": 0,
           "link_instance": None, "source_label": "", "stairs": None}

    host_element = doc.GetElement(picked.ElementId)
    link_instance = None
    source_doc = doc
    element = host_element

    if isinstance(host_element, RevitLinkInstance):
        link_instance = host_element
        source_doc = link_instance.GetLinkDocument()
        if source_doc is None:
            out["error"] = "That link is not loaded."
            return out
        linked_id = picked.LinkedElementId
        if linked_id is None or linked_id == ElementId.InvalidElementId:
            out["error"] = ("The pick returned the link instance rather than an element "
                            "inside it. Nested links are not supported.")
            return out
        element = source_doc.GetElement(linked_id)
    elif mode == "link":
        out["error"] = "That pick did not come from a Revit link."
        return out

    if element is None:
        out["error"] = "Nothing usable was selected."
        return out

    runs = []
    if isinstance(element, StairsRun):
        runs = [element]
    elif isinstance(element, Stairs):
        for run_id in element.GetStairsRuns():
            run_element = source_doc.GetElement(run_id)
            if run_element is not None:
                runs.append(run_element)
    else:
        out["error"] = "Selected element is a {0}, not a stair.".format(
            type(element).__name__)
        return out

    if not runs:
        out["error"] = "That stair has no runs."
        return out

    parent_stairs = element if isinstance(element, Stairs) else None
    if parent_stairs is None:
        try:
            parent_stairs = source_doc.GetElement(runs[0].StairsId)
        except Exception:
            parent_stairs = None

    run_infos = []
    for i, run in enumerate(runs):
        run_infos.append(RunData(run, i + 1, parent_stairs, link_instance))

    out["stairs"] = parent_stairs

    # which run did the click land on?
    # every run gets a segment, so nothing needs preselecting
    preselect = 0

    if link_instance is not None:
        out["source_label"] = "Linked model: {0}".format(source_doc.Title)
    else:
        out["source_label"] = "Host model: {0}".format(doc.Title)

    out["run_infos"] = run_infos
    out["preselect"] = preselect
    out["link_instance"] = link_instance
    return out


def create_chain_dimension(run_datas, stairs, settings, link_instance):
    """Place one multi-segment dimension up the stair. Returns (count, messages)."""

    planes, segments, messages = build_chain(run_datas, stairs)

    if len(planes) < 2:
        messages.append("No dimension planes could be established on this stair.")
        return 0, messages

    # -- lateral placement, past everything the stair occupies -------------
    right = active_view.RightDirection

    lateral = []
    for run_data in run_datas:
        for corner in run_data.corners:
            lateral.append(corner.DotProduct(right))
    if not lateral:
        messages.append("No bounding box on the stair - cannot place the dimension.")
        return 0, messages

    offset_mm = settings["offset_mm"]
    offset_ft = abs(offset_mm) / FT_TO_MM
    if offset_mm < 0:
        target_lateral = min(lateral) - offset_ft
    else:
        target_lateral = max(lateral) + offset_ft

    seed = None
    for run_data in run_datas:
        if run_data.corners:
            seed = run_data.corners[0]
            break
    base_pt = seed.Add(right.Multiply(target_lateral - seed.DotProduct(right)))

    # -- planes into host space -------------------------------------------
    transform = None
    for run_data in run_datas:
        if run_data.transform is not None:
            transform = run_data.transform
            break

    def to_host_z(z):
        if transform is None:
            return z
        return transform.OfPoint(XYZ(0.0, 0.0, z)).Z

    z_bottom = to_host_z(planes[0][1])
    z_top = to_host_z(planes[-1][1])

    if abs(z_top - z_bottom) < 1.0e-6:
        messages.append("The chain has no height.")
        return 0, messages

    dim_line = Line.CreateBound(XYZ(base_pt.X, base_pt.Y, z_bottom),
                                XYZ(base_pt.X, base_pt.Y, z_top))

    # -- references --------------------------------------------------------
    ref_array = ReferenceArray()
    for ref, _z, _label in planes:
        use = ref
        if link_instance is not None:
            try:
                use = ref.CreateLinkReference(link_instance)
            except Exception as ex:
                messages.append("A plane could not be referenced through the "
                                "link ({0}).".format(ex))
                return 0, messages
        ref_array.Append(use)

    suffix = settings["suffix"]

    t = Transaction(doc, "Stair Riser Chain Dimension")
    t.Start()
    try:
        dim = doc.Create.NewDimension(active_view, dim_line, ref_array,
                                      settings["dim_type"])
        if dim is None:
            raise Exception("NewDimension returned nothing.")

        written = write_segment_text(dim, segments, settings, suffix, messages)

        t.Commit()
    except Exception as ex:
        t.RollBack()
        messages.append("Dimension creation failed - {0}".format(ex))
        return 0, messages

    for index, (_ref, _z, label) in enumerate(planes):
        messages.append("Plane {0}: {1}".format(index, label))

    return written, messages


def write_segment_text(dim, segments, settings, suffix, messages):
    """Prefix/suffix onto each segment, or onto the dimension if there is one.

    A chained dimension exposes Dimension.Segments; a two-reference dimension
    has none and carries the text itself.
    """
    def text_for(run_data):
        return (settings["prefix_template"]
                .replace("{N}", str(run_data.num_risers))
                .replace("{H}", fmt_mm(run_data.riser_height_mm)))

    seg_array = None
    try:
        seg_array = dim.Segments
    except Exception:
        seg_array = None

    count = 0
    if seg_array is not None and seg_array.Size > 0:
        if seg_array.Size != len(segments):
            messages.append(
                "WARNING - {0} segments were created for {1} runs, so the "
                "segment text may not line up with the runs."
                .format(seg_array.Size, len(segments)))

        index = 0
        for segment in seg_array:
            if index >= len(segments):
                break
            run_data = segments[index]
            segment.Prefix = text_for(run_data)
            if suffix:
                segment.Suffix = suffix
            check_segment(segment, run_data, messages)
            index += 1
            count += 1
        return count

    # single segment
    run_data = segments[0]
    dim.Prefix = text_for(run_data)
    if suffix:
        dim.Suffix = suffix
    check_segment(dim, run_data, messages)
    return 1


def check_segment(segment, run_data, messages):
    """Compare what Revit measured against risers x riser height."""
    try:
        value = segment.Value
    except Exception:
        return
    if value is None:
        return

    measured = to_mm(value)
    expected = run_data.expected_mm
    if abs(measured - expected) > 1.0:
        short = int(round((expected - measured) / run_data.riser_height_mm))
        messages.append(
            "Run {0}: reads {1} mm, expected {2} risers x {3} mm = {4} mm "
            "({5} riser(s) short)."
            .format(run_data.index, fmt_mm(measured), run_data.num_risers,
                    fmt_mm(run_data.riser_height_mm), fmt_mm(expected), short))


main()