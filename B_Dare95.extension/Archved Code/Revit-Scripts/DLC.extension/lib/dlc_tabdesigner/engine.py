# -*- coding: utf-8 -*-
"""
DLC Tab Designer - engine (no Revit, no WPF).

Works in IronPython 2.7 (pyRevit) and CPython 3 (tests). Everything is found
relative to the running button, so the extension can live in any folder on
any PC.

Ribbon rules honoured (from pyRevit's source):
  * once a container has `layout:` in bundle.yaml, only listed children are
    created -> every item is always listed;
  * a stack renders with 2 or 3 items -> small tools are grouped 3,3,..,
    never leaving a single one (4 -> 2+2);
  * pulldowns hold plain buttons.
"""
import io
import json
import os
import re
import shutil
import stat
import time
import zipfile

VERSION = "1.1.0"

MARKER = "_dlc_generated.txt"          # marks folders this tool created
STACK_PREFIX = "DLC Stack "
MORE_NAME = "More"

PUSH_KINDS = (".pushbutton", ".smartbutton", ".linkbutton", ".invokebutton",
              ".urlbutton", ".content")
GROUP_KINDS = (".pulldown", ".splitbutton", ".splitpushbutton")
FIXED_KINDS = (".panelbutton", ".nobutton", ".combobox")
STACK_KIND = ".stack"
ITEM_KINDS = PUSH_KINDS + GROUP_KINDS + FIXED_KINDS

BIG, SMALL, MORE, KEEP = "BIG", "SMALL", "MORE", "KEEP"
MODE_LABELS = {BIG: u"Large", SMALL: u"Small", MORE: u"In “More” menu",
               KEEP: u"Keep as is"}
CODE_EXTS = (".py", ".cs", ".vb", ".dyn", ".xaml")
BAD_NAME_CHARS = '\\/:*?"<>|'


class DesignerError(Exception):
    """Message written for the user."""
    pass


# ----------------------------------------------------------------- basics
def kind(name):
    return os.path.splitext(name)[1].lower()


def base(name):
    return os.path.splitext(name)[0]


def subdirs(d):
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = [n for n in names if os.path.isdir(os.path.join(d, n))]
    out.sort(key=lambda n: n.lower())
    return out


def read_text(path):
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        return fh.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(u"%s" % text)


_STACK_RE = re.compile(r"^%s\d+\.stack$" % re.escape(STACK_PREFIX), re.I)


def is_generated(d):
    """Folders this tool made. The marker file is only a hint (sync tools
    can drop it), so the distinctive names count too: 'DLC Stack N.stack',
    and 'More.pulldown' inside one of those or carrying our tooltip."""
    if os.path.exists(os.path.join(d, MARKER)):
        return True
    leaf = os.path.basename(d)
    if _STACK_RE.match(leaf):
        return True
    if leaf.lower() == (MORE_NAME + ".pulldown").lower():
        if _STACK_RE.match(os.path.basename(os.path.dirname(d))):
            return True
        f = os.path.join(d, "bundle.yaml")
        try:
            if os.path.exists(f) and u"More tools" in read_text(f):
                return True
        except Exception:
            pass
    return False


def mark(d):
    write_text(os.path.join(d, MARKER),
               u"Created by DLC Tab Designer - safe to leave alone.\n")


# ----------------------------------------------------------------- bundle.yaml
_LAYOUT_RE = re.compile(r"^layout\s*:")
_ITEM_RE = re.compile(r"^\s*-\s*(.+?)\s*$")


_ESCAPES = {"n": u"\n", "t": u"\t", '"': u'"', "\\": u"\\", "/": u"/"}


