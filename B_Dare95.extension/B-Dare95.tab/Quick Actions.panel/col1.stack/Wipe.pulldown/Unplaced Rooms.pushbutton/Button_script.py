# -*- coding: utf-8 -*-

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *

# Variables
doc         =__revit__.ActiveUIDocument.Document

# Get All Rooms
tgrp=TransactionGroup(doc,"Wipe unplaced Rooms")
tgrp.Start()
all_rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

#Filter Unplaced Rooms
unplcd_rms=[]
for rm in all_rooms:
    if rm.LookupParameter("Unbounded Height").AsDouble() == 0 :
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