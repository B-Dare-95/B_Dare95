# -*- coding: utf-8 -*-
__title__ = "Leasing Generator"
__doc__ = """Version = 2.0
_____________________________________________________________________
Description:
Generates individual sales plans for all rooms named 'RETAIL' or 'F&B'.
Each room receives its own floor plan view with a fitted crop box,
rotated to align with the room's entrance door.
_____________________________________________________________________
Author: Erik Frits (refactored by Mohamed Bedair)"""

# IMPORTS
# ---------------------------------------------------------------------------
from Autodesk.Revit.DB import *

# .NET Imports
import clr
clr.AddReference("System")
from System.Collections.Generic import List

# VARIABLES
# ---------------------------------------------------------------------------
uidoc = __revit__.ActiveUIDocument
doc   = __revit__.ActiveUIDocument.Document  # type: Document

# Target room names
TARGET_ROOM_NAMES = ['RETAIL', 'F&B']


# FUNCTIONS
# ---------------------------------------------------------------------------
def rename_view(view, new_name):
    """Attempt to set the view name, appending '*' characters on conflict."""
    for i in range(20):
        try:
            view.Name = new_name
            break
        except:
            new_name += '*'


def get_room_BB(room, view):
    """Return an offset bounding box fitted around a single room."""
    offset_cm           = 50
    BOUNDING_BOX_OFFSET = UnitUtils.ConvertToInternalUnits(offset_cm, UnitTypeId.Centimeters)

    BB = room.get_BoundingBox(view)
    if BB is None:
        return None

    new_bb     = BoundingBoxXYZ()
    new_bb.Min = XYZ(BB.Min[0] - BOUNDING_BOX_OFFSET,
                     BB.Min[1] - BOUNDING_BOX_OFFSET,
                     BB.Min[2] - BOUNDING_BOX_OFFSET)
    new_bb.Max = XYZ(BB.Max[0] + BOUNDING_BOX_OFFSET,
                     BB.Max[1] + BOUNDING_BOX_OFFSET,
                     BB.Max[2] + BOUNDING_BOX_OFFSET)
    return new_bb


# MAIN
# ---------------------------------------------------------------------------

# 1. Collect all rooms and filter to RETAIL / F&B only
all_rooms = FilteredElementCollector(doc) \
                .OfCategory(BuiltInCategory.OST_Rooms) \
                .ToElements()

target_rooms = [r for r in all_rooms
                if r.get_Parameter(BuiltInParameter.ROOM_NAME).AsString() in TARGET_ROOM_NAMES]

if not target_rooms:
    print('No RETAIL or F&B rooms found in the model.')
else:
    print('Found {} target room(s). Generating sales plans...'.format(len(target_rooms)))

# 2. Create Transaction for all changes
t = Transaction(doc, 'Leasing Generator (Retail & F&B)')
t.Start()

try:
    plan_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeFloorPlan)

    for room in target_rooms:
        room_name   = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString()
        room_number = room.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString()
        lvl_id      = room.LevelId
        view_key    = 'Leasing Plan_{}_{}'.format(room_name, room_number)

        # 3. Create a floor plan for this room
        new_plan = ViewPlan.Create(doc, plan_type_id, lvl_id)
        rename_view(new_plan, view_key)

        # 4. Calculate and apply the crop box
        new_BB = get_room_BB(room, new_plan)
        if new_BB is None:
            print('Bounding box not available for: {} — skipping.'.format(view_key))
            continue

        new_plan.CropBox        = new_BB
        new_plan.CropBoxActive  = True
        new_plan.CropBoxVisible = True
        new_plan.DetailLevel    = ViewDetailLevel.Fine

        print('Generated: {}'.format(view_key))

except:
    t.RollBack()
    import traceback
    print(traceback.format_exc())
    raise

t.Commit()