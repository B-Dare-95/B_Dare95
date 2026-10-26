# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__version__ = '1.0.0'
__doc__ = """__________________________________________________
Description:

Lists every parking type used in the model with how many are placed and their share of the total, in a quick table.
__________________________________________________
How-to:

-> Click on the button
-> The table opens in the output window
-> Read the count and share of each parking type, and the total
__________________________________________________
Author: Mohamed Bedair"""

# Imports
from Autodesk.Revit.DB import *
from pyrevit import script

# Revit Variables
doc = __revit__.ActiveUIDocument.Document
output = script.get_output()

# Collect all parking elements
all_parkings = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Parking)\
    .WhereElementIsNotElementType()\
    .ToElements()

# Count each parking type using .get() to safely handle missing keys
parking_type_count_dict = {}

for park in all_parkings:
    park_type = doc.GetElement(park.GetTypeId())
    park_type_name = park_type.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsValueString()
    parking_type_count_dict[park_type_name] = parking_type_count_dict.get(park_type_name, 0) + 1

# Calculate total
total = sum(parking_type_count_dict.values())

# Print report
output.print_md("# Parking Type Count Report")
output.print_md("| Parking Type | Count | Percentage |")
output.print_md("| --- | --- | --- |")

for park_type_name, count in sorted(parking_type_count_dict.items()):
    percentage = (float(count) / float(total)) * 100
    output.print_md("| {} | {} | {:.1f}% |".format(park_type_name, count, percentage))

output.print_md("| --- | --- | --- |")
output.print_md("| **TOTAL** | **{}** | **100%** |".format(total))