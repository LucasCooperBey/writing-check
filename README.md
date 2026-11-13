<h1 align="center">writing-check</h1>

<p align="center"><strong>Score a draft for the shapes that make writing read as machine-made, line by line, before you post it.</strong></p>

<p align="center">
  <a href="https://github.com/LucasCooperBey/100-doors"><img alt="100 Doors: Door 29" src="https://img.shields.io/badge/100%20Doors-Door%2029-f94bf3"></a>
  <a href="LICENSE"><img alt="license MIT" src="https://img.shields.io/badge/license-MIT-9aff4a"></a>
  <img alt="python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-3776ab">
  <img alt="dependencies none" src="https://img.shields.io/badge/dependencies-none-9aff4a">
  <img alt="hooks Claude Code · git" src="https://img.shields.io/badge/hooks-Claude%20Code%20%C2%B7%20git-5ac4bf">
  <a href="https://github.com/LucasCooperBey/writing-check/commits/main"><img alt="last commit" src="https://img.shields.io/github/last-commit/LucasCooperBey/writing-check?color=9aff4a&label=updated"></a>
</p>

<p align="center"><a href="#quick-start">Quick start</a> · <a href="#example">Example</a> · <a href="#rules">Rules</a> · <a href="#limits">Limits</a> · <a href="https://github.com/LucasCooperBey/100-doors">All 100 Doors</a></p>

writing-check scores a draft for writing shapes that read as performed craft. It is one Python file from the standard library, and you run it on a draft before you post.

**Who it's for:** anyone who drafts posts, emails or docs with AI help and wants them to sound like a person wrote them.

## Contents

