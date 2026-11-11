# -*- coding: utf-8 -*-

__doc__ = """__________________________________________________
Description:

Copies the Shaft Function value from one shaft to as many other shafts as you click.
__________________________________________________
How-to:

-> Make sure the project has the Shaft Function parameter
-> Click on the button
-> Pick the source shaft
-> Click each shaft to match; it updates straight away
-> Press Esc when you're done
__________________________________________________
Author: Mohamed Bedair"""

from Autodesk.Revit.DB import BuiltInCategory

import bd_core as bd

TOOL = u"Match Shaft Function"
KEYS = [u"Shaft Function"]

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
only_shaft = bd.CategoryFilter(BuiltInCategory.OST_ShaftOpening)

source = bd.pick_element(uidoc, u"Pick the source shaft", only_shaft)
if source is None:
    bd.alert(u"No source shaft was picked.", TOOL, exit=True)

if bd.get_param(source, u"Shaft Function") is None:
    bd.alert(u"This project has no Shaft Function parameter.", TOOL,
             details=u"Run Create Shaft Function first, then try again.", exit=True)

skipped = [0]


def match(target):
    failed = bd.run_transaction(doc, TOOL, lambda: bd.copy_params(source, target, KEYS))
    if failed:
        skipped[0] += 1


bd.pick_repeat(uidoc, u"Pick a shaft to match (Esc to finish)", match,
               only_shaft, bar_title=u"Pick shafts to match the Shaft Function:")

if skipped[0]:
    bd.alert(u"{0} couldn't take every value (read-only or missing).".format(
        bd.plural(skipped[0], u"shaft")), TOOL)
