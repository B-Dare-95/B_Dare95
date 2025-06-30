# -*- coding: utf-8 -*-

#Imports
import clr
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script
from pyrevit import EXEC_PARAMS
from rpw.ui.forms import *
import xlsxwriter

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

all_parameter_filters = FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements()
all_parameter_filters_names = [f.Name for f in all_parameter_filters]

wall_types = FilteredElementCollector(doc).OfClass(WallType).ToElements()
wall_types_names = [Element.Name.GetValue(typ) for typ in wall_types]

