# -*- coding: utf-8 -*-
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
doc         =  __revit__.ActiveUIDocument.Document
uidoc       =  __revit__.ActiveUIDocument
selection   =  uidoc.Selection
import time
script = """
ref_selected_element=selection.PickObjects(ObjectType.Element,"Select Linked Element") #type: Reference
for ref_element in ref_selected_element:
    element_id = doc.GetElement(ref_element).Id
    element_name = doc.GetElement(ref_element).Name
    print("Element Name : " + element_name + ">>ID: " + str(element_id.IntegerValue))
    """
# List of commands (lines of code as strings)
commands = script.strip().splitlines()

# Store execution times
timing = []

# Execute each command and record time
for command in commands:
    start_time = time.time()
    try:
        # Compiling the command, but NOT executing it
        compile(command, '<string>', 'exec')
    except Exception as e:
        # If there's an error in the command (syntax, etc.), we capture it but do not execute
        print("Error compiling command: {}, Error: {}".format(command,e))
    timing.append(time.time() - start_time)

# Print the report
for idx, t in enumerate(timing):
    print("Line {} took {} seconds.".format(idx + 1,t))

# start_time = time.time()
# a = [i for i in range(100000)]
# end_time = time.time()
# print("Line took {} seconds.".format(end_time - start_time))
#
#
# start_time = time.time()
# b = sum(a)
# end_time = time.time()
# print("Line took {} seconds.".format(end_time - start_time))
#
# start_time = time.time()
# c = [x**2 for x in a]
# end_time = time.time()
# print("Line took {} seconds.".format(end_time - start_time))