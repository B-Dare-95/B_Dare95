# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__version__ = '1.0.0'
__doc__ = """__________________________________________________
Description:

Lists every room in the model with its name and area.
Each line is a link: click it to select that room in Revit.
__________________________________________________
How-to:

-> Click on the button
-> The room list opens in the output window
-> Click a line to select that room
__________________________________________________
Author: Mohamed Bedair"""

#Imports
from Autodesk.Revit.DB import *
from pyrevit import script

#Revit Variables
doc = __revit__.ActiveUIDocument.Document
output = script.get_output()

all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

for room in all_rooms:
    linkify_rooms = output.linkify(room.Id,"Room Name: {} >> Area = {} " .format(room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString(),room.get_Parameter(BuiltInParameter.ROOM_AREA).AsValueString()))
    print(linkify_rooms)