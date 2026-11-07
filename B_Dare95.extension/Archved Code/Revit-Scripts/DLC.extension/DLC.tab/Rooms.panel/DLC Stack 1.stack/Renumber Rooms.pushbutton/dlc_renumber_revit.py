# -*- coding: utf-8 -*-
"""
DLC_RenumberRooms - dlc_renumber_revit.py  (v1.1.0)

Every Revit-API touching operation that is NOT user-interface lives here, so
it can be exercised against a mock API in the test harness. bd_family_cleaner.py holds
only the WPF dialog and the pick/apply orchestration.

IronPython 2.7 compatible: no f-strings, no walrus, stdlib only.
"""

from Autodesk.Revit import DB
from Autodesk.Revit.DB import Architecture
from Autodesk.Revit.UI.Selection import ISelectionFilter

TEMP_NUMBER_PREFIX = "~DLCTMP~"
TRANSACTION_NAME = "DLC Renumber Rooms"


# ---------------------------------------------------------------------------
# Selection filters
# ---------------------------------------------------------------------------

class RoomPickFilter(ISelectionFilter):
    """Restricts PickObject to rooms."""

    def AllowElement(self, element):
        return isinstance(element, Architecture.Room)

    def AllowReference(self, reference, point):
        # Must return True: with ObjectType.Element Revit still consults this
        # for the element's reference, and returning False blocks the pick
        # entirely - the room highlights but will not accept a click.
        return True


class CurvePickFilter(ISelectionFilter):
    """Restricts PickObject to detail lines / model lines."""

    def AllowElement(self, element):
        return isinstance(element, DB.CurveElement)

    def AllowReference(self, reference, point):
        return True


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

class WarningSwallower(DB.IFailuresPreprocessor):
    """
    Renumbering a level can legitimately produce numbers that already exist on
    another level. Revit treats that as a warning, not an error, but the modal
    warning dialog would interrupt a batch mid-run. We delete warnings and
    leave errors alone so genuine failures still surface.
    """

    def PreprocessFailures(self, failures_accessor):
        for message in failures_accessor.GetFailureMessages():
            if message.GetSeverity() == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(message)
        return DB.FailureProcessingResult.Continue


# ---------------------------------------------------------------------------
# Parameter access
# ---------------------------------------------------------------------------

def get_element_name(element):
    """
    Element.Name is an explicit interface implementation; IronPython's dynamic
    dispatch cannot resolve it reliably via plain dotted access.
    """
    return DB.Element.Name.GetValue(element)


def get_room_number(room):
    param = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
    if param is None:
        return ""
    value = param.AsString()
    return value if value is not None else ""


def get_room_name(room):
    param = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
    if param is None:
        return ""
    value = param.AsString()
    return value if value is not None else ""


def set_room_number(room, value):
    param = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
    if param is None:
        raise ValueError("This room has no Number parameter.")
    if param.IsReadOnly:
        raise ValueError("This room's Number parameter is read-only.")
    param.Set(value)


def get_room_level_id(room):
    """Prefer Element.LevelId; fall back to the parameter on older API paths."""
    try:
        level_id = room.LevelId
        if level_id is not None and level_id != DB.ElementId.InvalidElementId:
            return level_id
    except Exception:
        pass
    param = room.get_Parameter(DB.BuiltInParameter.ROOM_LEVEL_ID)
    if param is None:
        return DB.ElementId.InvalidElementId
    return param.AsElementId()


def get_room_area(room):
    try:
        return room.Area
    except Exception:
        return 0.0


def get_room_xyz(room):
    location = room.Location
    if isinstance(location, DB.LocationPoint):
        point = location.Point
        return (point.X, point.Y, point.Z)
    return (None, None, None)


def room_to_record(room):
    x, y, z = get_room_xyz(room)
    return {
        "id": room.Id.IntegerValue,
        "x": x,
        "y": y,
        "z": z,
        "area": get_room_area(room),
        "number": get_room_number(room),
        "name": get_room_name(room),
    }


def build_records(rooms):
    """Returns (records, id_to_room) - records feed the pure core module."""
    records = []
    id_to_room = {}
    for room in rooms:
        record = room_to_record(room)
        records.append(record)
        id_to_room[record["id"]] = room
    return records, id_to_room


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def get_all_levels(doc):
    levels = list(
        DB.FilteredElementCollector(doc)
        .OfClass(DB.Level)
        .WhereElementIsNotElementType()
    )
    levels.sort(key=lambda lv: lv.Elevation)
    return levels


def collect_all_rooms(doc):
    return list(
        DB.FilteredElementCollector(doc)
        .OfCategory(DB.BuiltInCategory.OST_Rooms)
        .WhereElementIsNotElementType()
    )


def collect_rooms_on_level(doc, level_id):
    rooms = []
    for room in collect_all_rooms(doc):
        if get_room_level_id(room) == level_id:
            rooms.append(room)
    return rooms


def collect_rooms_by_ids(doc, element_ids):
    """
    Used for the 'Selected Rooms' scope. The caller must capture element ids
    ONCE at launch: PickObject clears the active selection, so re-reading
    uidoc.Selection after a pick would silently shrink the scope to one room.
    """
    rooms = []
    for element_id in element_ids:
        element = doc.GetElement(element_id)
        if isinstance(element, Architecture.Room):
            rooms.append(element)
    return rooms


