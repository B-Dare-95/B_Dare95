# -*- coding: utf-8 -*-
"""
Issue Logger  ·  pyRevit / IronPython 2.7
==========================================
Normal click   → run the issue logger window
Shift+click    → configure the save folder

Replaces:
  WinForms UI  → WPF  (XamlReader.Parse, Catppuccin Mocha theme)
  COM / Excel  → zero-dependency xlsx  (ZipArchive + raw XML strings)
  PIL          → System.Windows.Clipboard + PngBitmapEncoder
  subprocess   → System.Diagnostics.Process
  threading    → System.Threading.Thread
"""
import clr
import os

clr.AddReference('System.Drawing')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Xml')
clr.AddReference('System.IO.Compression')
clr.AddReference('System')


from System.Windows.Markup        import XamlReader
from System.Windows               import Clipboard
from System.Windows.Media         import SolidColorBrush, Color
from System.Windows.Media.Imaging import PngBitmapEncoder, BitmapFrame
from System.Windows.Threading     import DispatcherFrame, Dispatcher
from System.IO                    import File, FileStream, FileMode, MemoryStream, StreamReader
from System.IO.Compression        import ZipArchive, ZipArchiveMode
from System.Diagnostics           import Process
from System.Windows.Forms         import FolderBrowserDialog, DialogResult as WFDialogResult
from System.Drawing.Imaging       import ImageFormat
from System.Windows.Forms         import Clipboard as WFClipboard
from System.Threading             import Thread, ThreadStart
from System                       import Array, Byte, Action, DateTime
from System.Text                  import Encoding
import System.Xml as SysXml


# ═══════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE   = os.path.join(SCRIPT_DIR, u'issue_logger.cfg')
XLSX_FILENAME = u'Issue Logger.xlsx'
_EMU_PX       = 9525   # 1 pixel @ 96 dpi in EMU

# Catppuccin Mocha status brushes
_BR_SUBTEXT  = SolidColorBrush(Color.FromRgb(0xA6, 0xAD, 0xC8))
_BR_SUCCESS  = SolidColorBrush(Color.FromRgb(0xA6, 0xE3, 0xA1))
_BR_WARN     = SolidColorBrush(Color.FromRgb(0xF3, 0x8B, 0xA8))


# ═══════════════════════════════════════════════════════════════
#  SNIPASTE AUTO-DETECTION
# ═══════════════════════════════════════════════════════════════

