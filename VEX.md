# Vex - A database for files 

This README assumes some familiarily with `git`, `hg`, or `svn`

Note: This is a work-in-progress, large chunks of this README are fictional. Please don't link to this project yet, it isn't ready for an audience yet. Thank you!

## A Manifesto for yet-another Source Control System

- The working copy is sacred. Preserve it at all costs.
- Everything should be as easy to do as it is to undo/redo. Not the other way around: permanent changes should be hard.
- Don't ever leave the project in a broken state: unless the user *explicitly* asked, rollback. If it breaks, try and fix it before complaining about it. 
- The history of a project is when the changes were applied, not when the changes were written.
- Flags are a terrible idea, short flags are worse. (They should be for sharing behaviour across commands, not changing what commands ultimately do. Use another command instead of a flag)

Imagine `git`, except:

- Branches automatically stash and unstash
- It tracks directories as well as files, even empty ones.
- The index is the stage (like `hg`)
- Branches can have more than one working copy associated with it,  detached heads never get lost.
- Instead of a reflog, `undo` and `redo`.
- `log` always shows the changes in the order they were applied, not written
- Instead of rewriting history, rebasing creates a new merge commit, and then replays the changes atop. 
- Subtree checkouts, subversion-like fileprops

Imagine `hg`, except:

- Branches work more like `hg bookmarks` or `git branch` internally.
- Branches automatically stash and unstash.
- Branches can have multiple heads `hg heads` is roughly `vex sessions`.
- `log` always shows the changes in the order they were applied, not written
- `vex update` does a rebase without destroying history
- Subtree checkouts, subversion-like fileprops.

Imagine `svn`, except:

- Branches work as outlined above.
- Commiting offline and sharing changes asynchronously.
- But yes, subtree checkouts, and fileprops are still around. Finally.

Now Imagine:

- Online mode (i.e push on commit), Partial checkouts.
- Large file, large directory, and binary support.
- Branch configuration inside a tracked directory, used for default properties, ignore lists, author settings, and merge policies.
- UUIDs everywhere: Changing author information without rebuilding project
- Working submodules/repos
- Purging: a way strip changes from a project and push it to remote services

Good, because none of it is ready yet.

## Cheatsheet:

These commands are implemented, but are unfinished:

| vex | hg | git  |
| --- | --- | --- |
| `vex init`		| `hg init`		    | `git init` 	|
| `vex add`	    	| `hg add`	    	| `git add` 	|
| `vex forget`		| `hg forget`   	| `git remove --cached (-r)` 	|
| `vex remove`		| `hg remove`   	| `git remove (-r)` 	|
| `vex restore`		| `hg revert`   	| `git reset -- <file>` `git checkout -- <file>` |
| `vex status`		| `hg status`	    | `git status` 	|
| `vex commit`		| `hg commit`   	| `git commit -a` 	|
| `vex log`	    	| `hg log`		    | `git log --first-parent` 	|
| `vex branch:new`  | `hg bookmark -i`, `hg update -r` | `git branch`, `git checkout`|
| `vex branch:open`                 | `hg update -r <name>` | `git checkout` |
| `vex branch:saveas`               | `hg bookmark <name>` | `git checkout -b`|
| `vex branch:rename`               | `hg bookmark --rename` | `git branch`|
| `vex branch:swap`                 | ... | ... |
| `vex branches` / `branch:list`    | `hg bookmark` | `git branch --list` |
| `vex diff`	                	| `hg diff`	    | `git diff` / `git diff --cached` 	|
| `vex diff:branch`         		| `hg diff`   	| `git diff @{upstream}` 	|

| ...			    | ...			| ...		|
| `vex message:edit` | ... | ... |
| `vex message:get` | ... | ... |

| `vex undo`		| `hg rollback` for commits	| check stackoverflow 	|
| `vex redo`		|              	            | 	|
| `vex switch`		| no subtree checkouts		| no subtree checkouts	|


## `vex`

Every vex command looks like this: 

`vex <path:to:command> <--arguments> <--arguments=value> <value> ...`

`vex help <command>` will show the manual, and `vex <command> --help` shows usage.

Commands can be one or more names seperated by `:`, like `vex commit` or `vex undo:list`

Argument can take the following form:

- Boolean: `--name`, `--name=true`, `--name=false`

- Single value `--name=...`

- Multiple values `--name=... --name=...`

- Positional `vex command <value>`

- There are no single letter flags like, `-x`. 

Aside: Single letter flags are the work of the devil, mystery meat configuration at best. `vex` strives to avoid needing them, exposing new subcommands instead.

Use `complete -o nospace -C vex vex` to set up tab completion in bash. Command names (including subcommands), argument names, and some argument values can be tab completed.

## Debugging

If `vex` crashes with a known exception, it will not print the stack trace by default. Additionally, after a crash, `vex` will try to roll back any unfinished changes.

use `vex debug <command>` to always print the stack trace, but this will leave the repo in a broken state. use `vex debug:rollback` to rollback manually.

note: some things just break things, sorry.

use `vex fake <command>` to not break things and see what would be changed*

* sort-of, the stash might get changed but nothing else should
* and some commands rely on previous changes soooo
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
{- `vex include`
- `vex remove` 
- `vex restore` 
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
- `vex branch:close` *

### Working on an anonymous branch

- `vex session` (see all open branches/anonymous branches)
- `vex sessions`
- `vex session:new` *
- `vex session:open` *
- `vex session:detach` *
- `vex session:attach` *
- `vex rewind`  * (like git checkout)

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
{
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


### Internals

- a content addressable store 
- a json-like format with tagged values
- a transactional layer
- the project layer
- the cli layer

a project has sessions, one of which is active, which points to a branch, both the session and branch point to commits, commits point to each other, directory root and changelog entries. 

the file `vex` defines the commands and entry points, and sends `argv` etc to `cli.py`, which then calls into a `@cmd.on_call()` function, which runs, prints, and wraps error handling.

inside `project.py`, there is a `Project` method with `commit` `add` esque methods, which inside open a transaction, make changes, then exit

the transaction objects come in two flavours, physical and logical. the physical one stores entire snapshots of before, after, but the logical one stores the arguments to commands to run for undo/redo

the reason is undoing/redoing something like changing a branch can't be done with concrete snapshots, and has to stash/unstash files so can't really revert the old / new sessions.


