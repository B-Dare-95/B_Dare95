# -*- coding: utf-8 -*-

#Imports
import clr
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
output      = script.get_output()

# ===================================

# #Get All View Filters
# all_par_filters = FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements()
# all_par_filters_name = [f.Name for f in all_par_filters]
#
# #Get All Wall Types
# wall_types = FilteredElementCollector(doc).OfClass(WallType).ToElements()
# wall_type_names = [Element.Name.GetValue(typ) for typ in wall_types]
#
# with Transaction(doc,"Create ViewFilter") as t:
#
#     t.Start()
#
#     for wall_type_name in wall_type_names:
#         filter_name = "Wall Type_{} ".format(wall_type_name
#          if not filter_name in all_par_filters_name:
#
#              categories = List[ElementId]()
#              categories.Add(ElementId(BuiltInCategory.OST_Walls))
#
#              pvp = ParameterValueProvider(ElementId(BuiltInParameter.SYMBOL_NAME_PARAM))
#
#              rule1 = FilterStringEquals(pvp,FilterStringEquals,wall_type_name)
#
#              wall_filter = ElementParameterFilter(rule1)
#
#              view_filter = ParameterFilterElement.Create(doc,filter_name,categories,wall_filter)


