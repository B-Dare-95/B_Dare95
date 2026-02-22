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
from pyrevit import forms, revit, script
from pyrevit import EXEC_PARAMS

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

##########################################################################################################
def get_existing_filter(filter_name):
    """Returns a ParameterFilterElement if one with the given name exists, otherwise None."""
    all_par_filters = FilteredElementCollector(doc).OfClass(ParameterFilterElement).ToElements()
    for f in all_par_filters:
        if f.Name == filter_name:
            return f
    return None


def is_filter_applied_to_view(view, filter_id):
    """Returns True if the filter is already added to the given view."""
    applied_filter_ids = view.GetFilters()
    return filter_id in applied_filter_ids


def build_override_settings(doc):
    """Builds and returns the OverrideGraphicSettings with solid fill, given a color."""
    all_fill_patterns = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
    solid_pattern = [i for i in all_fill_patterns if i.GetFillPattern().IsSolidFill][0]

    all_line_patterns = FilteredElementCollector(doc).OfClass(LinePatternElement).ToElements()
    solid_line_pattern_id = [i.GetSolidPatternId() for i in all_line_patterns][0]

    return solid_pattern, solid_line_pattern_id


def create_view_filters(filter_name, cats, param_id, param_value, color):

    solid_pattern, solid_line_pattern_id = build_override_settings(doc)

    override_settings = OverrideGraphicSettings()
    override_settings.SetSurfaceForegroundPatternId(solid_pattern.Id)
    override_settings.SetSurfaceForegroundPatternColor(color)
    override_settings.SetSurfaceBackgroundPatternId(solid_pattern.Id)
    override_settings.SetSurfaceBackgroundPatternColor(color)
    override_settings.SetProjectionLinePatternId(solid_line_pattern_id)
    override_settings.SetProjectionLineColor(color)
    override_settings.SetProjectionLineWeight(1)

    existing_filter = get_existing_filter(filter_name)

    if existing_filter is not None:
        # Filter exists in the document — check if it is applied to the active view
        if is_filter_applied_to_view(active_view, existing_filter.Id):
            # Already applied — skip entirely
            output.print_md("**Skipped (already applied):** {}".format(filter_name))
        else:
            # Exists but not applied — apply it now
            active_view.AddFilter(existing_filter.Id)
            active_view.SetFilterOverrides(existing_filter.Id, override_settings)
            output.print_md("**Applied existing filter:** {}".format(filter_name))
    else:
        # Filter does not exist — create it from scratch
        cats_id = [ElementId(cat) for cat in cats]
        pvp = ParameterValueProvider(param_id)

        if app.VersionNumber <= 2021:
            rule = FilterStringRule(pvp, FilterStringContains(), param_value, True)
        else:
            rule = FilterStringRule(pvp, FilterStringContains(), param_value)

        element_filter = ElementParameterFilter(rule)
        view_filter = ParameterFilterElement.Create(doc, filter_name, List[ElementId](cats_id), element_filter)

        active_view.AddFilter(view_filter.Id)
        active_view.SetFilterOverrides(view_filter.Id, override_settings)
        output.print_md("**Created new filter:** {}".format(filter_name))

##########################################################################################################


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
    Color(0,128,255),
    Color(255,128,64),
    Color(0,128,0),
    Color(255,0,0),
    Color(128,128,0),
    Color(0,0,255),
    Color(255,115,47),
    Color(128,128,255),
    Color(255,255,128),
    Color(64,0,64),
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

elec_filters_names = ["COORD_ELECTRIC TRAYS", "COORD_ICT TRAYS"]

elec_filters_colors = [
    Color(255, 255, 0),
    Color(128, 255, 255)
]

elec_type_names = ["_E_", "_T_"]

electrical_categories = [
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_Conduit,
    BuiltInCategory.OST_ConduitFitting
]

mp_param_id   = ElementId(BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM)
elec_param_id = ElementId(BuiltInParameter.SYMBOL_NAME_PARAM)

# Start Transaction
with Transaction(doc, __title__) as t:
    t.Start()

    for i in range(len(mp_filters_names)):
        create_view_filters(
            mp_filters_names[i],
            mp_categories,
            mp_param_id,
            system_class_names[i],
            mp_filters_colors[i]
        )

    for i in range(len(elec_filters_names)):
        create_view_filters(
            elec_filters_names[i],
            electrical_categories,
            elec_param_id,
            elec_type_names[i],
            elec_filters_colors[i]
        )

    t.Commit()