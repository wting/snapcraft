# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2016-2019 Canonical Ltd
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

import os
from unittest import mock

from testtools.matchers import Contains, Equals, FileExists, Not
from xdg import BaseDirectory

from snapcraft import file_utils, storeapi, internal
from snapcraft.storeapi.errors import (
    StoreDeltaApplicationError,
    StorePushError,
    StoreUploadError,
)
import tests
from . import FakeStoreCommandsBaseTestCase


class PushCommandBaseTestCase(FakeStoreCommandsBaseTestCase):
    def setUp(self):
        super().setUp()

        self.fake_store_status.mock.return_value = {
            "amd64": [
                {
                    "info": "specific",
                    "version": "1.0-amd64",
                    "channel": "stable",
                    "revision": 2,
                },
                {
                    "info": "specific",
                    "version": "1.1-amd64",
                    "channel": "beta",
                    "revision": 4,
                },
                {"info": "tracking", "channel": "edge"},
            ]
        }

        self.snap_file = os.path.join(
            os.path.dirname(tests.__file__), "data", "test-snap.snap"
        )


class PushCommandTestCase(PushCommandBaseTestCase):
    def test_push_without_snap_must_raise_exception(self):
        result = self.run_command(["push"])

        self.assertThat(result.exit_code, Equals(2))
        self.assertThat(result.output, Contains("Usage:"))

    def test_push_a_snap(self):
        # Upload
        result = self.run_command(["push", self.snap_file])

        self.assertThat(result.exit_code, Equals(0))
        self.assertRegexpMatches(
            self.fake_logger.output, r"Revision 9 of 'basic' created\."
        )
        self.fake_store_upload.mock.assert_called_once_with(
            snap_name="basic",
            snap_filename=self.snap_file,
            built_at=None,
            channels=[],
            delta_format=None,
            delta_hash=None,
            source_hash=None,
            target_hash=None,
        )

    def test_push_with_started_at(self):
        snap_file = os.path.join(
            os.path.dirname(tests.__file__), "data", "test-snap-with-started-at.snap"
        )

        # Upload
        result = self.run_command(["push", snap_file])

        self.assertThat(result.exit_code, Equals(0))
        self.assertRegexpMatches(
            self.fake_logger.output, r"Revision 9 of 'basic' created\."
        )
        self.fake_store_upload.mock.assert_called_once_with(
            snap_name="basic",
            snap_filename=snap_file,
            built_at="2019-05-07T19:25:53.939041Z",
            channels=[],
            delta_format=None,
            delta_hash=None,
            source_hash=None,
            target_hash=None,
        )

    def test_push_without_login_must_ask(self):
        self.fake_store_push_precheck.mock.side_effect = [
            storeapi.errors.InvalidCredentialsError("error"),
            None,
        ]

        result = self.run_command(
            ["push", self.snap_file], input="\n\n\n\nuser@example.com\nsecret\n"
        )

        self.assertThat(
            result.output, Contains("You are required to login before continuing.")
        )

    def test_push_nonexisting_snap_must_raise_exception(self):
        result = self.run_command(["push", "test-unexisting-snap"])

        self.assertThat(result.exit_code, Equals(2))

    def test_push_invalid_snap_must_raise_exception(self):
        snap_path = os.path.join(
            os.path.dirname(tests.__file__), "data", "invalid.snap"
        )

        raised = self.assertRaises(
            internal.errors.SnapDataExtractionError,
            self.run_command,
            ["push", snap_path],
        )

        self.assertThat(str(raised), Contains("Cannot read data from snap"))

    def test_push_unregistered_snap_must_ask(self):
        class MockResponse:
            status_code = 404

            def json(self):
                return dict(
                    error_list=[
                        {
                            "code": "resource-not-found",
                            "message": "Snap not found for name=basic",
                        }
                    ]
                )

        self.fake_store_push_precheck.mock.side_effect = [
            StorePushError("basic", MockResponse()),
            None,
        ]

        result = self.run_command(["push", self.snap_file], input="y\n")

        self.assertThat(result.exit_code, Equals(0))
        self.assertThat(
            result.output,
            Contains("You are required to register this snap before continuing. "),
        )
        self.fake_store_register.mock.assert_called_once_with(
            "basic", is_private=False, series="16", store_id=None
        )

    def test_push_unregistered_snap_must_raise_exception_if_not_registering(self):
        class MockResponse:
            status_code = 404

            def json(self):
                return dict(
                    error_list=[
                        {
                            "code": "resource-not-found",
                            "message": "Snap not found for name=basic",
                        }
                    ]
                )

        self.fake_store_push_precheck.mock.side_effect = [
            StorePushError("basic", MockResponse()),
            None,
        ]

        raised = self.assertRaises(
            storeapi.errors.StorePushError, self.run_command, ["push", self.snap_file]
        )

        self.assertThat(
            str(raised),
            Contains("This snap is not registered. Register the snap and try again."),
        )
        self.fake_store_register.mock.assert_not_called()

    def test_push_with_updown_error(self):
        # We really don't know of a reason why this would fail
        # aside from a 5xx style error on the server.
        class MockResponse:
            text = "stub error"
            reason = "stub reason"

        self.fake_store_upload.mock.side_effect = StoreUploadError(MockResponse())

        self.assertRaises(
            storeapi.errors.StoreUploadError, self.run_command, ["push", self.snap_file]
        )

    def test_upload_raises_deprecation_warning(self):
        # Upload
        result = self.run_command(["upload", self.snap_file])

        self.assertThat(result.exit_code, Equals(0))
        self.assertThat(result.output, Contains("Revision 9 of 'basic' created."))
        self.assertThat(
            result.output, Contains("DEPRECATED: Use 'push' instead of 'upload'")
        )
        self.fake_store_upload.mock.assert_called_once_with(
            snap_name="basic",
            snap_filename=self.snap_file,
            built_at=None,
            channels=[],
            delta_format=None,
            delta_hash=None,
            source_hash=None,
            target_hash=None,
        )

    def test_push_and_release_a_snap(self):
        # Upload
        result = self.run_command(["push", self.snap_file, "--release", "beta"])

        self.assertThat(result.exit_code, Equals(0))
        self.assertThat(result.output, Contains("Revision 9 of 'basic' created"))
        self.fake_store_upload.mock.assert_called_once_with(
            snap_name="basic",
            snap_filename=self.snap_file,
            built_at=None,
            channels=["beta"],
            delta_format=None,
            delta_hash=None,
            source_hash=None,
            target_hash=None,
        )

    def test_push_and_release_a_snap_to_N_channels(self):
        # Upload
        result = self.run_command(
            ["push", self.snap_file, "--release", "edge,beta,candidate"]
        )

        self.assertThat(result.exit_code, Equals(0))
        self.assertThat(result.output, Contains("Revision 9 of 'basic' created"))
        self.fake_store_upload.mock.assert_called_once_with(
            snap_name="basic",
            snap_filename=self.snap_file,
            built_at=None,
            channels=["edge", "beta", "candidate"],
            delta_format=None,
            delta_hash=None,
            source_hash=None,
            target_hash=None,
        )

    def test_push_displays_humanized_message(self):
        result = self.run_command(
            ["push", self.snap_file, "--release", "edge,beta,candidate"]
        )

        self.assertThat(
            result.output,
            Contains(
                "After pushing, the resulting snap revision will be released to "
                "'beta', 'candidate', and 'edge' when it passes the Snap Store review."
            ),
        )