- [What's inside](#whats-inside)
- [Quick start](#quick-start)
- [Example](#example)
- [Rules](#rules)
- [Why shapes](#why-shapes)
- [Rewrite prompt](#rewrite-prompt)
- [Claude Code Stop hook](#claude-code-stop-hook)
- [Git pre-commit hook](#git-pre-commit-hook)
- [Limits](#limits)
- [Part of 100 Doors](#part-of-100-doors)
- [Credits](#credits)
- [License](#license)

## What's inside

| Path | What it is |
|---|---|
| `writing_check.py` | The checker: one file, standard library only |
| `examples/before.md, examples/after.md` | A draft full of the shapes, and the same news without them |
| `hooks/claude-code-stop-hook.sh` | Claude Code Stop hook: the model rechecks its own last reply |
| `hooks/pre-commit` | Git hook that scores staged .md and .txt files |
| `tests/` | unittest suite |

## Quick start

Install is a single download of one Python file, and the two commands below save it and score a draft named draft.md.

```
curl -fsSL -o writing_check.py https://raw.githubusercontent.com/LucasCooperBey/writing-check/main/writing_check.py
python3 writing_check.py draft.md
```

Add --max 15 when you want a failing exit code once the weighted rate goes over 15 hits per 1,000 words. A draft under 80 words still prints its rate, counted over 80 words with the structure rules off, and --max applies to that rate. Leave the max off when you only want the report.

Score a markdown file, a text file, or an HTML file with the tags stripped by passing the path. `--stdin` reads the draft from the terminal, and `--transcript FILE.jsonl --last N` scores the last N assistant turns in a Claude Code transcript. `--quiet` prints one summary line per input. `--json` prints the rule id, the weight, the line, and an excerpt for each hit, plus totals. `--words warn` is the default and lists the soft words at weight 0, while `--words off` hides that list. `--rewrite-prompt` prints a prompt you can paste into any chat model and then exits 0. Exit codes are 0 when the draft is under the max or when no max is set, 1 when the rate exceeds the max, 2 when the arguments are wrong, and 3 when the checker could not run, which keeps a bad call from looking like a clean draft.

## Example

`examples/before.md` is a 237-word bakery announcement written with the shapes this tool looks for, and `examples/after.md` gives the same news without them. The first lines of the report on the first file:

```
$ python3 writing_check.py examples/before.md
[PERFORMED] 164.6/1k   35 hits    237 words  examples/before.md
    filler      x1   (filler intensifiers, weight 2)
       - filler intensifier: Genuinely
    antithesis  x2   (manufactured antithesis, weight 3)
       - 'X, not Y' closer: The page is a promise, not a form.
       - verbless ', not Y' fragment: Orders close at 6 PM the day before, not later.
    aphorism    x1   (aphorism formulas, weight 3)
       - aphorism 'X is the Y of Z': It is the architecture of a calm pickup.
```

The rewrite scores clean, so `--max 15` exits 0 on it and exits 1 on the draft:

```
$ python3 writing_check.py examples/after.md --max 15
[CLEAN    ]   0.0/1k    0 hits    197 words  examples/after.md
```

A clean score means none of these shapes were found. It does not mean the claims in the draft are true or that it sounds like you.

## Rules

Each rule looks for a shape. The weight is what the shape adds to the rate. The rate is weighted hits per 1,000 words of your own prose, after code, quotes, tables, and URLs are set aside. Weight 0 means the hit is listed and then left out of the rate, so a deliberate use of a listed word does not push the draft over the max.

| id | what it catches | weight | example |
| --- | --- | --- | --- |
| dash | a prose em dash or a prose en dash | 3 | two clauses joined by an em dash |
| filler | an empty intensifier | 2 | genuinely incompatible |
| antithesis | manufactured symmetry | 3 | It is a status query, not a do-command. |
| aphorism | a metaphor formula | 3 | It is the architecture of a calm morning. |
| punchline | a run of very short sentences, or a short closer | 2 | Simple. Clear. Done. |
| solo-para | a one-sentence paragraph used as a beat | 2 | This is the whole point. |
| three | exactly three items closing a sentence | 1 | bread, buns, and rye. |
| tail-neg | a sentence that ends on a short negation | 2 | closed for the day, not later. |
| signpost | a stock phrase that announces a tour | 2 | a stock opener that invites a tour of the topic |
| bullets | three or more bullets that open with a bold label and a colon | 1 | a bullet, a bold label, a colon, repeated as a list |
| hedges | two or more hedges in one sentence | 1 | might possibly help and could arguably wait |
| unsourced_number | a percent, a multiplier such as 3x, or a study claim with no source | 1 | Studies show that 80% of regulars agree. |
| words | a soft list of model-prone words and phrases, shown only | 0 | delve |

The soft list, as shipped, is the block below. A hit on this list is reported and then ignored by the rate.

```
delve
tapestry
testament
seamless
robust
pivotal
realm
embark
elevate
unleash
game-changer
cutting-edge
multifaceted
underscore
foster
holistic
synergy
paradigm
transformative
groundbreaking
meticulous
intricate
plethora
myriad
nestled
bustling
furthermore
moreover
streamline
ever-evolving
in today's fast-paced world
it's important to note
navigate the complexities
it's worth noting
at the end of the day
```

## Why shapes

Shapes are the target because the repair is to say the point in plain words, and that repair leaves a word the writer chose where it is. The soft list is printed with weight 0 because a person may use any of those words on purpose, and a ban would delete real language from the draft.

## Rewrite prompt

Run the checker with `--rewrite-prompt` on the draft, paste the printed prompt into any chat model, read the rewrites it sends back, and keep the lines that say the thing you meant. The prompt names each flagged sentence and the rule it broke. It asks for a plain rewrite that keeps every fact, every number, every name, and every link, and the reply is supposed to use the form in this fence.

```
Rewrite only these sentences in plain words. Keep every fact, number, name and link. Do not add new claims. Return each as: original -> rewrite.
```

## Claude Code Stop hook

A Stop hook can run the checker on the last assistant turn. When the rate is over the max, the hook exits 2 and Claude Code shows the summary to the model. If the input has `stop_hook_active` set, the hook exits 0 so the check cannot loop forever. The default max is 15, and `WRITING_CHECK_MAX` overrides it. Put this in `.claude/settings.json` and start Claude Code from the project root, with the hook left at `hooks/claude-code-stop-hook.sh`.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "hooks/claude-code-stop-hook.sh"
          }
        ]
      }
    ]
  }
}
```

## Git pre-commit hook

The pre-commit hook scores staged `.md` and `.txt` files with the same max. Copy `hooks/pre-commit` to `.git/hooks/pre-commit` and mark that copy executable. It reads the checker from `$WRITING_CHECK` when that is set, otherwise from `writing_check.py` next to the hook's real location, otherwise from the repo top level, otherwise from `PATH`. When no staged file is markdown or text, the hook reports that it had no work and exits 0. `WRITING_CHECK_MAX` overrides the default of 15 for that run too.

## Limits

It flags shapes, and a flagged sentence can still be the one you meant to keep on the page. It reads English only, so a draft in another language will not be scored in a useful way. The score is a prompt to reread the lines it marked, and the number is there so you look again rather than treat the run as a grade.

## Part of 100 Doors

This is the gift behind **Door 29** of [100 Doors](https://github.com/LucasCooperBey/100-doors), where I open up the things I've built with AI, one door at a time.

- The door and every other door: [the 100 Doors index](https://github.com/LucasCooperBey/100-doors)
- Related door: [the breakdown skill](https://github.com/LucasCooperBey/claude-skills/tree/main/skills/breakdown) (Door 22) puts one plain sentence first
- The season: [sandiegoaistudio.com/season](https://sandiegoaistudio.com/season)

### Come see it live

If you want to see how this and the rest of the doors open up into my software factory, come to [Sharathon](https://sandiegoaistudio.com/sharathon), San Diego AI Studio's show-your-setup day. Sharathon 3 is Sunday, Nov 15 in La Mesa: [RSVP on Luma](https://luma.com/5y5ju7ud).

## Credits

- Built by [Lucas Cooper-Bey](https://github.com/LucasCooperBey) from the checks his own drafts go through

## License

MIT, see [LICENSE](LICENSE).
