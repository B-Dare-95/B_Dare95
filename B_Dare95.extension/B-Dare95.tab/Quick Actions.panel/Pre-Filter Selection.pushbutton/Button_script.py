# -*- coding: utf-8 -*-
__title__ = "Pre-Filter Selection"
__author__ = "Mohamed Bedair"
__version__ = '1.1.0'
__doc__ = """
Version = 1.1.0
Date    = 19.02.2025

Description:
Filters the Selection box to only selected categories. Also allows negating selection with SHIFT click.

How-to:
-> Run the script
-> Select desired categories from the menu
-> The selection box will only highlight selected categories

Last update:
- [19.02.2025] - 1.1.0 RELEASE
  - Added Feature to Negate Selection with SHIFT Click

Author: Mohamed Bedair
"""

# IMPORTS
import System
from System.Collections.Generic import List
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms, script
from pyrevit import EXEC_PARAMS

# Get active Revit document and selection objects
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
selection = uidoc.Selection


class CustomISelectionFilter(ISelectionFilter):
    """
    Custom Selection Filter to allow only elements belonging to specified categories.
    """

    def __init__(self, allowed_categories):
        self.allowed_categories = set(allowed_categories)

    def AllowElement(self, elem):
        return elem.Category and elem.Category.Name in self.allowed_categories

    def AllowReference(self, reference, position):
        return False  # Not handling reference selection


def get_all_category_names(doc):
    """Retrieve all category names from the document."""
    return sorted(cat.Name for cat in doc.Settings.Categories if cat.CategoryType == CategoryType.Model)


def negate_selection(names_chosen):
    """
    Allows selection of elements and removes elements that match selected categories.
    """
    try:
        elements_to_filter = selection.PickElementsByRectangle("Select Elements")
        filtered_ids = [el.Id for el in elements_to_filter if el.Category and el.Category.Name not in names_chosen]
        uidoc.Selection.SetElementIds(List[ElementId](filtered_ids))
    except Exception as e:
        script.exit()  # Exit silently if selection is canceled


def apply_category_filter(names_chosen):
    """
    Applies category filter and allows selecting only elements belonging to chosen categories.
    """
    try:
        sel_filter = CustomISelectionFilter(names_chosen)
        selected_elements = selection.PickElementsByRectangle(sel_filter, "Select Elements")
        selected_ids = [el.Id for el in selected_elements]
        uidoc.Selection.SetElementIds(List[ElementId](selected_ids))
    except Exception as e:
        script.exit()  # Exit silently if selection is canceled


# Main Execution Logic
all_categories = get_all_category_names(doc)
names_chosen = forms.SelectFromList.show(
    all_categories,
    title="Choose Categories",
    width=300,
    button_name="Make A Selection",
    multiselect=True
)

if not names_chosen:
    script.exit()

if EXEC_PARAMS.config_mode:
    negate_selection(names_chosen)
else:
    apply_category_filter(names_chosen)