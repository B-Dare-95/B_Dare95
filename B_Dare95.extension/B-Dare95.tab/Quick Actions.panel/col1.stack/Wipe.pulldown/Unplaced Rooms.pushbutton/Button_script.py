# -*- coding: utf-8 -*-

__title__ = "Wipe Unplaced Rooms"
__author__ = "Mohamed Bedair"
__version__ = '1.0.0'
__doc__ = """
Version = 1.1.0

Description:
Purges unplaced rooms from the model.

How-to:
-> Run the script

Author: Mohamed Bedair
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *

# Variables
doc = __revit__.ActiveUIDocument.Document

# Get All Rooms
tgrp=TransactionGroup(doc,__title__)

tgrp.Start()

all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

#Filter Unplaced Rooms
unplcd_rms=[]
for rm in all_rooms:
    location = rm.Location
    if location is None or (isinstance(location, LocationPoint) and location.Point is None):
        unplcd_rms.append(rm)

#Get Unplaced Rooms IDs
unplcd_rms_id=[]
for rm in unplcd_rms:
    rms_id = rm.Id

    #Start Deletion
    t=Transaction(doc,"Wipe unplaced Rooms")
    t.Start()

    deleted_rms=doc.Delete(rms_id)

    if not deleted_rms:
        pass
    t.Commit()
tgrp.Assimilate()