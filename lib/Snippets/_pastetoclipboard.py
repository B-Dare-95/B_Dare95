from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
#Revit Variables
uidoc     = __revit__.ActiveUIDocument
doc       = __revit__.ActiveUIDocument.Document
app       = __revit__.Application


def cut2clipboard():

    revit_command_id = RevitCommandId.LookupPostableCommandId(PostableCommand.PasteFromClipboard)

    if revit_command_id:
        return UIApplication(app).PostCommand(revit_command_id)