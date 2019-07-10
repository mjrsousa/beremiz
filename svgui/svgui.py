#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of Beremiz, a Integrated Development Environment for
# programming IEC 61131-3 automates supporting plcopen standard and CanFestival.
#
# Copyright (C) 2007: Edouard TISSERANT and Laurent BESSARD
# Copyright (C) 2017: Andrey Skvortsov
#
# See COPYING file for copyrights details.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.


from __future__ import absolute_import
import os
import shutil

import wx
from svgui.pyjs import translate

import util.paths as paths
from POULibrary import POULibrary
from docutil import open_svg
from py_ext import PythonFileCTNMixin


class SVGUILibrary(POULibrary):
    def GetLibraryPath(self):
        return paths.AbsNeighbourFile(__file__, "pous.xml")


class SVGUI(PythonFileCTNMixin):

    ConfNodeMethods = [
        {
            "bitmap":    "ImportSVG",
            "name":    _("Import SVG"),
            "tooltip": _("Import SVG"),
            "method":   "_ImportSVG"
        },
        {
            "bitmap":    "ImportSVG",  # should be something different
            "name":    _("Inkscape"),
            "tooltip": _("Create HMI"),
            "method":   "_StartInkscape"
        },
    ]

    def _getSVGpath(self, project_path=None):
        if project_path is None:
            project_path = self.CTNPath()
        # define name for SVG file containing gui layout
        return os.path.join(project_path, "gui.svg")

    def _getSVGUIserverpath(self):
        return paths.AbsNeighbourFile(__file__, "svgui_server.py")

    def OnCTNSave(self, from_project_path=None):
        if from_project_path is not None:
            shutil.copyfile(self._getSVGpath(from_project_path),
                            self._getSVGpath())
        return PythonFileCTNMixin.OnCTNSave(self, from_project_path)

    def CTNGenerate_C(self, buildpath, locations):
        """
        Return C code generated by iec2c compiler
        when _generate_softPLC have been called
        @param locations: ignored
        @return: [(C_file_name, CFLAGS),...] , LDFLAGS_TO_APPEND
        """

        current_location = self.GetCurrentLocation()
        # define a unique name for the generated C file
        location_str = "_".join(map(str, current_location))

        res = ([], "", False)

        svgfile = self._getSVGpath()
        if os.path.exists(svgfile):
            res += (("gui.svg", open(svgfile, "rb")),)

        svguiserverfile = open(self._getSVGUIserverpath(), 'r')
        svguiservercode = svguiserverfile.read()
        svguiserverfile.close()

        svguilibpath = os.path.join(self._getBuildPath(), "svguilib.js")
        svguilibfile = open(svguilibpath, 'w')
        fpath = paths.AbsDir(__file__)
        svguilibfile.write(translate(os.path.join(fpath, "pyjs", "lib", "sys.py"), "sys"))
        svguilibfile.write(open(os.path.join(fpath, "pyjs", "lib", "_pyjs.js"), 'r').read())
        svguilibfile.write(translate(os.path.join(fpath, "pyjs", "lib", "pyjslib.py"), "pyjslib"))
        svguilibfile.write(translate(os.path.join(fpath, "svguilib.py"), "svguilib"))
        svguilibfile.write("pyjslib();\nsvguilib();\n")
        svguilibfile.write(open(os.path.join(fpath, "pyjs", "lib", "json.js"), 'r').read())
        svguilibfile.write(open(os.path.join(fpath, "livesvg.js"), 'r').read())
        svguilibfile.close()
        jsmodules = {"LiveSVGPage": "svguilib.js"}
        res += (("svguilib.js", open(svguilibpath, "rb")),)

        runtimefile_path = os.path.join(buildpath, "runtime_%s.py" % location_str)
        runtimefile = open(runtimefile_path, 'w')
        runtimefile.write(svguiservercode % {"svgfile": "gui.svg"})
        runtimefile.write("""
def _runtime_%(location)s_start():
    website.LoadHMI(%(svgui_class)s, %(jsmodules)s)

def _runtime_%(location)s_stop():
    website.UnLoadHMI()

        """ % {"location": location_str,
               "svgui_class": "SVGUI_HMI",
               "jsmodules": str(jsmodules)})
        runtimefile.close()

        res += (("runtime_%s.py" % location_str, open(runtimefile_path, "rb")),)

        return res

    def _ImportSVG(self):
        dialog = wx.FileDialog(self.GetCTRoot().AppFrame, _("Choose a SVG file"), os.getcwd(), "",  _("SVG files (*.svg)|*.svg|All files|*.*"), wx.OPEN)
        if dialog.ShowModal() == wx.ID_OK:
            svgpath = dialog.GetPath()
            if os.path.isfile(svgpath):
                shutil.copy(svgpath, self._getSVGpath())
            else:
                self.GetCTRoot().logger.write_error(_("No such SVG file: %s\n") % svgpath)
        dialog.Destroy()

    def _StartInkscape(self):
        svgfile = self._getSVGpath()
        open_inkscape = True
        if not self.GetCTRoot().CheckProjectPathPerm():
            dialog = wx.MessageDialog(self.GetCTRoot().AppFrame,
                                      _("You don't have write permissions.\nOpen Inkscape anyway ?"),
                                      _("Open Inkscape"),
                                      wx.YES_NO | wx.ICON_QUESTION)
            open_inkscape = dialog.ShowModal() == wx.ID_YES
            dialog.Destroy()
        if open_inkscape:
            if not os.path.isfile(svgfile):
                svgfile = None
            open_svg(svgfile)
