"""
description: |
  recursively copies a directory to remote host.
  the path of a file relative to `src_root` will become the absolute path on remote host.
  owner, group, and permissions are also overwritten on all remote parent directories, except root.
  this can be destructive, so be sure to use overrides and first dry-run in check mode.
required arguments:
  owner: posix username
  group: posix group name
  mode: |
    posix permissions. a string containing four digits between 0 and 7.
    in most use cases, the first digit is 0.
    all files in the tree will have these permissions, unless an override is specified.
  parent_dirs_mode: |
    same syntax as mode.
    all directories in the tree (except root) will have these permissions, unless an override is specified.
  src_root: |
    the absolute path on the ansible control node from which files should be copied
    the path of a file relative to `src_root` will become the absolute path on remote host
optional arguments:
  mode_overrides: |
    a dictionary where the key is a mode, and the value is a list of absolute paths on remote host
    all paths in the list must correspond to the files being copied or their parent directories.
  owner_overrides: same syntax as mode_overrides but with a posix username
  group_overrides: same syntax as mode_overrides but with a posix group name
"""

import os
import re
import platform

from ansible.plugins.action import ActionBase
from ansible.plugins.loader import action_loader

SUPPORTED_OS = ["linux", "darwin"]  # assume that root is "/"


def _get_all_parent_dirs(paths: list) -> list:
    output = []
    assert all(os.path.isabs(path) for path in paths), "all paths must be absolute"
    for path in paths:
        cursor = path
        while (dirname := os.path.dirname(cursor)) not in output:
            output.append(dirname)
            cursor = dirname
    return output


class ActionModule(ActionBase):
    def _get_mode(self, path: str, file_or_dir: str) -> str:
        assert file_or_dir in ["file", "dir"]
        for mode, paths in self._task.args["mode_overrides"].items():
            if path in paths:
                return mode
        if file_or_dir == "file":
            return self._task.args["mode"]
        else:
            return self._task.args["parent_dirs_mode"]

    def _get_owner(self, path) -> str:
        for owner, paths in self._task.args["owner_overrides"].items():
            if path in paths:
                return owner
        return self._task.args["owner"]

    def _get_group(self, path) -> str:
        for owner, paths in self._task.args["group_overrides"].items():
            if path in paths:
                return owner
        return self._task.args["group"]

    def _copy_chmod_chown(self, src: str, dest: str, tmp, task_vars) -> dict:
        copy_task = self._task.copy()
        copy_task.args = {
            "src": src,
            "dest": dest,
            "owner": self._get_owner(dest),
            "group": self._get_group(dest),
            "mode": self._get_mode(dest, "file"),
        }
        copy_action = action_loader.get(
            "unity.copy_multi_diff.copy",
            task=copy_task,
            connection=self._connection,
            play_context=self._play_context,
            loader=self._loader,
            templar=self._templar,
            shared_loader_obj=self._shared_loader_obj,
        )
        return copy_action.run(tmp=tmp, task_vars=task_vars)

    def _mkdir_chmod_chown(self, path: str, task_vars) -> dict:
        return self._execute_module(
            module_name="unity.file_multi_diff.file",
            module_args={
                "path": path,
                "state": "directory",
                "owner": self._get_owner(path),
                "group": self._get_group(path),
                "mode": self._get_mode(path, "dir"),
            },
            task_vars=task_vars,
        )

    def _update_result_from_task(self, task_output: dict) -> None:
        if task_output.get("changed", False) is True:
            self.result["changed"] = True
        if task_output.get("failed", False) is True:
            self.result["failed"] = True
        if "msg" in task_output:
            self.result["msg"] += "\n"
            self.result["msg"] += task_output["msg"]

        def _do_save_diff(_task_output: dict) -> bool:
            if "diff" not in _task_output:
                return False
            if _task_output.get("changed", False) is True:
                return True
            if (
                "before" in _task_output["diff"]
                and "after" in _task_output["diff"]
                and _task_output["diff"]["before"] == _task_output["diff"]["after"]
            ):
                return False
            return True

        if _do_save_diff(task_output):
            if isinstance(task_output["diff"], list):
                self.result["diff"] += task_output["diff"]
            else:
                self.result["diff"].append(task_output["diff"])

    def run(self, tmp=None, task_vars=None):
        self.result = super(ActionModule, self).run(tmp, task_vars)
        self.result["changed"] = False
        self.result["failed"] = False
        self.result["msg"] = ""
        self.result["diff"] = []

        def _result_failed(msg: str) -> dict:
            self.result["failed"] = True
            self.result["msg"] = msg
            return self.result

        this_os = platform.system().lower()
        if this_os not in SUPPORTED_OS:
            return _result_failed(f'unsupported OS: "{this_os}"')

        args = self._task.args
        supported_args = [
            "owner",
            "group",
            "mode",
            "parent_dirs_mode",
            "src_root",
            "mode_overrides",
            "owner_overrides",
            "group_overrides",
        ]
        required_args = ["owner", "group", "mode", "parent_dirs_mode", "src_root"]
        for arg_name in required_args:
            if arg_name not in args:
                return _result_failed(f'argument required: "{arg_name}"')
        for arg_name in args:
            if arg_name not in supported_args:
                return _result_failed(f'unsupported argument: "{arg_name}"')

        if not os.path.isdir(args["src_root"]):
            return _result_failed(f'"{args["src_root"]}" is not a directory!')
        for mode in [
            args["mode"],
            args["parent_dirs_mode"],
            *args.get("mode_overrides", {}).keys(),
        ]:
            if not isinstance(mode, str):
                return _result_failed(f'mode "{mode}" is not a string! found type: "{type(mode)}"')
            mode_regex = r"[0-7]{4}"
            if not re.fullmatch(mode_regex, mode):
                return _result_failed(f'mode "{mode}" does not match regex: "{mode_regex}"')

        for arg_name in ["mode_overrides", "owner_overrides", "group_overrides"]:
            if arg_name not in args:
                args[arg_name] = {}
        for arg_name in ["mode_overrides", "owner_overrides", "group_overrides"]:
            for override, paths in args[arg_name].items():
                args[arg_name] = {override: [x.rstrip("/") for x in paths]}

        src_dest_tuples = []
        for dirpath, dirnames, filenames in os.walk(args["src_root"]):
            for filename in filenames:
                full_src_path = os.path.join(dirpath, filename)
                relative_src_path = os.path.relpath(full_src_path, args["src_root"])
                dest_path = os.path.join("/", relative_src_path)
                src_dest_tuples.append((full_src_path, dest_path))

        destination_files = [x[1] for x in src_dest_tuples]
        # parent directories first
        destination_dirs = sorted(_get_all_parent_dirs(destination_files), key=len)
        destination_dirs.remove("/")  # don't mess with root directory
        destination_paths = destination_files + destination_dirs
        override_paths = set()
        for arg_name in ["mode_overrides", "owner_overrides", "group_overrides"]:
            for path_list in args[arg_name].values():
                for path in path_list:
                    override_paths.add(path)
        overrides_not_found = set(override_paths) - set(destination_paths)
        if len(overrides_not_found) > 0:
            return _result_failed(
                f"overrides specified for invalid paths: {overrides_not_found}. "
                + f"valid paths: {destination_paths}"
            )

        for dest_dir in destination_dirs:
            self._update_result_from_task(self._mkdir_chmod_chown(dest_dir, task_vars))
            if self.result["failed"]:
                return self.result

        for src, dest in src_dest_tuples:
            self._update_result_from_task(self._copy_chmod_chown(src, dest, tmp, task_vars))
            if self.result["failed"]:
                return self.result
        return self.result
