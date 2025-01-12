from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *

doc         = __revit__.ActiveUIDocument.Document
uidoc       = __revit__.ActiveUIDocument
selection   = uidoc.Selection
active_view = doc.ActiveView

text_type_id = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElementId()

point = selection.PickPoint(ObjectSnapTypes.Endpoints,"Pick a Point")

text = "(" + str(point.X) + ", " +str(point.Y) + ", " + str(point.Z) + ")"

t=Transaction(doc,"Get Point")

t.Start()

text_note=TextNote.Create(doc, active_view.Id, point, text, text_type_id)

text_note.Pinned = True

t.Commit()