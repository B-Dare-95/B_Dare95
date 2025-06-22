#IMPORTS

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import TaskDialog

#VARIABLES

doc         = __revit__.ActiveUIDocument.Document
uidoc       = __revit__.ActiveUIDocument
selection   = uidoc.Selection

all_links = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_RvtLinks).WhereElementIsNotElementType().ToElements()

if not all_links:
    TaskDialog.Show("B-Dare95", "No Links Found in Document")

else :
    for link in all_links:
        try:
            link_doc=link.GetLinkDocument()
            all_linked_grids = FilteredElementCollector(link_doc).OfCategory(
                BuiltInCategory.OST_Grids).WhereElementIsNotElementType().ToElements()
            bad_grids = [grid for grid in all_linked_grids if
                         grid.LookupParameter("Workset").AsValueString not in ["Shared Levels and Grids",
                                                                               "Shared Views, Levels, Grids"]]

            if len(bad_grids) == 0:
                pass
            else:
                grid_counter = len(bad_grids)
                print("Link Name : {0} >>> {1} Grids are on a wrong workset, Please Fix!! ".format(link_doc.Title,
                                                                                                   grid_counter))

            all_linked_levels = FilteredElementCollector(link_doc).OfCategory(
                BuiltInCategory.OST_Levels).WhereElementIsNotElementType().ToElements()
            bad_levels = [level for level in all_linked_levels if
                          level.LookupParameter("Workset").AsValueString not in ["Shared Levels and Grids",
                                                                                 "Shared Views, Levels, Grids"]]

            if len(bad_levels) == 0:
                pass
            else:
                level_counter = len(bad_levels)
                print("Link Name : {0} >>> {1} Levels are on a wrong workset, Please Fix!! ".format(link_doc.Title,
                                                                                                    level_counter))

            print("-" * 100)
        except:
            pass