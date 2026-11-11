# -*- coding: utf-8 -*-

__doc__ = """__________________________________________________
Description:

Copies the Height Offset From Level of one floor onto as many other floors as you click.
Only the offset changes; each floor keeps its own level, type and sketch.
__________________________________________________
How-to:

-> Click on the button
-> Pick the floor that has the right height
-> Click the other floors one by one
-> Each one takes the new height straight away
-> Press Esc when you are done
__________________________________________________
Author: Mohamed Bedair"""

from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter

import bd_core as bd

TOOL = u"Match Floor Height"
KEYS = [BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM]

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
only_floor = bd.CategoryFilter(BuiltInCategory.OST_Floors)

source = bd.pick_element(uidoc, u"Pick the source floor", only_floor)
if source is None:
    bd.alert(u"No source floor was picked.", TOOL, exit=True)

skipped = [0]


def match(target):
    failed = bd.run_transaction(doc, TOOL, lambda: bd.copy_params(source, target, KEYS))
    if failed:
        skipped[0] += 1


bd.pick_repeat(uidoc, u"Pick a floor to match (Esc to finish)", match,
               only_floor, bar_title=u"Pick floors to match the height:")

if skipped[0]:
    bd.alert(u"{0} couldn't take every value (read-only or missing).".format(
        bd.plural(skipped[0], u"floor")), TOOL)
