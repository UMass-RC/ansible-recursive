Recursively calls `ansible.builtin.template` on every file in `templates_root`.

Path relative to `templates_root` becomes relative to `/` on remote host.

Example:

```yml
- name: install templates
  unity.template_recursive.template_recursive:
    templates_root: /path/to/templates
    mode: "0644" # defaults to 644, ignores umask
    new_dir_mode: "0755" # defaults to 755, ignores umask
    owner: nobody # used for both new directory and template
    group: nobody # used for both new directory and template
```
