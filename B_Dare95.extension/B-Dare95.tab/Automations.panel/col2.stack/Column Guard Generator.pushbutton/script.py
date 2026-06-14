# -*- coding: utf-8 -*-
__title__ = "Column Guard Generator"
__doc__ = """Version = 1.0
_____________________________________________________________________
Description:
Generates individual Column Guardrails for each column in a linked file.

How to use:

1-Select a Railing Type to use as Column Guardrail
2-Select Structural Columns to apply the guard 
3-Done!!
_____________________________________________________________________
Author: Mohamed Bedair"""

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import (Level,FilteredElementCollector, BuiltInParameter,
                                BuiltInCategory, Options, ViewDetailLevel,
                                GeometryInstance, Solid, CurveLoop,
                                Transaction, XYZ, RevitLinkInstance)
from Autodesk.Revit.DB.Architecture import Railing, RailingType
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import forms

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

#Select Railing for Column Guard

all_rail_types = FilteredElementCollector(doc).OfClass(RailingType).ToElements()

all_rail_types_id = FilteredElementCollector(doc).OfClass(RailingType).ToElementIds()

all_rail_names = [rail.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsValueString() for rail in all_rail_types]

rail_dict_type_name = dict(zip(all_rail_types, all_rail_names))

rail_dict_name_id = dict(zip(all_rail_names, all_rail_types_id))


selected_rail = forms.SelectFromList.show(
    all_rail_names,
    title="Choose Rail Type",
    width=300,
    button_name="Make A Selection",
    multiselect=False)

selected_rail_id = rail_dict_name_id.get(selected_rail)

# --- Selection Filter ---

class LinkedStructuralColumnFilter(ISelectionFilter):
    """Allows selection of structural columns from Revit link instances only."""

    def AllowElement(self, element):
        # We want the user to pick a link instance, not a direct element
        return isinstance(element, RevitLinkInstance)

    def AllowReference(self, reference, point):
        try:
            link_instance = doc.GetElement(reference.ElementId)
            if not isinstance(link_instance, RevitLinkInstance):
                return False
            linked_doc = link_instance.GetLinkDocument()
            linked_element = linked_doc.GetElement(reference.LinkedElementId)
            if linked_element is None or linked_element.Category is None:
                return False
            return linked_element.Category.Id.Value == int(BuiltInCategory.OST_StructuralColumns)
        except Exception:
            return False

# --- Helpers ---

def get_base_elevation(column, linked_doc):
    base_level_param = column.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)
    if base_level_param is None:
        return None
    base_level = linked_doc.GetElement(base_level_param.AsElementId())
    return base_level.Elevation if base_level else None

def _collect_solids(geom_obj):
    """Recursively collect all Solids from a geometry object, handling nested GeometryInstances."""
    solids = []
    if isinstance(geom_obj, Solid):
        if geom_obj.Volume > 0:
            solids.append(geom_obj)
    elif isinstance(geom_obj, GeometryInstance):
        for child in geom_obj.GetInstanceGeometry():
            solids.extend(_collect_solids(child))
    return solids


def get_footprint_curves(column, base_elevation, transform, tolerance=0.05):
    """
    Extract bottom-face edges from the column solid and transform to host coordinates.
    Strategy: find the lowest Z face in the solid (not relying on exact elevation match),
    then return its boundary curves transformed into host space.
    """
    options = Options()
    options.ComputeReferences = True
    options.DetailLevel = ViewDetailLevel.Fine

    geom_element = column.get_Geometry(options)
    if geom_element is None:
        return []

    # Collect all solids recursively (handles nested GeometryInstances)
    all_solids = []
    for geom_obj in geom_element:
        all_solids.extend(_collect_solids(geom_obj))

    if not all_solids:
        return []

    # Pick the solid with the largest volume (the main column body)
    main_solid = max(all_solids, key=lambda s: s.Volume)

    # Find the lowest horizontal face (base of column) by centroid Z
    best_face = None
    best_face_z = None
    for face in main_solid.Faces:
        normal = face.FaceNormal
        # Only consider near-horizontal faces pointing downward or upward
        if abs(normal.Z) < 0.9:
            continue
        # Compute approximate face centroid Z by averaging edge endpoints
        edge_loops = face.EdgeLoops
        z_vals = []
        for loop in edge_loops:
            for edge in loop:
                z_vals.append(edge.AsCurve().GetEndPoint(0).Z)
                z_vals.append(edge.AsCurve().GetEndPoint(1).Z)
        if not z_vals:
            continue
        face_z = sum(z_vals) / len(z_vals)
        if best_face_z is None or face_z < best_face_z:
            best_face_z = face_z
            best_face = face

    if best_face is None:
        return []

    # Extract outer boundary curves from the bottom face and transform to host space
    curves = []
    outer_loop = list(best_face.EdgeLoops)[0]  # first loop is always the outer boundary
    for edge in outer_loop:
        curve = edge.AsCurve()
        curves.append(curve.CreateTransformed(transform))

    return curves