def _unquote(v):
    """YAML scalar -> text (double quotes decode \\n, \\", \\\\)."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1),
                                                       u"\\" + m.group(1)),
                      v[1:-1])
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def read_layout(d):
    """Entries of `layout:` in d/bundle.yaml ("Name" or "Name[title:..]")."""
    f = os.path.join(d, "bundle.yaml")
    out = []
    if not os.path.exists(f):
        return out
    inside = False
    for line in read_text(f).splitlines():
        if _LAYOUT_RE.match(line):
            inside = True
            continue
        if inside:
            m = _ITEM_RE.match(line)
            if m:
                out.append(_unquote(m.group(1)))
                continue
            if not line.strip() or line.strip().startswith("#"):
                continue
            inside = False
    return out


def write_layout(d, entries, extra=None):
    """Replace (or add) the layout block; keep every other key."""
    f = os.path.join(d, "bundle.yaml")
    keep = []
    if os.path.exists(f):
        inside = False
        for line in read_text(f).splitlines():
            if _LAYOUT_RE.match(line):
                inside = True
                continue
            if inside:
                if _ITEM_RE.match(line) or not line.strip():
                    continue
                inside = False
            keep.append(line)
    elif extra:
        keep.extend(extra)
    while keep and not keep[-1].strip():
        keep.pop()
    keep.append(u"layout:")
    for e in entries:
        keep.append(u'  - "%s"' % e.replace("\\", "\\\\").replace('"', '\\"'))
    write_text(f, u"\n".join(keep) + u"\n")


def entry_name(entry):
    m = re.match(r"^(.+?)\[.+:.*\]$", entry)
    return m.group(1) if m else entry


def entry_directive(entry):
    m = re.match(r"^.+?(\[.+:.*\])$", entry)
    return m.group(1) if m else ""


def yaml_title(text):
    """`title:` from bundle.yaml text. Handles plain / quoted values, block
    scalars (title: |- then indented lines) and localised maps
    (title: then en_us: ...)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^title\s*:\s*(.*)$", line)
        if not m:
            continue
        v = m.group(1).strip()
        if v[:1] in ("|", ">"):
            fold = v[0] == ">"
            body = []
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    body.append(u"")
                    continue
                if not nxt[:1].isspace():
                    break
                body.append(nxt.strip())
            while body and not body[-1]:
                body.pop()
            return (u" " if fold else u"\n").join(body) or None
        if not v:
            vals = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and not nxt[:1].isspace():
                    break
                mm = re.match(r"^\s+([A-Za-z_\-]+)\s*:\s*(.+)$", nxt)
                if mm:
                    vals.append((mm.group(1).lower(), _unquote(mm.group(2))))
            for want in ("en_us", "en", "english"):
                for k, val in vals:
                    if k == want:
                        return val
            return vals[0][1] if vals else None
        return _unquote(v)
    return None


def read_title(d):
    f = os.path.join(d, "bundle.yaml")
    if os.path.exists(f):
        t = yaml_title(read_text(f))
        if t:
            return t
    s = os.path.join(d, "script.py")
    if os.path.exists(s):
        m = re.search(r"__title__\s*=\s*[uU]?['\"](.+?)['\"]", read_text(s))
        if m:
            return m.group(1)
    return None


def one_line(title):
    return re.sub(r"\s+", " ", title.replace("\\n", " ").replace("\n", " ")
                  ).strip()


def code_size(d):
    total = 0
    for root, dirs, files in os.walk(d):
        for f in files:
            if os.path.splitext(f)[1].lower() in CODE_EXTS:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return total


# ----------------------------------------------------------------- model
class Item(object):
    def __init__(self, name, path, mode="", key=0, locked=False):
        self.name = name                # folder name incl. suffix
        self.kind = kind(name)
        self.path = path
        self.mode = mode
        self.key = key
        self.locked = locked            # the designer's own button
        t = read_title(path)
        self.label = one_line(t) if t else base(name)

    def options(self):
        """Modes the user may pick for this item."""
        if self.kind in FIXED_KINDS:
            return [KEEP]
        if self.locked:
            return [BIG]
        if self.kind in PUSH_KINDS:
            return [BIG, SMALL, MORE]
        return [BIG, SMALL]

    def __repr__(self):
        return "Item(%s, %s)" % (self.name, self.mode)


class Panel(object):
    def __init__(self, name, path, items, color=None):
        self.name = name
        self.path = path
        self.items = items
        self.color = color          # title strip colour "#RRGGBB" or None

    @property
    def label(self):
        return base(self.name)


class Context(object):
    def __init__(self, ext_dir, tab_dir, self_dir):
        self.ext_dir = ext_dir
        self.tab_dir = tab_dir
        self.self_dir = self_dir

    @property
    def root(self):
        return os.path.dirname(self.ext_dir)

    @property
    def ext_name(self):
        return base(os.path.basename(self.ext_dir))

    @property
    def tab_name(self):
        return base(os.path.basename(self.tab_dir))


def find_context(script_path):
    """Locate extension and tab from the running button's own file."""
    d = os.path.dirname(os.path.abspath(script_path))
    self_dir = d
    tab = ext = None
    while True:
        k = kind(os.path.basename(d))
        if k == ".tab" and tab is None:
            tab = d
        if k == ".extension":
            ext = d
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    if tab is None or ext is None:
        raise DesignerError(
            "This button must sit inside <name>.extension\\<name>.tab\\... - "
            "found it at %s" % os.path.dirname(os.path.abspath(script_path)))
    return Context(ext, tab, self_dir)


# ----------------------------------------------------------------- scan
def _order(d):
    out = {}
    for i, e in enumerate(read_layout(d)):
        out[entry_name(e)] = i
    return out


def _pos(order, name, fallback):
    return order.get(base(name), fallback)


