# -*- coding: utf-8 -*-

#Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output = script.get_output()

#Select Element

element_reference = selection.PickObject(ObjectType.Element,"Select Element")
selected_element = doc.GetElement(element_reference.ElementId)

element_geometry = (selected_element.get_Geometry(Options()))

print(element_geometry)
enum = element_geometry.GetEnumerator()
print (enum)

for e in enum:
    print(e)
#     element_faces = e.Faces
    # for face in element_faces:
    #     # print(face)









