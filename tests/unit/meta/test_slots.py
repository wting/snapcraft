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
from snapcraft.internal.meta.slots import Slot, ContentSlot, DbusSlot
from tests import unit


class GenericSlotTests(unit.TestCase):
    def test_slot_name(self):
        slot_name = "slot-test"

        slot = Slot(slot_name=slot_name)
        slot_from_dict = Slot.from_dict(
            slot_dict={"interface": "somevalue"}, slot_name=slot_name
        )

        self.assertEqual(slot_name, slot.slot_name)
        self.assertEqual(slot_name, slot_from_dict.slot_name)

    def test_invalid_raises_exception(self):
        slot_name = "slot-test"

        slot = Slot(slot_name=slot_name)

        self.assertRaises(errors.SlotValidationError, slot.validate)

    def test_invalid_from_dict_raises_exception(self):
        slot_dict = OrderedDict({})
        slot_name = "slot-test"

        slot = Slot.from_dict(slot_dict=slot_dict, slot_name=slot_name)

        self.assertRaises(errors.SlotValidationError, slot.validate)

    def test_valid_from_dict(self):
        slot_dict = OrderedDict({"interface": "somevalue", "someprop": "somevalue"})
        slot_name = "slot-test"

        slot = Slot.from_dict(slot_dict=slot_dict, slot_name=slot_name)

        slot.validate()