def create_model_lines(curves, sketch_plane):
    for curve in curves:
        try:
            doc.Create.NewModelCurve(curve, sketch_plane)
        except Exception as e:
            print("Skipped curve: {}".format(str(e)))

def sort_curves_into_loop(curves, tolerance=1e-6):
    """Re-order curves so they form a single connected closed loop."""
    if not curves:
        return curves
    sorted_curves = [curves[0]]
    remaining = list(curves[1:])
    while remaining:
        last_end = sorted_curves[-1].GetEndPoint(1)
        matched = False
        for i, c in enumerate(remaining):
            if last_end.DistanceTo(c.GetEndPoint(0)) < tolerance:
                sorted_curves.append(c)
                remaining.pop(i)
                matched = True
                break
            elif last_end.DistanceTo(c.GetEndPoint(1)) < tolerance:
                sorted_curves.append(c.CreateReversed())
                remaining.pop(i)
                matched = True
                break
        if not matched:
            break  # open chain — let CurveLoop.Create surface the geometry error
    return sorted_curves

def get_nearest_host_level_id(host_doc, elevation):
    """Return the Id of the host-doc level closest to the given elevation."""
    levels = FilteredElementCollector(host_doc).OfClass(Level).ToElements()
    if not levels:
        return None
    return min(levels, key=lambda lvl: abs(lvl.Elevation - elevation)).Id

# --- Main ---

sel_filter = LinkedStructuralColumnFilter()

try:
    references = uidoc.Selection.PickObjects(
        ObjectType.LinkedElement,
        sel_filter,
        "Select structural columns from a Revit link (Finish when done)"
    )
except Exception:
    print("Selection cancelled.")
    references = []

if not references:
    print("No columns selected.")
else:
    t = Transaction(doc, "Generate Column Footprint Lines")
    t.Start()
    try:
        for ref in references:
            link_instance = doc.GetElement(ref.ElementId)
            linked_doc = link_instance.GetLinkDocument()
            transform = link_instance.GetTotalTransform()

            column = linked_doc.GetElement(ref.LinkedElementId)
            base_elevation = get_base_elevation(column, linked_doc)
            if base_elevation is None:
                print("Could not determine base elevation for element: {}".format(column.Id))
                continue

            # Transform base elevation into host coordinates (Z only)
            transformed_origin = transform.OfPoint(XYZ(0, 0, base_elevation))
            host_base_elevation = transformed_origin.Z

            curves = get_footprint_curves(column, base_elevation, transform)
            if not curves:
                print("No footprint curves found for element: {}".format(column.Id))
                continue

            # Fix 1: sort edges into a proper connected loop before creating CurveLoop
            ordered_curves = sort_curves_into_loop(curves)
            curveloop = CurveLoop.Create(ordered_curves)

            # Fix 2: resolve level against the HOST document by elevation
            host_level_id = get_nearest_host_level_id(doc, host_base_elevation)
            if host_level_id is None:
                print("No host level found for element: {}".format(column.Id))
                continue

            column_guards = Railing.Create(
                doc,
                curveloop,
                selected_rail_id,
                host_level_id
            )

            column_guards.Flip()

        t.Commit()

    except Exception as e:
        print(e)
        t.RollBack()