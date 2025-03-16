from Autodesk.Revit.DB import *

doc = __revit__.ActiveUIDocument.Document


all_elements=FilteredElementCollector(doc,doc.ActiveView.Id).WhereElementIsNotElementType().ToElements()

t=Transaction(doc,"Pin All")

t.Start()

for element in all_elements:
    try:
        element.Pinned = True
    except:
        continue

t.Commit()