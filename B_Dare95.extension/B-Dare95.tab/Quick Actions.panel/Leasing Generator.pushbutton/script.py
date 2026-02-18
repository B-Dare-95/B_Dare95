# -*- coding: utf-8 -*-
__title__ = "Leasing Generator"
__doc__ = """Version = 3.0
_____________________________________________________________________
Description:
Generates individual sales plan views for all rooms named 'RETAIL'
or 'F&B'. For each qualifying room the script produces:

  1. Floor Plan  — axis-aligned crop box fitted tightly around the room.
  2. Longitudinal Section — cut plane passes through the widest door's
     insertion point, perpendicular to the host wall, capturing the full
     room depth and height.
  3. Door Wall Elevation — section positioned at room centre, looking
     toward the wall that hosts the widest door from the interior.

If no door is found for a room the views still generate using a
fallback north-facing orientation for the sections, and a warning is
printed.
_____________________________________________________________________
Author: Erik Frits (refactored by Mohamed Bedair)"""

# ── Imports ────────────────────────────────────────────────────────────────
from Autodesk.Revit.DB import (
    BoundingBoxXYZ, BuiltInCategory, BuiltInParameter,
    ElementTypeGroup, FamilyInstance, FilteredElementCollector,
    LocationPoint, Transaction, Transform, UnitTypeId, UnitUtils,
    ViewDetailLevel, ViewFamilyType, ViewFamily, ViewPlan, ViewSection,
    XYZ,View
)

from pyrevit import forms,script

import clr
clr.AddReference("System")

# ── Variables ──────────────────────────────────────────────────────────────
uidoc = __revit__.ActiveUIDocument
doc   = __revit__.ActiveUIDocument.Document  # type: Document

TARGET_ROOM_NAMES = ['RETAIL', 'F&B']
OFFSET_CM         = 50   # padding added around each room's bounding box (cm)

#Selecting Rooms by Name
try:
    all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

    all_room_names = [room.LookupParameter("Name").AsValueString() for room in all_rooms]

    unique_room_names = set(all_room_names)

    room_dict_names = dict(zip(all_rooms, all_room_names))

    TARGET_ROOM_NAMES = forms.SelectFromList.show(
        unique_room_names,
        title="Choose Room Names",
        width=300,
        button_name="Make A Selection",
        multiselect=True)
except:
    script.exit()
#Selecting View Template to apply


all_views = FilteredElementCollector(doc).OfClass(View).ToElements()

view_templates = [vt for vt in all_views if vt.IsTemplate]

view_template_names = [vt.Name for vt in view_templates]

vt_dict = dict(zip(view_template_names, view_templates))

try:
    selected_view_template_plans = forms.SelectFromList.show(
        view_template_names,
        title="Choose View Template for Plans",
        width=1000,
        button_name="Make A Selection",
        multiselect=False)

except:
    script.exit()

try:
    selected_view_template_secs = forms.SelectFromList.show(
        view_template_names,
        title="Choose View Template for Sections",
        width=1000,
        button_name="Make A Selection",
        multiselect=False)

except:
    script.exit()

vt_to_apply_plans = vt_dict.get(selected_view_template_plans)
vt_to_apply_secs  = vt_dict.get(selected_view_template_secs)

# ══════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════

def rename_view(view, new_name):
    """Set view.Name, appending '*' characters if the name is already taken."""
    for _ in range(20):
        try:
            view.Name = new_name
            return
        except Exception:
            new_name += '*'


def get_cm(value_cm):
    """Convert centimetres to Revit internal units (decimal feet)."""
    return UnitUtils.ConvertToInternalUnits(value_cm, UnitTypeId.Centimeters)


def normalize_xy(vec):
    """
    Return a unit vector parallel to *vec* with its Z component zeroed out.
    Falls back to (0, 1, 0) if the projected length is negligible.
    """
    xy     = XYZ(vec.X, vec.Y, 0.0)
    length = xy.GetLength()
    if length < 1e-9:
        return XYZ(0.0, 1.0, 0.0)
    return xy.Multiply(1.0 / length)


def get_last_phase(doc):
    """Return the last phase defined in the project."""
    phases = doc.Phases
    return phases.get_Item(phases.Size - 1)


def get_room_corners(BB):
    """Return all 8 corners of a BoundingBoxXYZ as a list of XYZ points."""
    pts = []
    for x in [BB.Min.X, BB.Max.X]:
        for y in [BB.Min.Y, BB.Max.Y]:
            for z in [BB.Min.Z, BB.Max.Z]:
                pts.append(XYZ(x, y, z))
    return pts


def get_local_extents(BB, transform):
    """
    Return the axis-aligned extents of all 8 BB corners expressed in the
    local coordinate frame of *transform*.

    Returns (min_x, max_x, min_y, max_y, min_z, max_z).
    """
    inv   = transform.Inverse
    local = [inv.OfPoint(p) for p in get_room_corners(BB)]
    return (
        min(p.X for p in local), max(p.X for p in local),
        min(p.Y for p in local), max(p.Y for p in local),
        min(p.Z for p in local), max(p.Z for p in local),
    )