def scan_panel(panel_dir, self_dir=None):
    """Items as they are now. Tools inside this tool's stacks / More menu
    come back as SMALL / MORE; tools in your own stacks as SMALL; everything
    else at panel level as BIG (KEEP for special buttons)."""
    porder = _order(panel_dir)
    items = []

    def add(name, path, mode, key):
        locked = bool(self_dir) and os.path.normcase(os.path.abspath(path)) \
            == os.path.normcase(os.path.abspath(self_dir))
        it = Item(name, path, mode, key, locked)
        if it.kind in FIXED_KINDS:
            it.mode = KEEP
        if locked:
            it.mode = BIG
        items.append(it)

    for c in subdirs(panel_dir):
        cp = os.path.join(panel_dir, c)
        k = kind(c)
        cpos = _pos(porder, c, 900) * 10000
        if k == STACK_KIND:
            gen = is_generated(cp)
            sorder = _order(cp)
            for g in subdirs(cp):
                gp = os.path.join(cp, g)
                gk = kind(g)
                gpos = cpos + _pos(sorder, g, 90) * 100
                if gen and gk == ".pulldown" and is_generated(gp):
                    morder = _order(gp)
                    for m in subdirs(gp):
                        if kind(m) in ITEM_KINDS:
                            add(m, os.path.join(gp, m), MORE,
                                gpos + _pos(morder, m, 90))
                elif gk in ITEM_KINDS:
                    add(g, gp, SMALL, gpos)
        elif k == ".pulldown" and is_generated(cp):
            morder = _order(cp)
            for m in subdirs(cp):
                if kind(m) in ITEM_KINDS:
                    add(m, os.path.join(cp, m), MORE, cpos + _pos(morder, m, 90))
        elif k in ITEM_KINDS:
            add(c, cp, BIG, cpos)
    items.sort(key=lambda it: (it.key, it.name.lower()))
    return items


def scan_tab(ctx):
    torder = _order(ctx.tab_dir)
    panels = []
    for p in subdirs(ctx.tab_dir):
        if kind(p) != ".panel":
            continue
        pp = os.path.join(ctx.tab_dir, p)
        panels.append(Panel(p, pp, scan_panel(pp, ctx.self_dir),
                            read_panel_color(pp)))
    panels.sort(key=lambda p: (_pos(torder, p.name, 999), p.name.lower()))
    return panels


# ----------------------------------------------------------------- suggest
def suggest(panel):
    """Compact layout: the tool with the most code stays Large and goes
    first; up to five more become Small (two columns); the rest go into the
    More menu. Panels with 1-2 tools stay Large."""
    movable = [i for i in panel.items
               if i.kind not in FIXED_KINDS and not i.locked]
    fixed = [i for i in panel.items if i not in movable]
    for i in fixed:
        i.mode = KEEP if i.kind in FIXED_KINDS else BIG
    if len(movable) + len([i for i in fixed if i.locked]) <= 2:
        for i in movable:
            i.mode = BIG
        return
    hero = max(movable, key=lambda i: (code_size(i.path), i.name))
    n = 0
    for i in movable:
        if i is hero:
            i.mode = BIG
            continue
        n += 1
        i.mode = SMALL if (n <= 5 or i.kind not in PUSH_KINDS) else MORE
    rest = [i for i in panel.items if i is not hero]
    panel.items = [hero] + rest


def stack_sizes(n):
    """Groups of 3, never a lone 1 (4 -> 2+2)."""
    sizes = []
    left = n
    while left > 0:
        if left == 4:
            sizes += [2, 2]
            break
        if left <= 3:
            sizes.append(left)
            break
        sizes.append(3)
        left -= 3
    return sizes


def preview(panel):
    """Ribbon columns, left to right, as text (for the window)."""
    cols = []
    small = [i.label for i in panel.items if i.mode == SMALL]
    more = [i.label for i in panel.items if i.mode == MORE]
    group = small + ([u"More ▾ (%d)" % len(more)] if more else [])
    placed = False
    for i in panel.items:
        if i.mode in (SMALL, MORE):
            if not placed:
                placed = True
                if len(group) == 1:
                    cols.append([group[0]])
                else:
                    k = 0
                    for s in stack_sizes(len(group)):
                        cols.append(group[k:k + s])
                        k += s
            continue
        cols.append([i.label])
    return cols


def width_estimate(panel):
    """Rough ribbon width in 'large button' units (for the before/after)."""
    w = 0.0
    for col in preview(panel):
        w += 1.0 if len(col) == 1 else 1.6
    return w


