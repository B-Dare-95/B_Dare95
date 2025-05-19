import json, os, codecs

from Autodesk.Revit.DB import *

from pyrevit.script import toggle_icon

PATH_SCRIPT = os.path.dirname(__file__)

#Revit Variables
app = __revit__.Application
doc = __revit__.ActiveUIDocument.Document

def read_toggle_config():
    """Function to read toggle_state.json config located in the script's folder.
    If file is not found it will be created with False value."""
    json_toggle_state = os.path.join(PATH_SCRIPT, 'toggle_state.json')

    # READ/CREATE file
    if os.path.exists(json_toggle_state):
        with open(json_toggle_state) as f:
            json_data = json.load(f)
            TOGGLE = json_data['toggle_state']
    else:
        TOGGLE = False
    # REVERSE VALUE
    with open(json_toggle_state, "w") as f:
        x = not TOGGLE
        new_data = {"toggle_state": x}
        json.dump(new_data, f)
    return TOGGLE

all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

only_bound_rooms = [room for room in all_rooms if not room.LookupParameter("Area").AsDouble() == 0 or not room.LookupParameter("Volume").AsDouble() == 0]



TOGGLE = read_toggle_config()

# ACTIVATE/DEACTIVATE ICON
icon_on  = os.path.join(PATH_SCRIPT, 'on.png')
icon_off = os.path.join(PATH_SCRIPT, 'off.png')
toggle_icon(TOGGLE, icon_on, icon_off) #Change icon

room_solids = []

for room in only_bound_rooms:
    try:

        height = room.LookupParameter("Unbounded Height").AsDouble()
        bottom = room.LookupParameter("Base Offset").AsDouble()

        room_bounds_list = room.GetBoundarySegments(SpatialElementBoundaryOptions())

        profile = CurveLoop()

        for bound_list in room_bounds_list:

            for bound in bound_list:

                profile.Append(bound.GetCurve().CreateTransformed(Transform.CreateTranslation(XYZ(0,0,bottom))))



    except:
        continue

    room_solid = GeometryCreationUtilities.CreateExtrusionGeometry([profile], XYZ.BasisZ, height)
    room_solids.append(room_solid)
    if profile.IsOpen():
        pass

#Collecting Solid patterns
all_patterns  = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
solid_pattern = [i for i in all_patterns if i.GetFillPattern().IsSolidFill][0]

color = Color(89,42,250)

override_settings = OverrideGraphicSettings()

override_settings.SetSurfaceForegroundPatternId(solid_pattern.Id)
override_settings.SetSurfaceForegroundPatternColor(color)

override_settings.SetCutForegroundPatternId(solid_pattern.Id)
override_settings.SetCutForegroundPatternColor(color)

override_settings.SetSurfaceTransparency(25)

tgrp = TransactionGroup(doc,"3D Rooms")

tgrp.Start()

t1 = Transaction(doc,"create 3D Rooms")

t1.Start()

shapes = []

for solid in room_solids:

    direct_shape = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel)).SetShape([solid])
    created_shapes = FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType().ToElements()
    for shape in created_shapes:
        shapes.append(shape)
        doc.ActiveView.SetElementOverrides(shape.Id, override_settings)

t1.Commit()

# t2 = Transaction(doc,"3D Room Names")
#
# t2.Start()
#
#
# for shape,solid in shapes,room_solids:
#     for room in only_bound_rooms:
#         try:
#             solid_center = solid.ComputeCentroid()
#
#             if room.IsPointInRoom(solid_center):
#                 shape.LookupParameter("Comments").Set(room.Name)
#
#         except:
#             continue
#
# t2.Commit()

tgrp.Assimilate()

if not TOGGLE:

    t = Transaction(doc, "Delete 3D Rooms")

    t.Start()

    for shape in created_shapes:
        doc.Delete(shape.Id)

    t.Commit()