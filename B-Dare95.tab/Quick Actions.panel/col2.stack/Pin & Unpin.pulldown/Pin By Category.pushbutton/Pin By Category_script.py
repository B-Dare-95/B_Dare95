
from Autodesk.Revit.DB import *
from pyrevit import forms,script

doc = __revit__.ActiveUIDocument.Document

t=Transaction(doc,"Quick Pin")

t.Start()
def get_all_cats(doc):
    cats = doc.Settings.Categories
    return [cat.Name for cat in cats]

all_cats=sorted(get_all_cats(doc))

cats_chosen = forms.SelectFromList.show(all_cats, title="Choose Category" \
                                                , width=300 \
                                                , button_name="Done" \
                                                , multiselect=True)

for chosen_cat in cats_chosen:
    for cat in doc.Settings.Categories:
        if cat.Name == chosen_cat:
            elements_to_pin=FilteredElementCollector(doc).OfCategory(cat.BuiltInCategory).WhereElementIsNotElementType().ToElements()

            for elem in elements_to_pin:
                elem.Pinned = True
t.Commit()