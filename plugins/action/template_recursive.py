from ansible.errors import AnsibleError
from ansible.module_utils._text import to_native
from ansible.plugins.action import ActionBase
from ansible.plugins.loader import action_loader
from ansible.playbook.task import Task

import os


def strip_end(text: str, suffix: str) -> str:
    if isinstance(suffix, str) and len(suffix) > 0 and text.endswith(suffix):
        return text[: -len(suffix)]
    else:
        return text


class ActionModule(ActionBase):

    def _does_remote_directory_exist(self, path: str, task_vars, follow_symlinks=True) -> bool:
        stats = self._execute_remote_stat(path, all_vars=task_vars, follow=follow_symlinks)
        return stats["exists"] and stats["isdir"]

    def _run_template_action(self, src: str, dest: str, tmp=None, task_vars=None) -> dict:
        template_task = self._task.copy()
        template_task.args["src"] = src
        template_task.args["dest"] = dest
        del template_task.args["templates_root"]
        if "new_dir_mode" in template_task.args:
            del template_task.args["new_dir_mode"]
        template_action = action_loader.get(
            "unity.template_multi_diff.template",
            task=template_task,
            connection=self._connection,
            play_context=self._play_context,
            loader=self._loader,
            templar=self._templar,
            shared_loader_obj=self._shared_loader_obj,
        )
        return template_action.run(tmp=tmp, task_vars=task_vars)

    def _create_directory(self, path, task_vars=None) -> dict:
        module_args = {
            "path": path,
            "state": "directory",
        }
        module_args["mode"] = self._task.args.get("new_dir_mode", "0755")
        if "owner" in self._task.args:
            module_args["owner"] = self._task.args["owner"]
        if "group" in self._task.args:
            module_args["group"] = self._task.args["group"]
        return self._execute_module(
            module_name="file",
            module_args=module_args,
            task_vars=task_vars,
        )

    def run(self, tmp=None, task_vars=None):
        result = super(ActionModule, self).run(tmp, task_vars)
        result["changed"] = False
        result["failed"] = False
        result["msg"] = ""
        result["diff"] = []

        def update_result_from_task(task_output: dict) -> None:
            if "changed" in task_output and task_output["changed"] is True:
                result["changed"] = True
            if "failed" in task_output and task_output["failed"] is True:
                result["failed"] = True
            if "msg" in task_output:
                result["msg"] += "\n"
                result["msg"] += task_output["msg"]
            if "diff" in task_output:
                if isinstance(task_output["diff"], list):
                    result["diff"] += task_output["diff"]
                else:
                    result["diff"].append(task_output["diff"])

        def result_failed(msg: str) -> dict:
            result["failed"] = True
            result["msg"] = msg
            return result

        try:
            templates_root = self._task.args["templates_root"]
        except KeyError:
            return result_failed("`templates_root` argument is required!")
        if not os.path.isdir(templates_root):
            return result_failed(f'"{templates_root}" is not a directory!')
        if "mode" not in self._task.args:
            self._task.args["mode"] = "0644"

        template_files = []
        for dirpath, dirnames, filenames in os.walk(templates_root):
            for filename in filenames:
                full_src_path = os.path.join(dirpath, filename)
                relative_src_path = os.path.relpath(full_src_path, templates_root)
                dest_path = os.path.join("/", relative_src_path)
                dest_path = strip_end(dest_path, ".j2")
                template_files.append((full_src_path, dest_path))

        dest_dirs = [os.path.dirname(x[1]) for x in template_files]
        for dest_dir in list(set(dest_dirs)):
            if not self._does_remote_directory_exist(dest_dir, task_vars):
                update_result_from_task(self._create_directory(dest_dir, task_vars=task_vars))
                if result["failed"]:
                    return result

        for src, dest in template_files:
            update_result_from_task(
                self._run_template_action(src, dest, tmp=tmp, task_vars=task_vars)
            )
            if result["failed"]:
                return result

        return result
