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

import copy
import contextlib
import itertools
import logging
import os
import re
import shlex
import shutil
import stat
import subprocess
from typing import Any, Dict, List, Optional, Set  # noqa

from snapcraft import file_utils, formatting_utils, yaml_utils
from snapcraft import shell_utils, extractors
from snapcraft.project import _schema
from snapcraft.internal import common, errors, project_loader
from snapcraft.internal.project_loader import _config
from snapcraft.extractors import _metadata
from snapcraft.internal.deprecations import handle_deprecation_notice
from snapcraft.internal.meta import errors as meta_errors, _manifest, _version
from snapcraft.internal.meta.snap import Snap

logger = logging.getLogger(__name__)


# From snapd's snap/validate.go, appContentWhitelist, with a slight modification: don't
# allow leading slashes.
_APP_COMMAND_PATTERN = re.compile("^[A-Za-z0-9. _#:$-][A-Za-z0-9/. _#:$-]*$")


def create_snap_packaging(project_config: _config.Config) -> str:
    """Create snap.yaml and related assets in meta.

    Create the meta directory and provision it with snap.yaml in the snap dir
    using information from config_data. Also copy in the local 'snap'
    directory, and generate wrappers for hooks coming from parts.

    :param dict config_data: project values defined in snapcraft.yaml.
    :return: meta_dir.
    """

    # Update config_data using metadata extracted from the project
    extracted_metadata = _update_yaml_with_extracted_metadata(
        project_config.data, project_config.parts, project_config.project.prime_dir
    )

    # Now that we've updated config_data with random stuff extracted from
    # parts, re-validate it to ensure the it still conforms with the schema.
    validator = _schema.Validator(project_config.data)
    validator.validate(source="properties")

    # Update default values
    _update_yaml_with_defaults(project_config.data, project_config.validator.schema)

    packaging = _SnapPackaging(project_config, extracted_metadata)
    packaging.cleanup()
    packaging.validate_common_ids()
    packaging.finalize_snap_meta_commands()
    packaging.finalize_snap_meta_command_chains()
    packaging.finalize_snap_meta_version()
    packaging.write_snap_yaml()
    packaging.setup_assets()
    packaging.generate_hook_wrappers()
    packaging.write_snap_directory()

    return packaging.meta_dir


def _update_yaml_with_extracted_metadata(
    config_data: Dict[str, Any],
    parts_config: project_loader.PartsConfig,
    prime_dir: str,
) -> Optional[extractors.ExtractedMetadata]:
    if "adopt-info" not in config_data:
        return None

    part_name = config_data["adopt-info"]
    part = parts_config.get_part(part_name)
    if not part:
        raise meta_errors.AdoptedPartMissingError(part_name)

    pull_state = part.get_pull_state()
    build_state = part.get_build_state()
    stage_state = part.get_stage_state()
    prime_state = part.get_prime_state()

    # Get the metadata from the pull step first.
    metadata = pull_state.extracted_metadata["metadata"]

    # Now update it using the metadata from the build step (i.e. the data
    # from the build step takes precedence over the pull step).
    metadata.update(build_state.extracted_metadata["metadata"])

    # Now make sure any scriptlet data are taken into account. Later steps
    # take precedence, and scriptlet data (even in earlier steps) take
    # precedence over extracted data.
    metadata.update(pull_state.scriptlet_metadata)
    metadata.update(build_state.scriptlet_metadata)
    metadata.update(stage_state.scriptlet_metadata)
    metadata.update(prime_state.scriptlet_metadata)

    if not metadata:
        # If we didn't end up with any metadata, let's ensure this part was
        # actually supposed to parse info. If not, let's try to be very
        # clear about what's happening, here. We do this after checking for
        # metadata because metadata could be supplied by scriptlets, too.
        if "parse-info" not in config_data["parts"][part_name]:
            raise meta_errors.AdoptedPartNotParsingInfo(part_name)

    _adopt_info(config_data, metadata, prime_dir)

    return metadata


def _adopt_info(
    config_data: Dict[str, Any],
    extracted_metadata: _metadata.ExtractedMetadata,
    prime_dir: str,
):
    ignored_keys = _adopt_keys(config_data, extracted_metadata, prime_dir)
    if ignored_keys:
        logger.warning(
            "The {keys} {plural_property} {plural_is} specified in adopted "
            "info as well as the YAML: taking the {plural_property} from the "
            "YAML".format(
                keys=formatting_utils.humanize_list(list(ignored_keys), "and"),
                plural_property=formatting_utils.pluralize(
                    ignored_keys, "property", "properties"
                ),
                plural_is=formatting_utils.pluralize(ignored_keys, "is", "are"),
            )
        )


