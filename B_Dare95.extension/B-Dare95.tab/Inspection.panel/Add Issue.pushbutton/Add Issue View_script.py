# -*- coding: utf-8 -*-
"""
Issue Logger  ·  pyRevit / IronPython 2.7
==========================================
Normal click   → issue logger  (left: input  |  right: scrollable preview + delete)
Shift+click    → configure save folder

Replaces:
  WinForms UI  → WPF  (XamlReader.Parse, Catppuccin Mocha)
  COM / Excel  → zero-dependency xlsx  (ZipArchive + raw XML)
  PIL          → WinForms Clipboard + GDI+  (fixes transparent-alpha bug)
  subprocess   → System.Diagnostics.Process
  threading    → System.Threading.Thread
"""
import clr
import os

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
clr.AddReference('System.Xml')
clr.AddReference('System.IO.Compression')
clr.AddReference('System')

# ── WPF structural / layout types ───────────────────────────────────────────
from System.Windows.Markup   import XamlReader
from System.Windows          import (
    Visibility, Thickness, HorizontalAlignment, VerticalAlignment,
    CornerRadius, GridLength, GridUnitType, FontWeights, TextWrapping
)
from System.Windows.Controls import (
    Border, Grid as WpfGrid, ColumnDefinition, RowDefinition,
    StackPanel, TextBlock, Image as WpfImage, TextBox, Button
)
from System.Windows.Media         import SolidColorBrush, Color, Brushes, Stretch as MediaStretch
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Threading     import DispatcherFrame, Dispatcher
from System.Windows.Input         import Cursors

# ── I/O ─────────────────────────────────────────────────────────────────────
from System.IO            import File, FileStream, FileMode, MemoryStream, StreamReader
from System.IO.Compression import ZipArchive, ZipArchiveMode

# ── Clipboard (WinForms path avoids WPF transparent-alpha bug) ───────────────
from System.Windows.Forms   import (
    FolderBrowserDialog, DialogResult as WFDialogResult,
    Clipboard as WFClipboard
)
from System.Drawing         import Bitmap, Graphics
from System.Drawing.Imaging import ImageFormat, PixelFormat

# ── Process / Thread / Misc ──────────────────────────────────────────────────
from System.Diagnostics import Process, ProcessStartInfo
from System.Threading   import Thread, ThreadStart, ApartmentState
from System             import Array, Byte, Action, DateTime
from System.Text        import Encoding
import System.Xml as SysXml


# ═══════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE   = os.path.join(SCRIPT_DIR, u'issue_logger.cfg')
XLSX_FILENAME = u'Issue Logger.xlsx'
_EMU_PX       = 9525          # 1 px @ 96 dpi → EMU

# Catppuccin Mocha status brushes
_BR_SUBTEXT = SolidColorBrush(Color.FromRgb(0xA6, 0xAD, 0xC8))
_BR_SUCCESS = SolidColorBrush(Color.FromRgb(0xA6, 0xE3, 0xA1))
_BR_WARN    = SolidColorBrush(Color.FromRgb(0xF3, 0x8B, 0xA8))

# Card colours (used in programmatic card building)
_C_SURFACE = Color.FromRgb(0x2A, 0x2A, 0x3C)
_C_TEXT    = Color.FromRgb(0xCD, 0xD6, 0xF4)
_C_SUB     = Color.FromRgb(0xA6, 0xAD, 0xC8)
_C_DELBG   = Color.FromRgb(0x3D, 0x1A, 0x22)
_C_DELFG   = Color.FromRgb(0xF3, 0x8B, 0xA8)