# ----------------------------------------------------------------- checks
def check_panel(panel):
    problems = []
    for i in panel.items:
        if i.mode not in i.options():
            problems.append(u"%s: '%s' is not allowed for this tool"
                            % (i.label, MODE_LABELS.get(i.mode, i.mode)))
    if any(i.mode == MORE for i in panel.items):
        for c in subdirs(panel.path):
            if c.lower() == (MORE_NAME + ".pulldown").lower() and \
                    not is_generated(os.path.join(panel.path, c)):
                problems.append(
                    u"Panel %s already has your own '%s' - rename it, or "
                    u"don't put tools in the More menu for this panel"
                    % (panel.label, c))
    return problems


def check_name(name):
    name = (name or u"").strip()
    if not name:
        return u"The tab name can't be empty."
    if any(c in BAD_NAME_CHARS for c in name) or name.endswith("."):
        return u"The tab name can't contain \\ / : * ? \" < > | or end with a dot."
    return None


# ----------------------------------------------------------------- build
def _move(src, dst):
    if os.path.normcase(src) == os.path.normcase(dst):
        return
    if os.path.exists(dst):
        raise DesignerError("Can't move %s: %s already exists."
                            % (os.path.basename(src), dst))
    retry(lambda: os.rename(src, dst), "move %s" % os.path.basename(src))


def _directives(panel_dir):
    """name -> [title:..] from the panel layout and generated sub-layouts."""
    found = {}
    dirs = [panel_dir]
    for c in subdirs(panel_dir):
        if kind(c) in (STACK_KIND, ".pulldown"):
            cp = os.path.join(panel_dir, c)
            dirs.append(cp)
            for g in subdirs(cp):
                if kind(g) == ".pulldown":
                    dirs.append(os.path.join(cp, g))
    for d in dirs:
        for e in read_layout(d):
            dv = entry_directive(e)
            if dv:
                found[entry_name(e)] = dv
    return found


def _small_title(item_dir):
    t = read_title(item_dir)
    if t and ("\\n" in t or "\n" in t):
        return u"[title:%s]" % one_line(t)
    return u""


def build_panel(panel, more_icon=None, more_icon_dark=None):
    """Write the panel to disk as designed. Returns a one-line summary."""
    pdir = panel.path
    directives = _directives(pdir)
    # 1. every item back to panel level (except the designer itself, which
    #    never moves while it runs)
    for it in panel.items:
        dst = os.path.join(pdir, it.name)
        if not it.locked:
            _move(it.path, dst)
            it.path = dst
    # 2. tidy now-empty stacks / generated pulldowns - best effort: if
    #    Windows/OneDrive holds a folder, it stays, unlisted (so pyRevit
    #    never builds it) and is reused or removed on a later run
    for c in subdirs(pdir):
        cp = os.path.join(pdir, c)
        if kind(c) == STACK_KIND:
            for g in subdirs(cp):
                gp = os.path.join(cp, g)
                if kind(g) == ".pulldown" and is_generated(gp) \
                        and not subdirs(gp):
                    try_remove(gp)
            if not subdirs(cp) and is_generated(cp):
                try_remove(cp)
            elif not subdirs(cp):
                try_remove(cp)             # your own stack, now emptied
        elif kind(c) == ".pulldown" and is_generated(cp) and not subdirs(cp):
            try_remove(cp)

    def with_dir(name, large=False):
        """Name + your own [title:..]. A one-line title this tool added
        for a small icon is dropped again when the tool is Large."""
        b = base(name)
        dv = directives.get(b, u"")
        if large and dv and dv == _small_title(os.path.join(pdir, name)):
            dv = u""
        return b + dv

    # 3. More menu
    small = [i for i in panel.items if i.mode == SMALL]
    more = [i for i in panel.items if i.mode == MORE]
    group = [i.name for i in small]
    if more:
        md = os.path.join(pdir, MORE_NAME + ".pulldown")
        if not os.path.isdir(md):          # may be a kept leftover: reuse
            os.mkdir(md)
        mark(md)
        for i in more:
            _move(os.path.join(pdir, i.name), os.path.join(md, i.name))
        if more_icon and os.path.exists(more_icon):
            shutil.copyfile(more_icon, os.path.join(md, "icon.png"))
        if more_icon_dark and os.path.exists(more_icon_dark):
            shutil.copyfile(more_icon_dark, os.path.join(md, "icon.dark.png"))
        write_layout(md, [with_dir(i.name) for i in more],
                     extra=[u'title: "%s"' % MORE_NAME,
                            u'tooltip: "More tools"'])
        group.append(MORE_NAME + ".pulldown")
    # 4. stacks
    stacks = []
    if len(group) > 1:
        k = 0
        for n, size in enumerate(stack_sizes(len(group))):
            sname = "%s%d" % (STACK_PREFIX, n + 1)
            sd = os.path.join(pdir, sname + STACK_KIND)
            if not os.path.isdir(sd):      # may be a kept leftover: reuse
                os.mkdir(sd)
            mark(sd)
            entries = []
            for name in group[k:k + size]:
                _move(os.path.join(pdir, name), os.path.join(sd, name))
                b = base(name)
                entries.append(b + (directives.get(b) or
                                    _small_title(os.path.join(sd, name))))
            k += size
            write_layout(sd, entries)
            stacks.append(sname)
    # 5. panel layout
    layout = []
    placed = False
    for it in panel.items:
        if it.mode in (SMALL, MORE):
            if not placed:
                placed = True
                if stacks:
                    layout.extend(stacks)
                elif group:
                    layout.append(with_dir(group[0]))
            continue
        layout.append(with_dir(it.name, large=True))
    legacy = os.path.join(pdir, "_layout")
    if os.path.exists(legacy):
        os.remove(legacy)
    write_layout(pdir, layout)
    note = u"%s: %d large, %d small" % (
        panel.label, len([i for i in panel.items if i.mode in (BIG, KEEP)]),
        len(small))
    if more:
        note += u", %d in More" % len(more)
    if len(group) == 1:
        note += u" (one small tool shows as a normal button)"
    return note