def _adopt_keys(
    config_data: Dict[str, Any],
    extracted_metadata: _metadata.ExtractedMetadata,
    prime_dir: str,
) -> Set[str]:
    ignored_keys = set()
    metadata_dict = extracted_metadata.to_dict()

    # desktop_file_paths and common_ids are special cases that will be handled
    # after all the top level snapcraft.yaml keys.
    ignore = ("desktop_file_paths", "common_id")
    overrides = ((k, v) for k, v in metadata_dict.items() if k not in ignore)

    for key, value in overrides:
        if key not in config_data:
            if key == "icon":
                # Extracted appstream icon paths will be relative to the runtime tree,
                # so rebase it on the snap source root.
                value = os.path.join(prime_dir, str(value))
                if _icon_file_exists() or not os.path.exists(str(value)):
                    # Do not overwrite the icon file.
                    continue
            config_data[key] = value
        else:
            ignored_keys.add(key)

    if "desktop_file_paths" in metadata_dict and "common_id" in metadata_dict:
        app_name = _get_app_name_from_common_id(
            config_data, str(metadata_dict["common_id"])
        )
        if app_name and not _desktop_file_exists(app_name):
            for desktop_file_path in [
                os.path.join(prime_dir, d) for d in metadata_dict["desktop_file_paths"]
            ]:
                if os.path.exists(desktop_file_path):
                    config_data["apps"][app_name]["desktop"] = desktop_file_path
                    break

    return ignored_keys


def _icon_file_exists() -> bool:
    """Check if the icon is specified as a file in the assets dir.

    The icon file can be in two directories: 'setup/gui' (deprecated) or
    'snap/gui'. The icon can be named 'icon.png' or 'icon.svg'.

    :returns: True if the icon file exists, False otherwise.
    """
    for icon_path in (
        os.path.join(asset_dir, "gui", icon_file)
        for (asset_dir, icon_file) in itertools.product(
            ["setup", "snap"], ["icon.png", "icon.svg"]
        )
    ):
        if os.path.exists(icon_path):
            return True
    else:
        return False


def _get_app_name_from_common_id(config_data: Dict[str, Any], common_id: str) -> str:
    """Get the snap app name with a common-id.

    :params dict config_data: Project values defined in snapcraft.yaml.
    :params common_id: The common identifier across multiple packaging
        formats.
    :returns: The name of the snap app with the common-id.

    """
    if "apps" in config_data:
        for app in config_data["apps"]:
            if config_data["apps"][app].get("common-id") == common_id:
                return app
    return None


def _desktop_file_exists(app_name: str) -> bool:
    """Check if the desktop file is specified as a file in the assets dir.

    The desktop file can be in two directories: 'setup/gui' (deprecated) or
    'snap/gui'.

    :params app_name: The name of the snap app.
    :returns: True if the desktop file exists, False otherwise.
    """
    for desktop_path in (
        os.path.join(asset_dir, "gui", "{}.desktop".format(app_name))
        for asset_dir in ["setup", "snap"]
    ):
        if os.path.exists(desktop_path):
            return True
    else:
        return False


def _update_yaml_with_defaults(config_data, schema):
    # Ensure that grade and confinement have their defaults applied, if
    # necessary. Defaults are taken from the schema. Technically these are the
    # only two optional keywords currently WITH defaults, but we don't want to
    # risk setting something that we add later on accident.
    for key in ("confinement", "grade"):
        if key not in config_data:
            with contextlib.suppress(KeyError):
                default = schema[key]["default"]
                config_data[key] = default
                logger.warn(
                    "{!r} property not specified: defaulting to {!r}".format(
                        key, default
                    )
                )

    # Set default adapter
    app_schema = schema["apps"]["patternProperties"]["^[a-zA-Z0-9](?:-?[a-zA-Z0-9])*$"][
        "properties"
    ]
    default_adapter = app_schema["adapter"]["default"]
    for app in config_data.get("apps", {}).values():
        if "adapter" not in app and "command-chain" not in app:
            app["adapter"] = default_adapter
        elif "adapter" not in app and "command-chain" in app:
            app["adapter"] = "full"


