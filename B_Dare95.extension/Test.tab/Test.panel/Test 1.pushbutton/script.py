# -*- coding: utf-8 -*-

#Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script
from pyrevit import EXEC_PARAMS

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

all_wall_types = FilteredElementCollector(doc).OfClass(WallType).ToElements()

wall_type_names = {
        wt.LookupParameter("Type Name").AsString(): wt
        for wt in all_wall_types}

wall_type_ids = {wt:
            wt.Id
            for wt in all_wall_types}

wall_type_widths = {wt:
                    wt.Width
                    for wt in all_wall_types}


all_levels = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Levels).WhereElementIsNotElementType().ToElements()

#sort levels based on elevations for consistency
sorted_levels = sorted(all_levels, key=lambda level: level.Elevation)
sorted_levels_ids = [lvl.Id for lvl in sorted_levels]

#Collect Shafts based on no. of levels connected by the shaft
all_shafts = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_ShaftOpening).WhereElementIsNotElementType().ToElements()

shafts_less_than_3lvls = []
shafts_greater_than_3lvls = []

#start collecting shafts into their containers
for shaft in all_shafts:

    shaft_top = shaft.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()

    shaft_bottom = shaft.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()

    no_of_connected_lvls = (len
                            (sorted_levels_ids
                             [sorted_levels_ids.index(shaft_bottom)
                              :sorted_levels_ids.index(shaft_top)])+1
                            )

    if no_of_connected_lvls < 3:
        shafts_less_than_3lvls.append(shaft)
    elif no_of_connected_lvls >= 3:
        shafts_greater_than_3lvls.append(shaft)

TaskDialog.Show("Choose Wall Type","Choose a Wall Type for Shafts connecting less than 3 levels")

wall_1hr_chosen = forms.SelectFromList.show(
    sorted(wall_type_names.keys()),
    title="Choose a Wall Type",
    width=300,
    button_name="Done",
    multiselect=False)

chosen_one_hr_type_wall= wall_type_names[wall_1hr_chosen]

TaskDialog.Show("Choose Wall Type","Choose a Wall Type for Shafts connecting more than 3 levels")

wall_2hr_chosen = forms.SelectFromList.show(
    sorted(wall_type_names.keys()),
    title="Choose a Wall Type",
    width=300,
    button_name="Done",
    multiselect=False)

chosen_two_hr_type_wall= wall_type_names[wall_2hr_chosen]


t=Transaction(doc,"Create Shaft Encasing")

t.Start()

try:
    for shaft in shafts_less_than_3lvls:

        shaft_bounds = shaft.BoundaryCurves

        for i,l in enumerate(sorted_levels):

            current_lvl = l[i].Elevation
            next_lvl = l[i+1].Elevation

            wall_height = next_lvl - current_lvl

            for b in shaft_bounds:

                 shaft_wall = Wall.Create(doc,
                                         b,
                                         chosen_one_hr_type_wall.Id,
                                         l.Id,
                                         wall_height,
                                         0,
                                         False,
                                         False)



    for shaft in shafts_greater_than_3lvls:

        shaft_bounds = shaft.BoundaryCurves

        for b,l in shaft_bounds,sorted_levels:

             shaft_wall = Wall.Create(doc,
                                     b,
                                     chosen_two_hr_type_wall.Id,
                                     l.Id,
                                     3000,
                                     0,
                                     False,
                                     False)
except Exception as e:
    print(e)
    script.exit()

t.Commit()


# t=Transaction(doc,"Create Wall Shafts")
#
# t.Start()
#
# for s in all_shafts:
#
#     shaft_level = s.LevelId
#
#     shaft_bounds = s.BoundaryCurves
#
#     for b in shaft_bounds:
#
#
#
#         shaft_wall = Wall.Create(doc,b,shaft_level,True)
#
# t.Commit()


# #
# # #Special Variables
# #
# # #Special Functions
# #
# # def create_text_by_point(point_list,text):
# #     text_type_id = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElementId()
# #     for pt in point_list:
# #         TextNote.Create(doc, active_view.Id, pt, text, text_type_id)
# #
# # ########################################################################################################################
# #Get All Rooms
# all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()
#
# areas = []
#
# for room in all_rooms:
#     room_area = UnitUtils.ConvertToInternalUnits(room.get_Parameter(BuiltInParameter.ROOM_AREA).AsDouble(), UnitTypeId.SquareMeters)
#     if not room_area:
#         continue
#     areas.append(room_area)
#
# print(sum(areas))
# #
# # #Get Only Bounded Rooms
# # only_bound_rooms = [room for room in all_rooms
# #                     if not room.LookupParameter("Area").AsDouble() == 0
# #                     or not room.LookupParameter("Volume").AsDouble() == 0]
# #
# # # wall_type_dictionary = {wall_type.LookupParameter("Type Name").AsString() : wall_type for wall_type in all_wall_types
# # #                         if "FIN" in wall_type.LookupParameter("Type Name").AsString() }
# #
# # #Empty Lists
# #
# # for room in only_bound_rooms:
# #
# #     # Create Solids from Rooms to Get Centroids
# #     room_bounds_list = room.GetBoundarySegments(SpatialElementBoundaryOptions()) #List of List of Boundary Segments, Each Segment in a List
# #
# #     # Create Solid from Room
# #     profile = CurveLoop()
# #
# #     for bound_list in room_bounds_list:
# #
# #         for bound in bound_list:
# #
# #             bound_curve = bound.GetCurve().CreateTransformed(Transform.CreateTranslation(XYZ(0, 0, 0)))
# #
# #             profile.Append(bound_curve)
# #
# #             if profile.IsOpen():
# #                 continue
# #
# #             #Create a Provisional Solid to compute the room center
# #             room_solid = GeometryCreationUtilities.CreateExtrusionGeometry([profile], XYZ.BasisZ, 0.00001)
# #
# #             room_center = room_solid.ComputeCentroid()
# #
# #             # with Transaction(doc,"Room Center") as t:
# #             #
# #             #     text_type_id = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElementId()
# #             #
# #             #     t.Start()
# #             #
# #             #     TextNote.Create(doc, active_view.Id, room_center,"C",text_type_id)
# #             #
# #             #     t.Commit()
# #
# #             # Get The Midpoint of Each Room Boundary
# #             bound_midpoint = bound_curve.Evaluate(0.5, True)
# #
# #             # Create Vector from Boundary Midpoint to Room Location Point
# #             vektor = bound_midpoint.Subtract(room_center)
# #
# #             opposite_vektor = vektor.Negate()
# #
# #             inspection_point = bound_midpoint.Add(vektor)
# #
# #             print(inspection_point)
# # #
# # # # print(room_inspection_points)