# ----------------------------------------------------------------- rename
def _rmtree(path):
    def onerror(func, p, exc):
        try:                                   # read-only files (OneDrive)
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            raise
    shutil.rmtree(path, onerror=onerror)


def try_remove(path, tries=4, wait=0.4):
    """Best-effort delete. Used only for leftovers that are harmless if they
    stay (empty stacks no layout lists, '.dlc_old' folders pyRevit ignores).
    Returns True when gone."""
    for _ in range(tries):
        if not os.path.exists(path):
            return True
        try:
            _rmtree(path)
            return True
        except Exception:
            time.sleep(wait)
    return not os.path.exists(path)


def retry(fn, what, tries=10, wait=0.6):
    """OneDrive / antivirus briefly lock folders; try a few times."""
    last = None
    for _ in range(tries):
        try:
            return fn()
        except (OSError, IOError) as ex:
            last = ex
            time.sleep(wait)
    raise DesignerError(
        u"Couldn't %s (%s). A file in it is probably open or being synced "
        u"(OneDrive). Wait a moment and try again." % (what, last))


def rename_folder(path, new_leaf):
    dst = os.path.join(os.path.dirname(path), new_leaf)
    if os.path.normcase(dst) == os.path.normcase(path):
        if os.path.basename(path) != new_leaf:     # case-only change
            tmp = path + "_dlc_tmp"
            retry(lambda: os.rename(path, tmp), "rename")
            retry(lambda: os.rename(tmp, dst), "rename")
        return dst
    if os.path.exists(dst):
        raise DesignerError(u"%s already exists next to %s."
                            % (new_leaf, os.path.basename(path)))
    retry(lambda: os.rename(path, dst), "rename " + os.path.basename(path))
    return dst


def find_name_refs(ext_dir, names):
    """[(file, line no, text)] of files that mention old folder names."""
    hits = []
    pat = re.compile("|".join(re.escape(n) for n in names))
    for root, dirs, files in os.walk(ext_dir):
        for f in files:
            if os.path.splitext(f)[1].lower() not in (
                    ".py", ".yaml", ".yml", ".json", ".ps1", ".bat", ".cmd",
                    ".md", ".txt", ".xaml"):
                continue
            p = os.path.join(root, f)
            try:
                lines = read_text(p).splitlines()
            except Exception:
                continue
            for n, line in enumerate(lines):
                if pat.search(line):
                    hits.append((p, n + 1, line.strip()))
    return hits


def fix_name_refs(hits, pairs):
    files = sorted(set(h[0] for h in hits))
    for f in files:
        t = read_text(f)
        t2 = t
        for old, new in pairs:
            t2 = t2.replace(old, new)
        if t2 != t:
            write_text(f, t2)
    return len(files)


# ----------------------------------------------------------------- backups
def default_backup_dir():
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or \
        os.path.expanduser("~")
    return os.path.join(root, "DLC", "TabDesigner", "backups")


def _history_path(bdir):
    return os.path.join(bdir, "history.json")


def read_history(bdir):
    p = _history_path(bdir)
    if not os.path.exists(p):
        return []
    try:
        data = json.loads(read_text(p))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_history(bdir, hist):
    write_text(_history_path(bdir), json.dumps(hist, indent=2))


def _zip_dir(src, zpath):
    parent = os.path.dirname(src)
    zf = zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED)
    try:
        for root, dirs, files in os.walk(src):
            rel = os.path.relpath(root, parent)
            if not files and not dirs:
                zf.writestr(rel.replace("\\", "/") + "/", "")
            for f in files:
                p = os.path.join(root, f)
                zf.write(p, os.path.relpath(p, parent))
    finally:
        zf.close()


