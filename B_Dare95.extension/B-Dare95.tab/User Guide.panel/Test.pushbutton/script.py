# -*- coding: utf-8 -*-
__doc__ = """Description:
Temporary probe for the Warnings hook. Lists every ribbon item that matches a pushbutton folder name, shows its ID, and tests whether Revit can post it.

How-to:
-> Set FOLDER at the top of the script to your pushbutton folder name
-> Click the button
-> Copy the whole output window back

Author: Mohamed Bedair"""

import clr
clr.AddReference("AdWindows")

from Autodesk.Windows import ComponentManager
from Autodesk.Revit.UI import RevitCommandId

FOLDER = "Warning Chart.pushbutton"
POST_FIRST_MATCH = True     # also try opening the tool, outside the hook

SUFFIX = ".pushbutton"
name = FOLDER[:-len(SUFFIX)] if FOLDER.lower().endswith(SUFFIX) else FOLDER
needle = name.lower()


def walk(items, depth):
    for item in items:
        yield item, depth
        sub = getattr(item, "Items", None)
        if sub is not None:
            try:
                for pair in walk(sub, depth + 1):
                    yield pair
            except TypeError:
                pass


print("Looking for: '{0}'".format(name))
print("-" * 60)

matches = []
for tab in ComponentManager.Ribbon.Tabs:
    for panel in tab.Panels:
        source = panel.Source
        if source is None:
            continue
        for item, depth in walk(source.Items, 0):
            item_id = item.Id or ""
            text = (item.Text or "").replace("\n", " ").replace("\r", " ")
            if needle not in item_id.lower() and needle not in text.lower():
                continue
            cmd = RevitCommandId.LookupCommandId(item_id) if item_id else None
            can_post = __revit__.CanPostCommand(cmd) if cmd else False
            print("Tab title : {0}   (tab id: {1})".format(tab.Title, tab.Id))
            print("Panel     : {0}".format(source.Title))
            print("Item type : {0}   depth: {1}".format(item.GetType().Name, depth))
            print("Item text : {0}".format(text))
            print("Item id   : {0}".format(item_id))
            print("Ends with '%{0}': {1}".format(name, item_id.endswith("%" + name)))
            print("Lookup OK : {0}   CanPost: {1}".format(cmd is not None, can_post))
            print("-" * 60)
            matches.append((item_id, cmd, can_post))

if not matches:
    print("No ribbon item matched '{0}' by ID or text.".format(name))
elif POST_FIRST_MATCH:
    for item_id, cmd, can_post in matches:
        if can_post:
            __revit__.PostCommand(cmd)
            print("Posted: {0}  -> the tool should open after this script ends.".format(item_id))
            break
    else:
        print("None of the matches can be posted.")