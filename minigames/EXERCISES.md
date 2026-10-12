# Get Out: puzzle design experiments

Choose one question. Change one thing, predict its effect, and watch someone
play. Work in your own copy; trade games with a neighbor for testing.

These original exercises apply ideas from Jesse Schell's puzzle discussion.
In the course's third edition, puzzles are **Chapter 14**, with **Lens 58: The
Puzzle**. Chapter 13 concerns balance. Use chapter titles when comparing
editions. Consult the assigned text for Schell's full treatment; the exercises
below are our applications, not quotations or a replacement for the chapter.

## Start with a conversation

Play the reference's first board before requesting a hint. Discuss:

- What did you understand before your first move? What did you discover by moving?
- When were you making a decision, and when were you guessing?
- What made you believe the puzzle had a solution?
- Did the hint help you understand something, or just tell you what to do?
- What would make this puzzle satisfying even if it took fewer moves?

The reference slides until a wall or boundary. Crossing the exit wins, even
before the slide stops. Its shortest-path solver gives direct next-move hints.
Undo, reset, a board editor, and trace download are already available.

## Six starting exercises

Choose a row and write the prediction **before** asking Codex to implement it.
Principle IDs are accepted by the scaffold's `--principle` option.

| ID | Question for your group | One bounded variation | Evidence to look for |
| --- | --- | --- | --- |
| `entry` | How can a player learn the movement rule through one action? | Add a tiny introductory board or an optional move demonstration before the existing boards. | Can a new player predict where the next slide stops? Note first-action confusion and requests for explanation. |
| `progress` | What progress can the interface truthfully show? | Show visited stopping positions or a small record of discovered routes. Label it as exploration, not distance to victory. | Does a player use the information to choose a move? Note whether it adds confidence, clutter, or a false promise. |
| `solvability` | How much assurance should the game give before it becomes a spoiler? | Add a solver-verified “a route exists” message, or an optional clue that establishes a reachable intermediate position. | Ask when the player believed the board was solvable. Observe abandonment, repeated attempts, and requests for help. |
| `sequence` | What must a player learn before the next board makes sense? | Author three original boards: introduce an idea, vary it, combine it with another. | Can the player name or demonstrate the idea on the next board? Record where the sequence makes an unexpected jump. |
| `hints` | What is the smallest useful intervention when someone is stuck? | Replace the immediate next move with three optional levels: a question, a relevant feature, then the move. | Record which hint levels players request and whether they can explain the next action. Speed alone does not show understanding. |
| `perception` | When does a change in perspective feel fair? | Author a board whose route first goes away from the exit; change framing or a clue to make that possibility discoverable. | Ask what the player initially assumed. Observe the moment that assumption changes and whether the player calls it satisfying or arbitrary. |

For `progress`, straight-line distance to the exit is not reliable progress in
this game. For `solvability`, distinguish a route from the start from a route
from the **current** position. Your assurance and solver must agree. For
`sequence` and `perception`, use the editor and check reachability; a longer
shortest path alone does not establish greater human difficulty.

## Extensions for groups that finish early

- **`parallelism`:** Let the player choose between two puzzles and return to a
  stuck one. Does choice reduce frustration or make the lesson less clear?
- **`pyramid`:** Design two short teaching puzzles, then a third that requires
  both ideas. What evidence shows transfer rather than trial and error?
- **`solution`:** Offer an explicit, optional solution walkthrough after a
  player requests it. Follow with a new board using the same idea. Can the
  player apply what they saw? Keep hints and full reveal visibly distinct.

## Run a small human playtest

1. State your prediction and one observation that would challenge it.
2. Give a neighbor the game and its on-screen instructions. Watch quietly;
   avoid coaching. They may think aloud, but do not require it.
3. Note board, version, order, hints, resets, completion, and a revealing
   action or remark. Use “Player A,” not a name or email. Trace download can
   help reconstruct moves; it cannot tell you how someone felt.
4. If comparing reference and variation, use different players or alternate
   the order across pairs. Replaying a known solution creates a practice
   effect. For tutorial changes, use comparable new boards for transfer.
5. Ask: “What were you trying to do?” and “What changed your understanding?”
   Avoid leading questions such as “Were the hints better?”
6. Write what you observed, what it suggests, what remains uncertain, and one
   revision or next test. A tiny classroom sample is exploratory evidence.

## Connect the exercise to agent evaluation

Discuss these separately:

- **Rule correctness:** Do collisions, exit detection, reset, and terminal
  states behave as specified? Test deterministic examples.
- **Agent performance:** Can a baseline or model player reach the exit under
  the same boards, action interface, and move budget? Record success, moves,
  invalid actions, and model cost when applicable.
- **Player experience:** Did a human understand the goal or experience a
  satisfying insight? Observe and ask; a solver's score does not answer this.

The reference's breadth-first solver is a cheap perfect-information baseline.
It is neither a model player nor proof that a puzzle is good. If you change
rules, update or replace the solver and its tests before trusting hints.

## Carry the method into your projects

For the Motivation Atlas, choose a mechanic that makes the assigned motivation
observable and propose evidence for it. Follow that repository's contribution
format. A Get Out PR does **not** automatically fulfill the Atlas assignment,
which remains due October 18.

For the midterm, identify one bounded loop in your historical source, preserve
its important rule constraints, and separate the building agent from the
playing agent. Reuse the prediction/change/evidence/review method, with a
model player, cheap baseline, and bounded evaluation required by the brief.

References: Jesse Schell, *The Art of Game Design*, third edition, Chapter 14
and Lens 58; Eric Zimmerman, *The Rules We Break*, “Get Out,” exercise 11.
The browser adaptation uses original boards. The author's
[game sheets](https://theruleswebreak.com/gamesheets.html) accompany his book;
keep the course's book files in the private library.
