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
#
# #Special Variables
#
# #Special Functions
#
# def create_text_by_point(point_list,text):
#     text_type_id = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElementId()
#     for pt in point_list:
#         TextNote.Create(doc, active_view.Id, pt, text, text_type_id)
#
# ########################################################################################################################
#Get All Rooms
all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

areas = []

for room in all_rooms:
    room_area = UnitUtils.ConvertToInternalUnits(room.get_Parameter(BuiltInParameter.ROOM_AREA).AsDouble(), UnitTypeId.SquareMeters)
    if not room_area:
        continue
    areas.append(room_area)

print(sum(areas))
#
# #Get Only Bounded Rooms
# only_bound_rooms = [room for room in all_rooms
#                     if not room.LookupParameter("Area").AsDouble() == 0
#                     or not room.LookupParameter("Volume").AsDouble() == 0]
#
# # wall_type_dictionary = {wall_type.LookupParameter("Type Name").AsString() : wall_type for wall_type in all_wall_types
# #                         if "FIN" in wall_type.LookupParameter("Type Name").AsString() }
#
# #Empty Lists
#
# for room in only_bound_rooms:
#
#     # Create Solids from Rooms to Get Centroids
#     room_bounds_list = room.GetBoundarySegments(SpatialElementBoundaryOptions()) #List of List of Boundary Segments, Each Segment in a List
#
#     # Create Solid from Room
#     profile = CurveLoop()
#
#     for bound_list in room_bounds_list:
#
#         for bound in bound_list:
#
#             bound_curve = bound.GetCurve().CreateTransformed(Transform.CreateTranslation(XYZ(0, 0, 0)))
#
#             profile.Append(bound_curve)
#
#             if profile.IsOpen():
#                 continue
#
#             #Create a Provisional Solid to compute the room center
#             room_solid = GeometryCreationUtilities.CreateExtrusionGeometry([profile], XYZ.BasisZ, 0.00001)
#
#             room_center = room_solid.ComputeCentroid()
#
#             # with Transaction(doc,"Room Center") as t:
#             #
#             #     text_type_id = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElementId()
#             #
#             #     t.Start()
#             #
#             #     TextNote.Create(doc, active_view.Id, room_center,"C",text_type_id)
#             #
#             #     t.Commit()
#
#             # Get The Midpoint of Each Room Boundary
#             bound_midpoint = bound_curve.Evaluate(0.5, True)
#
#             # Create Vector from Boundary Midpoint to Room Location Point
#             vektor = bound_midpoint.Subtract(room_center)
#
#             opposite_vektor = vektor.Negate()
#
#             inspection_point = bound_midpoint.Add(vektor)
#
#             print(inspection_point)
# #
# # # print(room_inspection_points)
