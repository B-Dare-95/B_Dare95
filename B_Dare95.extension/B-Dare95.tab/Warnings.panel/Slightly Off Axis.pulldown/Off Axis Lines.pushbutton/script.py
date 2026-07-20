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


# ---- Step 1: collect only model/detail lines currently carrying a "slightly off axis" warning ----
warnings = doc.GetWarnings()
seen_ids = {}
off_axis_lines = []

for warning in warnings:
    description = warning.GetDescriptionText()
    if description and WARNING_TEXT in description.lower():
        for eid in warning.GetFailingElements():
            key = get_id_value(eid)
            if key in seen_ids:
                continue
            element = doc.GetElement(eid)
            # CurveElement covers both ModelLine and DetailLine
            if isinstance(element, CurveElement):
                seen_ids[key] = True
                off_axis_lines.append(element)

line_count = len(off_axis_lines)

# ---- Step 2: report findings and ask the user whether to proceed ----
if line_count == 0:
    TaskDialog.Show(
        "Align Off-Axis Lines",
        "No lines with a 'slightly off axis' warning were found."
    )
else:
    dialog_result = TaskDialog.Show(
        "Align Off-Axis Lines",
        "{} line(s) found with a 'slightly off axis' warning.\n\nProceed with fixing them?".format(line_count),
        TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
    )

    if dialog_result == TaskDialogResult.Yes:
        t = Transaction(doc, "Align Off-Axis Lines")
        t.Start()

        aligned_lines_count = 0
        skipped_pinned_count = 0
        skipped_error_count = 0

        try:
            for line_element in off_axis_lines:
                curve = line_element.GeometryCurve
                try:
                    if align_off_axis_element(line_element, curve):
                        aligned_lines_count += 1
                        print("Fixed line ID: {}".format(line_element.Id))
                except Exception as ex:
                    if line_element.Pinned:
                        skipped_pinned_count += 1
                        print("Skipped line ID: {} - reason: element is pinned".format(line_element.Id))
                    else:
                        skipped_error_count += 1
                        print("Skipped line ID: {} - reason: {}".format(line_element.Id, ex))

            t.Commit()
        except Exception as ex:
            t.RollBack()
            print("Transaction rolled back due to: {}".format(ex))
            raise

        print("{} of {} flagged lines were aligned.".format(aligned_lines_count, line_count))
        if skipped_pinned_count:
            print("{} lines skipped (pinned).".format(skipped_pinned_count))
        if skipped_error_count:
            print("{} lines skipped (other errors) - see log above.".format(skipped_error_count))
    else:
        print("Operation cancelled by user.")