def backup(ctx, bdir, label):
    """Zip the whole extension (hidden files too) and record it."""
    if not os.path.isdir(bdir):
        os.makedirs(bdir)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    zpath = os.path.join(bdir, "%s_%s_%s.zip" % (ctx.ext_name, stamp, label))
    n = 1
    while os.path.exists(zpath):
        n += 1
        zpath = os.path.join(bdir, "%s_%s_%s_%d.zip"
                             % (ctx.ext_name, stamp, label, n))
    _zip_dir(ctx.ext_dir, zpath)
    return zpath


def record(bdir, zpath, root, old_ext, new_ext):
    hist = read_history(bdir)
    hist.append({"zip": zpath, "root": root, "old_ext": old_ext,
                 "new_ext": new_ext, "time": time.strftime("%Y-%m-%d %H:%M")})
    write_history(bdir, hist)


def undo_entries(bdir, ctx):
    """History entries that belong to THIS extension in THIS folder."""
    here = os.path.normcase(os.path.abspath(ctx.root))
    cur = os.path.basename(ctx.ext_dir).lower()
    return [h for h in read_history(bdir)
            if os.path.normcase(os.path.abspath(h["root"])) == here
            and h["new_ext"].lower() == cur]


def undo_last(bdir, ctx):
    """Put the extension back as it was before the last Apply here. The
    current state is zipped first, so the undo itself can be reversed by
    hand. Returns the restored extension folder name."""
    entries = undo_entries(bdir, ctx)
    if not entries:
        raise DesignerError(u"Nothing to undo for this extension in this "
                            u"folder.")
    h = entries[-1]
    if not os.path.exists(h["zip"]):
        raise DesignerError(u"The backup file is missing: %s" % h["zip"])
    safety = backup(ctx, bdir, "before_undo")
    old = os.path.join(ctx.root, h["old_ext"])
    if os.path.normcase(old) != os.path.normcase(ctx.ext_dir) and \
            os.path.exists(old):
        raise DesignerError(u"%s already exists - can't restore over it."
                            % h["old_ext"])
    # 1) unpack next to it, 2) rename current away, 3) rename restored in.
    #    Renames are all-or-nothing, so a locked file can't leave a
    #    half-deleted extension behind.
    stamp = time.strftime("%Y%m%d_%H%M%S")
    staging = os.path.join(ctx.root, "_dlc_restore_" + stamp)
    os.mkdir(staging)
    zf = zipfile.ZipFile(h["zip"])
    try:
        zf.extractall(staging)
    finally:
        zf.close()
    restored = os.path.join(staging, h["old_ext"])
    if not os.path.isdir(restored):
        try_remove(staging)
        raise DesignerError(u"The backup doesn't contain %s." % h["old_ext"])
    parked = ctx.ext_dir + ".dlc_old_" + stamp
    try:
        retry(lambda: os.rename(ctx.ext_dir, parked),
              "set the current extension aside")
    except DesignerError:
        try_remove(staging)
        raise
    try:
        retry(lambda: os.rename(restored, old), "put the backup in place")
    except DesignerError:
        os.rename(parked, ctx.ext_dir)     # put things back as they were
        try_remove(staging)
        raise
    try_remove(staging)
    try_remove(parked)                     # leftover is ignored by pyRevit
    hist = read_history(bdir)
    for i in range(len(hist) - 1, -1, -1):
        if hist[i]["zip"] == h["zip"]:
            del hist[i]
            break
    write_history(bdir, hist)
    return h["old_ext"], safety


# ----------------------------------------------------------------- apply
def sweep_leftovers(ctx):
    """Remove leftovers a locked folder left behind on an earlier run."""
    for n in os.listdir(ctx.root):
        p = os.path.join(ctx.root, n)
        if os.path.isdir(p) and (".dlc_old_" in n or
                                 n.startswith("_dlc_restore_")):
            try_remove(p)


# ----------------------------------------------------------------- live refresh
# On refresh pyRevit finds each panel by its title and each button by its
# name, and only *updates* what already exists - Revit can't move a button or
# turn a large one into a stacked one while running. So a re-designed panel
# would only show after restarting Revit. Giving every panel a title it has
# never had in this session (same text + invisible zero-width characters)
# makes pyRevit build it fresh; the old one is hidden.
_INVIS = (u"\u200b", u"\u200c", u"\u200d", u"\u2060")
_SUFFIX_LEN = 10


def fresh_suffix():
    n = int(time.time() * 10) % (4 ** _SUFFIX_LEN)   # unique for ~29 hours
    return u"".join(_INVIS[(n >> (2 * i)) & 3] for i in range(_SUFFIX_LEN))


def strip_invisible(text):
    return u"".join(c for c in (text or u"") if c not in _INVIS)


