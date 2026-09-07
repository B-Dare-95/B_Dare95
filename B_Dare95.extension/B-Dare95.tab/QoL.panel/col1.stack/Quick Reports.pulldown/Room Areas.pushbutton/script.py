# -*- coding: utf-8 -*-

__title__ = "Room Area Lister"
__author__ = "Mohamed Bedair"
__version__ = '1.0.0'
__doc__ = """

Description:
 scans your entire Revit project and generates an instant, clickable report of every Room in the model

How-to:
>> Click the tool button
>> The output window will open automatically and populate with a list of all rooms found in the model.

Author: Mohamed Bedair
"""

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