def find_snipaste():
    """Search common Snipaste installation locations. Returns path or None."""
    env = os.environ
    candidates = [
        # Microsoft Store / WindowsApps (most common)
        os.path.join(env.get(u'LOCALAPPDATA', u''),
                     u'Microsoft', u'WindowsApps', u'Snipaste.exe'),
        # Manual install – Program Files
        os.path.join(env.get(u'PROGRAMFILES',    u''), u'Snipaste', u'Snipaste.exe'),
        os.path.join(env.get(u'PROGRAMFILES(X86)', u''), u'Snipaste', u'Snipaste.exe'),
        os.path.join(env.get(u'PROGRAMW6432',    u''), u'Snipaste', u'Snipaste.exe'),
        # Scoop package manager
        os.path.join(env.get(u'USERPROFILE', u''),
                     u'scoop', u'apps', u'snipaste', u'current', u'Snipaste.exe'),
        # AppData local (some installs)
        os.path.join(env.get(u'LOCALAPPDATA', u''), u'Snipaste', u'Snipaste.exe'),
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    # Fall back: scan PATH
    for d in env.get(u'PATH', u'').split(u';'):
        p = os.path.join(d.strip(), u'Snipaste.exe')
        if os.path.isfile(p):
            return p
    return None


SNIPASTE_PATH = find_snipaste()


# ═══════════════════════════════════════════════════════════════
#  CONFIG PERSISTENCE  (plain-text, one line = folder path)
# ═══════════════════════════════════════════════════════════════

def load_config():
    """Return the configured save folder, or None."""
    if File.Exists(CONFIG_FILE):
        txt = File.ReadAllText(CONFIG_FILE, Encoding.UTF8).strip()
        if txt:
            return txt
    return None


def save_config(folder):
    File.WriteAllText(CONFIG_FILE, folder, Encoding.UTF8)


def xlsx_path_from(folder):
    return os.path.join(folder, XLSX_FILENAME)


# ═══════════════════════════════════════════════════════════════
#  CLIPBOARD  →  PNG bytes
# ═══════════════════════════════════════════════════════════════

def clipboard_to_png():
    """Return .NET Array[Byte] PNG from clipboard image, or None.
    Uses WinForms + GDI+ instead of WPF Clipboard to avoid the
    transparent-alpha bug with pre-multiplied BitmapSource."""
    if not WFClipboard.ContainsImage():
        return None
    img = WFClipboard.GetImage()   # returns System.Drawing.Image
    if img is None:
        return None
    ms = MemoryStream()
    img.Save(ms, ImageFormat.Png)
    return ms.ToArray()


# ═══════════════════════════════════════════════════════════════
#  XLSX ENGINE  (zero-dependency — no openpyxl, no Excel)
# ═══════════════════════════════════════════════════════════════

def _esc(text):
    """XML-escape a string value."""
    return (unicode(text)
            .replace(u'&', u'&amp;').replace(u'<', u'&lt;')
            .replace(u'>', u'&gt;') .replace(u'"', u'&quot;')
            .replace(u"'", u'&apos;'))


def _build_xlsx(issues):
    """
    Build an xlsx file from scratch.
    issues : [(timestamp:str, comment:str, png:Array[Byte]|None), ...]
    Returns  Array[Byte]  — write with File.WriteAllBytes().
    """
    out = MemoryStream()
    za  = ZipArchive(out, ZipArchiveMode.Create, True)

    def wt(name, xml_str):
        """Write a UTF-8 text entry into the zip."""
        e   = za.CreateEntry(name)
        s   = e.Open()
        raw = Encoding.UTF8.GetBytes(xml_str)
        s.Write(raw, 0, raw.Length)
        s.Dispose()

    def wb(name, data):
        """Write a binary entry (e.g. PNG) into the zip."""
        e = za.CreateEntry(name)
        s = e.Open()
        s.Write(data, 0, data.Length)
        s.Dispose()

    has_img = any(img is not None for _, _, img in issues)

    # ── [Content_Types].xml ─────────────────────────────────────
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
       u'</Types>'
    )

    # ── _rels/.rels ─────────────────────────────────────────────
    wt(u'_rels/.rels',
       u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
       u'<Relationship Id="rId1"'
       u' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
       u' Target="xl/workbook.xml"/>'
       u'</Relationships>'
    )

    # ── xl/workbook.xml ─────────────────────────────────────────
    wt(u'xl/workbook.xml',
       u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       u'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
       u' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
       u'<sheets><sheet name="Issues" sheetId="1" r:id="rId1"/></sheets>'
       u'</workbook>'
    )

    # ── xl/_rels/workbook.xml.rels ──────────────────────────────
    wt(u'xl/_rels/workbook.xml.rels',
       u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
       u'<Relationship Id="rId1"'
       u' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
       u' Target="worksheets/sheet1.xml"/>'
       u'<Relationship Id="rId2"'
       u' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"'
       u' Target="styles.xml"/>'
       u'</Relationships>'
    )

    # ── xl/styles.xml  (minimal – Calibri 11pt) ─────────────────
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
       u'</styleSheet>'
    )

    # ── xl/worksheets/sheet1.xml ────────────────────────────────
    ROW_H = 135   # row height in points  ≈ 170 px @ 96 dpi
    rows  = [
        u'<row r="1">'
        u'<c r="A1" t="inlineStr"><is><t>Timestamp</t></is></c>'
        u'<c r="B1" t="inlineStr"><is><t>Comment</t></is></c>'
        u'<c r="C1" t="inlineStr"><is><t>Screenshot</t></is></c>'
        u'</row>'
    ]
    for i, (ts, cmt, _) in enumerate(issues):
        rn = i + 2
        rows.append(
            u'<row r="{r}" ht="{h}" customHeight="1">'
            u'<c r="A{r}" t="inlineStr"><is><t>{ts}</t></is></c>'
            u'<c r="B{r}" t="inlineStr"><is><t>{cmt}</t></is></c>'
            u'</row>'.format(r=rn, h=ROW_H, ts=_esc(ts), cmt=_esc(cmt))
        )

    # r namespace is only needed when a <drawing> tag references rId1
    sheet_r_ns = (u' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
                  if has_img else u'')
    wt(u'xl/worksheets/sheet1.xml',
       u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
       + sheet_r_ns + u'>'
       u'<sheetFormatPr defaultRowHeight="15"/>'
       u'<cols>'
       u'<col min="1" max="1" width="22" customWidth="1"/>'
       u'<col min="2" max="2" width="50" customWidth="1"/>'
       u'<col min="3" max="3" width="45" customWidth="1"/>'
       u'</cols>'
       u'<sheetData>' + u''.join(rows) + u'</sheetData>'
       + (u'<drawing r:id="rId1"/>' if has_img else u'') +
       u'</worksheet>'
    )

    # ── xl/worksheets/_rels/sheet1.xml.rels  (only if images) ───
    if has_img:
        wt(u'xl/worksheets/_rels/sheet1.xml.rels',
           u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           u'<Relationship Id="rId1"'
           u' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"'
           u' Target="../drawings/drawing1.xml"/>'
           u'</Relationships>'
        )

    # ── Images + drawing XML ────────────────────────────────────
    if has_img:
        anchors  = []
        img_rels = []
        n        = 1

        for i, (_, _, png) in enumerate(issues):
            if png is None:
                continue

            # Row index is 0-based in xlsx drawing coords.
            # Header occupies row-index 0; first data row is row-index 1.
            row0 = i + 1
            cx   = _EMU_PX * 300   # 300 px wide
            cy   = _EMU_PX * 170   # 170 px tall
            rid  = u'rId{0}'.format(n)

            wb(u'xl/media/image{0}.png'.format(n), png)

            img_rels.append(
                u'<Relationship Id="{rid}"'
                u' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"'
                u' Target="../media/image{n}.png"/>'.format(rid=rid, n=n)
            )
            anchors.append(
                u'<xdr:oneCellAnchor>'
                u'<xdr:from>'
                u'<xdr:col>2</xdr:col><xdr:colOff>0</xdr:colOff>'
                u'<xdr:row>{r}</xdr:row><xdr:rowOff>0</xdr:rowOff>'
                u'</xdr:from>'
                u'<xdr:ext cx="{cx}" cy="{cy}"/>'
                u'<xdr:pic>'
                u'<xdr:nvPicPr>'
                u'<xdr:cNvPr id="{n}" name="Picture {n}"/>'
                u'<xdr:cNvPicPr/>'
                u'</xdr:nvPicPr>'
                u'<xdr:blipFill>'
                u'<a:blip r:embed="{rid}"/>'
                u'<a:stretch><a:fillRect/></a:stretch>'
                u'</xdr:blipFill>'
                u'<xdr:spPr>'
                u'<a:xfrm><a:off x="0" y="0"/>'
                u'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
                u'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
                u'</xdr:spPr>'
                u'</xdr:pic>'
                u'<xdr:clientData/>'
                u'</xdr:oneCellAnchor>'.format(r=row0, cx=cx, cy=cy, n=n, rid=rid)
            )
            n += 1

        wt(u'xl/drawings/drawing1.xml',
           u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           u'<xdr:wsDr'
           u' xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"'
           u' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
           u' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
           + u''.join(anchors) +
           u'</xdr:wsDr>'
        )
        wt(u'xl/drawings/_rels/drawing1.xml.rels',
           u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           + u''.join(img_rels) +
           u'</Relationships>'
        )

    za.Dispose()
    return out.ToArray()