class PushCommandDeltasTestCase(PushCommandBaseTestCase):
    def setUp(self):
        super().setUp()

        self.latest_snap_revision = 8
        self.new_snap_revision = self.latest_snap_revision + 1

        self.mock_tracker.track.return_value = {
            "code": "ready_to_release",
            "processed": True,
            "can_release": True,
            "url": "/fake/url",
            "revision": self.new_snap_revision,
        }

    def test_push_revision_cached_with_experimental_deltas(self):
        # Upload
        result = self.run_command(["push", self.snap_file])

        self.assertThat(result.exit_code, Equals(0))
        snap_cache = os.path.join(
            BaseDirectory.xdg_cache_home,
            "snapcraft",
            "projects",
            "basic",
            "snap_hashes",
            "amd64",
        )
        cached_snap = os.path.join(
            snap_cache, file_utils.calculate_sha3_384(self.snap_file)
        )

        self.assertThat(cached_snap, FileExists())

    def test_push_revision_uses_available_delta(self):
        # Push
        result = self.run_command(["push", self.snap_file])

        self.assertThat(result.exit_code, Equals(0))

        # Push again
        result = self.run_command(["push", self.snap_file])

        self.assertThat(result.exit_code, Equals(0))
        _, kwargs = self.fake_store_upload.mock.call_args
        self.assertThat(kwargs.get("delta_format"), Equals("xdelta3"))

    def test_push_with_delta_generation_failure_falls_back(self):
        # Upload and ensure fallback is called
        with mock.patch(
            "snapcraft._store._push_delta",
            side_effect=StoreDeltaApplicationError("error"),
        ):
            result = self.run_command(["push", self.snap_file])

        self.assertThat(result.exit_code, Equals(0))
        self.fake_store_upload.mock.assert_called_once_with(
            snap_name="basic",
            snap_filename=self.snap_file,
            built_at=None,
            channels=[],
            delta_format=None,
            delta_hash=None,
            source_hash=None,
            target_hash=None,
        )

    def test_push_with_delta_upload_failure_falls_back(self):
        # Upload
        result = self.run_command(["push", self.snap_file])

        self.assertThat(result.exit_code, Equals(0))

        result = {
            "code": "processing_upload_delta_error",
            "errors": [{"message": "Delta service failed to apply delta within 60s"}],
        }
        self.mock_tracker.raise_for_code.side_effect = [
            storeapi.errors.StoreReviewError(result=result),
            None,
        ]

        # Upload and ensure fallback is called
        result = self.run_command(["push", self.snap_file])

        self.assertThat(result.exit_code, Equals(0))
        self.fake_store_upload.mock.assert_has_calls(
            [
                mock.call(
                    snap_name="basic",
                    snap_filename=mock.ANY,
                    built_at=None,
                    channels=[],
                    delta_format="xdelta3",
                    delta_hash=mock.ANY,
                    source_hash=mock.ANY,
                    target_hash=mock.ANY,
                ),
                mock.call(
                    snap_name="basic",
                    snap_filename=self.snap_file,
                    built_at=None,
                    channels=[],
                    delta_format=None,
                    delta_hash=None,
                    source_hash=None,
                    target_hash=None,
                ),
            ]
        )

    def test_push_with_disabled_delta_falls_back(self):
        # Upload
        result = self.run_command(["push", self.snap_file])

        self.assertThat(result.exit_code, Equals(0))

        class _FakeResponse:
            status_code = 501

            def json(self):
                return {
                    "error_list": [
                        {
                            "code": "feature-disabled",
                            "message": "The delta upload support is currently disabled.",
                        }
                    ]
                }

        self.fake_store_upload.mock.side_effect = [
            storeapi.errors.StoreServerError(_FakeResponse()),
            self.mock_tracker,
        ]

        # Upload and ensure fallback is called
        with mock.patch("snapcraft.storeapi._status_tracker.StatusTracker"):
            result = self.run_command(["push", self.snap_file])
        self.assertThat(result.exit_code, Equals(0))
        self.fake_store_upload.mock.assert_has_calls(
            [
                mock.call(
                    snap_name="basic",
                    snap_filename=mock.ANY,
                    built_at=None,
                    channels=[],
                    delta_format="xdelta3",
                    delta_hash=mock.ANY,
                    source_hash=mock.ANY,
                    target_hash=mock.ANY,
                ),
                mock.call(
                    snap_name="basic",
                    snap_filename=self.snap_file,
                    built_at=None,
                    channels=[],
                    delta_format=None,
                    delta_hash=None,
                    source_hash=None,
                    target_hash=None,
                ),
            ]
        )


