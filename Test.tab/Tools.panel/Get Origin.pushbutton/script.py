from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *

doc         = __revit__.ActiveUIDocument.Document
uidoc       = __revit__.ActiveUIDocument
selection   = uidoc.Selection

origin_point = XYZ(0,0,0)
all_txt_note_types=FilteredElementCollector(doc).OfClass(TextNoteType).ToElements()

t=Transaction(doc,"Origin Point Placer")

t.Start()

text_note = TextNote.Create(doc,doc.ActiveView.Id,origin_point,"(0,0,0)",all_txt_note_types[2].Id)

t.Commit()