def _read_xlsx(path):
    """
    Read an existing xlsx file built by _build_xlsx.
    Returns [(timestamp, comment, png_bytes_or_None), ...].
    Returns [] silently on any read error.
    """
    issues = []
    fs     = None
    za     = None
    try:
        fs = FileStream(path, FileMode.Open)
        za = ZipArchive(fs, ZipArchiveMode.Read)

        # ── Sheet text data ──────────────────────────────────────
        se = za.GetEntry(u'xl/worksheets/sheet1.xml')
        if se is None:
            return issues
        sr       = StreamReader(se.Open(), Encoding.UTF8)
        sheet_xml = sr.ReadToEnd()
        sr.Dispose()

        sdoc = SysXml.XmlDocument()
        sdoc.LoadXml(sheet_xml)
        sns = SysXml.XmlNamespaceManager(sdoc.NameTable)
        sns.AddNamespace(u'ss', u'http://schemas.openxmlformats.org/spreadsheetml/2006/main')

        rows_data = {}   # row_num (int) → (timestamp, comment)
        for row_nd in sdoc.SelectNodes(u'//ss:row', sns):
            rn = int(row_nd.GetAttribute(u'r') or u'0')
            if rn < 2:
                continue   # skip header row
            vals = {}
            for c in row_nd.SelectNodes(u'ss:c', sns):
                ref = c.GetAttribute(u'r')
                if not ref:
                    continue
                col    = ref[0]
                t_list = c.SelectNodes(u'ss:is/ss:t', sns)
                if t_list.Count > 0:
                    vals[col] = t_list.Item(0).InnerText
            rows_data[rn] = (vals.get(u'A', u''), vals.get(u'B', u''))

        # ── Drawing XML: rId → 1-based row number ───────────────
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
                    row0  = int(rn_nd.InnerText)
                    embed = blip.GetAttribute(u'embed', REL_NS)
                    if embed:
                        rid_to_rn[embed] = row0 + 1   # convert 0-based → 1-based

        # ── Drawing rels: rId → media zip path ──────────────────
        rid_to_media = {}
        re_ent = za.GetEntry(u'xl/drawings/_rels/drawing1.xml.rels')
        if re_ent is not None:
            rr       = StreamReader(re_ent.Open(), Encoding.UTF8)
            rels_xml = rr.ReadToEnd()
            rr.Dispose()

            rdoc = SysXml.XmlDocument()
            rdoc.LoadXml(rels_xml)
            rns  = SysXml.XmlNamespaceManager(rdoc.NameTable)
            rns.AddNamespace(u'rel', u'http://schemas.openxmlformats.org/package/2006/relationships')

            for rel in rdoc.SelectNodes(u'//rel:Relationship', rns):
                rid    = rel.GetAttribute(u'Id')
                target = rel.GetAttribute(u'Target')
                # Target = '../media/imageN.png' → normalise to 'xl/media/imageN.png'
                rid_to_media[rid] = u'xl/media/' + target.split(u'/')[-1]

        # ── Load image bytes per row ─────────────────────────────
        img_by_rn = {}
        for rid, rn in rid_to_rn.items():
            media = rid_to_media.get(rid)
            if not media:
                continue
            img_ent = za.GetEntry(media)
            if img_ent is None:
                continue
            ms  = MemoryStream()
            ies = img_ent.Open()
            buf = Array.CreateInstance(Byte, 8192)
            while True:
                n = ies.Read(buf, 0, buf.Length)
                if n == 0:
                    break
                ms.Write(buf, 0, n)
            ies.Dispose()
            img_by_rn[rn] = ms.ToArray()

        # ── Assemble in row order ────────────────────────────────
        for rn in sorted(rows_data.keys()):
            ts, cmt = rows_data[rn]
            issues.append((ts, cmt, img_by_rn.get(rn)))

    except Exception as ex:
        print(u'[IssueLogger] _read_xlsx error: ' + unicode(ex))
        issues = []
    finally:
        if za:  za.Dispose()
        if fs:  fs.Dispose()

    return issues


