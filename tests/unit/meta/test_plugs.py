# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2019 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from collections import OrderedDict
from snapcraft.internal.meta import errors
from snapcraft.internal.meta.plugs import Plug, ContentPlug
from tests import unit


class GenericPlugTests(unit.TestCase):
    def test_plug_name(self):
        plug_name = "plug-test"

        plug = Plug(plug_name=plug_name)
        plug_from_dict = Plug.from_dict(
            plug_dict={"interface": "somevalue"}, plug_name=plug_name
        )

        self.assertEqual(plug_name, plug.plug_name)
        self.assertEqual(plug_name, plug_from_dict.plug_name)

    def test_invalid_raises_exception(self):
        plug_name = "plug-test"

        plug = Plug(plug_name=plug_name)

        self.assertRaises(errors.PlugValidationError, plug.validate)

    def test_invalid_from_dict_raises_exception(self):
        plug_dict = OrderedDict({})
        plug_name = "plug-test"

        plug = Plug.from_dict(plug_dict=plug_dict, plug_name=plug_name)

        self.assertRaises(errors.PlugValidationError, plug.validate)

    def test_valid_from_dict(self):
        plug_dict = OrderedDict({"interface": "somevalue", "someprop": "somevalue"})
        plug_name = "plug-test"

        plug = Plug.from_dict(plug_dict=plug_dict, plug_name=plug_name)

        plug.validate()


class ContentPlugTests(unit.TestCase):
    def test_invalid_target_raises_exception(self):
        plug = ContentPlug(plug_name="plug-test", target="")

        self.assertRaises(errors.PlugValidationError, plug.validate)

    def test_invalid_target_from_dict_raise_exception(self):
        plug_dict = OrderedDict({"interface": "content", "target": ""})

        plug = Plug.from_dict(plug_dict=plug_dict, plug_name="plug-test")

        self.assertRaises(errors.PlugValidationError, plug.validate)

    def test_content_defaults_to_name(self):
        plug = ContentPlug(plug_name="plug-test", target="target")

        self.assertEqual("plug-test", plug.content)

    def test_basic_from_dict(self):
        plug_dict = OrderedDict(
            {
                "interface": "content",
                "content": "content",
                "target": "target",
                "default-provider": "gtk-common-themes:gtk-3-themes",
            }
        )
        plug_name = "plug-test"
        plug_provider = "gtk-common-themes"

        plug = ContentPlug.from_dict(plug_dict=plug_dict, plug_name=plug_name)
        plug.validate()

        # default-provider is not written as <provider>:<name>, just <provider>.
        transformed_dict = plug_dict.copy()
        transformed_dict["default-provider"] = plug_provider

        self.assertEqual(transformed_dict, plug.to_dict())
        self.assertEqual(plug_name, plug.plug_name)
        self.assertEqual(plug_dict["content"], plug.content)
        self.assertEqual(plug_dict["target"], plug.target)
        self.assertEqual(plug_provider, plug.provider)
