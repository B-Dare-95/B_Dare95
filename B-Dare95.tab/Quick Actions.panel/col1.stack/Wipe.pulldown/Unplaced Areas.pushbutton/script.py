# -*- coding: utf-8 -*-

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *

#Variables
doc         =__revit__.ActiveUIDocument.Document

# Get All Rooms
tgrp=TransactionGroup(doc,"Wipe unplaced Rooms")
tgrp.Start()
all_areas = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Areas).WhereElementIsNotElementType().ToElements()

#Filter Unplaced Rooms
unplcd_ars=[]
for ar in all_areas:
    if not ar.LookupParameter("Level").HasValue:
        unplcd_ars.append(ar)

#Get Unplaced Rooms IDs
unplcd_ars_id=[]
for ar in unplcd_ars:
    ars_id = ar.Id

    #Start Deletion
    t=Transaction(doc,"Wipe Unplaced Areas")
    t.Start()

    deleted_ars=doc.Delete(ars_id)

    if not deleted_ars:
        pass
    t.Commit()
tgrp.Assimilate()