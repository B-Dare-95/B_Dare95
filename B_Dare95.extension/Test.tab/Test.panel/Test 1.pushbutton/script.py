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

#Special Variables

#Special Functions

def create_text_by_point(point_list,text):
    text_type_id = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElementId()
    for pt in point_list:
        TextNote.Create(doc, active_view.Id, pt, text, text_type_id)

########################################################################################################################
#Get All Rooms
all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

#Get Only Bounded Rooms
only_bound_rooms = [room for room in all_rooms
                    if not room.LookupParameter("Area").AsDouble() == 0
                    or not room.LookupParameter("Volume").AsDouble() == 0]

#Empty Lists
room_dictionary = {}

room_bounds     = []
room_centers    = []
room_inspection_points = []

for room in only_bound_rooms:

    # Create Solids from Rooms to Get Centroids
    room_bounds_list = room.GetBoundarySegments(SpatialElementBoundaryOptions()) #List of List of Boundary Segments, Each Segment in a List

    profile = CurveLoop()
    for bound_list in room_bounds_list:

        room_bounds.append(bound_list)

        for bound in bound_list:
            profile.Append(bound.GetCurve().CreateTransformed(Transform.CreateTranslation(XYZ(0, 0, 0))))
            if profile.IsOpen():
                continue
            room_solid = GeometryCreationUtilities.CreateExtrusionGeometry([profile], XYZ.BasisZ, 0.00001)
            room_center = room_solid.ComputeCentroid()

            room_centers.append(room_center)

for center,bound_list in zip(room_centers,room_bounds):
    room_dictionary[center] = bound_list


for center,bound_list in room_dictionary.items():
    for bound in bound_list:
        points = []
        # Get Room Boundary as Curve
        bound_curve = bound.GetCurve().CreateTransformed(Transform.CreateTranslation(XYZ(0, 0, 0)))

        #Get The Midpoint of Each Room Boundary
        bound_midpoint = bound_curve.Evaluate(0.5, True)

        #Create Vector from Boundary Midpoint to Room Location Point
        vektor = bound_midpoint.Subtract(center)
        opposite_vektor = vektor.Negate()

        inspection_point = bound_midpoint.Add(vektor)
        points.append(inspection_point)
        room_inspection_points.append(points)

print(room_inspection_points)

































































# element_reference = selection.PickObject(ObjectType.Element,"Select Element")
# selected_element = doc.GetElement(element_reference.ElementId)
#
# element_geometry = (selected_element.get_Geometry(Options()))
#
# print(element_geometry)
# enum = element_geometry.GetEnumerator()
# print (enum)
#
# for e in enum:
#     print(e)