# ═══════════════════════════════════════════════════════════════════════════
#  SNIPASTE AUTO-DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def find_snipaste():
    env = os.environ
    candidates = [
        os.path.join(env.get(u'LOCALAPPDATA', u''),
                     u'Microsoft', u'WindowsApps', u'Snipaste.exe'),
        os.path.join(env.get(u'PROGRAMFILES',      u''), u'Snipaste', u'Snipaste.exe'),
        os.path.join(env.get(u'PROGRAMFILES(X86)', u''), u'Snipaste', u'Snipaste.exe'),
        os.path.join(env.get(u'PROGRAMW6432',      u''), u'Snipaste', u'Snipaste.exe'),
        os.path.join(env.get(u'USERPROFILE',       u''),
                     u'scoop', u'apps', u'snipaste', u'current', u'Snipaste.exe'),
        os.path.join(env.get(u'LOCALAPPDATA', u''), u'Snipaste', u'Snipaste.exe'),
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    for d in env.get(u'PATH', u'').split(u';'):
        p = os.path.join(d.strip(), u'Snipaste.exe')
        if os.path.isfile(p):
            return p
    return None


SNIPASTE_PATH = find_snipaste()


# ═══════════════════════════════════════════════════════════════════════════
#  CONFIG PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════

def load_config():
    if File.Exists(CONFIG_FILE):
        txt = File.ReadAllText(CONFIG_FILE, Encoding.UTF8).strip()
        if txt:
            return txt
    return None


def save_config(folder):
    File.WriteAllText(CONFIG_FILE, folder, Encoding.UTF8)


def xlsx_path_from(folder):
    return os.path.join(folder, XLSX_FILENAME)


# ═══════════════════════════════════════════════════════════════════════════
#  CLIPBOARD  →  PNG bytes
#  Uses GDI+ (WinForms) path to avoid WPF transparent-alpha bug.
#  Draws onto a fresh 24-bpp RGB bitmap so A is always 255.
# ═══════════════════════════════════════════════════════════════════════════

def clipboard_to_png():
    if not WFClipboard.ContainsImage():
        return None
    img = WFClipboard.GetImage()
    if img is None:
        return None
    rgb = Bitmap(img.Width, img.Height, PixelFormat.Format24bppRgb)
    g   = Graphics.FromImage(rgb)
    g.DrawImage(img, 0, 0, img.Width, img.Height)
    g.Dispose()
    ms = MemoryStream()
    rgb.Save(ms, ImageFormat.Png)
    rgb.Dispose()
    img.Dispose()
    return ms.ToArray()


# ═══════════════════════════════════════════════════════════════════════════
#  XLSX ENGINE  (zero-dependency — no openpyxl, no Excel)
# ═══════════════════════════════════════════════════════════════════════════

def _esc(text):
    return (unicode(text)
            .replace(u'&', u'&amp;').replace(u'<', u'&lt;')
            .replace(u'>', u'&gt;') .replace(u'"', u'&quot;')
            .replace(u"'", u'&apos;'))


def _col_letter(idx0):
    """0-based column index -> spreadsheet column letter(s), e.g. 0->A, 26->AA."""
    n = idx0 + 1
    s = u''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _parse_col_index(cell_ref):
    """'B7' -> 1 (0-based column index)."""
    i = 0
    while i < len(cell_ref) and cell_ref[i].isalpha():
        i += 1
    letters = cell_ref[:i]
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _build_xlsx(columns, issues):
    """
    Build xlsx from:
      columns - [name, ...]                          dynamic field headers
      issues  - [(ts, values, png_bytes|None), ...]   values aligned to columns
    Returns Array[Byte].
    """
    out = MemoryStream()
    za  = ZipArchive(out, ZipArchiveMode.Create, True)

    def wt(name, xml_str):
        e = za.CreateEntry(name)
        s = e.Open()
        b = Encoding.UTF8.GetBytes(xml_str)
        s.Write(b, 0, b.Length)
        s.Dispose()

    def wb(name, data):
        e = za.CreateEntry(name)
        s = e.Open()
        s.Write(data, 0, data.Length)
        s.Dispose()

    has_img = any(img is not None for _, _, img in issues)

    wt(u'[Content_Types].xml',
       u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       u'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       u'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       u'<Default Extension="xml"  ContentType="application/xml"/>'
       u'<Default Extension="png"  ContentType="image/png"/>'
       u'<Override PartName="/xl/workbook.xml"'
       u' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
       u'<Override PartName="/xl/worksheets/sheet1.xml"'
       u' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
       u'<Override PartName="/xl/styles.xml"'
       u' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
       + (u'<Override PartName="/xl/drawings/drawing1.xml"'
          u' ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
          if has_img else u'') +
       u'</Types>')

    wt(u'_rels/.rels',
       u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
       u'<Relationship Id="rId1"'
       u' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
       u' Target="xl/workbook.xml"/>'
       u'</Relationships>')

    wt(u'xl/workbook.xml',
       u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       u'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
       u' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
       u'<sheets><sheet name="Issues" sheetId="1" r:id="rId1"/></sheets>'
       u'</workbook>')

    wt(u'xl/_rels/workbook.xml.rels',
       u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
       u'<Relationship Id="rId1"'
       u' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
       u' Target="worksheets/sheet1.xml"/>'
       u'<Relationship Id="rId2"'
       u' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"'
       u' Target="styles.xml"/>'
       u'</Relationships>')

    wt(u'xl/styles.xml',
       u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       u'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
       u'<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
       u'<fills count="2">'
       u'<fill><patternFill patternType="none"/></fill>'
       u'<fill><patternFill patternType="gray125"/></fill>'
       u'</fills>'
       u'<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
       u'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
       u'<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
       u'</styleSheet>')

    ROW_H        = 135
    n_cols       = len(columns)
    shot_col_idx = 1 + n_cols     # 0-based: 0=Timestamp, 1..n_cols=fields, this=Screenshot

    header_cells = [u'<c r="A1" t="inlineStr"><is><t>Timestamp</t></is></c>']
    for i, name in enumerate(columns):
        col = _col_letter(1 + i)
        header_cells.append(
            u'<c r="{c}1" t="inlineStr"><is><t>{v}</t></is></c>'.format(c=col, v=_esc(name)))
    header_cells.append(
        u'<c r="{c}1" t="inlineStr"><is><t>Screenshot</t></is></c>'.format(
            c=_col_letter(shot_col_idx)))
    rows = [u'<row r="1">' + u''.join(header_cells) + u'</row>']

    for i, (ts, values, _) in enumerate(issues):
        rn    = i + 2
        cells = [u'<c r="A{r}" t="inlineStr"><is><t>{ts}</t></is></c>'.format(r=rn, ts=_esc(ts))]
        for ci in range(n_cols):
            val = values[ci] if ci < len(values) else u''
            cells.append(
                u'<c r="{c}{r}" t="inlineStr"><is><t>{v}</t></is></c>'.format(
                    c=_col_letter(1 + ci), r=rn, v=_esc(val)))
        rows.append(
            u'<row r="{r}" ht="{h}" customHeight="1">'.format(r=rn, h=ROW_H)
            + u''.join(cells) + u'</row>')

    cols_xml = [u'<col min="1" max="1" width="22" customWidth="1"/>']
    for i in range(n_cols):
        colnum = i + 2
        cols_xml.append(
            u'<col min="{n}" max="{n}" width="34" customWidth="1"/>'.format(n=colnum))
    cols_xml.append(
        u'<col min="{n}" max="{n}" width="45" customWidth="1"/>'.format(n=shot_col_idx + 1))

    sheet_r = (u' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
               if has_img else u'')
    wt(u'xl/worksheets/sheet1.xml',
       u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
       + sheet_r + u'>'
       u'<sheetFormatPr defaultRowHeight="15"/>'
       u'<cols>' + u''.join(cols_xml) + u'</cols>'
       u'<sheetData>' + u''.join(rows) + u'</sheetData>'
       + (u'<drawing r:id="rId1"/>' if has_img else u'') +
       u'</worksheet>')

    if has_img:
        wt(u'xl/worksheets/_rels/sheet1.xml.rels',
           u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           u'<Relationship Id="rId1"'
           u' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"'
           u' Target="../drawings/drawing1.xml"/>'
           u'</Relationships>')

        anchors  = []
        img_rels = []
        n        = 1
        for i, (_, _, png) in enumerate(issues):
            if png is None:
                continue
            row0 = i + 1
            cx   = _EMU_PX * 300
            cy   = _EMU_PX * 170
            rid  = u'rId{0}'.format(n)
            wb(u'xl/media/image{0}.png'.format(n), png)
            img_rels.append(
                u'<Relationship Id="{rid}"'
                u' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"'
                u' Target="../media/image{n}.png"/>'.format(rid=rid, n=n))
            anchors.append(
                u'<xdr:oneCellAnchor>'
                u'<xdr:from><xdr:col>{sc}</xdr:col><xdr:colOff>0</xdr:colOff>'
                u'<xdr:row>{r}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
                u'<xdr:ext cx="{cx}" cy="{cy}"/>'
                u'<xdr:pic><xdr:nvPicPr>'
                u'<xdr:cNvPr id="{n}" name="Picture {n}"/>'
                u'<xdr:cNvPicPr/></xdr:nvPicPr>'
                u'<xdr:blipFill><a:blip r:embed="{rid}"/>'
                u'<a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
                u'<xdr:spPr><a:xfrm><a:off x="0" y="0"/>'
                u'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
                u'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
                u'</xdr:spPr></xdr:pic><xdr:clientData/>'
                u'</xdr:oneCellAnchor>'.format(r=row0, cx=cx, cy=cy, n=n, rid=rid, sc=shot_col_idx))
            n += 1

        wt(u'xl/drawings/drawing1.xml',
           u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           u'<xdr:wsDr'
           u' xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"'
           u' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
           u' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
           + u''.join(anchors) + u'</xdr:wsDr>')
        wt(u'xl/drawings/_rels/drawing1.xml.rels',
           u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           + u''.join(img_rels) + u'</Relationships>')

    za.Dispose()
    return out.ToArray()


def _read_xlsx(path):
    """
    Read xlsx built by _build_xlsx.
    Returns (columns, issues) where columns is [name, ...] and issues is
    [(ts, values, png|None), ...] with values aligned to columns.
    """
    columns = []
    issues  = []
    fs = za = None
    try:
        fs = FileStream(path, FileMode.Open)
        za = ZipArchive(fs, ZipArchiveMode.Read)

        se = za.GetEntry(u'xl/worksheets/sheet1.xml')
        if se is None:
            return columns, issues
        sr = StreamReader(se.Open(), Encoding.UTF8)
        sheet_xml = sr.ReadToEnd()
        sr.Dispose()

        sdoc = SysXml.XmlDocument()
        sdoc.LoadXml(sheet_xml)
        sns = SysXml.XmlNamespaceManager(sdoc.NameTable)
        sns.AddNamespace(u'ss', u'http://schemas.openxmlformats.org/spreadsheetml/2006/main')

        header   = {}
        rows_raw = {}
        for row_nd in sdoc.SelectNodes(u'//ss:row', sns):
            rn = int(row_nd.GetAttribute(u'r') or u'0')
            vals = {}
            for c in row_nd.SelectNodes(u'ss:c', sns):
                ref = c.GetAttribute(u'r')
                if not ref:
                    continue
                tl   = c.SelectNodes(u'ss:is/ss:t', sns)
                text = tl.Item(0).InnerText if tl.Count > 0 else u''
                vals[_parse_col_index(ref)] = text
            if rn == 1:
                header = vals
            elif rn > 1:
                rows_raw[rn] = vals

        if header:
            max_ci  = max(header.keys())
            # index 0 = Timestamp, 1..max_ci-1 = field columns, max_ci = Screenshot
            columns = [header.get(ci, u'Field {0}'.format(ci)) for ci in range(1, max_ci)]
        n_cols = len(columns)

        rid_to_rn = {}
        de = za.GetEntry(u'xl/drawings/drawing1.xml')
        if de is not None:
            dr   = StreamReader(de.Open(), Encoding.UTF8)
            dxml = dr.ReadToEnd()
            dr.Dispose()
            ddoc = SysXml.XmlDocument()
            ddoc.LoadXml(dxml)
            dns = SysXml.XmlNamespaceManager(ddoc.NameTable)
            dns.AddNamespace(u'xdr', u'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing')
            dns.AddNamespace(u'a',   u'http://schemas.openxmlformats.org/drawingml/2006/main')
            REL_NS = u'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
            for anc in ddoc.SelectNodes(u'//xdr:oneCellAnchor', dns):
                rn_nd = anc.SelectSingleNode(u'xdr:from/xdr:row', dns)
                blip  = anc.SelectSingleNode(u'.//a:blip', dns)
                if rn_nd and blip:
                    embed = blip.GetAttribute(u'embed', REL_NS)
                    if embed:
                        rid_to_rn[embed] = int(rn_nd.InnerText) + 1

        rid_to_media = {}
        re_ent = za.GetEntry(u'xl/drawings/_rels/drawing1.xml.rels')
        if re_ent is not None:
            rr = StreamReader(re_ent.Open(), Encoding.UTF8)
            rels_xml = rr.ReadToEnd()
            rr.Dispose()
            rdoc = SysXml.XmlDocument()
            rdoc.LoadXml(rels_xml)
            rns  = SysXml.XmlNamespaceManager(rdoc.NameTable)
            rns.AddNamespace(u'rel', u'http://schemas.openxmlformats.org/package/2006/relationships')
            for rel in rdoc.SelectNodes(u'//rel:Relationship', rns):
                rid_to_media[rel.GetAttribute(u'Id')] = (
                    u'xl/media/' + rel.GetAttribute(u'Target').split(u'/')[-1])

        img_by_rn = {}
        for rid, rn in rid_to_rn.items():
            media = rid_to_media.get(rid)
            if not media:
                continue
            ie = za.GetEntry(media)
            if ie is None:
                continue
            ms  = MemoryStream()
            ies = ie.Open()
            buf = Array.CreateInstance(Byte, 8192)
            while True:
                n = ies.Read(buf, 0, buf.Length)
                if n == 0:
                    break
                ms.Write(buf, 0, n)
            ies.Dispose()
            img_by_rn[rn] = ms.ToArray()

        for rn in sorted(rows_raw.keys()):
            vals   = rows_raw[rn]
            ts     = vals.get(0, u'')
            values = [vals.get(1 + ci, u'') for ci in range(n_cols)]
            issues.append((ts, values, img_by_rn.get(rn)))

    except Exception as ex:
        print(u'[IssueLogger] _read_xlsx error: ' + unicode(ex))
        columns, issues = [], []
    finally:
        if za:  za.Dispose()
        if fs:  fs.Dispose()

    if not columns:
        columns = [u'Comment']
    return columns, issues


# ═══════════════════════════════════════════════════════════════════════════
#  SHARED WPF HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _pick_folder(initial=u''):
    dlg = FolderBrowserDialog()
    dlg.Description         = u'Select folder for Issue Logger.xlsx'
    dlg.ShowNewFolderButton = True
    if initial and os.path.isdir(initial):
        dlg.SelectedPath = initial
    return dlg.SelectedPath if dlg.ShowDialog() == WFDialogResult.OK else None


def _push_frame(window):
    """Show WPF window modeless; block pyRevit script thread via PushFrame."""
    frame = [DispatcherFrame()]
    def on_close(s, e):
        frame[0].Continue = False
    window.Closed += on_close
    window.Show()
    Dispatcher.PushFrame(frame[0])


# ═══════════════════════════════════════════════════════════════════════════
#  PREVIEW CARD HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _bytes_to_bitmap(png_bytes):
    """Convert Array[Byte] PNG to a frozen WPF BitmapImage, or None on failure."""
    if png_bytes is None:
        return None
    try:
        ms  = MemoryStream(png_bytes)
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.StreamSource = ms
        bmp.CacheOption  = BitmapCacheOption.OnLoad
        bmp.EndInit()
        bmp.Freeze()      # detach from stream, make thread-safe
        ms.Dispose()
        return bmp
    except Exception:
        return None


# Parsed once; reused per card to avoid repeated XAML parsing.
_DEL_BTN_XML = (
    u'<Button'
    u' xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"'
    u' xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
    u' Background="#3D1A22" Foreground="#F38BA8"'
    u' BorderThickness="0" Padding="9,5" Cursor="Hand" FontSize="14">'
    u'<Button.Template><ControlTemplate TargetType="Button">'
    u'<Border x:Name="bd" Background="{TemplateBinding Background}"'
    u' CornerRadius="4" Padding="{TemplateBinding Padding}">'
    u'<ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>'
    u'</Border>'
    u'<ControlTemplate.Triggers>'
    u'<Trigger Property="IsMouseOver" Value="True">'
    u'<Setter TargetName="bd" Property="Opacity" Value="0.72"/></Trigger>'
    u'<Trigger Property="IsPressed" Value="True">'
    u'<Setter TargetName="bd" Property="Opacity" Value="0.50"/></Trigger>'
    u'</ControlTemplate.Triggers>'
    u'</ControlTemplate></Button.Template>'
    u'</Button>'
)


def _make_card_delete_btn():
    """Return a styled WPF delete Button with 🗑 icon."""
    btn         = XamlReader.Parse(_DEL_BTN_XML)
    btn.Content = u'\U0001F5D1'   # set after parsing to dodge XML surrogate issues
    return btn


def _make_issue_card(num, ts, columns, values, png_bytes, delete_handler, edit_handler):
    """
    Build one issue preview card entirely in Python (no extra XAML parsing).
    `columns`/`values` are aligned lists of field names/values.
    The screenshot thumbnail (if any) is clickable via `edit_handler`,
    which loads this issue back into the left panel for re-editing.
    Returns a WPF Border element ready to be added to a StackPanel.
    """
    # ── outer card border ────────────────────────────────────────
    card             = Border()
    card.Background  = SolidColorBrush(_C_SURFACE)
    card.CornerRadius = CornerRadius(6)
    card.Margin      = Thickness(0, 0, 0, 8)
    card.Padding     = Thickness(10, 8, 10, 8)

    inner = StackPanel()
    card.Child = inner

    # ── header: "Issue · #N" + timestamp  |  delete button ──────
    hdr = WpfGrid()
    hdr.Margin = Thickness(0, 0, 0, 6)
    c0 = ColumnDefinition(); c0.Width = GridLength(1, GridUnitType.Star)
    c1 = ColumnDefinition(); c1.Width = GridLength.Auto
    hdr.ColumnDefinitions.Add(c0)
    hdr.ColumnDefinitions.Add(c1)

    meta = StackPanel()
    meta.VerticalAlignment = VerticalAlignment.Center

    title_lbl            = TextBlock()
    title_lbl.Text       = u'Issue  \u00b7  #{0}'.format(num)
    title_lbl.FontSize   = 12
    title_lbl.FontWeight = FontWeights.Bold
    title_lbl.Foreground = SolidColorBrush(_C_TEXT)
    meta.Children.Add(title_lbl)

    ts_lbl            = TextBlock()
    ts_lbl.Text       = ts
    ts_lbl.FontSize   = 10
    ts_lbl.Foreground = SolidColorBrush(_C_SUB)
    ts_lbl.Margin     = Thickness(0, 2, 0, 0)
    meta.Children.Add(ts_lbl)

    WpfGrid.SetColumn(meta, 0)
    hdr.Children.Add(meta)

    del_btn                  = _make_card_delete_btn()
    del_btn.VerticalAlignment = VerticalAlignment.Center
    del_btn.Click            += delete_handler
    WpfGrid.SetColumn(del_btn, 1)
    hdr.Children.Add(del_btn)

    inner.Children.Add(hdr)

    # ── screenshot thumbnail (clickable → re-edit) ────────────────
    if png_bytes is not None:
        bmp = _bytes_to_bitmap(png_bytes)
        if bmp is not None:
            img_wrap                    = Border()
            img_wrap.Cursor             = Cursors.Hand
            img_wrap.Margin             = Thickness(0, 0, 0, 6)
            img_wrap.ToolTip            = u'Click to load this issue for editing'
            img                         = WpfImage()
            img.Source                  = bmp
            img.MaxHeight               = 150
            img.Stretch                 = MediaStretch.Uniform
            img.HorizontalAlignment     = HorizontalAlignment.Stretch
            img_wrap.Child               = img
            img_wrap.MouseLeftButtonUp  += edit_handler
            inner.Children.Add(img_wrap)

    # ── field values ────────────────────────────────────────────
    for i, col_name in enumerate(columns):
        val = values[i] if i < len(values) else u''
        if not val.strip():
            continue
        field_stack        = StackPanel()
        field_stack.Margin = Thickness(0, 0, 0, 5)

        name_lbl              = TextBlock()
        name_lbl.Text         = col_name + u':'
        name_lbl.FontSize     = 10
        name_lbl.FontWeight   = FontWeights.Bold
        name_lbl.Foreground   = SolidColorBrush(_C_SUB)
        field_stack.Children.Add(name_lbl)

        val_lbl              = TextBlock()
        val_lbl.Text         = val
        val_lbl.FontSize     = 12
        val_lbl.Foreground   = SolidColorBrush(_C_TEXT)
        val_lbl.TextWrapping = TextWrapping.Wrap
        field_stack.Children.Add(val_lbl)

        inner.Children.Add(field_stack)

    return card


def _make_field_row(name, value, delete_handler):
    """
    Build one editable field row for the left panel: a renamable title chip
    next to a multi-line value TextBox, with a small remove button.
    Returns (row, name_box, value_box).
    """
    row = WpfGrid()
    row.Margin = Thickness(0, 0, 0, 8)
    c0 = ColumnDefinition(); c0.Width = GridLength(92)
    c1 = ColumnDefinition(); c1.Width = GridLength(1, GridUnitType.Star)
    c2 = ColumnDefinition(); c2.Width = GridLength(24)
    row.ColumnDefinitions.Add(c0)
    row.ColumnDefinitions.Add(c1)
    row.ColumnDefinitions.Add(c2)

    # ── renamable title chip ────────────────────────────────────
    name_wrap                  = Border()
    name_wrap.Background       = SolidColorBrush(_C_SURFACE)
    name_wrap.CornerRadius     = CornerRadius(6)
    name_wrap.Padding          = Thickness(6, 5, 6, 5)
    name_wrap.VerticalAlignment = VerticalAlignment.Top
    name_wrap.Margin           = Thickness(0, 0, 8, 0)

    name_box                = TextBox()
    name_box.Text            = name
    name_box.Background      = Brushes.Transparent
    name_box.BorderThickness = Thickness(0)
    name_box.Padding         = Thickness(0)
    name_box.Foreground      = SolidColorBrush(_C_TEXT)
    name_box.CaretBrush      = SolidColorBrush(_C_TEXT)
    name_box.FontSize        = 12
    name_box.FontWeight      = FontWeights.Bold
    name_box.TextWrapping    = TextWrapping.Wrap
    name_box.AcceptsReturn   = False
    name_box.ToolTip         = u'Click to rename this field'
    name_wrap.Child          = name_box
    WpfGrid.SetColumn(name_wrap, 0)
    row.Children.Add(name_wrap)

    # ── value box ────────────────────────────────────────────────
    value_box                          = TextBox()
    value_box.Text                     = value
    value_box.AcceptsReturn            = True
    value_box.TextWrapping             = TextWrapping.Wrap
    value_box.MinHeight                = 56
    value_box.VerticalContentAlignment = VerticalAlignment.Top
    WpfGrid.SetColumn(value_box, 1)
    row.Children.Add(value_box)

    # ── remove field button ─────────────────────────────────────
    del_btn                    = Button()
    del_btn.Content             = u'\u00d7'
    del_btn.FontSize            = 13
    del_btn.Width                = 22
    del_btn.Height               = 22
    del_btn.Padding              = Thickness(0)
    del_btn.Background           = Brushes.Transparent
    del_btn.Foreground           = SolidColorBrush(_C_SUB)
    del_btn.Cursor               = Cursors.Hand
    del_btn.ToolTip              = u'Remove this field'
    del_btn.VerticalAlignment    = VerticalAlignment.Top
    del_btn.Click               += delete_handler
    WpfGrid.SetColumn(del_btn, 2)
    row.Children.Add(del_btn)

    return row, name_box, value_box


# ═══════════════════════════════════════════════════════════════════════════
#  SHARED BUTTON / TEXTBOX STYLES  (injected into both windows)
# ═══════════════════════════════════════════════════════════════════════════

_SHARED_STYLES = u"""
    <Window.Resources>
        <Style TargetType="Button">
            <Setter Property="Background"      Value="#313244"/>
            <Setter Property="Foreground"      Value="#CDD6F4"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Padding"         Value="14,9"/>
            <Setter Property="FontSize"        Value="13"/>
            <Setter Property="Cursor"          Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="bd"
                                Background="{TemplateBinding Background}"
                                CornerRadius="6"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="bd" Property="Opacity" Value="0.80"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="bd" Property="Opacity" Value="0.60"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="bd" Property="Opacity" Value="0.35"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
        <Style TargetType="TextBox">
            <Setter Property="Background"      Value="#313244"/>
            <Setter Property="Foreground"      Value="#CDD6F4"/>
            <Setter Property="BorderBrush"     Value="#45475A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Padding"         Value="8,6"/>
            <Setter Property="FontSize"        Value="13"/>
            <Setter Property="CaretBrush"      Value="#CDD6F4"/>
            <Setter Property="SelectionBrush"  Value="#F0A500"/>
        </Style>
        <Style TargetType="TextBlock">
            <Setter Property="Foreground" Value="#CDD6F4"/>
        </Style>
    </Window.Resources>
"""


# ═══════════════════════════════════════════════════════════════════════════
#  CONFIG WINDOW XAML  (shift-click)
# ═══════════════════════════════════════════════════════════════════════════

CONFIG_XAML = (
    u'<Window'
    u'    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"'
    u'    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
    u'    Title="Issue Logger \u2014 Configure Save Location"'
    u'    Width="520" Height="200" ResizeMode="NoResize"'
    u'    WindowStartupLocation="CenterScreen" Background="#1E1E2E">'
    + _SHARED_STYLES +
    u'    <Grid Margin="20,16,20,16">'
    u'        <Grid.RowDefinitions>'
    u'            <RowDefinition Height="Auto"/>'
    u'            <RowDefinition Height="Auto"/>'
    u'            <RowDefinition Height="*"/>'
    u'            <RowDefinition Height="Auto"/>'
    u'        </Grid.RowDefinitions>'
    u'        <TextBlock Grid.Row="0" Text="Configure Save Location"'
    u'                   FontSize="17" FontWeight="Bold" Margin="0,0,0,14"/>'
    u'        <Grid Grid.Row="1" Margin="0,0,0,8">'
    u'            <Grid.ColumnDefinitions>'
    u'                <ColumnDefinition Width="*"/>'
    u'                <ColumnDefinition Width="10"/>'
    u'                <ColumnDefinition Width="Auto"/>'
    u'            </Grid.ColumnDefinitions>'
    u'            <Border Grid.Column="0" Background="#2A2A3C" CornerRadius="6" Padding="10,7">'
    u'                <TextBlock x:Name="PathDisplay" Text="(not configured)"'
    u'                           Foreground="#A6ADC8" FontSize="12"'
    u'                           TextTrimming="CharacterEllipsis" VerticalAlignment="Center"/>'
    u'            </Border>'
    u'            <Button Grid.Column="2" x:Name="BrowseBtn" Content="Browse..." Padding="12,7"/>'
    u'        </Grid>'
    u'        <TextBlock Grid.Row="2" x:Name="CfgStatus" Text=" "'
    u'                   Foreground="#A6ADC8" FontSize="11" VerticalAlignment="Center"/>'
    u'        <Grid Grid.Row="3">'
    u'            <Grid.ColumnDefinitions>'
    u'                <ColumnDefinition Width="*"/>'
    u'                <ColumnDefinition Width="10"/>'
    u'                <ColumnDefinition Width="Auto"/>'
    u'            </Grid.ColumnDefinitions>'
    u'            <Button Grid.Column="0" x:Name="SaveCfgBtn"'
    u'                    Content="Save &amp; Close"'
    u'                    Background="#F0A500" Foreground="#1E1E2E" FontWeight="Bold"/>'
    u'            <Button Grid.Column="2" x:Name="CancelCfgBtn"'
    u'                    Content="Cancel" Padding="18,9"/>'
    u'        </Grid>'
    u'    </Grid>'
    u'</Window>'
)


# ═══════════════════════════════════════════════════════════════════════════
#  LOGGER WINDOW XAML  (normal click)
#  Two-column layout: left = input, right = scrollable issue preview
# ═══════════════════════════════════════════════════════════════════════════

LOGGER_XAML = u"""<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Issue Logger"
    Width="960" Height="540"
    MinWidth="720" MinHeight="440"
    WindowStartupLocation="CenterScreen"
    Background="#1E1E2E"
    ResizeMode="CanResize">
    __STYLES__

    <Grid Margin="20,16,20,16">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
        </Grid.RowDefinitions>

        <!-- ── Snipaste not-found warning banner (hidden when found) ── -->
        <Border Grid.Row="0" x:Name="SnipWarning"
                Background="#3D2A1A" CornerRadius="6"
                Padding="12,9" Margin="0,0,0,10"
                Visibility="Collapsed">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Grid.Column="0" VerticalAlignment="Center">
                    <TextBlock Text="Snipaste is not installed on this machine."
                               Foreground="#FAB387" FontSize="12" FontWeight="Bold"/>
                    <TextBlock Text="Screenshot capture is disabled. Install Snipaste to enable it."
                               Foreground="#FAB387" FontSize="11" Margin="0,3,0,0"/>
                </StackPanel>
                <Button Grid.Column="1" x:Name="GetSnipBtn"
                        Content="Get from Microsoft Store"
                        Background="#F0A500" Foreground="#1E1E2E"
                        FontWeight="Bold" FontSize="11"
                        Padding="12,6" Margin="14,0,0,0"/>
            </Grid>
        </Border>

        <!-- ── Main two-column layout ── -->
        <Grid Grid.Row="1">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*" MinWidth="340"/>
                <ColumnDefinition Width="16"/>
                <ColumnDefinition Width="360"/>
            </Grid.ColumnDefinitions>

            <!-- Vertical divider -->
            <Rectangle Grid.Column="1" Fill="#313244" Width="1"
                       VerticalAlignment="Stretch" HorizontalAlignment="Center"/>

            <!-- ═══ LEFT: input panel ═══ -->
            <Grid Grid.Column="0">
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="*"/>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                </Grid.RowDefinitions>

                <!-- Title row -->
                <Grid Grid.Row="0" Margin="0,0,0,12">
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="Auto"/>
                    </Grid.ColumnDefinitions>
                    <TextBlock Text="Issue Logger"
                               FontSize="19" FontWeight="Bold" VerticalAlignment="Center"/>
                    <StackPanel Grid.Column="1" Orientation="Horizontal"
                                VerticalAlignment="Center">
                        <Border x:Name="SnipPill" Background="#313244" CornerRadius="9"
                                Padding="10,4" Margin="0,0,8,0">
                            <TextBlock x:Name="SnipPillText" Text="Snipaste: checking..."
                                       Foreground="#A6ADC8" FontSize="11"/>
                        </Border>
                        <Button x:Name="ChangeFolderBtn" Content="Change Folder"
                                FontSize="11" Padding="10,5"/>
                    </StackPanel>
                </Grid>

                <!-- Path chip -->
                <Border Grid.Row="1" Background="#2A2A3C" CornerRadius="6"
                        Padding="10,5" Margin="0,0,0,10">
                    <TextBlock x:Name="PathChip" Text="No file configured"
                               Foreground="#A6ADC8" FontSize="11"
                               TextTrimming="CharacterEllipsis"/>
                </Border>

                <!-- Thumbnail + editing indicator -->
                <Border Grid.Row="2" Background="#2A2A3C" CornerRadius="6"
                        Padding="10" Margin="0,0,0,10">
                    <Grid>
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="80"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <Border Grid.Column="0" Background="#181825" CornerRadius="4"
                                Width="80" Height="80" HorizontalAlignment="Left">
                            <Grid>
                                <TextBlock x:Name="ThumbPlaceholder" Text="No image"
                                           Foreground="#6C7086" FontSize="10"
                                           HorizontalAlignment="Center" VerticalAlignment="Center"
                                           TextWrapping="Wrap" TextAlignment="Center"/>
                                <Image x:Name="ThumbImage" Stretch="Uniform" Visibility="Collapsed"/>
                            </Grid>
                        </Border>
                        <StackPanel Grid.Column="1" Margin="10,0,0,0" VerticalAlignment="Center">
                            <TextBlock x:Name="ThumbCaption"
                                       Text="Take a screenshot to begin, or click a saved issue to re-edit it."
                                       Foreground="#A6ADC8" FontSize="11" TextWrapping="Wrap"/>
                            <StackPanel Orientation="Horizontal" Margin="0,8,0,0">
                                <Button x:Name="SnipBtn" Content="Take Screenshot"
                                        FontSize="11" Padding="10,5"/>
                                <Button x:Name="CancelEditBtn" Content="Cancel edit"
                                        FontSize="10" Padding="8,5" Margin="8,0,0,0"
                                        Visibility="Collapsed"/>
                            </StackPanel>
                        </StackPanel>
                    </Grid>
                </Border>

                <!-- Dynamic fields (Comment + any user-added columns) -->
                <ScrollViewer Grid.Row="3"
                              VerticalScrollBarVisibility="Auto"
                              HorizontalScrollBarVisibility="Disabled"
                              Margin="0,0,0,8">
                    <StackPanel x:Name="FieldsPanel"/>
                </ScrollViewer>

                <Button Grid.Row="4" x:Name="AddFieldBtn" Content="+ Add Field"
                        HorizontalAlignment="Left" FontSize="11" Padding="10,5"
                        Margin="0,0,0,10"/>

                <!-- Status bar -->
                <Border Grid.Row="5" Background="#2A2A3C" CornerRadius="6"
                        Padding="10,6" Margin="0,0,0,12">
                    <TextBlock x:Name="StatusLabel"
                               Text="Ready &#x2014; take a screenshot, fill in the fields, then save."
                               Foreground="#A6ADC8" FontSize="11" TextWrapping="Wrap"/>
                </Border>

                <!-- Action buttons -->
                <Grid Grid.Row="6">
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="12"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>
                    <Button Grid.Column="0" x:Name="NewIssueBtn" Content="New Issue"/>
                    <Button Grid.Column="2" x:Name="SaveBtn" Content="Save Issue"
                            Background="#F0A500" Foreground="#1E1E2E" FontWeight="Bold"/>
                </Grid>
            </Grid>

            <!-- ═══ RIGHT: issues preview panel ═══ -->
            <Grid Grid.Column="2">
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="*"/>
                </Grid.RowDefinitions>

                <TextBlock Grid.Row="0" x:Name="PreviewHeader"
                           Text="Saved Issues  (0)"
                           FontSize="13" FontWeight="Bold" Margin="8,0,0,10"/>

                <ScrollViewer Grid.Row="1"
                              VerticalScrollBarVisibility="Auto"
                              HorizontalScrollBarVisibility="Disabled"
                              Margin="8,0,0,0">
                    <StackPanel x:Name="IssuesPanel"/>
                </ScrollViewer>
            </Grid>
        </Grid>
    </Grid>
</Window>""".replace(u'__STYLES__', _SHARED_STYLES)


# ═══════════════════════════════════════════════════════════════════════════
#  SHIFT-CLICK MODE  —  configure save folder
# ═══════════════════════════════════════════════════════════════════════════

def run_config():
    window     = XamlReader.Parse(CONFIG_XAML)
    path_disp  = window.FindName(u'PathDisplay')
    cfg_status = window.FindName(u'CfgStatus')
    browse_btn = window.FindName(u'BrowseBtn')
    save_btn   = window.FindName(u'SaveCfgBtn')
    cancel_btn = window.FindName(u'CancelCfgBtn')

    current = load_config() or u''
    state   = {u'folder': current}
    if current:
        path_disp.Text = xlsx_path_from(current)

    def on_browse(s, e):
        new = _pick_folder(state[u'folder'])
        if new:
            state[u'folder']      = new
            path_disp.Text        = xlsx_path_from(new)
            cfg_status.Text       = u''
            cfg_status.Foreground = _BR_SUBTEXT

    def on_save(s, e):
        if not state[u'folder']:
            cfg_status.Text       = u'Please select a folder first.'
            cfg_status.Foreground = _BR_WARN
            return
        save_config(state[u'folder'])
        window.Close()

    def on_cancel(s, e):
        window.Close()

    browse_btn.Click += on_browse
    save_btn.Click   += on_save
    cancel_btn.Click += on_cancel
    _push_frame(window)


# ═══════════════════════════════════════════════════════════════════════════
#  NORMAL CLICK MODE  —  issue logger
# ═══════════════════════════════════════════════════════════════════════════

def _show_no_config_prompt():
    XAML = (
        u'<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"'
        u'        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
        u'        Title="Issue Logger" Width="400" Height="160"'
        u'        ResizeMode="NoResize" WindowStartupLocation="CenterScreen"'
        u'        Background="#1E1E2E">'
        u'    <StackPanel Margin="24" VerticalAlignment="Center">'
        u'        <TextBlock Text="No save location configured."'
        u'                   Foreground="#F38BA8" FontSize="14" FontWeight="Bold"'
        u'                   Margin="0,0,0,8"/>'
        u'        <TextBlock Text="Shift+click the button to choose where to save Issue Logger.xlsx."'
        u'                   Foreground="#A6ADC8" FontSize="12" TextWrapping="Wrap"'
        u'                   Margin="0,0,0,18"/>'
        u'        <Button x:Name="OkBtn" Content="OK" Width="80" HorizontalAlignment="Right"'
        u'                Background="#313244" Foreground="#CDD6F4"'
        u'                BorderThickness="0" Padding="0,8" Cursor="Hand">'
        u'            <Button.Template><ControlTemplate TargetType="Button">'
        u'                <Border Background="{TemplateBinding Background}" CornerRadius="6"'
        u'                        Padding="{TemplateBinding Padding}">'
        u'                    <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>'
        u'                </Border>'
        u'            </ControlTemplate></Button.Template>'
        u'        </Button>'
        u'    </StackPanel>'
        u'</Window>'
    )
    w  = XamlReader.Parse(XAML)
    ok = w.FindName(u'OkBtn')
    ok.Click += lambda s, e: w.Close()
    _push_frame(w)


def run_logger():
    folder = load_config()
    if not folder:
        _show_no_config_prompt()
        return

    state = {
        u'path':          xlsx_path_from(folder),
        u'columns':       [u'Comment'],
        u'issues':        [],
        u'field_rows':    [],   # [{'name_box':TextBox, 'value_box':TextBox}, ...]
        u'pending_png':   None, # Array[Byte] of the screenshot staged for save
        u'editing_index': None, # index into state['issues'] being re-edited, or None
    }
    if File.Exists(state[u'path']):
        cols, iss = _read_xlsx(state[u'path'])
        if cols:
            state[u'columns'] = cols
        state[u'issues'] = iss

    # ── Find all named elements ──────────────────────────────────
    window            = XamlReader.Parse(LOGGER_XAML)
    path_chip         = window.FindName(u'PathChip')
    status_lbl        = window.FindName(u'StatusLabel')
    snip_btn          = window.FindName(u'SnipBtn')
    save_btn          = window.FindName(u'SaveBtn')
    snip_pill_txt     = window.FindName(u'SnipPillText')
    snip_pill         = window.FindName(u'SnipPill')
    change_folder     = window.FindName(u'ChangeFolderBtn')
    snip_warning      = window.FindName(u'SnipWarning')
    get_snip_btn      = window.FindName(u'GetSnipBtn')
    preview_header    = window.FindName(u'PreviewHeader')
    issues_panel      = window.FindName(u'IssuesPanel')
    fields_panel      = window.FindName(u'FieldsPanel')
    add_field_btn     = window.FindName(u'AddFieldBtn')
    thumb_image       = window.FindName(u'ThumbImage')
    thumb_placeholder = window.FindName(u'ThumbPlaceholder')
    thumb_caption     = window.FindName(u'ThumbCaption')
    cancel_edit_btn   = window.FindName(u'CancelEditBtn')
    new_issue_btn     = window.FindName(u'NewIssueBtn')

    # ── Helpers ──────────────────────────────────────────────────
    def set_status(msg, brush=None):
        status_lbl.Text       = msg
        status_lbl.Foreground = brush if brush else _BR_SUBTEXT

    def update_path_chip():
        n = len(state[u'issues'])
        path_chip.Text = u'{p}   ({n} issue{s})'.format(
            p=state[u'path'], n=n, s=u's' if n != 1 else u'')

    def set_thumbnail(png_bytes):
        bmp = _bytes_to_bitmap(png_bytes) if png_bytes else None
        if bmp is not None:
            thumb_image.Source           = bmp
            thumb_image.Visibility       = Visibility.Visible
            thumb_placeholder.Visibility = Visibility.Collapsed
        else:
            thumb_image.Source           = None
            thumb_image.Visibility       = Visibility.Collapsed
            thumb_placeholder.Visibility = Visibility.Visible

    def sync_column_names():
        """Pull any in-progress renames out of the title chips into state['columns']."""
        for i, fr in enumerate(state[u'field_rows']):
            if i < len(state[u'columns']):
                txt = fr[u'name_box'].Text.strip()
                if txt:
                    state[u'columns'][i] = txt

    def clear_field_values():
        for fr in state[u'field_rows']:
            fr[u'value_box'].Text = u''

    def load_field_values(values):
        for i, fr in enumerate(state[u'field_rows']):
            fr[u'value_box'].Text = values[i] if i < len(values) else u''

    def remove_column_everywhere(idx):
        state[u'columns'].pop(idx)
        for k, (ts, values, png) in enumerate(state[u'issues']):
            if idx < len(values):
                nv = list(values)
                nv.pop(idx)
                state[u'issues'][k] = (ts, nv, png)

    def rebuild_fields_ui():
        fields_panel.Children.Clear()
        state[u'field_rows'] = []
        for i, name in enumerate(state[u'columns']):
            def make_delete(i=i):
                def _del(s, e):
                    if len(state[u'columns']) <= 1:
                        set_status(u'At least one field must remain.', _BR_WARN)
                        return
                    sync_column_names()
                    was_editing = state[u'editing_index']
                    remove_column_everywhere(i)
                    rebuild_fields_ui()
                    if was_editing is not None:
                        ts, values, png = state[u'issues'][was_editing]
                        load_field_values(values)
                    rebuild_preview()
                    try:
                        File.WriteAllBytes(
                            state[u'path'], _build_xlsx(state[u'columns'], state[u'issues']))
                    except Exception as ex:
                        set_status(u'Field removed, but re-saving the file failed: ' + unicode(ex), _BR_WARN)
                return _del
            row, name_box, value_box = _make_field_row(name, u'', make_delete())
            fields_panel.Children.Add(row)
            state[u'field_rows'].append(
                {u'name_box': name_box, u'value_box': value_box})

    rebuild_fields_ui()

    def rebuild_preview():
        """Repopulate the right panel; newest issue shown first."""
        issues_panel.Children.Clear()
        n = len(state[u'issues'])
        preview_header.Text = u'Saved Issues  ({0})'.format(n)
        for i, (ts, values, png) in enumerate(reversed(state[u'issues'])):
            real_idx = n - 1 - i
            card = _make_issue_card(
                real_idx + 1, ts, state[u'columns'], values, png,
                lambda s, e, idx=real_idx: on_delete(idx),
                lambda s, e, idx=real_idx: on_edit(idx)
            )
            issues_panel.Children.Add(card)

    def reset_editing_state(msg=None, brush=None):
        state[u'editing_index'] = None
        state[u'pending_png']   = None
        set_thumbnail(None)
        clear_field_values()
        thumb_caption.Text         = u'Take a screenshot to begin, or click a saved issue to re-edit it.'
        cancel_edit_btn.Visibility = Visibility.Collapsed
        save_btn.Content           = u'Save Issue'
        if msg:
            set_status(msg, brush)

    def on_delete(idx):
        deleted = state[u'issues'][idx]
        state[u'issues'].pop(idx)
        try:
            File.WriteAllBytes(state[u'path'], _build_xlsx(state[u'columns'], state[u'issues']))
            if state[u'editing_index'] == idx:
                reset_editing_state()
            elif state[u'editing_index'] is not None and state[u'editing_index'] > idx:
                state[u'editing_index'] -= 1
            rebuild_preview()
            update_path_chip()
            set_status(u'Issue #{0} deleted.'.format(idx + 1))
        except Exception as ex:
            state[u'issues'].insert(idx, deleted)   # rollback
            rebuild_preview()
            set_status(
                u'Delete failed \u2014 is the file open in Excel?  ' + unicode(ex),
                _BR_WARN)

    def on_edit(idx):
        sync_column_names()
        ts, values, png          = state[u'issues'][idx]
        state[u'editing_index']  = idx
        state[u'pending_png']    = png
        set_thumbnail(png)
        load_field_values(values)
        thumb_caption.Text         = (
            u'Editing Issue #{0} \u2014 take a new screenshot to replace it, '
            u'then press Update.'.format(idx + 1))
        cancel_edit_btn.Visibility = Visibility.Visible
        save_btn.Content           = u'Update Issue #{0}'.format(idx + 1)
        set_status(u'Editing Issue #{0}. Make your changes and press Update.'.format(idx + 1))

    cancel_edit_btn.Click += lambda s, e: reset_editing_state(u'Edit cancelled.')
    new_issue_btn.Click   += lambda s, e: reset_editing_state(u'Started a new issue \u2014 fields are cleared.')

    # ── Snipaste status ──────────────────────────────────────────
    if SNIPASTE_PATH:
        snip_pill_txt.Text       = u'Snipaste: found'
        snip_pill_txt.Foreground = _BR_SUCCESS
        snip_pill.Background     = SolidColorBrush(Color.FromRgb(0x1E, 0x35, 0x27))
    else:
        snip_pill_txt.Text       = u'Snipaste: not found'
        snip_pill_txt.Foreground = _BR_WARN
        snip_pill.Background     = SolidColorBrush(Color.FromRgb(0x35, 0x1A, 0x22))
        snip_warning.Visibility  = Visibility.Visible
        snip_btn.IsEnabled       = False

    # ── Initial population ───────────────────────────────────────
    update_path_chip()
    rebuild_preview()

    # ── Get Snipaste from Microsoft Store ────────────────────────
    def on_get_snipaste(s, e):
        try:
            psi                = ProcessStartInfo()
            psi.FileName       = u'ms-windows-store://pdp/?ProductId=9P1WXPKB68KX'
            psi.UseShellExecute = True
            Process.Start(psi)
        except Exception as ex:
            set_status(u'Could not open Microsoft Store: ' + unicode(ex), _BR_WARN)

    get_snip_btn.Click += on_get_snipaste

    # ── Change Folder ────────────────────────────────────────────
    def on_change_folder(s, e):
        new = _pick_folder(os.path.dirname(state[u'path']))
        if not new:
            return
        save_config(new)
        state[u'path'] = xlsx_path_from(new)
        if File.Exists(state[u'path']):
            cols, iss = _read_xlsx(state[u'path'])
            state[u'columns'] = cols if cols else [u'Comment']
            state[u'issues']  = iss
        else:
            state[u'columns'] = [u'Comment']
            state[u'issues']  = []
        rebuild_fields_ui()
        reset_editing_state()
        update_path_chip()
        rebuild_preview()
        set_status(u'Folder updated \u2014 {0} issue(s) loaded.'.format(
            len(state[u'issues'])))

    change_folder.Click += on_change_folder

    # ── Take Screenshot ──────────────────────────────────────────
    # Note: when Snipaste is already running in the background, invoking
    # "Snipaste.exe snip" just relays the command to that instance and the
    # spawned process exits almost immediately -- long before the user has
    # actually drawn a selection. Waiting on proc.WaitForExit() therefore
    # captures the clipboard too early. Instead we clear the clipboard first
    # and poll (on an STA thread, required for clipboard access) until a new
    # image actually lands there, so the thumbnail updates the moment the
    # screenshot is really taken.
    def on_snip(s, e):
        if not SNIPASTE_PATH:
            set_status(u'Snipaste not found \u2014 install it from the Microsoft Store.',
                       _BR_WARN)
            return
        window.Hide()
        try:
            WFClipboard.Clear()
        except Exception:
            pass

        proc                     = Process()
        proc.StartInfo.FileName  = SNIPASTE_PATH
        proc.StartInfo.Arguments = u'snip'
        proc.Start()

        def watch():
            found = None
            for _ in range(300):            # ~60s timeout (300 * 200ms)
                Thread.Sleep(200)
                try:
                    if WFClipboard.ContainsImage():
                        found = clipboard_to_png()
                        if found is not None:
                            break
                except Exception:
                    pass

            def restore():
                window.Show()
                if found is not None:
                    state[u'pending_png'] = found
                    set_thumbnail(found)
                    set_status(u'Screenshot captured \u2014 fill in the fields and save.',
                               _BR_SUCCESS)
                else:
                    set_status(u'No screenshot captured \u2014 the snip was cancelled or timed out.',
                               _BR_WARN)
            window.Dispatcher.Invoke(Action(restore))

        t = Thread(ThreadStart(watch))
        t.IsBackground = True
        t.SetApartmentState(ApartmentState.STA)
        t.Start()

    snip_btn.Click += on_snip

    # ── Add Field (+) ───────────────────────────────────────────
    def on_add_field(s, e):
        sync_column_names()
        state[u'columns'].append(u'Field {0}'.format(len(state[u'columns']) + 1))
        rebuild_fields_ui()
        if state[u'editing_index'] is not None:
            ts, values, png = state[u'issues'][state[u'editing_index']]
            load_field_values(values)
        try:
            last = state[u'field_rows'][-1][u'name_box']
            last.Focus()
            last.SelectAll()
        except Exception:
            pass

    add_field_btn.Click += on_add_field

    # ── Save / Update Issue ────────────────────────────────────────
    def on_save(s, e):
        values = [fr[u'value_box'].Text.strip() for fr in state[u'field_rows']]
        sync_column_names()
        if not any(v for v in values):
            set_status(u'Please fill in at least one field before saving.', _BR_WARN)
            return
        png = state[u'pending_png']
        if png is None:
            set_status(u'No screenshot captured \u2014 take one first.', _BR_WARN)
            return

        editing   = state[u'editing_index']
        prev_item = state[u'issues'][editing] if editing is not None else None
        if editing is not None:
            ts = prev_item[0]
            state[u'issues'][editing] = (ts, values, png)
        else:
            ts = DateTime.Now.ToString(u'yyyy-MM-dd HH:mm:ss')
            state[u'issues'].append((ts, values, png))

        try:
            File.WriteAllBytes(state[u'path'], _build_xlsx(state[u'columns'], state[u'issues']))
            n = len(state[u'issues'])
            reset_editing_state()
            rebuild_preview()
            update_path_chip()
            if editing is not None:
                set_status(u'Issue #{0} updated \u2192 {1}'.format(editing + 1, state[u'path']),
                           _BR_SUCCESS)
            else:
                set_status(u'Issue #{0} saved \u2192 {1}'.format(n, state[u'path']), _BR_SUCCESS)
        except Exception as ex:
            if editing is not None:
                state[u'issues'][editing] = prev_item   # rollback
            else:
                state[u'issues'].pop()
            set_status(
                u'Save failed \u2014 is the file open in Excel?  ' + unicode(ex),
                _BR_WARN)

    save_btn.Click += on_save

    _push_frame(window)


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

try:
    _is_shift = __shiftclick__
except NameError:
    _is_shift = False

if _is_shift:
    run_config()
else:
    run_logger()