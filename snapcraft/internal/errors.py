# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2016-2018 Canonical Ltd
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

from abc import ABC, abstractmethod
from snapcraft import formatting_utils
from snapcraft.internal import steps
from subprocess import CalledProcessError
from typing import Dict, List, Union, Optional


class SnapcraftError(Exception):
    """DEPRECATED: Use SnapcraftException instead."""

    fmt = "Daughter classes should redefine this"

    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __str__(self):
        return self.fmt.format([], **self.__dict__)

    def get_exit_code(self):
        """Exit code to use if this exception causes Snapcraft to exit."""
        return 2


class SnapcraftReportableError(SnapcraftError):
    """DEPRECATED: Use SnapcraftException instead with reportable=True."""


class SnapcraftException(Exception, ABC):
    """Base class for Snapcraft Exceptions."""

    @abstractmethod
    def get_brief(self) -> str:
        """Concise, single-line description of the error."""

    @abstractmethod
    def get_resolution(self) -> str:
        """Concise suggestion for user to resolve error."""

    def get_details(self) -> Optional[str]:
        """Detailed technical information, if required for user to debug issue."""
        return None

    def get_docs_url(self) -> Optional[str]:
        """Link to documentation on docs.snapcraft.io, if applicable."""
        return None

    def get_exit_code(self) -> int:
        """Exit code to use when exiting snapcraft due to this exception."""
        return 2

    def get_reportable(self) -> bool:
        """Defines if error is reportable (an exception trace should be shown)."""
        return False

    def __str__(self) -> str:
        return self.get_brief()


class MissingStateCleanError(SnapcraftError):
    fmt = (
        "Failed to clean: "
        "Missing state for {step.name!r}. "
        "To clean the project, run `snapcraft clean`."
    )

    def __init__(self, step):
        super().__init__(step=step)


class StepOutdatedError(SnapcraftError):

    fmt = (
        "Failed to reuse files from previous run: "
        "The {step.name!r} step of {part!r} is out of date:\n"
        "{report}"
        "To continue, clean that part's {step.name!r} step by running "
        "`snapcraft clean {parts_names} -s {step.name}`."
    )

    def __init__(
        self, *, step, part, dirty_report=None, outdated_report=None, dependents=None
    ):
        messages = []

        if dirty_report:
            messages.append(dirty_report.get_report())

        if outdated_report:
            messages.append(outdated_report.get_report())

        if dependents:
            humanized_dependents = formatting_utils.humanize_list(dependents, "and")
            pluralized_dependents = formatting_utils.pluralize(
                dependents, "depends", "depend"
            )
            messages.append(
                "The {0!r} step for {1!r} needs to be run again, "
                "but {2} {3} on it.\n".format(
                    step.name, part, humanized_dependents, pluralized_dependents
                )
            )
            parts_names = ["{!s}".format(d) for d in sorted(dependents)]
        else:
            parts_names = [part]

        super().__init__(
            step=step,
            part=part,
            report="".join(messages),
            parts_names=" ".join(parts_names),
        )


class SnapcraftEnvironmentError(SnapcraftError):
    # FIXME This exception is too generic.
    # https://bugs.launchpad.net/snapcraft/+bug/1734231
    # --elopio - 20171123

    fmt = "{message}"

    def __init__(self, message):
        super().__init__(message=message)


class SnapcraftDataDirectoryMissingError(SnapcraftReportableError):
    fmt = (
        "Cannot find snapcraft's data files required for proper operation.\n"
        "Please re-install snapcraft or verify installation is correct."
    )


class SnapcraftMissingLinkerInBaseError(SnapcraftError):

    fmt = (
        "Cannot find the linker to use for the target base {base!r}.\n"
        "Please verify that the linker exists at the expected path "
        "{linker_path!r} and try again. If the linker does not exist "
        "contact the author of the base (run `snap info {base}` to get "
        "information for this base)."
    )

    def __init__(self, *, base, linker_path):
        super().__init__(base=base, linker_path=linker_path)


class IncompatibleBaseError(SnapcraftError):
    fmt = (
        "The linker version {linker_version!r} used by the base {base!r} is "
        "incompatible with files in this snap:\n"
        "{file_list}"
    )

    def __init__(
        self, *, base: str, linker_version: str, file_list: Dict[str, str]
    ) -> None:
        spaced_file_list = ("    {} ({})".format(k, v) for k, v in file_list.items())
        super().__init__(
            base=base,
            linker_version=linker_version,
            file_list="\n".join(sorted(spaced_file_list)),
        )


