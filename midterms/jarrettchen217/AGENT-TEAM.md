# Agent Team

I worked as the producer and creative director of this project. I made the
design calls and approved every merge, and I gave each AI agent one line of
work. This page describes how the team was organized, what worked, what went
wrong, and what I would change.

## How the team was organized

I started with Codex and one main agent. I talked through my ideas and logic
with it, and it turned them into code. Early on I also had agents design the
tooling around version control and task tracking, because I quickly hit two
problems.

**Problem 1: my thinking jumps between tasks.** While planning task A, I
think about how its result shapes task B, and then about how B's design
changes what A needs. A single LLM context handles this badly. A long thread
about B pushes A out of the window, and when we come back to A, it has been
polluted by details from B. My fix was an Asana skill. During brainstorming,
each idea goes under the to-do list of the task it belongs to. When an agent
starts a task, it reads that task's full list first. For me, Asana is more
than a timeline and a kanban board. It is the place where context lives,
outside any one agent's memory.

**Problem 2: long sessions get worse, and handovers were manual.** Agent
quality drops as the context window fills, so I keep sessions short and give
different tasks to different agents. At first that meant asking each finished
agent to write a prompt for the next one by hand, and README files kept going
out of date. So I wrote a handoff skill. When a session ends, the agent:
- opens its own pull request;
- links the PR to the matching Asana task, which also shows the PR because
  GitHub and Asana are connected;
- updates a HANDOFF document that summarizes the repo and points to every
  README and key document.

The next session starts by reading Asana and the HANDOFF file. Together with
resume, verify and create-PR skills, this let agents pick up each other's
work smoothly.

**Parallel lines.** Near the deadline I ran several agents at once, each in
its own git worktree, so they never touched each other's files:
- **Baseline model:** connect the mature, publicly released Killfield v17b
  model to our environment. It was the fastest way to get a strong opponent,
  even though it meant compromising on some rules. This is the version I
  deployed and showed at the Oct 27 office hour, and that classmates used to
  get an overview of the rules.
- **Our own PPO model:** train our own policy in our own simulator, using a
  PPO trainer and optimizer adapted from Killfield. A borrowed model cannot
  learn new game mechanics; our own trainer can. It also taught me the RL
  pipeline end to end, and it adapts to our environment's quirks. This line
  produced u19588, which replaced v17b and is the Hybrid opponent in this
  submission.
- **Support lines:** web deployment, a frozen archive line, and packaging for
  this midterm.

A more capable model acted as coordinator over the running agents. When a
shared piece changed, such as how the game is packaged, it told the other
agents to cherry-pick the change. This avoided duplicate work and large merge
conflicts.

**Review.** Before code was committed, the Codex agent ran a built-in review
skill. The skill starts a reviewer subagent that did not write the code. It
checks the change and reports findings, and the implementing agent fixes them
before the PR. This reviewer is a subagent of the same Codex session, not a
fully separate agent.

**Hardware.** I code, test and build the web version on a 14-inch MacBook
Pro (M2 Pro). Training runs on a Linux RTX 3070 training machine (i7-11800H,
32 GB RAM, Ubuntu 22.04) that stays on at home. Agents reach it over SSH
inside an isolated sandbox. Before each run they must ask me for time, disk
and memory limits.

## What went wrong

- **I underestimated PPO training time.** I first trained on my laptop. It
  overheated and slowed down, and training kept being delayed. Moving
  training to the dedicated machine fixed this.
- **Our first PPO results were poor, and we had to backtrack.** I found the
  Killfield source and used it as a reference. That gave us a way forward,
  but it also changed the project's direction midway: many rules now come
  from Killfield's code, not from our original design.
- **So we walked on two legs.** The v17b line proved the game loop worked
  and gave us a playable build on time. In parallel we trained our own PPO
  model. We put a model interface between the game/web packaging and the
  model, so swapping in our own model later would not break compatibility.
  It did not: u19588 replaced v17b a few days later through that interface.

## Peer notes

*(To be added after the partner playtest.)*

## Limitations and future work

- **60 Hz is demanding on weak hardware.** Killfield's agent decides 25 times
  per second. I moved the game to 60 Hz for two reasons. Our first 30 Hz
  version felt choppy. And a model that decides 60 times per second has more
  room to act, so it can be a stronger opponent. The game runs smoothly on
  my Mac and on the instructor's laptop. On a classmate's Windows gaming
  laptop, unplugged and probably on integrated graphics, it could not reach
  60 FPS in the browser. A manual switch for the decision rate is future
  work.
- **Rules lean on Killfield.** Many rules were taken from Killfield's source.
  This is a reconstruction, not a new design.
- **Review is not fully independent.** The reviewer is a subagent started by
  the implementing agent's own skill, not a separate agent.
- **Next mechanics.** At the office hour, the instructor suggested new
  mechanics once the reconstruction is stable, for example breakable or
  pushable walls. I also want more players and controllers, which would need
  a server running the model in the background.

## Evidence (agent configuration and review)

- Roles: [design](agent-config/roles/design.md), [implementation](agent-config/roles/implementation.md),
  [reviewer](agent-config/roles/reviewer.md), and the read-only
  [Claude Code reviewer](agent-config/roles/claude-tank-reviewer.md) used for the packaging line.
- Skills: [resume](agent-config/skills/tank-resume/SKILL.md), [handoff](agent-config/skills/tank-handoff/SKILL.md),
  [verify](agent-config/skills/tank-verify-change/SKILL.md) and [create-PR](agent-config/skills/tank-create-pr/SKILL.md),
  each with its invocation policy in `agents/openai.yaml`. Copies are as used, with private identifiers redacted.
- Review findings and how each was resolved: [agent-config/review-examples.md](agent-config/review-examples.md).