# ═══════════════════════════════════════════════════════════════
#  SHARED WPF HELPERS
# ═══════════════════════════════════════════════════════════════

def _pick_folder(initial=u''):
    """Show WinForms FolderBrowserDialog. Returns path string or None."""
    dlg = FolderBrowserDialog()
    dlg.Description         = u'Select folder for Issue Logger.xlsx'
    dlg.ShowNewFolderButton = True
    if initial and os.path.isdir(initial):
        dlg.SelectedPath = initial
    return dlg.SelectedPath if dlg.ShowDialog() == WFDialogResult.OK else None


def _push_frame(window):
    """Show a WPF window modeless, block the pyRevit script thread via PushFrame."""
    frame = [DispatcherFrame()]

    def on_close(s, e):
        frame[0].Continue = False

    window.Closed += on_close
    window.Show()
    Dispatcher.PushFrame(frame[0])


# ═══════════════════════════════════════════════════════════════
#  SHARED BUTTON / TEXTBOX STYLE  (injected into both windows)
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
#  CONFIG WINDOW XAML  (shift-click)
# ═══════════════════════════════════════════════════════════════

CONFIG_XAML = (
    u'<Window'
    u'    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"'
    u'    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
    u'    Title="Issue Logger \u2014 Configure Save Location"'
    u'    Width="520" Height="200"'
    u'    ResizeMode="NoResize"'
    u'    WindowStartupLocation="CenterScreen"'
    u'    Background="#1E1E2E">'
    + _SHARED_STYLES +
    u'    <Grid Margin="20,16,20,16">'
    u'        <Grid.RowDefinitions>'
    u'            <RowDefinition Height="Auto"/>'
    u'            <RowDefinition Height="Auto"/>'
    u'            <RowDefinition Height="*"/>'
    u'            <RowDefinition Height="Auto"/>'
    u'        </Grid.RowDefinitions>'

    # Title
    u'        <TextBlock Grid.Row="0"'
    u'                   Text="Configure Save Location"'
    u'                   FontSize="17" FontWeight="Bold"'
    u'                   Margin="0,0,0,14"/>'

    # Path row: chip + Browse button
    u'        <Grid Grid.Row="1" Margin="0,0,0,8">'
    u'            <Grid.ColumnDefinitions>'
    u'                <ColumnDefinition Width="*"/>'
    u'                <ColumnDefinition Width="10"/>'
    u'                <ColumnDefinition Width="Auto"/>'
    u'            </Grid.ColumnDefinitions>'
    u'            <Border Grid.Column="0" Background="#2A2A3C" CornerRadius="6" Padding="10,7">'
    u'                <TextBlock x:Name="PathDisplay"'
    u'                           Text="(not configured)"'
    u'                           Foreground="#A6ADC8" FontSize="12"'
    u'                           TextTrimming="CharacterEllipsis"'
    u'                           VerticalAlignment="Center"/>'
    u'            </Border>'
    u'            <Button Grid.Column="2" x:Name="BrowseBtn"'
    u'                    Content="Browse..."'
    u'                    Padding="12,7"/>'
    u'        </Grid>'

    # Inline status text
    u'        <TextBlock Grid.Row="2" x:Name="CfgStatus"'
    u'                   Text=" " Foreground="#A6ADC8" FontSize="11"'
    u'                   VerticalAlignment="Center"/>'

    # Save & Cancel
    u'        <Grid Grid.Row="3">'
    u'            <Grid.ColumnDefinitions>'
    u'                <ColumnDefinition Width="*"/>'
    u'                <ColumnDefinition Width="10"/>'
    u'                <ColumnDefinition Width="Auto"/>'
    u'            </Grid.ColumnDefinitions>'
    u'            <Button Grid.Column="0" x:Name="SaveCfgBtn"'
    u'                    Content="Save &amp; Close"'
    u'                    Background="#F0A500"'
    u'                    Foreground="#1E1E2E"'
    u'                    FontWeight="Bold"/>'
    u'            <Button Grid.Column="2" x:Name="CancelCfgBtn"'
    u'                    Content="Cancel"'
    u'                    Padding="18,9"/>'
    u'        </Grid>'
    u'    </Grid>'
    u'</Window>'
)


