# Vex - A database for files and directories.

Note: This is a work-in-progress, Please don't link to this project yet, it isn't ready for an audience yet. Thank you!

`vex` is a command line tool for tracking and sharing changes, like `hg`, `git`, or `svn`. Unlike other source
control systems, vex comes with `vex undo`, and `vex redo`.

## Undo and Redo are faster than re-downloading and crying.

Added the wrong file? Run: `vex undo`

```
$ vex add wrong_file.txt
$ vex undo
```

Deleted an important file? Run `vex undo`

```
$ vex remove important.txt
$ vex undo
```

Restored the wrong file? Run `vex undo`

```
$ vex restore file_with_changes.txt
$ vex undo

```

Commited on the wrong branch? Yes, `vex undo`

```
$ vex commit 
$ vex undo
$ vex branch:save_as testing
```

Created a project with the wrong settings? ... `vex undo`!

```
$ vex init . --include='*.py'
$ vex undo
$ vex init . --include='*.rb' --include='Gemspec'
```

## What makes vex different:

- Tab Completion built in!
- Empty Directories are tracked too.
- You can work on a subdirectory, rather than the project as a whole.
- You can change branches without having to commit or remove unsaved changes.
- Branches can have multiple sessions attached, with different changes (committed & uncommited).
- Output goes through `less` if it's too big for your terminal.
- Commands are named after their purpose, rather than implemention.
- Changed files do not need to be `vex add`'d before commit, just new ones

... and if there's a bug in `vex`, it tries its best to leave the project in a working state too!

## Quick Install

Install python 3.6, I recommend using the wonderful "Homebrew" tool. Then, enable tab completion:

```
$ alias vex=/path/to/project/vex # or `pwd`/vex if you're inside the project
$ complete -o nospace -O vex vex
```

### Command Cheatsheet

Every vex command looks like this: 

`vex <path:to:command> <--arguments> <--arguments=value> <value> ...`

`vex help <command>` will show the manual, and `vex <command> --help` shows usage.

Commands can be one or more names seperated by `:`, like `vex commit` or `vex undo:list`

### Undo/Redo

| `vex` | `hg` | `git` |
| ----- | ----- | ----- |
| `vex undo`		| `hg rollback` for commits	| `git reset --hard HEAD~1` for commits, check stackoverflow otherwise |
| `vex redo`		| ...             	        | ... 	|
| `vex undo:list`	| ...             	        | ... 	|
| `vex redo:list`	| ...             	        | ... 	|

### General

| `vex` | `hg` | `git` |
| ----- | ----- | ----- |
| `vex init`		| `hg init`		    | `git init` 	|
| `vex status`		| `hg status`	    | `git status` 	|
| `vex log`	    	| `hg log`		    | `git log --first-parent` 	|
| `vex diff`	            	| `hg diff`	    | `git diff` / `git diff --cached` 	|
| `vex diff:branch`      		| `hg diff`   	| `git diff @{upstream}` 	|

### Files

| `vex` | `hg` | `git` |
| ----- | ----- | ----- |
| `vex add`	 (only for new files)   	| `hg add`	    	| `git add` (for changed and new files)	|
| `vex forget`		| `hg forget`   	| `git remove --cached (-r)` 	|
| `vex remove`		| `hg remove`   	| `git remove (-r)` 	|
| `vex restore`		| `hg revert`   	| `git checkout HEAD -- <file>` |
| `vex switch`		| no subtree checkouts		| no subtree checkouts	|

### Commits

| `vex` | `hg` | `git` |
| ----- | ----- | ----- |
| `vex id`		        | `hg id`   	| `git rev-parse HEAD` 	|
| `vex commit`		    | `hg commit`	| `git commit -a` 	|
| `vex commit:amend`	| ...        	| `git commit --amend` 	|
| `vex message:edit` | ... | ... |
| `vex message:get` | ... | ... |

### Branches

| `vex` | `hg` | `git` |
| ----- | ----- | ----- |
| `vex branch:new`                  | `hg bookmark -i`, `hg update -r` | `git branch`, `git checkout`|
| `vex branch:open`                 | `hg update -r <name>` | `git checkout` |
| `vex branch:saveas`               | `hg bookmark <name>` | `git checkout -b`|
| `vex branch:rename`               | `hg bookmark --rename` | `git branch`|
| `vex branch:swap`                 | ... | ... |
| `vex branches` / `branch:list`    | `hg bookmark` | `git branch --list` |
| ...			    | ...			| ...		|


### Options/Arguments

The argument to a command can take one the following form:

- Boolean: `--name`, `--name=true`, `--name=false`
- Single value `--name=...`
- Multiple values `--name=... --name=...`
- Positional `vex command <value> <value>`

There are no single letter flags like, `-x`. Tab completion works, and vex opts for a new command over a flag to change behaviour.

## Debugging

