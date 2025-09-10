# -*- coding: utf-8 -*-

__title__   = "MEP Filters"
__doc__     = """
________________________________________________________________
Description:
- Creates View Filters for MEP for Visual Inspection 

How to Use:
- Run the script
- View Filters will be created for each MEP Network Individually
________________________________________________________________
Author: Mohamed Bedair"""

#Imports
import clr
clr.AddReference('System')
from System.Collections.Generic import List

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms, revit,script
from pyrevit import EXEC_PARAMS

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

##########################################################################################################
def create_view_filters(filter_name,cats,param_id,param_value,color):

    cats_id = [ElementId(cat) for cat in cats]

    pvp = ParameterValueProvider(param_id)

    if app.VersionNumber <= 2021:
        rule = FilterStringRule(pvp,FilterStringContains(),param_value,True)
    elif app.VersionNumber >= 2022:
        rule = FilterStringRule(pvp,FilterStringContains(),param_value)

    element_filter = ElementParameterFilter(rule)

    view_filter = ParameterFilterElement.Create(doc,filter_name,List[ElementId](cats_id),element_filter)

    all_fill_patterns = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
    solid_pattern = [i for i in all_fill_patterns if i.GetFillPattern().IsSolidFill][0]

    all_line_patterns = FilteredElementCollector(doc).OfClass(LinePatternElement).ToElements()
    solid_line_pattern_id = [i.GetSolidPatternId() for i in all_line_patterns][0]

    override_settings = OverrideGraphicSettings()
    override_settings.SetSurfaceForegroundPatternId(solid_pattern.Id)
    override_settings.SetSurfaceForegroundPatternColor(color)
    override_settings.SetSurfaceBackgroundPatternId(solid_pattern.Id)
    override_settings.SetSurfaceBackgroundPatternColor(color)

    override_settings.SetProjectionLinePatternId(solid_line_pattern_id)
    override_settings.SetProjectionLineColor(color)
    override_settings.SetProjectionLineWeight(1)

    active_view.AddFilter(view_filter.Id)
    active_view.SetFilterOverrides(view_filter.Id, override_settings)

##########################################################################################################


all_par_filters = FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements()
all_par_filters_names = [f.Name for f in all_par_filters]

mp_filters_names = [
    "COORD_SUPPLY DUCTS",
    "COORD_RETURN DUCTS",
    "COORD_EXHAUST DUCTS",
    "COORD_FIRE PIPES",
    "COORD_NOVEC PIPES",
    "COORD_COLD WATER PIPES",
    "COORD_HOT WATER PIPES",
    "COORD_SUPPLY CHILLED WATER",
    "COORD_RETURN CHILLED WATER",
    "COORD_DRAINAGE",
]



mp_filters_colors = [
    Color(0,128,255),   # color_supply_ducts
    Color(255,128,64),  # color_return_ducts
    Color(0,128,0),     # color_exhaust_ducts
    Color(255,0,0),     # color_fire_pipes
    Color(128,128,0),   # color_novec_pipes
    Color(0,0,255),     # color_cold_water_pipes
    Color(255,115,47),  # color_hot_water_pipes
    Color(128,128,255), # color_supply_chilled_water
    Color(255,255,128), # color_return_chilled_water
    Color(64,0,64),      # color_drainage
]

system_class_names = [
    "Supply Air",
    "Return Air",
    "Exhaust Air",
    "Fire Protection Wet",
    "Fire Protection Other",
    "Domestic Cold Water",
    "Domestic Hot Water",
    "Hydronic Supply",
    "Hydronic Return",
    "Sanitary"
]

mp_categories = [
    BuiltInCategory.OST_DuctSystem,
    BuiltInCategory.OST_DuctAccessory,
    BuiltInCategory.OST_DuctCurves,
    BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_DuctTerminal,
    BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_PipeAccessory,
    BuiltInCategory.OST_FlexPipeCurves,
    BuiltInCategory.OST_PipingSystem
]


elec_filters_names = ["COORD_ELECTRIC TRAYS","COORD_ICT TRAYS"]


t=Transaction(doc,"MEP Filters Check")

t.Start()

for f in all_par_filters:
    if f.Name in mp_filters_names or elec_filters_names:
        doc.Delete(f.Id)

t.Commit()

elec_filters_colors = [
    Color(255, 255, 0),   # color_electric_trays
    Color(128, 255, 255)  # color_ict_trays
]

elec_type_names = ["_E_","_T_"]

electrical_categories = [
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_Conduit,
    BuiltInCategory.OST_ConduitFitting
]

mp_param_id   = ElementId(BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM)

elec_param_id = ElementId(BuiltInParameter.SYMBOL_NAME_PARAM)

#Start Transaction
with Transaction(doc,__title__) as t:
    t.Start()


    for i in range(len(mp_filters_names)):

        create_view_filters(mp_filters_names[i],
                            mp_categories,
                            mp_param_id,
                            system_class_names[i],
                            mp_filters_colors[i])

    for i in range(len(elec_filters_names)):

        create_view_filters(elec_filters_names[i],
                            electrical_categories,
                            elec_param_id,
                            elec_type_names[i],
                            elec_filters_colors[i])

    t.Commit()