# ═══════════════════════════════════════════════════════════════
#  LOGGER WINDOW XAML  (normal click)
# ═══════════════════════════════════════════════════════════════

LOGGER_XAML = (
    u'<Window'
    u'    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"'
    u'    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
    u'    Title="Issue Logger"'
    u'    Width="600" Height="450"'
    u'    MinWidth="460" MinHeight="350"'
    u'    WindowStartupLocation="CenterScreen"'
    u'    Background="#1E1E2E"'
    u'    ResizeMode="CanResize">'
    + _SHARED_STYLES +
    u'    <Grid Margin="20,16,20,16">'
    u'        <Grid.RowDefinitions>'
    u'            <RowDefinition Height="Auto"/>'   # title row
    u'            <RowDefinition Height="Auto"/>'   # path chip
    u'            <RowDefinition Height="*"/>'      # comment box
    u'            <RowDefinition Height="Auto"/>'   # status bar
    u'            <RowDefinition Height="Auto"/>'   # action buttons
    u'        </Grid.RowDefinitions>'

    # ── Title row ────────────────────────────────────────────────
    u'        <Grid Grid.Row="0" Margin="0,0,0,12">'
    u'            <Grid.ColumnDefinitions>'
    u'                <ColumnDefinition Width="*"/>'
    u'                <ColumnDefinition Width="Auto"/>'
    u'            </Grid.ColumnDefinitions>'
    u'            <TextBlock Text="Issue Logger"'
    u'                       FontSize="19" FontWeight="Bold"'
    u'                       VerticalAlignment="Center"/>'
    u'            <StackPanel Grid.Column="1" Orientation="Horizontal"'
    u'                        VerticalAlignment="Center">'
    # Snipaste status pill (non-interactive)
    u'                <Border x:Name="SnipPill"'
    u'                        Background="#313244" CornerRadius="9"'
    u'                        Padding="10,4" Margin="0,0,8,0">'
    u'                    <TextBlock x:Name="SnipPillText"'
    u'                               Text="Snipaste: checking..."'
    u'                               Foreground="#A6ADC8" FontSize="11"/>'
    u'                </Border>'
    u'                <Button x:Name="ChangeFolderBtn"'
    u'                        Content="Change Folder"'
    u'                        FontSize="11" Padding="10,5"/>'
    u'            </StackPanel>'
    u'        </Grid>'

    # ── Save path chip ───────────────────────────────────────────
    u'        <Border Grid.Row="1" Background="#2A2A3C" CornerRadius="6"'
    u'                Padding="10,5" Margin="0,0,0,10">'
    u'            <TextBlock x:Name="PathChip"'
    u'                       Text="No file configured"'
    u'                       Foreground="#A6ADC8" FontSize="11"'
    u'                       TextTrimming="CharacterEllipsis"/>'
    u'        </Border>'

    # ── Comment text box ─────────────────────────────────────────
    u'        <TextBox Grid.Row="2"'
    u'                 x:Name="CommentBox"'
    u'                 AcceptsReturn="True"'
    u'                 TextWrapping="Wrap"'
    u'                 VerticalScrollBarVisibility="Auto"'
    u'                 VerticalContentAlignment="Top"'
    u'                 Margin="0,0,0,10"/>'

    # ── Status bar ───────────────────────────────────────────────
    u'        <Border Grid.Row="3" Background="#2A2A3C" CornerRadius="6"'
    u'                Padding="10,6" Margin="0,0,0,12">'
    u'            <TextBlock x:Name="StatusLabel"'
    u'                       Text="Ready \u2014 take a screenshot, enter a comment, then save."'
    u'                       Foreground="#A6ADC8" FontSize="11"'
    u'                       TextWrapping="Wrap"/>'
    u'        </Border>'

    # ── Action buttons ───────────────────────────────────────────
    u'        <Grid Grid.Row="4">'
    u'            <Grid.ColumnDefinitions>'
    u'                <ColumnDefinition Width="*"/>'
    u'                <ColumnDefinition Width="12"/>'
    u'                <ColumnDefinition Width="*"/>'
    u'            </Grid.ColumnDefinitions>'
    u'            <Button Grid.Column="0" x:Name="SnipBtn"'
    u'                    Content="Take Screenshot"/>'
    u'            <Button Grid.Column="2" x:Name="SaveBtn"'
    u'                    Content="Save Issue"'
    u'                    Background="#F0A500"'
    u'                    Foreground="#1E1E2E"'
    u'                    FontWeight="Bold"/>'
    u'        </Grid>'
    u'    </Grid>'
    u'</Window>'
)


