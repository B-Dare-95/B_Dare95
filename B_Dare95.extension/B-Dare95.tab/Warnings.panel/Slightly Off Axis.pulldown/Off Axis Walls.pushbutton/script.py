import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult

# Get the current Revit document
doc = __revit__.ActiveUIDocument.Document  # Works in the Revit Python Shell / pyRevit

max_distance = 0.0001
WARNING_TEXT = "slightly off axis"


def get_id_value(element_id):
    """ElementId -> plain int, safe across pre/post Revit 2024 API (Int32 vs Int64)."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def align_off_axis_element(element, curve):
    """Rotate a straight element back onto the X or Y axis if it's within
    max_distance of already being aligned. Returns True if rotated."""

    if not isinstance(curve, Line):
        return False

    direction = (curve.GetEndPoint(1) - curve.GetEndPoint(0)).Normalize()
    distance2hor = direction.DotProduct(XYZ.BasisY)
    distance2vert = direction.DotProduct(XYZ.BasisX)
    angle = 0

    if abs(distance2hor) < max_distance:
        vector = direction if direction.X >= 0 else direction.Negate()
        angle = math.asin(-vector.Y)

    if abs(distance2vert) < max_distance:
        vector = direction if direction.Y >= 0 else direction.Negate()
        angle = math.asin(vector.X)

    if angle != 0:
        rotation_axis = Line.CreateBound(curve.GetEndPoint(0), curve.GetEndPoint(0) + XYZ.BasisZ)
        ElementTransformUtils.RotateElement(doc, element.Id, rotation_axis, angle)
        return True
    return False


# ---- Step 1: collect only walls currently carrying a "slightly off axis" warning ----
warnings = doc.GetWarnings()
seen_ids = {}
off_axis_walls = []

for warning in warnings:
    description = warning.GetDescriptionText()
    if description and WARNING_TEXT in description.lower():
        for eid in warning.GetFailingElements():
            key = get_id_value(eid)
            if key in seen_ids:
                continue
            element = doc.GetElement(eid)
            if isinstance(element, Wall):
                seen_ids[key] = True
                off_axis_walls.append(element)

wall_count = len(off_axis_walls)

# ---- Step 2: report findings and ask the user whether to proceed ----
if wall_count == 0:
    TaskDialog.Show(
        "Align Off-Axis Walls",
        "No walls with a 'slightly off axis' warning were found."
    )
else:
    dialog_result = TaskDialog.Show(
        "Align Off-Axis Walls",
        "{} wall(s) found with a 'slightly off axis' warning.\n\nProceed with fixing them?".format(wall_count),
        TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
    )

    if dialog_result == TaskDialogResult.Yes:
        t = Transaction(doc, "Align Off-Axis Walls")
        t.Start()

        aligned_walls_count = 0
        skipped_pinned_count = 0
        skipped_error_count = 0

        try:
            for wall in off_axis_walls:
                location = wall.Location
                if isinstance(location, LocationCurve):
                    try:
                        if align_off_axis_element(wall, location.Curve):
                            aligned_walls_count += 1
                            print("Fixed wall ID: {}".format(wall.Id))
                    except Exception as ex:
                        if wall.Pinned:
                            skipped_pinned_count += 1
                            print("Skipped wall ID: {} - reason: element is pinned".format(wall.Id))
                        else:
                            skipped_error_count += 1
                            print("Skipped wall ID: {} - reason: {}".format(wall.Id, ex))

            t.Commit()
        except Exception as ex:
            t.RollBack()
            print("Transaction rolled back due to: {}".format(ex))
            raise

        print("{} of {} flagged walls were aligned.".format(aligned_walls_count, wall_count))
        if skipped_pinned_count:
            print("{} walls skipped (pinned).".format(skipped_pinned_count))
        if skipped_error_count:
            print("{} walls skipped (other errors) - see log above.".format(skipped_error_count))
    else:
        print("Operation cancelled by user.")