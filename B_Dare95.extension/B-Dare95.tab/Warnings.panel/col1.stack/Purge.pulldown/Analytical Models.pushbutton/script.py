# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes the analytical members, panels and openings you tick, not only unused ones; they aren't needed for the physical model. The analytical nodes, links, loads and boundary conditions on them go with them. Energy-analysis spaces and surfaces and the load cases, natures and combinations are kept. Nothing is ticked for you.
__________________________________________________
How-to:

-> Click on the button
-> Read the list: nothing is ticked for you, so tick what to delete
-> Leave "Purge up to 3 times" ticked to also purge what this purge frees
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "analytical_models")  # noqa: F821
