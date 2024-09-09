# -*- coding: utf-8 -*-

#Imports
from Autodesk.Revit.DB import *

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

all_views = FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements()

inspection_views = [view for view in all_views if "Issue" in view.Name]

t = Transaction(doc,"Add Issue View")

t.Start()

snapshot_view_id = active_view.Duplicate(ViewDuplicateOption.WithDetailing)

snapshot_view = doc.GetElement(snapshot_view_id)

new_main_folder = snapshot_view.LookupParameter("SDC_Main-Folder").Set("DRAFTING")

new_sub_discipline = snapshot_view.LookupParameter("SDC_Sub-Discipline").Set("ARCHITECTURAL")

new_view_group = snapshot_view.LookupParameter("SDC_View-Group").Set("INSPECTION")

new_view_name = snapshot_view.LookupParameter("View Name").Set("Issue" + " " + str(len(inspection_views)+1))

snapshot_view.SaveOrientationAndLock()

t.Commit()