# ═══════════════════════════════════════════════════════════════
#  SHIFT-CLICK MODE  —  configure save folder
# ═══════════════════════════════════════════════════════════════

def run_config():
    window     = XamlReader.Parse(CONFIG_XAML)
    path_disp  = window.FindName(u'PathDisplay')
    cfg_status = window.FindName(u'CfgStatus')
    browse_btn = window.FindName(u'BrowseBtn')
    save_btn   = window.FindName(u'SaveCfgBtn')
    cancel_btn = window.FindName(u'CancelCfgBtn')

    current_folder = load_config() or u''
    state          = {u'folder': current_folder}

    if current_folder:
        path_disp.Text = xlsx_path_from(current_folder)

    def on_browse(s, e):
        new = _pick_folder(state[u'folder'])
        if new:
            state[u'folder'] = new
            path_disp.Text   = xlsx_path_from(new)
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


# ═══════════════════════════════════════════════════════════════
#  NORMAL CLICK MODE  —  issue logger
# ═══════════════════════════════════════════════════════════════

def _show_no_config_prompt():
    """Lightweight WPF nudge shown when no save path is configured yet."""
    XAML = (
        u'<Window'
        u'    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"'
        u'    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
        u'    Title="Issue Logger" Width="400" Height="160"'
        u'    ResizeMode="NoResize" WindowStartupLocation="CenterScreen"'
        u'    Background="#1E1E2E">'
        u'    <StackPanel Margin="24" VerticalAlignment="Center">'
        u'        <TextBlock Text="No save location configured."'
        u'                   Foreground="#F38BA8" FontSize="14" FontWeight="Bold"'
        u'                   Margin="0,0,0,8"/>'
        u'        <TextBlock'
        u'            Text="Shift+click the ribbon button to choose where to save Issue Logger.xlsx."'
        u'            Foreground="#A6ADC8" FontSize="12" TextWrapping="Wrap"'
        u'            Margin="0,0,0,18"/>'
        u'        <Button x:Name="OkBtn" Content="OK" Width="80"'
        u'                HorizontalAlignment="Right"'
        u'                Background="#313244" Foreground="#CDD6F4"'
        u'                BorderThickness="0" Padding="0,8" Cursor="Hand">'
        u'            <Button.Template>'
        u'                <ControlTemplate TargetType="Button">'
        u'                    <Border Background="{TemplateBinding Background}"'
        u'                            CornerRadius="6" Padding="{TemplateBinding Padding}">'
        u'                        <ContentPresenter HorizontalAlignment="Center"'
        u'                                          VerticalAlignment="Center"/>'
        u'                    </Border>'
        u'                </ControlTemplate>'
        u'            </Button.Template>'
        u'        </Button>'
        u'    </StackPanel>'
        u'</Window>'
    )
    w      = XamlReader.Parse(XAML)
    ok_btn = w.FindName(u'OkBtn')

    def on_ok(s, e):
        w.Close()

    ok_btn.Click += on_ok
    _push_frame(w)