class PrimeFileConflictError(SnapcraftError):

    fmt = (
        "Failed to filter files: "
        "The following files have been excluded by the `stage` keyword, "
        "but included by the `prime` keyword: {fileset!r}. "
        "Edit the `snapcraft.yaml` to make sure that the files included in "
        "`prime` are also included in `stage`."
    )


class PluginError(SnapcraftError):

    fmt = (
        "Failed to load plugin: "
        "{message}"
        # FIXME include how to fix each of the possible plugin errors.
        # https://bugs.launchpad.net/snapcraft/+bug/1727484
        # --elopio - 2017-10-25
    )

    def __init__(self, message):
        super().__init__(message=message)


class PluginBaseError(SnapcraftError):

    fmt = "The plugin used by part {part_name!r} does not support snaps using base {base!r}."

    def __init__(self, *, part_name, base):
        super().__init__(part_name=part_name, base=base)


class SnapcraftPartConflictError(SnapcraftError):

    fmt = (
        "Failed to stage: "
        "Parts {other_part_name!r} and {part_name!r} have the following "
        "files, but with different contents:\n"
        "{file_paths}\n\n"
        "Snapcraft offers some capabilities to solve this by use of the "
        "following keywords:\n"
        "    - `filesets`\n"
        "    - `stage`\n"
        "    - `snap`\n"
        "    - `organize`\n\n"
        "To learn more about these part keywords, run "
        "`snapcraft help plugins`."
    )

    def __init__(self, *, part_name, other_part_name, conflict_files):
        spaced_conflict_files = ("    {}".format(i) for i in conflict_files)
        super().__init__(
            part_name=part_name,
            other_part_name=other_part_name,
            file_paths="\n".join(sorted(spaced_conflict_files)),
        )


class SnapcraftOrganizeError(SnapcraftError):

    fmt = "Failed to organize part {part_name!r}: {message}"

    def __init__(self, part_name, message):
        super().__init__(part_name=part_name, message=message)


class MissingCommandError(SnapcraftError):

    fmt = (
        "Failed to run command: "
        "One or more packages are missing, please install:"
        " {required_commands!r}"
    )

    def __init__(self, required_commands):
        super().__init__(required_commands=required_commands)


class InvalidWikiEntryError(SnapcraftError):

    fmt = (
        "Invalid wiki entry: "
        "{error!r}"
        # FIXME include how to fix each of the possible wiki errors.
        # https://bugs.launchpad.net/snapcraft/+bug/1727490
        # --elopio - 2017-10-25
    )

    def __init__(self, error=None):
        super().__init__(error=error)


class MissingGadgetError(SnapcraftError):

    fmt = (
        "Failed to generate snap metadata: "
        "Missing gadget.yaml file.\n"
        "When creating gadget snaps you are required to provide a gadget.yaml "
        "file\n"
        "in the root of your snapcraft project\n\n"
        "Read more about gadget snaps and the gadget.yaml on:\n"
        "https://github.com/snapcore/snapd/wiki/Gadget-snap"
    )


class PluginOutdatedError(SnapcraftError):

    fmt = "This plugin is outdated: {message}"

    def __init__(self, message):
        super().__init__(message=message)


class ToolMissingError(SnapcraftReportableError):

    fmt = (
        "A tool snapcraft depends on could not be found: {command_name!r}.\n"
        "Ensure the tool is installed and available, and try again."
    )

    def __init__(self, *, command_name: str) -> None:
        super().__init__(command_name=command_name)


class RequiredCommandFailure(SnapcraftError):

    fmt = "{command!r} failed."


class RequiredCommandNotFound(SnapcraftError):

    fmt = "{cmd_list[0]!r} not found."


class RequiredPathDoesNotExist(SnapcraftError):

    fmt = "Required path does not exist: {path!r}"


class SnapcraftPathEntryError(SnapcraftError):

    fmt = (
        "Failed to generate snap metadata: "
        "The path {value!r} set for {key!r} in {app!r} does not exist. "
        "Make sure that the files are in the `prime` directory."
    )


class InvalidPullPropertiesError(SnapcraftError):

    fmt = (
        "Failed to load plugin: "
        "Invalid pull properties specified by {plugin_name!r} plugin: "
        "{properties}"
        # TODO add a link to some docs about pull properties?
        # --elopio - 2017-10-25
    )

    def __init__(self, plugin_name, properties):
        super().__init__(plugin_name=plugin_name, properties=properties)