def _check_passthrough_duplicates_section(yaml: Dict[str, Any]) -> None:
    # Any value already in the original dictionary must
    # not be specified in passthrough at the same time.
    if "passthrough" not in yaml:
        return

    passthrough = yaml["passthrough"]
    duplicates = list(yaml.keys() & passthrough.keys())
    if duplicates:
        raise meta_errors.AmbiguousPassthroughKeyError(duplicates)


def _check_passthrough_duplicates(snap_yaml: Dict[str, Any]) -> None:
    """Check passthrough properties for duplicate keys.

    Passthrough options may override assumed/extracted configuration,
    so this check must be done on the original YAML."""

    for section in ["apps", "hooks"]:
        if section not in snap_yaml:
            continue

        for value in snap_yaml[section].values():
            _check_passthrough_duplicates_section(value)

    _check_passthrough_duplicates_section(snap_yaml)


class _SnapPackaging:
    def __init__(
        self,
        project_config: _config.Config,
        extracted_metadata: _metadata.ExtractedMetadata,
    ) -> None:
        self._project_config = project_config
        self._extracted_metadata = extracted_metadata
        self._snapcraft_yaml_path = project_config.project.info.snapcraft_yaml_file_path
        self._prime_dir = project_config.project.prime_dir
        self._parts_dir = project_config.project.parts_dir

        self._arch_triplet = project_config.project.arch_triplet
        self._global_state_file = project_config.project._get_global_state_file_path()
        self._is_host_compatible_with_base = (
            project_config.project.is_host_compatible_with_base
        )
        self.meta_dir = os.path.join(self._prime_dir, "meta")
        self.meta_gui_dir = os.path.join(self.meta_dir, "gui")
        self._config_data = project_config.data.copy()
        self._original_snapcraft_yaml = project_config.project.info.get_raw_snapcraft()

        self._install_path_pattern = re.compile(
            r"{}/[a-z0-9][a-z0-9+-]*/install".format(re.escape(self._parts_dir))
        )

        os.makedirs(self.meta_dir, exist_ok=True)

        # TODO: create_snap_packaging managles config data, so we create
        # a new private instance of snap_meta.  Longer term, this needs
        # to converge with project's snap_meta.
        self._snap_meta = Snap.from_dict(project_config.data)

    def cleanup(self):
        if os.path.exists(self.meta_gui_dir):
            for f in os.listdir(self.meta_gui_dir):
                if os.path.splitext(f)[1] == ".desktop":
                    os.remove(os.path.join(self.meta_gui_dir, f))

    def finalize_snap_meta_commands(self) -> None:
        for app_name, app in self._snap_meta.apps.items():
            app.prime_commands(
                base=self._project_config.project.info.base, prime_dir=self._prime_dir
            )

    def finalize_snap_meta_command_chains(self) -> None:
        prepend_command_chain = self._generate_command_chain()
        for app_name, app in self._snap_meta.apps.items():
            app.prepend_command_chain = prepend_command_chain

    def finalize_snap_meta_version(self) -> None:
        # Reparse the version, the order should stick.
        version = self._config_data["version"]
        version_script = self._config_data.get("version-script")

        if version_script:
            # Deprecation warning for use of version-script.
            handle_deprecation_notice("dn10")

        self._snap_meta.version = _version.get_version(version, version_script)

    def write_snap_yaml(self) -> None:
        # Ensure snap meta is valid before writing.
        self._snap_meta.validate()
        _check_passthrough_duplicates(self._original_snapcraft_yaml)

        package_snap_path = os.path.join(self.meta_dir, "snap.yaml")
        self._snap_meta.write_snap_yaml(path=package_snap_path)

    def setup_assets(self) -> None:
        # We do _setup_from_setup first since it is legacy and let the
        # declarative items take over.
        self._setup_gui()

        # Extracted metadata (e.g. from the AppStream) can override the
        # icon location.
        if self._extracted_metadata:
            icon_path = self._extracted_metadata.get_icon()
        else:
            icon_path = None

        snap_name = self._project_config.project.info.name
        for app_name, app in self._snap_meta.apps.items():
            app.write_command_wrappers(prime_dir=self._prime_dir)
            app.write_application_desktop_file(
                snap_name=snap_name,
                prime_dir=self._prime_dir,
                gui_dir=self.meta_gui_dir,
                icon_path=icon_path,
            )
            app.validate_command_chain_executables(self._prime_dir)

        if "icon" in self._config_data:
            # TODO: use developer.ubuntu.com once it has updated documentation.
            icon_ext = self._config_data["icon"].split(os.path.extsep)[-1]
            icon_path = os.path.join(self.meta_gui_dir, "icon.{}".format(icon_ext))
            os.makedirs(self.meta_gui_dir, exist_ok=True)
            if os.path.exists(icon_path):
                os.unlink(icon_path)
            file_utils.link_or_copy(self._config_data["icon"], icon_path)

        if self._config_data.get("type", "") == "gadget":
            if not os.path.exists("gadget.yaml"):
                raise errors.MissingGadgetError()
            file_utils.link_or_copy(
                "gadget.yaml", os.path.join(self.meta_dir, "gadget.yaml")
            )

    def _generate_command_chain(self) -> List[str]:
        command_chain = list()
        # Classic confinement or building on a host that does not match the target base
        # means we cannot setup an environment that will work.
        if (
            self._config_data["confinement"] == "classic"
            or not self._is_host_compatible_with_base
            or not self._snap_meta.apps
        ):
            assembled_env = None
        else:
            meta_runner = os.path.join(
                self._prime_dir, "snap", "command-chain", "snapcraft-runner"
            )

            common.env = self._project_config.snap_env()
            assembled_env = common.assemble_env()
            assembled_env = assembled_env.replace(self._prime_dir, "$SNAP")
            assembled_env = self._install_path_pattern.sub("$SNAP", assembled_env)

            if assembled_env:
                os.makedirs(os.path.dirname(meta_runner), exist_ok=True)
                with open(meta_runner, "w") as f:
                    print("#!/bin/sh", file=f)
                    print(assembled_env, file=f)
                    print(
                        "export LD_LIBRARY_PATH=$SNAP_LIBRARY_PATH:$LD_LIBRARY_PATH",
                        file=f,
                    )
                    print('exec "$@"', file=f)
                os.chmod(meta_runner, 0o755)

            common.reset_env()
            command_chain.append(os.path.relpath(meta_runner, self._prime_dir))

        return command_chain

    def _record_manifest_and_source_snapcraft_yaml(self):
        prime_snap_dir = os.path.join(self._prime_dir, "snap")
        recorded_snapcraft_yaml_path = os.path.join(prime_snap_dir, "snapcraft.yaml")
        if os.path.isfile(recorded_snapcraft_yaml_path):
            os.unlink(recorded_snapcraft_yaml_path)
        manifest_file_path = os.path.join(prime_snap_dir, "manifest.yaml")
        if os.path.isfile(manifest_file_path):
            os.unlink(manifest_file_path)

        # FIXME hide this functionality behind a feature flag for now
        if os.environ.get("SNAPCRAFT_BUILD_INFO"):
            os.makedirs(prime_snap_dir, exist_ok=True)
            shutil.copy2(self._snapcraft_yaml_path, recorded_snapcraft_yaml_path)
            annotated_snapcraft = _manifest.annotate_snapcraft(
                self._project_config.project, copy.deepcopy(self._config_data)
            )
            with open(manifest_file_path, "w") as manifest_file:
                yaml_utils.dump(annotated_snapcraft, stream=manifest_file)

    def write_snap_directory(self) -> None:
        snap_assets_dir = self._project_config.project._get_snapcraft_assets_dir()
        prime_snap_dir = os.path.join(self._prime_dir, "snap")

        snap_dir_iter = itertools.product([prime_snap_dir], ["hooks"])
        meta_dir_iter = itertools.product([self.meta_dir], ["hooks", "gui"])

        for origin in itertools.chain(snap_dir_iter, meta_dir_iter):
            src_dir = os.path.join(snap_assets_dir, origin[1])
            dst_dir = os.path.join(origin[0], origin[1])
            if os.path.isdir(src_dir):
                os.makedirs(dst_dir, exist_ok=True)
                for asset in os.listdir(src_dir):
                    source = os.path.join(src_dir, asset)
                    destination = os.path.join(dst_dir, asset)

                    with contextlib.suppress(FileNotFoundError):
                        os.remove(destination)

                    file_utils.link_or_copy(source, destination, follow_symlinks=True)

                    # Ensure that the hook is executable in meta/hooks, this is a moot
                    # point considering the prior link_or_copy call, but is technically
                    # correct and allows for this operation to take place only once.
                    if origin[0] == self.meta_dir and origin[1] == "hooks":
                        _prepare_hook(destination)

        self._record_manifest_and_source_snapcraft_yaml()

    def generate_hook_wrappers(self) -> None:
        snap_hooks_dir = os.path.join(self._prime_dir, "snap", "hooks")
        hooks_dir = os.path.join(self._prime_dir, "meta", "hooks")
        if os.path.isdir(snap_hooks_dir):
            os.makedirs(hooks_dir, exist_ok=True)
            for hook_name in os.listdir(snap_hooks_dir):
                file_path = os.path.join(snap_hooks_dir, hook_name)
                # Make sure the hook is executable
                _prepare_hook(file_path)

                hook_exec = os.path.join("$SNAP", "snap", "hooks", hook_name)
                hook_path = os.path.join(hooks_dir, hook_name)
                with contextlib.suppress(FileNotFoundError):
                    os.remove(hook_path)

                self._write_wrap_exe(hook_exec, hook_path)

    def _setup_gui(self):
        # Handles the setup directory which only contains gui assets.
        setup_dir = "setup"
        if not os.path.exists(setup_dir):
            return

        handle_deprecation_notice("dn3")

        gui_src = os.path.join(setup_dir, "gui")
        if os.path.exists(gui_src):
            for f in os.listdir(gui_src):
                if not os.path.exists(self.meta_gui_dir):
                    os.mkdir(self.meta_gui_dir)
                shutil.copy2(os.path.join(gui_src, f), self.meta_gui_dir)

    def _write_wrap_exe(self, wrapexec, wrappath, shebang=None, args=None, cwd=None):
        if args:
            quoted_args = ['"{}"'.format(arg) for arg in args]
        else:
            quoted_args = []
        args = " ".join(quoted_args) + ' "$@"' if args else '"$@"'
        cwd = "cd {}".format(cwd) if cwd else ""

        executable = '"{}"'.format(wrapexec)

        if shebang:
            if shebang.startswith("/usr/bin/env "):
                shebang = shell_utils.which(shebang.split()[1])
            new_shebang = self._install_path_pattern.sub("$SNAP", shebang)
            new_shebang = re.sub(self._prime_dir, "$SNAP", new_shebang)
            if new_shebang != shebang:
                # If the shebang was pointing to and executable within the
                # local 'parts' dir, have the wrapper script execute it
                # directly, since we can't use $SNAP in the shebang itself.
                executable = '"{}" "{}"'.format(new_shebang, wrapexec)

        with open(wrappath, "w+") as f:
            print("#!/bin/sh", file=f)
            if cwd:
                print("{}".format(cwd), file=f)
            print("exec {} {}".format(executable, args), file=f)

        os.chmod(wrappath, 0o755)

    def _wrap_exe(self, command, basename=None):
        execparts = shlex.split(command)
        exepath = os.path.join(self._prime_dir, execparts[0])
        if basename:
            wrappath = os.path.join(self._prime_dir, basename) + ".wrapper"
        else:
            wrappath = exepath + ".wrapper"
        shebang = None

        if os.path.exists(wrappath):
            os.remove(wrappath)

        wrapexec = "$SNAP/{}".format(execparts[0])
        if not os.path.exists(exepath) and "/" not in execparts[0]:
            _find_bin(execparts[0], self._prime_dir)
            wrapexec = execparts[0]
        else:
            with open(exepath, "rb") as exefile:
                # If the file has a she-bang, the path might be pointing to
                # the local 'parts' dir. Extract it so that _write_wrap_exe
                # will have a chance to rewrite it.
                if exefile.read(2) == b"#!":
                    shebang = exefile.readline().strip().decode("utf-8")

        self._write_wrap_exe(wrapexec, wrappath, shebang=shebang, args=execparts[1:])

        return os.path.relpath(wrappath, self._prime_dir)

    def validate_common_ids(self) -> None:
        if (
            not self._extracted_metadata
            or not self._extracted_metadata.common_id_list
            or "apps" not in self._config_data
        ):
            return

        common_id_list = self._extracted_metadata.common_id_list
        for app in self._config_data["apps"]:
            app_common_id = self._config_data["apps"][app].get("common-id")
            if app_common_id not in common_id_list:
                logger.warning(
                    "Common ID {common_id!r} specified in app {app!r} is "
                    "not used in any metadata file.".format(
                        common_id=app_common_id, app=app
                    )
                )


def _find_bin(binary, basedir):
    # If it doesn't exist it might be in the path
    logger.debug("Checking that {!r} is in the $PATH".format(binary))
    try:
        shell_utils.which(binary, cwd=basedir)
    except subprocess.CalledProcessError:
        raise meta_errors.CommandError(binary)


def _prepare_hook(hook_path):
    # Ensure hook is executable
    if not os.stat(hook_path).st_mode & stat.S_IEXEC:
        os.chmod(hook_path, 0o755)
