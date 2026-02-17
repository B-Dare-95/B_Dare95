import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Architecture import Railing
from Autodesk.Revit.DB import RevitLinkInstance
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument


# --- Selection Filter ---

class LinkedStructuralColumnFilter(ISelectionFilter):
    """Allows selection of structural columns from Revit link instances only."""

    def AllowElement(self, element):
        # We want the user to pick a link instance, not a direct element
        return isinstance(element, RevitLinkInstance)

    def AllowReference(self, reference, point):
        # Resolve the reference to the linked element and check its category
        try:
            link_instance = doc.GetElement(reference.ElementId)
            if not isinstance(link_instance, RevitLinkInstance):
                return False
            linked_doc = link_instance.GetLinkDocument()
            linked_element = linked_doc.GetElement(reference.LinkedElementId)
            return (
                linked_element is not None
                and linked_element.Category is not None
                and linked_element.Category.Id.IntegerValue
                    == int(BuiltInCategory.OST_StructuralColumns)
            )
        except Exception:
            return False


# --- Helpers ---

def get_base_elevation(column, linked_doc):
    base_level_param = column.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)
    if base_level_param is None:
        return None
    base_level = linked_doc.GetElement(base_level_param.AsElementId())
    return base_level.Elevation if base_level else None


def get_footprint_curves(column, base_elevation, transform, tolerance=0.01):
    """Extract edges at the base elevation and transform them into host coordinates."""
    options = Options()
    options.ComputeReferences = True
    options.DetailLevel = ViewDetailLevel.Fine

    curves = []
    geom_element = column.get_Geometry(options)
    if geom_element is None:
        return curves

    for geom_obj in geom_element:
        solids = []

        if isinstance(geom_obj, GeometryInstance):
            solids = [obj for obj in geom_obj.GetInstanceGeometry() if isinstance(obj, Solid)]
        elif isinstance(geom_obj, Solid):
            solids = [geom_obj]

        for solid in solids:
            if solid.Volume <= 0:
                continue
            for edge in solid.Edges:
                curve = edge.AsCurve()
                p0 = curve.GetEndPoint(0)
                p1 = curve.GetEndPoint(1)
                if abs(p0.Z - base_elevation) < tolerance and abs(p1.Z - base_elevation) < tolerance:
                    curves.append(curve.CreateTransformed(transform))

    return curves


def create_model_lines(curves, sketch_plane):
    for curve in curves:
        try:
            doc.Create.NewModelCurve(curve, sketch_plane)
        except Exception as e:
            print("Skipped curve: {}".format(str(e)))


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

            curveloop = CurveLoop.Create(curves)

            #Create Railing

            column_guards = Railing.Create(
                doc,
                curveloop,
                ElementId(1659996),
                ElementId(30)
            )

        t.Commit()


    except Exception as e:
        print(e)
        t.RollBack()

