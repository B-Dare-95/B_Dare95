# DLC Select By Parameter

Select elements by category, optionally filtered by parameter values.

## Install
1. Copy the `Select.panel` folder into your existing `DLC.extension\DLC.tab\` folder
   (or copy just `Select By Parameter.pushbutton` into any panel you already have).
2. pyRevit tab → **Reload**. The button appears on the DLC tab.
   If your tab uses a `layout` list in its `bundle.yaml`, add `Select` to it.

## Use
1. **Look in** – Active view, Whole model, or Current selection (greyed out when
   nothing is selected or the active view is a sheet/schedule).
2. **Category** – type to filter, click one (e.g. `Rooms (140)`).
3. **Parameter** (optional) – leave on *no filter* to select every element of the
   category, or pick one (type parameters show as `[Type] Name`).
4. **Values** – tick one or more (`L01 (24)`, `L02 (31)` …). `<empty>` catches
   blanks. *All / None* act on the values currently shown by the search box.
5. **Select** – elements are selected and the view zooms to the ones visible in it.

Switching scope keeps your category, parameter and ticks.

## Settings (top of `script.py`)
| Key | Default | Meaning |
|---|---|---|
| `ZOOM_TO_SELECTION` | True | Zoom to selected elements visible in the active view |
| `SKIP_UNPLACED_SPATIAL` | True | Hide unplaced rooms/spaces/areas |
| `INCLUDE_TYPE_PARAMETERS` | True | Offer type parameters as `[Type] …` |
| `PARAM_SAMPLE_SIZE` | 300 | Elements read per category to list parameters |
| `EXCLUDED_CATEGORIES` | cameras, project info… | Never listed |
| `EXTRA_CATEGORIES` | Levels, Grids | Non-model categories still offered |
| `DEFAULT_SCOPE` | `view` | Scope the window opens on |

Values are matched as displayed in Properties (e.g. `22.50 m²`, level names).