def _without_key(text, key):
    """Lines of a bundle.yaml with the top-level `key:` entry (and its
    indented block) removed."""
    out = []
    lines = text.splitlines()
    i = 0
    pat = re.compile(r"^%s\s*:" % re.escape(key))
    while i < len(lines):
        if pat.match(lines[i]):
            i += 1
            while i < len(lines) and (not lines[i].strip() or
                                      lines[i][:1].isspace()):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return out


def _set_title(text, title):
    """Replace the whole `title:` entry (plain, block or localised) with a
    single quoted line; keep every other key."""
    out = _without_key(text, "title")
    esc = title.replace("\\", "\\\\").replace('"', '\\"') \
        .replace("\n", "\\n")
    return u'title: "%s"\n' % esc + (u"\n".join(out) + u"\n" if out else u"")


def rekey_panels(tab_dir, suffix=None):
    """Same visible titles, never-used internal names (see above)."""
    suffix = suffix or fresh_suffix()
    n = 0
    for p in subdirs(tab_dir):
        if kind(p) != ".panel":
            continue
        pdir = os.path.join(tab_dir, p)
        f = os.path.join(pdir, "bundle.yaml")
        text = read_text(f) if os.path.exists(f) else u""
        current = yaml_title(text) if text else None
        visible = strip_invisible(current) if current else base(p)
        write_text(f, _set_title(text, visible + suffix))
        n += 1
    return n


def rekey_extension(ext_dir):
    for t in subdirs(ext_dir):
        if kind(t) == ".tab":
            rekey_panels(os.path.join(ext_dir, t))


# ----------------------------------------------------------------- colours
# pyRevit 6 bundle.yaml:  background: {title: "#RRGGBB"} colours only the
# panel's title strip; a plain `background: "#.."` colours the whole panel.
PALETTE = [(u"Red", "#E53935"), (u"Blue", "#1E88E5"), (u"Yellow", "#FDD835"),
           (u"Green", "#43A047"), (u"Purple", "#8E24AA"),
           (u"Orange", "#FB8C00"), (u"Teal", "#00897B"), (u"Pink", "#D81B60"),
           (u"Light blue", "#64B5F6"), (u"Grey", "#757575")]
_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")


def normalize_color(c):
    """'#rrggbb' / 'rrggbb' / '#aarrggbb' -> '#RRGGBB' style, or None."""
    if not c:
        return None
    m = _HEX_RE.match(c.strip())
    return u"#" + m.group(1).upper() if m else None


def text_color_for(c):
    """Black or white - whichever reads better on colour c."""
    c = normalize_color(c)
    if not c:
        return u"#1F2937"
    h = c[-6:]
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return u"#1F2937" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 \
        else u"#FFFFFF"


