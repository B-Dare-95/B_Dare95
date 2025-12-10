# -*- coding: utf-8 -*-

#Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from pyrevit import script

#Revit Variables
   uidoc    = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

all_views = FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements()

inspection_views = [view for view in all_views if "Issue" in view.Name]

if not active_view.ViewType == ViewType.ThreeD:
    TaskDialog.Show("Error","You must use this tool in a 3D View")
    script.exit()

t = Transaction(doc,"Add Issue View")

t.Start()

snapshot_view_id = active_view.Duplicate(ViewDuplicateOption.WithDetailing)

snapshot_view = doc.GetElement(snapshot_view_id)

new_view_name = snapshot_view.LookupParameter("View Name").Set("Issue View" + " " + str(len(inspection_views)+1))

snapshot_view.SaveOrientationAndLock()

t.Commit()