class PushCommandDeltasWithPruneTestCase(PushCommandBaseTestCase):

    scenarios = [
        (
            "delete other cache files with valid name",
            {
                "cached_snaps": [
                    "a-cached-snap_0.3_{}_8.snap",
                    "another-cached-snap_1.0_fakearch_6.snap",
                ]
            },
        ),
        (
            "delete other cache files with invalid name",
            {
                "cached_snaps": [
                    "a-cached-snap_0.3_{}.snap",
                    "cached-snap-without-revision_1.0_fakearch.snap",
                    "another-cached-snap-without-version_fakearch.snap",
                ]
            },
        ),
    ]

    def test_push_revision_prune_snap_cache(self):
        snap_revision = 9

        self.mock_tracker.track.return_value = {
            "code": "ready_to_release",
            "processed": True,
            "can_release": True,
            "url": "/fake/url",
            "revision": snap_revision,
        }

        deb_arch = "amd64"

        snap_cache = os.path.join(
            BaseDirectory.xdg_cache_home,
            "snapcraft",
            "projects",
            "basic",
            "snap_hashes",
            deb_arch,
        )
        os.makedirs(snap_cache)

        for cached_snap in self.cached_snaps:
            cached_snap = cached_snap.format(deb_arch)
            open(os.path.join(snap_cache, cached_snap), "a").close()

        # Upload
        result = self.run_command(["push", self.snap_file])

        self.assertThat(result.exit_code, Equals(0))

        real_cached_snap = os.path.join(
            snap_cache, file_utils.calculate_sha3_384(self.snap_file)
        )

        self.assertThat(os.path.join(snap_cache, real_cached_snap), FileExists())

        for snap in self.cached_snaps:
            snap = snap.format(deb_arch)
            self.assertThat(os.path.join(snap_cache, snap), Not(FileExists()))
        self.assertThat(len(os.listdir(snap_cache)), Equals(1))