If `vex` crashes with a known exception, it will not print the stack trace by default. Additionally, after a crash, `vex` will try to roll back any unfinished changes. Use `vex debug <command>` to always print the stack trace, but this will leave the repo in a broken state, so use `vex debug:rollback` to rollback manually.

Note: some things just break horribly, and a `rollback` isn't enough. Use `vex fake <command>` to not break things and see what would be changed (for some commands, they rely on changes being written and so `fake` gives weird results, sorry).


## Workflows

### Creating a project

`vex init` or `vex init <directory>`. 

```
$ vex init . --include="*.py" --ignore="*.py?"
$ vex add
$ vex status
... # *.py files added and waiting for commit
```

By default, `vex init name` creates a repository with a `/name` directory inside. 

(Note: `vex undo`/`vex redo` will undo `vex init`, but leave the `/.vex` directory intact)

You can create a git backed repo with `vex init --git`, or `vex git:init`. The latter command creates a bare, empty git repository, but the first one will include settings files inside the first commit. `vex git:init` also defaults to a checkout prefix of `/` and a branch called `master`. `vex init --git` uses the same defaults as `vex init`, a prefix that matches the name of the working directory, and a branch called `latest`.

### Undoing changes

- `vex undo` undoes the last command that changed something
- `vex undo:list` shows the list of commands that can be undone
- `vex undo` can be run more than once,
- `vex redo` redoes the last undone command
- `vex redo:list` shows the potential options, `vex redo --choice=<n>` to pick one
- `vex redo` can be run more than once, and redone more than once

### Moving around the project

- `vex switch` (change repo subtree checkout)

### Adding/removing files from the project

- `vex add`
- `vex forget` 
- `vex ignore` 
- `vex include`
- `vex remove` 
- `vex restore` 

TODO

- `vex restore --pick` *

### File properties

- `vex fileprops` / `vex properties`
- `vex fileprops:set`

### Inspecting changes

- `vex log`
- `vex status`
- `vex diff <file> <file...>`
- `vex diff:branch <branch>`

### Saving changes

- `vex message` edit message
- `vex message:get` print message
- `vex commit <files>`
- `vex commit:prepare` / 'vex commit:prepared'

TODO 

- `vex commit:amend` *
- `vex commit --pick` * 
- `vex commit:rollback` *
- `vex commit:revert` *
- `vex commit:squash` * (flatten a branch)

### Working on a branch

- `vex branch` what branch are you on
- `vex branch:new` create a new branch
- `vex branch:open` open existing branch
- `vex branch:saveas`  (see `git checkout -b`)
- `vex branch:swap`  
- `vex branch:rename` 
- `vex branches` list all branches

TODO

- `vex branch:close` *

### Working on an anonymous branch

- `vex session` (see all open branches/anonymous branches)
- `vex sessions`

TODO

- `vex session:new` *
- `vex session:open` *
- `vex session:detach` *
- `vex session:attach` *
- `vex rewind`  * (like git checkout)

## TODO

### Applying changes from a branch *

When applying changes from another branch, vex creates new commits with new timestamps

- `vex commit:apply <branch>` *
- `vex commit:append <branch>` *
   create a new commit for each change in the other branch, as-is
- `vex commit:replay <branch>` *
   create a new commit for each change in the branch, reapplying the changes
- `vex commit:apply --squash` *
   create a new commit with the changes from the other branch
- `vex commit:apply --pick`  *

### Rebuilding a branch with upsteam changes *

- `vex update` * (rebase, --all affecting downstream branches too) 
- `vex update --manual` * (handle conflcts)

### Subprojects *

- `vex project:init name` *
- `vex mount <branch/remote> <path>` *

### Sharing changes *

- `vex export` * 
- `vex import` *
- `vex pull` *
- `vex push` *
- `vex sync` * (pull, update, push)
- `vex remotes` *
- `vex remotes:add` *
- `vex serve` *
- `vex clone` *

### Cleaning the changelog

- `vex purge` *
- `vex truncate` *

### Project settings *

- `vex project:settings` * 
- `vex project:authors`  *
- `vex project:set author.name ...` *

### Branch Settings *

- `vex baranch:lock <branch>` * (sets a `/.vex/settings/policy` file inside a branch with a `{branch-name: policy } ` entry
- `vex branch:set ..` *

### Subcommands *

Store some environment variables and entry points in a settings file, and run those commands

- `vex env` *
- `vex exec` / `vex run` *
- `vex exec:make` *
- `vex exec:test` *

The directory `/.vex/settings/bin/` inside working copy is tracked, and added to the `PATH`

### Scripting

- `vex --rson/--json/--yaml` * (note: subset of yaml)
- `vex debug`
- `vex debug:cat` *
- `vex debug:ls` *

### Versioning

- `vex commit --major/--minor/--patch`  *
- /.vex/setting/features *