class InvalidBuildPropertiesError(SnapcraftError):

    fmt = (
        "Failed to load plugin: "
        "Invalid build properties specified by {plugin_name!r} plugin: "
        "{properties}"
        # TODO add a link to some docs about build properties?
        # --elopio - 2017-10-25
    )

    def __init__(self, plugin_name, properties):
        super().__init__(plugin_name=plugin_name, properties=properties)


class StagePackageDownloadError(SnapcraftError):

    fmt = (
        "Failed to fetch stage packages: "
        "Error downloading packages for part {part_name!r}: {message}."
    )

    def __init__(self, part_name, message):
        super().__init__(part_name=part_name, message=message)


class OsReleaseIdError(SnapcraftError):

    fmt = "Unable to determine host OS ID"


class OsReleaseNameError(SnapcraftError):

    fmt = "Unable to determine host OS name"


class OsReleaseVersionIdError(SnapcraftError):

    fmt = "Unable to determine host OS version ID"


class OsReleaseCodenameError(SnapcraftError):

    fmt = "Unable to determine host OS version codename"


class InvalidContainerImageInfoError(SnapcraftError):

    fmt = (
        "Failed to parse container image info: "
        "SNAPCRAFT_IMAGE_INFO is not a valid JSON string: {image_info}"
    )

    def __init__(self, image_info: str) -> None:
        super().__init__(image_info=image_info)


class PatcherError(SnapcraftError):
    pass


class PatcherGenericError(PatcherError):

    fmt = (
        "{elf_file!r} cannot be patched to function properly in a classic "
        "confined snap: {message}"
    )

    def __init__(self, *, elf_file, process_exception):
        message = "{} failed with exit code {}".format(
            " ".join(process_exception.cmd), process_exception.returncode
        )
        super().__init__(elf_file=elf_file, message=message)


class PatcherNewerPatchelfError(PatcherError):

    fmt = (
        "{elf_file!r} cannot be patched to function properly in a classic "
        "confined snap: {message}.\n"
        "{patchelf_version!r} may be too old. A newer version of patchelf "
        "may be required.\n"
        "Try adding the `after: [patchelf]` and a `patchelf` part that would "
        "filter out files from prime `prime: [-*]` or "
        "`build-snaps: [patchelf/latest/edge]` to the failing part in your "
        "`snapcraft.yaml` to use a newer patchelf."
    )

    def __init__(self, *, elf_file, process_exception, patchelf_version):
        message = "{} failed with exit code {}".format(
            " ".join(process_exception.cmd), process_exception.returncode
        )
        super().__init__(
            elf_file=elf_file, message=message, patchelf_version=patchelf_version
        )


class StagePackageMissingError(SnapcraftError):

    fmt = (
        "{package!r} is required inside the snap for this part to work "
        "properly.\n"
        "Add it as a `stage-packages` entry for this part."
    )

    def __init__(self, *, package):
        super().__init__(package=package)


class MetadataExtractionError(SnapcraftError):
    pass


class MissingMetadataFileError(MetadataExtractionError):

    fmt = (
        "Failed to generate snap metadata: "
        "Part {part_name!r} has a 'parse-info' referring to metadata file "
        "{path!r}, which does not exist."
    )

    def __init__(self, part_name: str, path: str) -> None:
        super().__init__(part_name=part_name, path=path)


class UnhandledMetadataFileTypeError(MetadataExtractionError):

    fmt = (
        "Failed to extract metadata from {path!r}: "
        "This type of file is not supported for supplying metadata."
    )

    def __init__(self, path: str) -> None:
        super().__init__(path=path)


class InvalidExtractorValueError(MetadataExtractionError):

    fmt = (
        "Failed to extract metadata from {path!r}: "
        "Extractor {extractor_name!r} didn't return ExtractedMetadata as "
        "expected."
    )

    def __init__(self, path: str, extractor_name: str) -> None:
        super().__init__(path=path, extractor_name=extractor_name)


class SnapcraftCommandError(SnapcraftError, CalledProcessError):
    """Exception for generic command errors.

    Processes should capture this error for specific messaging.
    This exception carries the signature of CalledProcessError for backwards
    compatibility.
    """

    fmt = "Failed to run {command!r}: Exited with code {exit_code}."

    def __init__(self, *, command: str, call_error: CalledProcessError) -> None:
        super().__init__(command=command, exit_code=call_error.returncode)
        CalledProcessError.__init__(
            self,
            returncode=call_error.returncode,
            cmd=call_error.cmd,
            output=call_error.output,
            stderr=call_error.stderr,
        )


