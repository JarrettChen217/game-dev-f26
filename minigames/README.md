# Minigame lab

[Play Get Out](get-out/index.html), read the [student guide](STUDENT-GUIDE.md),
and choose an [exercise](EXERCISES.md). The reference has original boards and
runs in a browser with no build step, server, or model connection.

Each student makes an independent copy under
`submissions/<github-login>/get-out/`, then opens one draft pull request.
The instructor reference in `get-out/` stays available for comparison.

Start with the [three-step student guide](STUDENT-GUIDE.md): play manually,
exchange boards, then ask Codex to create a variation. The course skill reads
the authenticated GitHub login and creates the student branch and copy.
Students do not type their username or run scaffold commands.

## Tool reference for Codex and instructors

The skill obtains `<login>` using `gh api user --jq .login`, creates or resumes
`<login>/get-out` from the class base, then invokes the existing scaffold with
the principle matching the student's design idea:

```text
python3 scripts/minigames.py new <login> --principle <principle>
python3 scripts/minigames.py check --owner <login>
python3 scripts/minigames.py test --owner <login>
python3 scripts/minigames.py gallery
```

These commands are run by Codex, not a student setup checklist. The new command
refuses to overwrite an existing game. Open `build/minigames/index.html` for the
generated gallery; every valid manifest appears automatically. Generated files
stay uncommitted. CI uploads a gallery artifact without publishing a website.
The shared gallery grows as the instructor merges student PRs.

See the [reference README](get-out/README.md) for controls, rules, attribution,
and deterministic engine interface. Keep copyrighted course books and private
feedback out of this public repository.
