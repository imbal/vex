# Vex - A database for files 

Note: This is a work-in-progress, large chunks of this README are fictional. Please don't link to this project yet, it isn't ready for an audience yet. Thank you!

This README assumes some familiarily with `git`, `hg`, or `svn`

## Cheatsheet:

| vex | hg | git  |
| --- | --- | --- |
| `vex init`		| `hg init`		| `hg init` 	|
| `vex add`		| `hg add`		| `hg add` 	|
| `vex forget`		| `hg forget`		| `git remove --cached (-r)` 	|
| `vex status`		| `hg status`		| `git init` 	|
| `vex commit`		| `hg commit`		| `git init` 	|
| `vex log`		| `hg log`		| `git init` 	|
| ...			| ...			| ...		|
| `vex undo`		| `hg ???`		| `git ???` 	|
| `vex redo`		| `hg ???`		| `git ???` 	|
| `vex switch`		| `hg ???`		| `git ???` 	|

## `vex` vs ....

For `hg` users:

- `vex branch` works like `hg bookmark` or `git branch` 
- Almost everything else works the same on the outside (except `hg merge`)

For `git` users:

- branches that automatically stash and unstash
- a linear history without having to rebase or untangle merge commits
- using a modern hash algorithm
- tracks empty directories

For `svn` users:

- Like `git`, `hg`, offline and asynchronous commits.
- Files can have properties attached to them
- Subtree checkouts `vex switch <path>`

For everyone:

- `vex undo` undoes the last command that changed something
- for `vex commit`, it undoes the history but leaves the working copy alone
- for `vex switch`, it changes back to the old subtree checkout

- `vex redo` redoes the last undone command
- `vex redo --list` shows the potential options, `vex redo --choice=<n>` to pick one

## Workflows

### Creating a project

`vex init` or `vex init <directory>`. 

```
$ vex init . --include="*.py" --ignore="*.py?"
...
$ vex status
... # *.py files added and waiting for commit
```

By default, `vex init name` creates a repository with a `/name` directory inside. 

(Note: `vex undo`/`vex redo` will undo `vex init`, but leave the `/.vex` directory intact0


### Moving around the project

- `vex switch` (change repo subtree checkout)

- `vex mounts` (how repo paths map to working directory)

### Adding/removing files from the project

- `vex add`

- `vex forget`

- `vex remove`

- `vex ignore`


### Inspecting changes

- `vex log`

- `vex status`

- `vex diff`


### Saving changes

- `vex prepare` / `vex save`

- `vex prepare --watch`

- `vex commit`

- `vex amend`

- `--pick`

### Undoing changes

- `vex history` 

- `vex undo`

- `vex redo`

- `vex rollback`

- `vex revert`

### Working on a branch

- `vex open`

- `vex saveas` (see `git checkout -b`)

- `vex close`

- `vex branches`


### Merging work back

`vex` *always* creates a linear history:

- `vex apply`

   create a new commit with the changes from the other branch

- `vex replay` / `--pick`

   create a new commit for each change in the branch, reapplying the changes

- `vex append`

   create a new commit for each change in the other branch, as-is

### Working on an anonymous branch

- `vex session` (see all open branches/anonymous branches)

- `vex rewind` (like git checkout)


### Sharing changes

- `vex export`

- `vex import`

- `vex pull` 

- `vex push`

- `vex remotes`

- `vex remotes:add`

### Updating a branch

- `vex update` (--all affecting downstream branches too) 

- `vex sync`

### Handlng conflicts

- `vex update --manual`

### Handling mistakes, purging old commits

- `vex purge`

### Truncating old commits

- `vex truncate`

### Subprojects

- `vex subproject:init name`

### Running a server

- `vex serve`

- `/.vex/settings/authorized_keys`

### Project settings

- `vex settings` 

   `<working_dir>/.vex/settings/foo` mapped to a `<repo>/.vex/foo` file

   used for ignore,include and others 

### Author information

- `vex authors` 

- `vex project:set author.name ...`

Note: authors are stored as uuids internally, using a hidden file in the current branch to find names.

Note 2: purge commits can be used to remove old names, emails, contact information

### Locking a branch

Sets a `/.vex/settings/policy` file inside a branch

- `vex lock <branch>`

- `vex 

- `vex branch:set ..`

### File properties

- `vex properties:set`

### Subcommands

Store some environment variables and entry points in a settings file, and run those commands

- `vex env`

- `vex make`

- `vex test`

- `vex grep'

- `vex exec` 

 `/.vex/settings/bin/x

### Scripting

- `vex --rson/--json/--yaml`

   note: subset of yaml

- `vex debug`

- `vex debug:cat` `vex debug:ls`

### Versioning

- `vex commit --major/--minor/--patch`

- /.vex/setting/features