def collect_rooms_in_view(doc, view):
    if view is None:
        return []
    try:
        return list(
            DB.FilteredElementCollector(doc, view.Id)
            .OfCategory(DB.BuiltInCategory.OST_Rooms)
            .WhereElementIsNotElementType()
        )
    except Exception:
        # Sheets, schedules and some 3D views reject a view-scoped collector.
        return []


# ---------------------------------------------------------------------------
# Path-mode projection
# ---------------------------------------------------------------------------

def _chord_parameter(curve, x, y):
    """
    Normalised position along the infinite 2D line through the curve's end
    points. Used as a consistent fallback when Curve.Project fails.
    """
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    dx = p1.X - p0.X
    dy = p1.Y - p0.Y
    denominator = (dx * dx) + (dy * dy)
    if denominator == 0.0:
        return None
    return (((x - p0.X) * dx) + ((y - p0.Y) * dy)) / denominator


def build_path_parameters(records, curve):
    """
    Returns (pairs, mode) where pairs is [(room_id, parameter), ...].

    Curve.Project returns None for points falling outside a bounded curve, so
    rooms past either end of a picked line would vanish from the ordering.
    Mixing projected and fallback values is not safe either - Project returns
    raw curve parameters while the fallback is normalised, and sorting two
    different metrics together scrambles the order. So it is all-or-nothing:
    if every room projects, use Project; otherwise use the chord fallback for
    every room so one consistent metric is compared.
    """
    projected = []
    all_projected = True

    for record in records:
        if record["x"] is None:
            continue
        z = record["z"]
        if z is None:
            z = curve.GetEndPoint(0).Z
        point = DB.XYZ(record["x"], record["y"], z)
        result = None
        try:
            result = curve.Project(point)
        except Exception:
            result = None
        if result is None:
            all_projected = False
            break
        projected.append((record["id"], result.Parameter))

    if all_projected and projected:
        return projected, "project"

    fallback = []
    for record in records:
        if record["x"] is None:
            continue
        parameter = _chord_parameter(curve, record["x"], record["y"])
        if parameter is not None:
            fallback.append((record["id"], parameter))
    return fallback, "chord"


# ---------------------------------------------------------------------------
# Collision reporting
# ---------------------------------------------------------------------------

def find_external_collisions(doc, new_numbers_by_id, scope_room_ids):
    """
    Target numbers already used by rooms OUTSIDE the scope. Revit permits
    duplicate room numbers with a warning, so this does not block the run -
    it is surfaced in the preview so the choice is deliberate.
    """
    scope = set(scope_room_ids)
    targets = {}
    for room_id, number in new_numbers_by_id.items():
        targets.setdefault(number, []).append(room_id)

    collisions = []
    for room in collect_all_rooms(doc):
        room_id = room.Id.IntegerValue
        if room_id in scope:
            continue
        number = get_room_number(room)
        if number in targets:
            collisions.append((number, room_id, get_room_name(room)))
    return collisions


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_rename_plan(doc, id_to_room, temp_pass, final_pass, original_numbers):
    """
    Two-pass write inside one Transaction, each element in its own
    SubTransaction so a single bad room cannot roll back the batch.

    If a room takes its temp number but then fails its final number, it would
    be left showing '~DLCTMP~...' in the model. That is worse than not having
    run at all, so the original number is restored for that room and the
    failure is reported.

    Returns (errors, applied_count).
    """
    errors = []
    applied = 0
    temped = set()

    transaction = DB.Transaction(doc, TRANSACTION_NAME)
    transaction.Start()
    try:
        try:
            options = transaction.GetFailureHandlingOptions()
            options.SetFailuresPreprocessor(WarningSwallower())
            options.SetClearAfterRollback(True)
            transaction.SetFailureHandlingOptions(options)
        except Exception:
            # Failure-handling options are a convenience; never abort over them.
            pass

        for room_id, number in temp_pass:
            room = id_to_room.get(room_id)
            if room is None:
                errors.append("Room id %s was no longer available." % room_id)
                continue
            sub = DB.SubTransaction(doc)
            sub.Start()
            try:
                set_room_number(room, number)
                sub.Commit()
                temped.add(room_id)
            except Exception as error:
                sub.RollBack()
                errors.append(
                    "Could not stage room id %s: %s" % (room_id, str(error))
                )

        for room_id, number in final_pass:
            room = id_to_room.get(room_id)
            if room is None:
                continue
            if room_id not in temped:
                # Staging failed for this room; leave it untouched.
                continue
            sub = DB.SubTransaction(doc)
            sub.Start()
            try:
                set_room_number(room, number)
                sub.Commit()
                applied += 1
            except Exception as error:
                sub.RollBack()
                errors.append(
                    "Could not set room id %s to '%s': %s"
                    % (room_id, number, str(error))
                )
                _restore_original(doc, room, room_id, original_numbers, errors)

        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise

    return errors, applied


def _restore_original(doc, room, room_id, original_numbers, errors):
    original = original_numbers.get(room_id)
    if original is None:
        errors.append(
            "Room id %s is left on a temporary number and its original is "
            "unknown. Set its number manually." % room_id
        )
        return
    sub = DB.SubTransaction(doc)
    sub.Start()
    try:
        set_room_number(room, original)
        sub.Commit()
    except Exception as error:
        sub.RollBack()
        errors.append(
            "Room id %s is left on a temporary number - restoring '%s' also "
            "failed (%s). Set its number manually."
            % (room_id, original, str(error))
        )
