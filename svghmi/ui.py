#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of Beremiz
# Copyright (C) 2021: Edouard TISSERANT
#
# See COPYING file for copyrights details.

from __future__ import absolute_import
import os
import hashlib
import weakref
from tempfile import NamedTemporaryFile

import wx
from wx.lib.scrolledpanel import ScrolledPanel

from lxml import etree
from lxml.etree import XSLTApplyError
from XSLTransform import XSLTransform

import util.paths as paths
from IDEFrame import EncodeFileSystemPath, DecodeFileSystemPath
from docutil import get_inkscape_path

from util.ProcessLogger import ProcessLogger

ScriptDirectory = paths.AbsDir(__file__)

HMITreeDndMagicWord = "text/beremiz-hmitree"

class HMITreeSelector(wx.TreeCtrl):
    def __init__(self, parent):

        wx.TreeCtrl.__init__(self, parent, style=(
            wx.TR_MULTIPLE |
            wx.TR_HAS_BUTTONS |
            wx.SUNKEN_BORDER |
            wx.TR_LINES_AT_ROOT))

        self.ordered_items = []
        self.parent = parent

        self.MakeTree()

        self.Bind(wx.EVT_TREE_SEL_CHANGED, self.OnTreeNodeSelection)
        self.Bind(wx.EVT_TREE_BEGIN_DRAG, self.OnTreeBeginDrag)

    def _recurseTree(self, current_hmitree_root, current_tc_root):
        for c in current_hmitree_root.children:
            if hasattr(c, "children"):
                display_name = ('{} (class={})'.format(c.name, c.hmiclass)) \
                               if c.hmiclass is not None else c.name
                tc_child = self.AppendItem(current_tc_root, display_name)
                self.SetPyData(tc_child, c)

                self._recurseTree(c,tc_child)
            else:
                display_name = '{} {}'.format(c.nodetype[4:], c.name)
                tc_child = self.AppendItem(current_tc_root, display_name)
                self.SetPyData(tc_child, c)

    def OnTreeNodeSelection(self, event):
        items = self.GetSelections()
        items_pydata = [self.GetPyData(item) for item in items]

        # append new items to ordered item list
        for item_pydata in items_pydata:
            if item_pydata not in self.ordered_items:
                self.ordered_items.append(item_pydata)

        # filter out vanished items
        self.ordered_items = [
            item_pydata 
            for item_pydata in self.ordered_items 
            if item_pydata in items_pydata]

        self.parent.OnHMITreeNodeSelection(self.ordered_items)

    def OnTreeBeginDrag(self, event):
        """
        Called when a drag is started in tree
        @param event: wx.TreeEvent
        """
        if self.ordered_items:
            print("boink")
            # Just send a recognizable mime-type, drop destination
            # will get python data from parent
            data = wx.CustomDataObject(HMITreeDndMagicWord)
            dragSource = wx.DropSource(self)
            dragSource.SetData(data)
            dragSource.DoDragDrop()

    def MakeTree(self, hmi_tree_root=None):

        self.Freeze()

        self.root = None
        self.DeleteAllItems()

        root_display_name = _("Please build to see HMI Tree") \
            if hmi_tree_root is None else "HMI"
        self.root = self.AddRoot(root_display_name)
        self.SetPyData(self.root, hmi_tree_root)

        if hmi_tree_root is not None:
            self._recurseTree(hmi_tree_root, self.root)
            self.Expand(self.root)

        self.Thaw()

