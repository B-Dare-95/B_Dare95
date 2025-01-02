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

########################################################################################################################

all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

room_dictionary = {}

for room in all_rooms:

#Get Room Location Point
    room_location = room.Location
    room_location_point = room_location.Point

#Get Room Boundaries
    room_bounds_list = room.GetBoundarySegments(SpatialElementBoundaryOptions())

    for bound_list in room_bounds_list:
        room_dictionary.update({room_location_point:bound_list})



for k,v in room_dictionary.items():
    #Get Lines from Boundary Segment Lists
    for bound in v:
        #Get The Bounding Element
        bounding_element = doc.GetElement(bound.ElementId)

        #Get The Midpoint of Bounding Element
        if isinstance(bounding_element,Wall):
            location_curve = bounding_element.Location
            bound_midpoint = location_curve.Curve.Evaluate(0.5,True)

            #Create Vector from Boundary Midpoint to Room Location Point
            vektor =  bound_midpoint.Add(k)
            #Negate The Vector
            opposite_vektor = vektor.Negate()

            inspection_point = bound_midpoint.Move(opposite_vektor)
            print(inspection_point)

            moved_curve = location_curve.Move(opposite_vektor)

            new_inspection_point = moved_curve.Curve.Evaluate(0.5,True)

            print(new_inspection_point)





































































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