# ══════════════════════════════════════════════════════════════════════════
# DOOR DISCOVERY
# ══════════════════════════════════════════════════════════════════════════

def get_widest_door_in_room(room, all_doors, phase):
    """
    Return the FamilyInstance (door) with the greatest nominal width that
    belongs to *room* in the given *phase*.  Returns None if no door is found.

    Membership is determined by checking door.ToRoom / door.FromRoom against
    the room's ElementId.  Width is read from the instance parameter first;
    if absent or zero, the type (Symbol) parameter is used instead.
    """
    widest_door = None
    max_width   = -1.0

    for door in all_doors:
        try:
            to_room   = door.ToRoom[phase]
            from_room = door.FromRoom[phase]
        except Exception:
            continue

        room_match = (
            (to_room   is not None and to_room.Id   == room.Id) or
            (from_room is not None and from_room.Id == room.Id)
        )
        if not room_match:
            continue

        # Prefer instance-level width; fall back to type-level width.
        param = door.get_Parameter(BuiltInParameter.DOOR_WIDTH)
        if param is None or param.AsDouble() < 1e-9:
            param = door.Symbol.get_Parameter(BuiltInParameter.DOOR_WIDTH)

        if param is not None:
            w = param.AsDouble()
            if w > max_width:
                max_width   = w
                widest_door = door

    return widest_door


# ══════════════════════════════════════════════════════════════════════════
# FLOOR PLAN: AXIS-ALIGNED CROP BOX
# ══════════════════════════════════════════════════════════════════════════

def make_floor_plan_crop_box(room, ref_view):
    """
    Build a plain axis-aligned BoundingBoxXYZ fitted around *room* with a
    uniform padding on all sides.  No Transform is applied — the plan keeps
    Revit's default north-up orientation.

    Parameters
    ----------
    room     : SpatialElement  – the Revit room
    ref_view : ViewPlan        – used to query the room bounding box
    """
    offset = get_cm(OFFSET_CM)
    BB     = room.get_BoundingBox(ref_view)
    if BB is None:
        return None

    new_bb     = BoundingBoxXYZ()
    new_bb.Min = XYZ(BB.Min.X - offset, BB.Min.Y - offset, BB.Min.Z - offset)
    new_bb.Max = XYZ(BB.Max.X + offset, BB.Max.Y + offset, BB.Max.Z + offset)
    return new_bb


# ══════════════════════════════════════════════════════════════════════════
# SECTION VIEWS
# ══════════════════════════════════════════════════════════════════════════

def get_section_type_id(doc):
    """Return the ElementId of the first Section ViewFamilyType found."""
    for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        if vft.ViewFamily == ViewFamily.Section:
            return vft.Id
    return None


def make_section_bb(room, ref_view, origin, view_dir_xy):
    """
    Build a BoundingBoxXYZ ready for ViewSection.CreateSection.

    The convention used here:
      BasisX — right direction in the section (horizontal in the view)
      BasisY — up direction in the section (world Z)
      BasisZ — look direction (the section displays everything in front of
                the cut plane along +BasisZ)

    The cut plane is located at *origin*.  Min.Z = 0 (the cut itself);
    Max.Z covers the full depth of the room plus a small padding.

    Parameters
    ----------
    room         : SpatialElement
    ref_view     : ViewPlan  – used to query the room bounding box
    origin       : XYZ       – point on the section cut plane
    view_dir_xy  : XYZ       – normalised XY direction the section looks toward
    """
    offset   = get_cm(OFFSET_CM)
    BB       = room.get_BoundingBox(ref_view)
    if BB is None:
        return None

    world_up = XYZ(0.0, 0.0, 1.0)
    z_axis   = view_dir_xy
    x_axis   = z_axis.CrossProduct(world_up).Normalize()
    y_axis   = world_up

    tf         = Transform.Identity
    tf.BasisX  = x_axis
    tf.BasisY  = y_axis
    tf.BasisZ  = z_axis
    tf.Origin  = origin

    mn_x, mx_x, mn_y, mx_y, mn_z, mx_z = get_local_extents(BB, tf)

    # Section crops horizontally and vertically; depth runs from cut (0) to far clip.
    sec_bb           = BoundingBoxXYZ()
    sec_bb.Transform = tf
    sec_bb.Min       = XYZ(mn_x - offset, mn_y - offset, 0.0)
    sec_bb.Max       = XYZ(mx_x + offset, mx_y + offset, (mx_z - mn_z) + offset)
    return sec_bb


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

# 1. Collect target rooms.
all_rooms = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_Rooms)
             .ToElements())

target_rooms = [
    r for r in all_rooms
    if r.get_Parameter(BuiltInParameter.ROOM_NAME).AsString() in TARGET_ROOM_NAMES
]

# 2. Collect all door instances.
all_doors = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_Doors)
             .OfClass(FamilyInstance)
             .ToElements())

phase        = get_last_phase(doc)
sec_type_id  = get_section_type_id(doc)
plan_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeFloorPlan)

if not target_rooms:
    print('No RETAIL or F&B rooms found in the model.')
