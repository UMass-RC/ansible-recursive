recursively calls `copy` or `template` using files in a local directory.

The builtin ansible `copy` action plugin does have recursive support, but it has some downsides:

* required that the source path ends in a slash
* preserves owner/group/mode on any existing remote directories, which means that the same task may produce different results on different remote hosts
* allows owner/group/mode to be undefined, which means that the same task may produce different results on different remote hosts
* uses the same owner/group/mode for all files
* allows [dubious permissions](https://ansible.readthedocs.io/projects/lint/rules/risky-octal/)
* calls the `stat` module once for each file, which is slow

The builtin ansible `synchronize` action plugin can also do recursive copies, but its diff output does not contain the actual changes made, only a list of files that were changed.

### WARNING: these plugins will set owner/group/mode on *all* parent directories of every file in your tree. You should always run these plugins in check mode first to see what the results will be. To avoid breaking parent directory permissions, use the override arguments.

```yml
required arguments:
  owner: posix username
  group: posix group name
  mode: |
    posix permissions. a string containing four digits between 0 and 7.
    in most use cases, the first digit is 0. A leading zero does **not** denote an octal number
    like in yaml number syntax, it represents special permissions like setuid.
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
```

### example

```yml
- name: install templates
  unity.recursive.r_template:
    src_root: "{{ playbook_dir }}/roles/bind/templates/auto-copy"
    mode: "0664"
    parent_dirs_mode: "0755"
    owner: root
    group: root
    mode_overrides:
      "2755": [/etc/bind] # setgid bit set by default from deb package
    owner_overrides:
      bind:
        - /etc/bind
        - /etc/bind/named.conf.options
        - /etc/bind/named.conf.local
    group_overrides:
      bind:
        - /etc/bind
        - /etc/bind/named.conf.options
        - /etc/bind/named.conf.local
  notify: reload bind9
```
