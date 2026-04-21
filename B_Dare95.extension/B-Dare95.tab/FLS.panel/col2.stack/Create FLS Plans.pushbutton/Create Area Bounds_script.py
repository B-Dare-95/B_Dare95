# -*- coding: utf-8 -*-

#Imports

from Autodesk.Revit.DB import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView

fls_area_views = []

all_views = FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements()

for view in all_views:
    if view.ViewType == ViewType.AreaPlan:
        if view.AreaScheme.Name == "FLS":
            fls_area_views.append(view)

fls_views_dict = {view.Name : view for view in fls_area_views}

try:
    selected_area_view_names = forms.SelectFromList.show(
        fls_views_dict.keys(),
        title="Choose Area Plans",
        width=300,
        button_name="Make A Selection",
        multiselect=True)
except:
    script.exit()

for name in selected_area_view_names:
    selected_area_views = [fls_views_dict[name]]