else:
    print('Found {} target room(s). Generating views...\n'.format(len(target_rooms)))

# 3. Single transaction covers all view creation.
t = Transaction(doc, 'Leasing Generator v3 (Retail & F&B)')
t.Start()

try:
    for room in target_rooms:
        room_name   = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString()
        room_number = room.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString()
        lvl_id      = room.LevelId
        tag         = '{}_{}'.format(room_name, room_number)

        print('Processing: {}'.format(tag))

        # ── Determine orientation from the widest door ──────────────────────
        widest_door = get_widest_door_in_room(room, all_doors, phase)

        if widest_door is not None:
            door_facing_xy = normalize_xy(widest_door.FacingOrientation)
        else:
            door_facing_xy = XYZ(0.0, 1.0, 0.0)
            print('  [WARN] No door found — defaulting to north-facing orientation.')

        # ── 1. Floor Plan (axis-aligned, no rotation) ──────────────────────
        plan_name = 'Leasing Plan_{}'.format(tag)
        new_plan  = ViewPlan.Create(doc, plan_type_id, lvl_id)
        rename_view(new_plan, plan_name)

        crop_bb = make_floor_plan_crop_box(room, new_plan)
        if crop_bb is not None:
            new_plan.CropBox        = crop_bb
            new_plan.CropBoxActive  = True
            new_plan.CropBoxVisible = True
        new_plan.DetailLevel = ViewDetailLevel.Fine
        new_plan.ViewTemplateId = vt_to_apply_plans.Id
        print('  [OK] Floor plan:              {}'.format(plan_name))

        # Derive the room centre from the newly oriented plan.
        plan_BB     = room.get_BoundingBox(new_plan)
        room_centre = (plan_BB.Min + plan_BB.Max) * 0.5 if plan_BB else XYZ.Zero

        # ── 2. Longitudinal Section through the widest door ────────────────
        # To cut *through* the door opening the cut plane must be perpendicular
        # to the host wall — i.e., it must contain the door-facing vector.
        # That means the section's look direction must run *along* the wall
        # (parallel to the wall face), not away from it.
        #
        # door_facing_xy  →  perpendicular to wall (outward through opening)
        # door_wall_dir   →  door_facing_xy rotated 90° in plan = along the wall
        #
        # With door_wall_dir as the look direction the cut plane is at 90° to
        # the wall, passes through the door insertion point, and the section
        # captures the full room depth and height as you look from one side of
        # the room toward the other.
        world_up     = XYZ(0.0, 0.0, 1.0)
        door_wall_dir = normalize_xy(door_facing_xy.CrossProduct(world_up))

        if widest_door is not None and isinstance(widest_door.Location, LocationPoint):
            door_pt     = widest_door.Location.Point
            sec1_origin = XYZ(door_pt.X, door_pt.Y, room_centre.Z)
        else:
            sec1_origin = room_centre   # fallback when no door location is available

        sec1_name = 'Leasing Section - Longitudinal_{}'.format(tag)
        sec1_bb   = make_section_bb(room, new_plan, sec1_origin, door_wall_dir)

        if sec1_bb is not None and sec_type_id is not None:
            sec1             = ViewSection.CreateSection(doc, sec_type_id, sec1_bb)
            sec1.DetailLevel = ViewDetailLevel.Fine
            rename_view(sec1, sec1_name)
            print('  [OK] Longitudinal section:    {}'.format(sec1_name))
        else:
            print('  [WARN] Could not create longitudinal section for {}.'.format(tag))

        # ── 3. Door Wall Elevation (section looking toward entrance wall) ────
        # The look direction is computed as the normalised vector from the
        # room centre to the door's insertion point.  This is more robust than
        # relying solely on FacingOrientation, because it always points from
        # the room's interior toward the wall hosting the door regardless of
        # how the door instance was placed.
        if widest_door is not None and isinstance(widest_door.Location, LocationPoint):
            door_pt     = widest_door.Location.Point
            to_door_vec = XYZ(
                door_pt.X - room_centre.X,
                door_pt.Y - room_centre.Y,
                0.0
            )
            sec2_view_dir = normalize_xy(to_door_vec)
        else:
            # Fallback: assume the door faces outward, so looking inward = reversed.
            sec2_view_dir = normalize_xy(
                XYZ(-door_facing_xy.X, -door_facing_xy.Y, 0.0)
            )

        sec2_name = 'Leasing Section - Door Wall Elevation_{}'.format(tag)
        sec2_bb   = make_section_bb(room, new_plan, room_centre, sec2_view_dir)

        if sec2_bb is not None and sec_type_id is not None:
            sec2             = ViewSection.CreateSection(doc, sec_type_id, sec2_bb)
            sec2.DetailLevel = ViewDetailLevel.Fine
            rename_view(sec2, sec2_name)

            print('  [OK] Door wall elevation:     {}'.format(sec2_name))
        else:
            print('  [WARN] Could not create door wall elevation for {}.'.format(tag))

        print('')

    t.Commit()
    print('Done. All views generated successfully.')

except Exception:
    t.RollBack()
    import traceback
    print(traceback.format_exc())
    raise