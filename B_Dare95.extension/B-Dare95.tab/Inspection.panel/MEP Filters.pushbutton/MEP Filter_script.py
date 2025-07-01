# -*- coding: utf-8 -*-

__title__   = "MEP Filters"
__doc__     = """
________________________________________________________________
Description:
- Creates View Filters for MEP for Visual Inspection 

- Run the script
- View Filters will be created for each MEP Network Individually
________________________________________________________________
Author: Mohamed Bedair"""

import random

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
def create_view_filters(filter_name,cats,sys_class_name,color):

    cats_id = [cat.Id for cat in cats]

    pvp = ParameterValueProvider(ElementId(BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM))

    if app.VersionNumber >= 2021:
        rule = FilterStringRule(pvp,FilterStringEquals(),sys_class_name,True)
    elif app.VersionNumber <= 2022:
        rule = FilterStringRule(pvp,FilterStringEquals(),sys_class_name)

    element_filter = ElementParameterFilter(rule)

    view_filter = ParameterFilterElement.Create(doc,filter_name,cats_id,element_filter)

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

coordination_filters_names [
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
    "COORD_ELECTRIC TRAYS",
    "COORD_ICT TRAYS"
]

coordination_filters_colors = [
    Color(0,128,255),   # color_supply_ducts
    Color(255,128,64),  # color_return_ducts
    Color(0,128,0),     # color_exhaust_ducts
    Color(255,0,0),     # color_fire_pipes
    Color(128,128,0),   # color_novec_pipes
    Color(0,0,255),     # color_cold_water_pipes
    Color(255,115,47),  # color_hot_water_pipes
    Color(128,128,255), # color_supply_chilled_water
    Color(255,255,128), # color_return_chilled_water
    Color(0,64,0),      # color_drainage
    Color(255,255,0),   # color_electric_trays
    Color(128,255,255)  # color_ict_trays
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

hvac_categories = [
    BuiltInCategory.OST_DuctSystem,
    BuiltInCategory.OST_DuctCurves,
    BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_DuctInsulations,
    BuiltInCategory.OST_DuctTerminal]


plumbing_categories = [
    BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_FlexPipeCurves,
    BuiltInCategory.OST_PipeInsulations,
    BuiltInCategory.OST_PipingSystem]

electrical_categories = [
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_CableTrayFitting]

#Start Transaction
with Transaction(doc,"Create View Filters") as t:
    t.Start()

    cats = List[ElementId]()
    cats.Add(ElementId(BuiltInCategory.OST_DuctSystem))
    cats.Add(ElementId(BuiltInCategory.OST_DuctCurves))
    cats.Add(ElementId(BuiltInCategory.OST_DuctFitting))

    # for wall_type_name in wall_types_names:
    #     filter_name = wall_type_name + " Filter_{}".format(wall_type_name)
    #     if not filter_name in all_par_filters_names:
    #
    #         #Select View Filter Categories
    #         cats = List[ElementId]()
    #         cats.Add(ElementId(BuiltInCategory.OST_Walls))
    #
    #         #Rule 1 - Wall Function
    #         pvp = ParameterValueProvider(ElementId(BuiltInParameter.SYMBOL_NAME_PARAM))
    #         rule_1 = FilterStringRule(pvp, FilterStringEquals(),wall_type_name,True)
    #
    #         #Create an Element Parameter Filter
    #         wall_filter = ElementParameterFilter(rule_1)
    #
    #         #Create View Filter
    #         view_filter = ParameterFilterElement.Create(doc,filter_name,cats,wall_filter)
    #
    #         #Create Color and Solid Pattern
    #         R = random.randint(0,255)
    #         G = random.randint(0,255)
    #         B = random.randint(0,255)
    #
    #         color = Color(R,G,B)
    #         all_patterns = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
    #
    #         solid_pattern = [i for i in all_patterns if i.GetFillPattern().IsSolidFill][0]
    #
    #         override_settings = OverrideGraphicSettings()
    #         override_settings.SetSurfaceForegroundPatternId(solid_pattern.Id)
    #         override_settings.SetSurfaceForegroundPatternColor(color)
    #
    #         active_view.AddFilter(view_filter.Id)
    #         active_view.SetFilterOverrides(view_filter.Id,override_settings)

    t.Commit()