def run_logger():
    folder = load_config()
    if not folder:
        _show_no_config_prompt()
        return

    state = {
        u'path':   xlsx_path_from(folder),
        u'issues': []
    }
    if File.Exists(state[u'path']):
        state[u'issues'] = _read_xlsx(state[u'path'])

    # ── Wire up window ───────────────────────────────────────────
    window        = XamlReader.Parse(LOGGER_XAML)
    path_chip     = window.FindName(u'PathChip')
    comment_box   = window.FindName(u'CommentBox')
    status_lbl    = window.FindName(u'StatusLabel')
    snip_btn      = window.FindName(u'SnipBtn')
    save_btn      = window.FindName(u'SaveBtn')
    snip_pill_txt = window.FindName(u'SnipPillText')
    snip_pill     = window.FindName(u'SnipPill')
    change_folder = window.FindName(u'ChangeFolderBtn')

    # ── Initial state ────────────────────────────────────────────
    def _update_path_chip():
        n = len(state[u'issues'])
        path_chip.Text = u'{p}   ({n} issue{s})'.format(
            p=state[u'path'], n=n, s=u's' if n != 1 else u''
        )

    _update_path_chip()

    if SNIPASTE_PATH:
        snip_pill_txt.Text       = u'Snipaste: found'
        snip_pill_txt.Foreground = _BR_SUCCESS
        snip_pill.Background     = SolidColorBrush(Color.FromRgb(0x1E, 0x35, 0x27))
    else:
        snip_pill_txt.Text       = u'Snipaste: not found'
        snip_pill_txt.Foreground = _BR_WARN
        snip_pill.Background     = SolidColorBrush(Color.FromRgb(0x35, 0x1A, 0x22))

    def set_status(msg, brush=None):
        status_lbl.Text       = msg
        status_lbl.Foreground = brush if brush else _BR_SUBTEXT

    # ── Change Folder button ─────────────────────────────────────
    def on_change_folder(s, e):
        new = _pick_folder(os.path.dirname(state[u'path']))
        if not new:
            return
        save_config(new)
        state[u'path']   = xlsx_path_from(new)
        state[u'issues'] = (_read_xlsx(state[u'path'])
                            if File.Exists(state[u'path']) else [])
        _update_path_chip()
        set_status(
            u'Folder updated  \u2014  {n} issue(s) loaded.'.format(
                n=len(state[u'issues']))
        )

    change_folder.Click += on_change_folder

    # ── Take Screenshot ──────────────────────────────────────────
    def on_snip(s, e):
        if not SNIPASTE_PATH:
            set_status(
                u'Snipaste not found. Install it or add it to PATH, then restart.',
                _BR_WARN
            )
            return

        window.Hide()

        proc = Process()
        proc.StartInfo.FileName  = SNIPASTE_PATH
        proc.StartInfo.Arguments = u'snip'
        proc.Start()

        def watch():
            proc.WaitForExit()
            def restore():
                window.Show()
                set_status(
                    u'Screenshot ready in clipboard  \u2014  enter a comment and save.',
                    _BR_SUCCESS
                )
            window.Dispatcher.Invoke(Action(restore))

        t = Thread(ThreadStart(watch))
        t.IsBackground = True
        t.Start()

    snip_btn.Click += on_snip

    # ── Save Issue ───────────────────────────────────────────────
    def on_save(s, e):
        cmt = comment_box.Text.strip()
        if not cmt:
            set_status(u'Please enter a comment before saving.', _BR_WARN)
            return

        png = clipboard_to_png()
        if png is None:
            set_status(
                u'No image in clipboard  \u2014  take a screenshot first.',
                _BR_WARN
            )
            return

        ts = DateTime.Now.ToString(u'yyyy-MM-dd HH:mm:ss')
        state[u'issues'].append((ts, cmt, png))

        try:
            File.WriteAllBytes(state[u'path'], _build_xlsx(state[u'issues']))
            comment_box.Clear()
            _update_path_chip()
            set_status(
                u'Issue #{n} saved  \u2192  {p}'.format(
                    n=len(state[u'issues']), p=state[u'path']),
                _BR_SUCCESS
            )
        except Exception as ex:
            state[u'issues'].pop()   # rollback in-memory
            set_status(
                u'Save failed  \u2014  is the file open in Excel?   ' + unicode(ex),
                _BR_WARN
            )

    save_btn.Click += on_save

    _push_frame(window)


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

try:
    _is_shift_click = __shiftclick__      # injected by pyRevit
except NameError:
    _is_shift_click = False

if _is_shift_click:
    run_config()
else:
    run_logger()