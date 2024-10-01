from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import TaskDialog

#Revit Variables

doc       = __revit__.ActiveUIDocument.Document

all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

only_bound_rooms = [room for room in all_rooms if not room.LookupParameter("Area").AsDouble() == 0 or not room.LookupParameter("Volume").AsDouble() == 0]

room_solids = []
for room in only_bound_rooms:
    height = room.LookupParameter("Unbounded Height").AsDouble()
    bottom = room.LookupParameter("Base Offset").AsDouble()

    room_bounds_list = room.GetBoundarySegments(SpatialElementBoundaryOptions())

    profile = CurveLoop()
    for bound_list in room_bounds_list:
        for bound in bound_list:
            profile.Append(bound.GetCurve().CreateTransformed(Transform.CreateTranslation(XYZ(0,0,bottom))))

    room_solid = GeometryCreationUtilities.CreateExtrusionGeometry([profile], XYZ.BasisZ, height)
    room_solids.append(room_solid)
    if profile.IsOpen():
        continue

all_patterns  = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
solid_pattern = [i for i in all_patterns if i.GetFillPattern().IsSolidFill][0]

color = Color(89,42,250)

override_settings = OverrideGraphicSettings()

override_settings.SetSurfaceForegroundPatternId(solid_pattern.Id)
override_settings.SetSurfaceForegroundPatternColor(color)

override_settings.SetCutForegroundPatternId(solid_pattern.Id)
override_settings.SetCutForegroundPatternColor(color)

override_settings.SetSurfaceTransparency(50)

t = Transaction(doc,"Create 3D Rooms")

t.Start()

for solid in room_solids:

    direct_shape = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel)).SetShape([solid])
    created_shapes = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType().ToElements()
    for shape in created_shapes:
        doc.ActiveView.SetElementOverrides(shape.Id, override_settings)

t.Commit()