def _parse_background(text):
    """(scalar, {area: colour}) from a bundle.yaml `background:` entry."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^background\s*:\s*(.*)$", line)
        if not m:
            continue
        v = m.group(1).strip()
        if v.startswith("{") and v.endswith("}"):
            out = {}
            for part in v[1:-1].split(","):
                if ":" in part:
                    k, val = part.split(":", 1)
                    out[_unquote(k).lower()] = _unquote(val)
            return None, out
        if v:
            return _unquote(v), {}
        out = {}
        for nxt in lines[i + 1:]:
            if nxt.strip() and not nxt[:1].isspace():
                break
            mm = re.match(r"^\s+([A-Za-z_]+)\s*:\s*(.+)$", nxt)
            if mm:
                out[mm.group(1).lower()] = _unquote(mm.group(2))
        return None, out
    return None, {}


def read_panel_color(panel_dir):
    f = os.path.join(panel_dir, "bundle.yaml")
    if not os.path.exists(f):
        return None
    scalar, areas = _parse_background(read_text(f))
    return normalize_color(areas.get("title") or scalar)


def write_panel_color(panel_dir, color):
    """Set (or clear, color=None) the title-strip colour. Other background
    areas you set yourself (panel / slideout) are kept."""
    f = os.path.join(panel_dir, "bundle.yaml")
    text = read_text(f) if os.path.exists(f) else u""
    scalar, areas = _parse_background(text)
    if scalar:                       # old 'whole panel' colour -> explicit
        areas = {"panel": scalar, "title": scalar, "slideout": scalar}
    color = normalize_color(color)
    if color:
        areas["title"] = color
    else:
        areas.pop("title", None)
    lines = _without_key(text, "background")
    while lines and not lines[-1].strip():
        lines.pop()
    if areas:
        lines.append(u"background:")
        for k in ("title", "panel", "slideout"):
            if k in areas:
                lines.append(u'  %s: "%s"' % (k, areas[k]))
        for k in sorted(areas):
            if k not in ("title", "panel", "slideout"):
                lines.append(u'  %s: "%s"' % (k, areas[k]))
    if lines or os.path.exists(f):
        write_text(f, u"\n".join(lines) + u"\n")


class ApplyResult(object):
    def __init__(self):
        self.notes = []
        self.renamed = []
        self.backup = None
        self.name_refs = []
        self.fixed_files = 0
        self.ext_dir = None


def apply_design(ctx, panels, new_tab_name, rename_ext, fix_refs, bdir,
                 more_icon=None, more_icon_dark=None):
    """Back up, write every panel, rename tab (and extension). Each step
    leaves a valid extension, so a failure midway never breaks the ribbon."""
    err = check_name(new_tab_name)
    if err:
        raise DesignerError(err)
    problems = []
    for p in panels:
        problems.extend(check_panel(p))
    new_tab_leaf = new_tab_name.strip() + ".tab"
    new_ext_leaf = new_tab_name.strip() + ".extension" if rename_ext \
        else os.path.basename(ctx.ext_dir)
    if os.path.normcase(new_tab_leaf) != os.path.normcase(
            os.path.basename(ctx.tab_dir)) and os.path.exists(
            os.path.join(ctx.ext_dir, new_tab_leaf)):
        problems.append(u"%s already exists in this extension." % new_tab_leaf)
    if os.path.normcase(new_ext_leaf) != os.path.normcase(
            os.path.basename(ctx.ext_dir)) and os.path.exists(
            os.path.join(ctx.root, new_ext_leaf)):
        problems.append(u"%s already exists in %s." % (new_ext_leaf, ctx.root))
    if problems:
        raise DesignerError(u"Nothing was changed:\n- " + u"\n- ".join(problems))

    if not more_icon:
        more_icon = os.path.join(ctx.self_dir, "more_icon.png")
    if not more_icon_dark:
        more_icon_dark = os.path.join(ctx.self_dir, "more_icon.dark.png")
    sweep_leftovers(ctx)
    res = ApplyResult()
    old_ext_leaf = os.path.basename(ctx.ext_dir)
    old_tab_leaf = os.path.basename(ctx.tab_dir)
    res.backup = backup(ctx, bdir, "before_apply")
    record(bdir, res.backup, ctx.root, old_ext_leaf, old_ext_leaf)

    def update_record(new_ext):
        hist = read_history(bdir)
        for h in hist:
            if h["zip"] == res.backup:
                h["new_ext"] = new_ext
        write_history(bdir, hist)

    for p in panels:
        res.notes.append(build_panel(p, more_icon, more_icon_dark))
        if normalize_color(p.color) != read_panel_color(p.path):
            write_panel_color(p.path, p.color)      # only when you changed it

    ext_dir = ctx.ext_dir
    if old_tab_leaf != new_tab_leaf:
        rename_folder(ctx.tab_dir, new_tab_leaf)
        res.renamed.append((old_tab_leaf, new_tab_leaf))
    if old_ext_leaf != new_ext_leaf:
        ext_dir = rename_folder(ctx.ext_dir, new_ext_leaf)
        res.renamed.append((old_ext_leaf, new_ext_leaf))
        update_record(new_ext_leaf)
    res.ext_dir = ext_dir
    rekey_panels(os.path.join(ext_dir, new_tab_leaf))

    olds = [o for o, n in res.renamed]
    if olds:
        res.name_refs = find_name_refs(ext_dir, olds)
        if fix_refs and res.name_refs:
            res.fixed_files = fix_name_refs(res.name_refs, res.renamed)
    return res


# ----------------------------------------------------------------- window model
class Design(object):
    """What the window edits. Keeps no WPF objects, so it can be tested."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.panels = scan_tab(ctx)
        self.index = 0 if self.panels else -1

    @property
    def panel(self):
        return self.panels[self.index] if self.index >= 0 else None

    def reset(self):
        cur = self.index
        self.panels = scan_tab(self.ctx)
        self.index = min(cur, len(self.panels) - 1)

    def suggest_all(self):
        for p in self.panels:
            suggest(p)

    def set_mode(self, item, mode):
        if mode not in item.options():
            raise DesignerError(u"%s can't be %s." % (item.label,
                                                     MODE_LABELS[mode]))
        item.mode = mode

    def move(self, item, delta):
        items = self.panel.items
        i = items.index(item)
        j = i + delta
        if 0 <= j < len(items):
            items[i], items[j] = items[j], items[i]
            return True
        return False

    def set_color(self, panel, color):
        panel.color = normalize_color(color)

    def auto_colors(self):
        """Distinct palette colour per panel, in ribbon order."""
        for i, p in enumerate(self.panels):
            p.color = PALETTE[i % len(PALETTE)][1]

    def counts(self, panel):
        return (len(panel.items),
                width_estimate(panel))