class SnapcraftPluginCommandError(SnapcraftError):
    """Command executed by a plugin fails."""

    fmt = (
        "Failed to run {command!r} for {part_name!r}: "
        "Exited with code {exit_code}.\n"
        "Verify that the part is using the correct parameters and try again."
    )

    def __init__(
        self, *, command: Union[List, str], part_name: str, exit_code: int
    ) -> None:
        if isinstance(command, list):
            command = " ".join(command)
        super().__init__(command=command, part_name=part_name, exit_code=exit_code)


class ScriptletBaseError(SnapcraftError):
    """Base class for all scriptlet-related exceptions.

    :cvar fmt: A format string that daughter classes override

    """


class ScriptletRunError(ScriptletBaseError):
    fmt = "Failed to run {scriptlet_name!r}: Exit code was {code}."

    def __init__(self, scriptlet_name: str, code: int) -> None:
        super().__init__(scriptlet_name=scriptlet_name, code=code)


class ScriptletDuplicateDataError(ScriptletBaseError):
    fmt = (
        "Failed to save data from scriptlet into {step.name!r} state: "
        "The {humanized_keys} key(s) were already saved in the "
        "{other_step.name!r} step."
    )

    def __init__(
        self, step: steps.Step, other_step: steps.Step, keys: List[str]
    ) -> None:
        self.keys = keys
        super().__init__(
            step=step,
            other_step=other_step,
            humanized_keys=formatting_utils.humanize_list(keys, "and"),
        )


class ScriptletDuplicateFieldError(ScriptletBaseError):
    fmt = "Unable to set {field}: it was already set in the {step.name!r} step."

    def __init__(self, field: str, step: steps.Step) -> None:
        super().__init__(field=field, step=step)


class SnapcraftctlError(ScriptletBaseError):
    fmt = "{message}"

    def __init__(self, message: str) -> None:
        super().__init__(message=message)


class SnapcraftInvalidCLIConfigError(SnapcraftError):

    fmt = "The cli configuration file {config_file!r} has invalid data: {error!r}."

    def __init__(self, *, config_file: str, error: str) -> None:
        super().__init__(config_file=config_file, error=error)
        # This is to keep mypy happy
        self.config_file = config_file


class SnapcraftCopyFileNotFoundError(SnapcraftError):
    fmt = (
        "Failed to copy {path!r}: no such file or directory.\n"
        "Check the path and try again."
    )

    def __init__(self, path):
        super().__init__(path=path)


class InvalidStepError(SnapcraftError):
    fmt = "{step_name!r} is not a valid lifecycle step"

    def __init__(self, step_name):
        super().__init__(step_name=step_name)


class StepHasNotRunError(SnapcraftError):
    fmt = "The {part_name!r} part has not yet run the {step.name!r} step"

    def __init__(self, part_name, step):
        super().__init__(part_name=part_name, step=step)


class NoLatestStepError(SnapcraftError):
    fmt = "The {part_name!r} part hasn't run any steps"

    def __init__(self, part_name):
        super().__init__(part_name=part_name)


class NoNextStepError(SnapcraftError):
    fmt = "The {part_name!r} part has run through its entire lifecycle"

    def __init__(self, part_name):
        super().__init__(part_name=part_name)


class MountPointNotFoundError(SnapcraftError):
    fmt = "Nothing is mounted at {mount_point!r}"

    def __init__(self, mount_point):
        super().__init__(mount_point=mount_point)


class RootNotMountedError(SnapcraftError):
    fmt = "{root!r} is not mounted"

    def __init__(self, root):
        super().__init__(root=root)


class InvalidMountinfoFormat(SnapcraftError):
    fmt = "Unable to parse mountinfo row: {row}"

    def __init__(self, row):
        super().__init__(row=row)


class CrossCompilationNotSupported(SnapcraftError):
    fmt = (
        "The plugin used by {part_name!r} does not support cross-compiling "
        "to a different target architecture."
    )

    def __init__(self, *, part_name: str) -> None:
        super().__init__(part_name=part_name)


class SnapDataExtractionError(SnapcraftError):
    fmt = "Cannot read data from snap {snap!r}. The file may be corrupted."

    def __init__(self, snap):
        super().__init__(snap=snap)


class ProjectNotFoundError(SnapcraftReportableError):
    fmt = "Failed to find project files."
