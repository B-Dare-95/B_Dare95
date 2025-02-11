# -*- coding: utf-8 -*-
from symbol import continue_stmt

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

#Override ISelectionFilter to Select Rooms
class RoomFilter(ISelectionFilter):
    def AllowElement(self, elem):
        if elem.Category.Name == "Rooms":
            return True
try:
    reference_room = uidoc.Selection.PickObject(ObjectType.Element, RoomFilter(), "Select Room")

except:
    script.exit()

#Get All Wall Types Names
all_wall_types = FilteredElementCollector(doc).OfClass(WallType).ToElements()

wall_type_dictionary = {wall_type.LookupParameter("Type Name").AsString() : wall_type for wall_type in all_wall_types
                        if "FIN" in wall_type.LookupParameter("Type Name").AsString() }
wall_type_names = wall_type_dictionary.keys()

#Prompt the user to select a wall type
selected_type_name=forms.SelectFromList.show(wall_type_names,title="Choose Wall Type"\
                                       ,width=400\
                                       ,button_name="Make A Selection"\
                                       ,multiselect=False)
#Error Handling in case user selected nothing or aborted selection
if not selected_type_name:
    script.exit()


selected_wall_type = wall_type_dictionary[selected_type_name]

wall_type_id = selected_wall_type.Id
wall_width = selected_wall_type.Width

#Extract Room Parameters
element_room   = doc.GetElement(reference_room)

height     = element_room .LookupParameter("Unbounded Height").AsDouble()
bottom     = element_room .LookupParameter("Base Offset").AsDouble()
room_level = element_room.Level
level_id = room_level.Id

room_bound_box = element_room.get_BoundingBox(doc.ActiveView)       #Use this method, dont use room.BoundingBox

room_center_bb = (room_bound_box.Min + room_bound_box.Max) / 2

room_center_2d = XYZ(room_center_bb.X,room_center_bb.Y,room_level.Elevation)


room_bounds_list = element_room.GetBoundarySegments(SpatialElementBoundaryOptions())

offset_vektors = []

t = Transaction(doc,"Create Wall Finishes")

t.Start()

for bound_list in room_bounds_list:
    for bound in bound_list:
        bound_curve = bound.GetCurve().CreateTransformed(Transform.CreateTranslation(XYZ(0,0,bottom)))

        bound_midpoint = bound_curve.Evaluate(0.5, True)

        # Create Vector from Boundary Midpoint to Room Location Point
        vektor = bound_midpoint.Add(room_center_2d)

        offset_bound = bound_curve.CreateOffset((wall_width*100),vektor)


        new_wall = Wall.Create(doc,offset_bound,wall_type_id,level_id,height,0,False,False)

t.Commit()