class WidgetPicker(wx.TreeCtrl):
    def __init__(self, parent, initialdir=None):
        wx.TreeCtrl.__init__(self, parent, style=(
            wx.TR_MULTIPLE |
            wx.TR_HAS_BUTTONS |
            wx.SUNKEN_BORDER |
            wx.TR_LINES_AT_ROOT))

        self.MakeTree(initialdir)

    def _recurseTree(self, current_dir, current_tc_root, dirlist):
        """
        recurse through subdirectories, but creates tree nodes 
        only when (sub)directory conbtains .svg file
        """
        res = []
        for f in sorted(os.listdir(current_dir)):
            p = os.path.join(current_dir,f)
            if os.path.isdir(p):

                r = self._recurseTree(p, current_tc_root, dirlist + [f])
                if len(r) > 0 :
                    res = r
                    dirlist = []
                    current_tc_root = res.pop()

            elif os.path.splitext(f)[1].upper() == ".SVG":
                if len(dirlist) > 0 :
                    res = []
                    for d in dirlist:
                        current_tc_root = self.AppendItem(current_tc_root, d)
                        res.append(current_tc_root)
                        self.SetPyData(current_tc_root, None)
                    dirlist = []
                    res.pop()
                tc_child = self.AppendItem(current_tc_root, f)
                self.SetPyData(tc_child, p)
        return res

    def MakeTree(self, lib_dir = None):

        self.Freeze()

        self.root = None
        self.DeleteAllItems()

        root_display_name = _("Please select widget library directory") \
            if lib_dir is None else os.path.basename(lib_dir)
        self.root = self.AddRoot(root_display_name)
        self.SetPyData(self.root, None)

        if lib_dir is not None:
            self._recurseTree(lib_dir, self.root, [])
            self.Expand(self.root)

        self.Thaw()

class PathDropTarget(wx.DropTarget):

    def __init__(self, parent):
        data = wx.CustomDataObject(HMITreeDndMagicWord)
        wx.DropTarget.__init__(self, data)
        self.ParentWindow = parent

    def OnDrop(self, x, y):
        self.ParentWindow.OnHMITreeDnD()
        return True

class ParamEditor(wx.Panel):
    def __init__(self, parent, paramdesc):

        wx.Panel.__init__(self, parent.main_panel)
        label = paramdesc.get("name")+ ": " + paramdesc.get("accepts") 
        if paramdesc.text:
            label += "\n\"" + paramdesc.text + "\""
        self.desc = wx.StaticText(self, label=label)
        self.valid_bmp = wx.ArtProvider.GetBitmap(wx.ART_TICK_MARK, wx.ART_TOOLBAR, (16,16))
        self.invalid_bmp = wx.ArtProvider.GetBitmap(wx.ART_CROSS_MARK, wx.ART_TOOLBAR, (16,16))
        self.validity_sbmp = wx.StaticBitmap(self, -1, self.invalid_bmp)
        self.edit = wx.TextCtrl(self)
        self.edit_sizer = wx.FlexGridSizer(cols=2, hgap=0, rows=1, vgap=0)
        self.edit_sizer.AddGrowableCol(0)
        self.edit_sizer.AddGrowableRow(0)
        self.edit_sizer.Add(self.edit, flag=wx.GROW)
        self.edit_sizer.Add(self.validity_sbmp, flag=wx.GROW)
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.main_sizer.Add(self.desc, flag=wx.GROW)
        self.main_sizer.Add(self.edit_sizer, flag=wx.GROW)
        self.SetSizer(self.main_sizer)
        self.main_sizer.Fit(self)

class ArgEditor(ParamEditor):
    pass

class PathEditor(ParamEditor):
    def __init__(self, parent, pathdesc):
        ParamEditor.__init__(self, parent, pathdesc)
        self.ParentObj = parent
        DropTarget = PathDropTarget(self)
        self.edit.SetDropTarget(DropTarget)
        self.Bind(wx.EVT_TEXT_ENTER, self.OnPathChanged, self.edit)

    def OnHMITreeDnD(self):
        self.ParentObj.GotPathDnDOn(self)

    def SetPathValue(self, value):
        self.edit.SetValue(value)

    def OnPathChanged(self, event):
        # TODO : update validity
        event.Skip()
    