class ContentSlotTests(unit.TestCase):
    def test_empty(self):
        slot_dict = OrderedDict({"interface": "content"})
        slot_name = "slot-test"

        slot = ContentSlot(slot_name=slot_name)

        # "use_source_key" is default, account for that.
        transformed_dict = slot_dict.copy()
        transformed_dict["source"] = {}

        self.assertEqual(transformed_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertRaises(errors.SlotValidationError, slot.validate)
        self.assertEqual(set(), slot.get_content_dirs(installed_path=""))

    def test_empty_from_dict(self):
        slot_dict = OrderedDict({"interface": "content"})
        slot_name = "slot-name"

        slot = Slot.from_dict(slot_dict=slot_dict, slot_name=slot_name)

        self.assertIsInstance(slot, ContentSlot)
        self.assertEqual(slot_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertRaises(errors.SlotValidationError, slot.validate)
        self.assertEqual(set(), slot.get_content_dirs(installed_path=""))

    def test_empty_force_no_source(self):
        slot_dict = OrderedDict({"interface": "content"})
        slot_name = "slot-test"

        slot = ContentSlot(use_source_key=False, slot_name=slot_name)

        self.assertEqual(slot_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertRaises(errors.SlotValidationError, slot.validate)
        self.assertEqual(set(), slot.get_content_dirs(installed_path=""))

    def test_read_from_dict(self):
        slot_dict = OrderedDict({"interface": "content", "read": ["some/path"]})
        slot_name = "slot-test"

        slot = ContentSlot.from_dict(slot_dict=slot_dict, slot_name=slot_name)
        slot.validate()

        self.assertEqual(slot_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertEqual(slot_dict["read"], slot.read)
        self.assertEqual(
            set(slot_dict["read"]), slot.get_content_dirs(installed_path="")
        )

    def test_read_from_dict_force_source_key(self):
        slot_dict = OrderedDict({"interface": "content", "read": ["some/path"]})
        slot_name = "slot-test"

        slot = ContentSlot.from_dict(slot_dict=slot_dict, slot_name=slot_name)
        slot.use_source_key = True
        slot.validate()
        transformed_dict = slot_dict.copy()
        transformed_dict["source"] = dict()
        transformed_dict["source"]["read"] = transformed_dict.pop("read")

        self.assertEqual(transformed_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertEqual(slot_dict["read"], slot.read)
        self.assertEqual(
            set(slot_dict["read"]), slot.get_content_dirs(installed_path="")
        )

    def test_source_read_from_dict(self):
        slot_dict = OrderedDict(
            {"interface": "content", "source": {"read": ["some/path"]}}
        )
        slot_name = "slot-test"

        slot = ContentSlot.from_dict(slot_dict=slot_dict, slot_name=slot_name)
        slot.validate()

        self.assertEqual(slot_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertEqual(slot_dict["source"]["read"], slot.read)
        self.assertEqual(
            set(slot_dict["source"]["read"]), slot.get_content_dirs(installed_path="")
        )

    def test_write_from_dict(self):
        slot_dict = OrderedDict({"interface": "content", "write": ["some/path"]})
        slot_name = "slot-test"

        slot = ContentSlot.from_dict(slot_dict=slot_dict, slot_name=slot_name)
        slot.validate()

        self.assertEqual(slot_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertEqual(slot_dict["write"], slot.write)
        self.assertEqual(
            set(slot_dict["write"]), slot.get_content_dirs(installed_path="")
        )

    def test_write_from_dict_force_source_key(self):
        slot_dict = OrderedDict({"interface": "content", "write": ["some/path"]})
        slot_name = "slot-test"

        slot = ContentSlot.from_dict(slot_dict=slot_dict, slot_name=slot_name)
        slot.use_source_key = True
        slot.validate()
        transformed_dict = slot_dict.copy()
        transformed_dict["source"] = dict()
        transformed_dict["source"]["write"] = transformed_dict.pop("write")

        self.assertEqual(transformed_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertEqual(slot_dict["write"], slot.write)
        self.assertEqual(
            set(slot_dict["write"]), slot.get_content_dirs(installed_path="")
        )

    def test_source_write_from_dict(self):
        slot_dict = OrderedDict(
            {"interface": "content", "source": {"write": ["some/path"]}}
        )
        slot_name = "slot-test"

        slot = ContentSlot.from_dict(slot_dict=slot_dict, slot_name=slot_name)
        slot.validate()

        self.assertEqual(slot_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertEqual(slot_dict["source"]["write"], slot.write)
        self.assertEqual(
            set(slot_dict["source"]["write"]), slot.get_content_dirs(installed_path="")
        )


class DbusSlotTests(unit.TestCase):
    def test_invalid_target_raises_exception(self):
        slot = DbusSlot(slot_name="slot-test", bus="", name="")

        self.assertRaises(errors.SlotValidationError, slot.validate)

    def test_invalid_interface_from_dict_raises_exception(self):
        slot_dict = OrderedDict({"interface": "content", "bus": "", "name": ""})

        self.assertRaises(
            errors.SlotValidationError,
            DbusSlot.from_dict,
            slot_dict=slot_dict,
            slot_name="slot-test",
        )

    def test_invalid_target_from_dict_raises_exception(self):
        slot_dict = OrderedDict({"interface": "dbus", "bus": "", "name": ""})

        slot = DbusSlot.from_dict(slot_dict=slot_dict, slot_name="slot-test")

        self.assertRaises(errors.SlotValidationError, slot.validate)

    def test_basic(self):
        slot_dict = OrderedDict({"interface": "dbus", "bus": "bus", "name": "name"})
        slot_name = "slot-test"

        slot = DbusSlot(
            slot_name=slot_name, bus=slot_dict["bus"], name=slot_dict["name"]
        )
        slot.validate()

        self.assertEqual(slot_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertEqual(slot_dict["bus"], slot.bus)
        self.assertEqual(slot_dict["name"], slot.name)

    def test_basic_from_dict(self):
        slot_dict = OrderedDict({"interface": "dbus", "bus": "bus", "name": "name"})
        slot_name = "slot-test"

        slot = DbusSlot.from_dict(slot_dict=slot_dict, slot_name=slot_name)
        slot.validate()

        self.assertEqual(slot_dict, slot.to_dict())
        self.assertEqual(slot_name, slot.slot_name)
        self.assertEqual(slot_dict["bus"], slot.bus)
        self.assertEqual(slot_dict["name"], slot.name)
