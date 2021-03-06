# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2016, Alex Băluț <alexandru.balut@gmail.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.
"""Tests for the render module."""
# pylint: disable=protected-access,no-self-use
# pylint: disable=too-many-locals
from unittest import mock
from unittest import skipUnless

from gi.repository import GES
from gi.repository import Gst
from gi.repository import GstPbutils
from gi.repository import Gtk

from pitivi.preset import EncodingTargetManager
from pitivi.render import Encoders
from pitivi.render import extension_for_muxer
from pitivi.utils.ui import get_combo_value
from pitivi.utils.ui import set_combo_value
from tests import common


def factory_exists(*factories):
    """Checks if @factories exists."""
    for factory in factories:
        if not Gst.ElementFactory.find(factory):
            return False, "%s not present on the system" % (factory)

    return True, ""


def find_preset_row_index(combo, name):
    """Finds @name in @combo."""
    for i, row in enumerate(combo.get_model()):
        if row[0] == name:
            return i

    return None


class TestRender(common.TestCase):
    """Tests for functions."""

    def test_extensions_supported(self):
        """Checks we associate file extensions to the well supported muxers."""
        for muxer, unused_audio, unused_video in Encoders.SUPPORTED_ENCODERS_COMBINATIONS:
            self.assertIsNotNone(extension_for_muxer(muxer), muxer)

    def test_extensions_presets(self):
        """Checks we associate file extensions to the muxers of the presets."""
        project = self.create_simple_project()
        with mock.patch("pitivi.preset.xdg_data_home") as xdg_data_home:
            xdg_data_home.return_value = "/pitivi-dir-which-does-not-exist"
            preset_manager = EncodingTargetManager(project.app)
            preset_manager.loadAll()
            self.assertTrue(preset_manager.presets)
            for unused_name, container_profile in preset_manager.presets.items():
                # Preset name is only set when the project loads it
                project.set_container_profile(container_profile)
                muxer = container_profile.get_preset_name()
                self.assertIsNotNone(extension_for_muxer(muxer), container_profile)

    def create_simple_project(self):
        """Creates a Project with a layer a clip."""
        timeline_container = common.create_timeline_container()
        app = timeline_container.app
        project = app.project_manager.current_project
        if not project.ges_timeline.get_layers():
            project.ges_timeline.append_layer()

        mainloop = common.create_main_loop()

        def asset_added_cb(project, asset):  # pylint: disable=missing-docstring
            mainloop.quit()

        project.connect("asset-added", asset_added_cb)
        uris = [common.get_sample_uri("tears_of_steel.webm")]
        project.addUris(uris)
        mainloop.run()

        layer, = project.ges_timeline.get_layers()
        layer.add_asset(project.list_assets(GES.UriClip)[0],
                        0, 0, Gst.CLOCK_TIME_NONE, GES.TrackType.UNKNOWN)

        return project

    def create_rendering_dialog(self, project):
        """Creates a RenderingDialog ready for testing"""
        from pitivi.render import RenderDialog

        class MockedBuilder(Gtk.Builder):
            """Specialized builder suitable for RenderingDialog testing."""

            # pylint: disable=arguments-differ
            def get_object(self, name):
                """Get @name widget or a MagicMock for render dialog window."""
                if name == "render-dialog":
                    return mock.MagicMock()

                return super().get_object(name)

        with mock.patch.object(Gtk.Builder, "__new__", return_value=MockedBuilder()):
            return RenderDialog(project.app, project)

    def test_launching_rendering(self):
        """Checks no exception is raised when clicking the render button."""
        project = self.create_simple_project()
        dialog = self.create_rendering_dialog(project)

        from pitivi.render import RenderingProgressDialog
        with mock.patch.object(dialog, "startAction"):
            with mock.patch.object(RenderingProgressDialog, "__new__"):
                with mock.patch.object(dialog, "_pipeline"):
                    return dialog._renderButtonClickedCb(None)

    @skipUnless(*factory_exists("x264enc", "matroskamux"))
    def test_encoder_restrictions(self):
        """Checks the mechanism to respect encoder specific restrictions."""
        project = self.create_simple_project()
        dialog = self.create_rendering_dialog(project)

        # Explicitly set the encoder
        self.assertTrue(set_combo_value(dialog.muxer_combo,
                                        Gst.ElementFactory.find("matroskamux")))
        self.assertTrue(set_combo_value(dialog.video_encoder_combo,
                                        Gst.ElementFactory.find("x264enc")))
        self.assertEqual(project.video_profile.get_restriction()[0]["format"],
                         "Y444")

        # Set encoding profile
        if getattr(GstPbutils.EncodingProfile, "copy"):  # Available only in > 1.11
            profile = project.container_profile.copy()
            vprofile, = [p for p in profile.get_profiles()
                         if isinstance(p, GstPbutils.EncodingVideoProfile)]
            vprofile.set_restriction(Gst.Caps('video/x-raw'))
            project.set_container_profile(profile)
            self.assertEqual(project.video_profile.get_restriction()[0]["format"],
                             "Y444")

    @skipUnless(*factory_exists("vorbisenc", "theoraenc", "oggmux",
                                "opusenc", "vp8enc"))
    def test_loading_preset(self):
        """Checks preset values are properly exposed in the UI."""
        def preset_changed_cb(combo, changed):
            """Callback for the 'combo::changed' signal."""
            changed.append(1)

        project = self.create_simple_project()
        dialog = self.create_rendering_dialog(project)

        preset_combo = dialog.render_presets.combo
        changed = []
        preset_combo.connect("changed", preset_changed_cb, changed)

        test_data = [
            ("test", {'aencoder': "vorbisenc",
                      'vencoder': "theoraenc",
                      'muxer': "oggmux"}),
            ("test_ogg-vp8-opus", {
                "aencoder": "opusenc",
                "vencoder": "vp8enc",
                "muxer": "oggmux"}),
            ("test_fullhd", {
                "aencoder": "vorbisenc",
                "vencoder": "theoraenc",
                "muxer": "oggmux",
                "videowidth": 1920,
                "videoheight": 1080,
                "videorate": Gst.Fraction(120, 1)}),
            ("test_ogg-vp8-opus", {
                "aencoder": "opusenc",
                "vencoder": "vp8enc",
                "muxer": "oggmux"}),
            ("test_fullhd", {
                "aencoder": "vorbisenc",
                "vencoder": "theoraenc",
                "muxer": "oggmux",
                "videowidth": 1920,
                "videoheight": 1080,
                "videorate": Gst.Fraction(120, 1)}),
        ]

        attr_dialog_widget_map = {
            "videorate": dialog.frame_rate_combo,
            "aencoder": dialog.audio_encoder_combo,
            "vencoder": dialog.video_encoder_combo,
            "muxer": dialog.muxer_combo,
        }

        for preset_name, values in test_data:
            i = find_preset_row_index(preset_combo, preset_name)
            self.assertNotEqual(i, None)

            del changed[:]
            preset_combo.set_active(i)
            self.assertEqual(changed, [1], "Preset %s" % preset_name)

            for attr, val in values.items():
                combo = attr_dialog_widget_map.get(attr)
                if combo:
                    combo_value = get_combo_value(combo)
                    if isinstance(combo_value, Gst.ElementFactory):
                        combo_value = combo_value.get_name()
                    self.assertEqual(combo_value, val, preset_name)

                self.assertEqual(getattr(project, attr), val)

    @skipUnless(*factory_exists("vorbisenc", "theoraenc", "oggmux",
                                "opusenc", "vp8enc"))
    def test_remove_profile(self):
        """Tests removing EncodingProfile and re-saving it."""
        project = self.create_simple_project()
        dialog = self.create_rendering_dialog(project)
        preset_combo = dialog.render_presets.combo
        i = find_preset_row_index(preset_combo, 'test')
        self.assertIsNotNone(i)
        preset_combo.set_active(i)

        # Check the 'test' profile is selected
        active_iter = preset_combo.get_active_iter()
        self.assertEqual(preset_combo.props.model.get_value(active_iter, 0), 'test')

        # Remove current profile and verify it has been removed
        dialog.render_presets.action_remove.activate()
        profile_names = [i[0] for i in preset_combo.props.model]
        active_iter = preset_combo.get_active_iter()
        self.assertEqual(active_iter, None)

        # Re save the current EncodingProfile calling it the same as before.
        preset_combo.get_child().set_text("test")
        self.assertTrue(dialog.render_presets.action_save.get_enabled())
        dialog.render_presets.action_save.activate(None)
        self.assertEqual([i[0] for i in preset_combo.props.model],
                         profile_names + ['test'])
        active_iter = preset_combo.get_active_iter()
        self.assertEqual(preset_combo.props.model.get_value(active_iter, 0), 'test')