_conf_key = "SVGHMIWidgetLib"
_preview_height = 200
_preview_margin = 5
class WidgetLibBrowser(wx.SplitterWindow):
    def __init__(self, parent, id=wx.ID_ANY, pos=wx.DefaultPosition,
                 size=wx.DefaultSize):

        wx.SplitterWindow.__init__(self, parent,
                                   style=wx.SUNKEN_BORDER | wx.SP_3D)

        self.bmp = None
        self.msg = None
        self.hmitree_nodes = []
        self.selected_SVG = None

        self.Config = wx.ConfigBase.Get()
        self.libdir = self.RecallLibDir()

        self.picker_desc_splitter = wx.SplitterWindow(self, style=wx.SUNKEN_BORDER | wx.SP_3D)

        self.picker_panel = wx.Panel(self.picker_desc_splitter)
        self.picker_sizer = wx.FlexGridSizer(cols=1, hgap=0, rows=2, vgap=0)
        self.picker_sizer.AddGrowableCol(0)
        self.picker_sizer.AddGrowableRow(1)

        self.widgetpicker = WidgetPicker(self.picker_panel, self.libdir)
        self.libbutton = wx.Button(self.picker_panel, -1, _("Select SVG widget library"))

        self.picker_sizer.Add(self.libbutton, flag=wx.GROW)
        self.picker_sizer.Add(self.widgetpicker, flag=wx.GROW)
        self.picker_sizer.Layout()
        self.picker_panel.SetAutoLayout(True)
        self.picker_panel.SetSizer(self.picker_sizer)

        self.Bind(wx.EVT_TREE_SEL_CHANGED, self.OnWidgetSelection, self.widgetpicker)
        self.Bind(wx.EVT_BUTTON, self.OnSelectLibDir, self.libbutton)



        self.main_panel = ScrolledPanel(parent=self,
                                                name='MiscellaneousPanel',
                                                style=wx.TAB_TRAVERSAL)

        self.main_sizer = wx.FlexGridSizer(cols=1, hgap=0, rows=3, vgap=0)
        self.main_sizer.AddGrowableCol(0)
        self.main_sizer.AddGrowableRow(2)

        self.staticmsg = wx.StaticText(self, label = _("Drag selected Widget from here to Inkscape"))
        self.preview = wx.Panel(self.main_panel, size=(-1, _preview_height + _preview_margin*2))
        self.signature_sizer = wx.BoxSizer(wx.VERTICAL)
        self.args_box = wx.StaticBox(self.main_panel, -1,
                                     _("Widget's arguments"),
                                     style = wx.ALIGN_RIGHT)
        self.args_sizer = wx.StaticBoxSizer(self.args_box, wx.VERTICAL)
        self.paths_box = wx.StaticBox(self.main_panel, -1,
                                      _("Widget's variables"),
                                      style = wx.ALIGN_RIGHT)
        self.paths_sizer = wx.StaticBoxSizer(self.paths_box, wx.VERTICAL)
        self.signature_sizer.Add(self.args_sizer, flag=wx.GROW)
        self.signature_sizer.AddSpacer(5)
        self.signature_sizer.Add(self.paths_sizer, flag=wx.GROW)
        self.main_sizer.Add(self.staticmsg, flag=wx.GROW)
        self.main_sizer.Add(self.preview, flag=wx.GROW)
        self.main_sizer.Add(self.signature_sizer, flag=wx.GROW)
        self.main_sizer.Layout()
        self.main_panel.SetAutoLayout(True)
        self.main_panel.SetSizer(self.main_sizer)
        self.main_sizer.Fit(self.main_panel)
        self.preview.Bind(wx.EVT_PAINT, self.OnPaint)
        self.preview.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)

        self.desc = wx.TextCtrl(self.picker_desc_splitter, size=wx.Size(-1, 160),
                                   style=wx.TE_READONLY | wx.TE_MULTILINE)

        self.picker_desc_splitter.SplitHorizontally(self.picker_panel, self.desc, 400)
        self.SplitVertically(self.main_panel, self.picker_desc_splitter, 300)

        self.tempf = None 

        self.args_editors = []
        self.paths_editors = []

    def ResetSignature(self):
        self.args_sizer.Clear()
        for editor in self.args_editors:
            editor.Destroy()
        self.args_editors = []

        self.paths_sizer.Clear()
        for editor in self.paths_editors:
            editor.Destroy()
        self.paths_editors = []

    def AddArgToSignature(self, arg):
        new_editor = ArgEditor(self, arg)
        self.args_editors.append(new_editor)
        self.args_sizer.Add(new_editor, flag=wx.GROW)

    def AddPathToSignature(self, path):
        new_editor = PathEditor(self, path)
        self.paths_editors.append(new_editor)
        self.paths_sizer.Add(new_editor, flag=wx.GROW)

    def GotPathDnDOn(self, target_editor):
        dndindex = self.paths_editors.index(target_editor)

        for selected,editor in zip(self.hmitree_nodes,
                                   self.paths_editors[dndindex:]):
            editor.SetPath(selected.hmi_path())

    def RecallLibDir(self):
        conf = self.Config.Read(_conf_key)
        if len(conf) == 0:
            return None
        else:
            return DecodeFileSystemPath(conf)

    def RememberLibDir(self, path):
        self.Config.Write(_conf_key,
                          EncodeFileSystemPath(path))
        self.Config.Flush()

    def DrawPreview(self):
        """
        Refresh preview panel 
        """
        # Init preview panel paint device context
        dc = wx.PaintDC(self.preview)
        dc.Clear()

        if self.bmp:
            # Get Preview panel size
            sz = self.preview.GetClientSize()
            w = self.bmp.GetWidth()
            dc.DrawBitmap(self.bmp, (sz.width - w)/2, _preview_margin)



    def OnSelectLibDir(self, event):
        defaultpath = self.RecallLibDir()
        if defaultpath == None:
            defaultpath = os.path.expanduser("~")

        dialog = wx.DirDialog(self, _("Choose a widget library"), defaultpath,
                              style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        if dialog.ShowModal() == wx.ID_OK:
            self.libdir = dialog.GetPath()
            self.RememberLibDir(self.libdir)
            self.widgetpicker.MakeTree(self.libdir)

        dialog.Destroy()

    def OnPaint(self, event):
        """
        Called when Preview panel needs to be redrawn
        @param event: wx.PaintEvent
        """
        self.DrawPreview()
        event.Skip()

    def GenThumbnail(self, svgpath, thumbpath):
        inkpath = get_inkscape_path()
        if inkpath is None:
            self.msg = _("Inkscape is not installed.")
            return False
        # TODO: spawn a thread, to decouple thumbnail gen
        status, result, _err_result = ProcessLogger(
            None,
            '"' + inkpath + '" "' + svgpath + '" -e "' + thumbpath +
            '" -D -h ' + str(_preview_height)).spin()
        if status != 0:
            self.msg = _("Inkscape couldn't generate thumbnail.")
            return False
        return True

    def OnWidgetSelection(self, event):
        """
        Called when tree item is selected
        @param event: wx.TreeEvent
        """
        item_pydata = self.widgetpicker.GetPyData(event.GetItem())
        if item_pydata is not None:
            svgpath = item_pydata
            dname = os.path.dirname(svgpath)
            fname = os.path.basename(svgpath)
            hasher = hashlib.new('md5')
            with open(svgpath, 'rb') as afile:
                while True:
                    buf = afile.read(65536)
                    if len(buf) > 0:
                        hasher.update(buf)
                    else:
                        break
            digest = hasher.hexdigest()
            thumbfname = os.path.splitext(fname)[0]+"_"+digest+".png"
            thumbdir = os.path.join(dname, ".svghmithumbs") 
            thumbpath = os.path.join(thumbdir, thumbfname) 

            have_thumb = os.path.exists(thumbpath)

            try:
                if not have_thumb:
                    if not os.path.exists(thumbdir):
                        os.mkdir(thumbdir)
                    have_thumb = self.GenThumbnail(svgpath, thumbpath)

                self.bmp = wx.Bitmap(thumbpath) if have_thumb else None

                self.selected_SVG = svgpath if have_thumb else None

                self.AnalyseWidgetAndUpdateUI(fname)

                if self.msg:
                    self.staticmsg.Show()
                    self.staticmsg.SetLabel(self.msg)
                else:
                    self.staticmsg.Hide()


            except IOError:
                self.msg = _("Widget library must be writable")

            self.Refresh()
        event.Skip()

    def OnHMITreeNodeSelection(self, hmitree_nodes):
        self.hmitree_nodes = hmitree_nodes
        # [0] if len(hmitree_nodes) else None
        # self.ValidateWidget()
        # self.Refresh()

    def OnLeftDown(self, evt):
        if self.tempf is not None:
            filename = self.tempf.name
            data = wx.FileDataObject()
            data.AddFile(filename)
            dropSource = wx.DropSource(self)
            dropSource.SetData(data)
            dropSource.DoDragDrop(wx.Drag_AllowMove)

    def GiveDetails(self, _context, msgs):
        for msg in msgs:
            self.msg += msg.text + "\n"
        
    def PassMessage(self, _context, msgs):
        for msg in msgs:
            self.msg += msg.text + "\n"

    def GetSubHMITree(self, _context):
        return [self.hmitree_node.etree()]

    def AnalyseWidgetAndUpdateUI(self, fname):
        self.msg = ""
        self.ResetSignature()

        try:
            if self.selected_SVG is None:
                raise Exception(_("No widget selected"))

            transform = XSLTransform(
                os.path.join(ScriptDirectory, "analyse_widget.xslt"),[])

            svgdom = etree.parse(self.selected_SVG)

            signature = transform.transform(svgdom)

            for entry in transform.get_error_log():
                self.msg += "XSLT: " + entry.message + "\n" 

        except Exception as e:
            self.msg += str(e)
        except XSLTApplyError as e:
            self.msg += "Widget " + fname + " analysis error: " + e.message
        else:
            
            self.msg += "Widget " + fname + ": OK"

            print(etree.tostring(signature, pretty_print=True))
            widgets = signature.getroot()
            for defs in widgets.iter("defs"):

                # Keep double newlines (to mark paragraphs)
                self.desc.SetValue(defs.find("type").text + ":\n" + "\n\n".join(map(
                    lambda s:s.replace("\n"," ").replace("  ", " "),
                    defs.find("longdesc").text.split("\n\n"))))
                args = [arg for arg in defs.iter("arg")]
                self.args_box.Show(len(args)!=0)
                for arg in args:
                    self.AddArgToSignature(arg)
                    print(arg.get("name"))
                    print(arg.get("accepts"))
                paths = [path for path in defs.iter("path")]
                self.paths_box.Show(len(paths)!=0)
                for path in paths:
                    self.AddPathToSignature(path)
                    print(path.get("name"))
                    print(path.get("accepts"))

            for widget in widgets:
                widget_type = widget.get("type")
                print(widget_type)
                for path in widget.iterchildren("path"):
                    path_value = path.get("value")
                    path_accepts = map(
                        str.strip, path.get("accepts", '')[1:-1].split(','))
                    print(path, path_value, path_accepts)

        self.main_panel.SetupScrolling(scroll_x=False)



    def ValidateWidget(self):
        self.msg = ""

        if self.tempf is not None:
            os.unlink(self.tempf.name)
            self.tempf = None

        try:
            if self.selected_SVG is None:
                raise Exception(_("No widget selected"))
            if self.hmitree_node is None:
                raise Exception(_("No HMI tree node selected"))

            transform = XSLTransform(
                os.path.join(ScriptDirectory, "gen_dnd_widget_svg.xslt"),
                [("GetSubHMITree", self.GetSubHMITree),
                 ("PassMessage", self.GiveDetails)])

            svgdom = etree.parse(self.selected_SVG)

            result = transform.transform(
                svgdom, hmi_path = self.hmitree_node.hmi_path())

            for entry in transform.get_error_log():
                self.msg += "XSLT: " + entry.message + "\n" 

            self.tempf = NamedTemporaryFile(suffix='.svg', delete=False)
            result.write(self.tempf, encoding="utf-8")
            self.tempf.close()

        except Exception as e:
            self.msg += str(e)
        except XSLTApplyError as e:
            self.msg += "Widget transform error: " + e.message
                
    def __del__(self):
        if self.tempf is not None:
            os.unlink(self.tempf.name)

class SVGHMI_UI(wx.SplitterWindow):

    def __init__(self, parent, register_for_HMI_tree_updates):
        wx.SplitterWindow.__init__(self, parent,
                                   style=wx.SUNKEN_BORDER | wx.SP_3D)

        self.SelectionTree = HMITreeSelector(self)
        self.Staging = WidgetLibBrowser(self)
        self.SplitVertically(self.SelectionTree, self.Staging, 300)
        register_for_HMI_tree_updates(weakref.ref(self))

    def HMITreeUpdate(self, hmi_tree_root):
        self.SelectionTree.MakeTree(hmi_tree_root)

    def OnHMITreeNodeSelection(self, hmitree_nodes):
        self.Staging.OnHMITreeNodeSelection(hmitree_nodes)
