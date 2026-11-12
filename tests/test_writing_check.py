#!/usr/bin/env python3
"""Known-positive, known-clean, and interface tests for writing_check.py."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import atexit
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import writing_check as wc

BEFORE = os.path.join(ROOT, "examples", "before.md")
AFTER = os.path.join(ROOT, "examples", "after.md")
HOOK = os.path.join(ROOT, "hooks", "claude-code-stop-hook.sh")
SCRIPT = os.path.join(ROOT, "writing_check.py")


def _wipe_bytecode():
    root = pathlib.Path(__file__).resolve().parent.parent
    for folder in root.rglob("__pycache__"):
        shutil.rmtree(folder, ignore_errors=True)


atexit.register(_wipe_bytecode)
_wipe_bytecode()


def setUpModule():
    _wipe_bytecode()


CLEAN = (
    "The weekday ordering page lists the country loaf and the sesame bun "
    "for people who stop at the counter before work.\n"
)
DIRTY = (
    "Where they are genuinely incompatible, pick one and explain the choice "
    "in writing for the team.\n"
)


class PortedShapeTests(unittest.TestCase):
    def test_known_cases(self):
        # source: Door 29, known-positive and known-clean shapes from the private checker
        cases = [
            ("prose em dash", "The gate blocked the push \u2014 the guard is working.", wc.r_dash, True),
            ("digit range", "Doors open 2\u20139 PM on the night of the show.", wc.r_dash, False),
            ("page range", "See pages 4\u20137 for the full table.", wc.r_dash, False),
            ("code-span range", "Use the separate `/1`\u2013`/5` routes only on greenfield.", wc.r_dash, False),
            ("X not Y closer", "It is a status query, not a do-command.", wc.r_antithesis, True),
            ("rather-than rewrite", "It is a status query rather than a do-command.", wc.r_antithesis, False),
            ("filler intensifier", "Where they are genuinely incompatible, pick one.", wc.r_filler_intensifier, True),
            ("no filler", "Where they are incompatible, pick one.", wc.r_filler_intensifier, False),
        ]
        for label, text, rule, want in cases:
            with self.subTest(label=label):
                self.assertEqual(bool(rule(text)), want)

    def test_blockquote_not_in_denominator(self):
        # source: Door 29, quoted material is stripped so a long quote cannot dilute the rate
        _hits, _weighted, words = wc.score("> " + ("filler filler " * 60))
        self.assertLessEqual(words, 40)


class SoftWordTests(unittest.TestCase):
    def test_soft_list_is_about_35(self):
        # source: Door 29, the soft list is about 35 words and phrases
        self.assertGreaterEqual(len(wc.SOFT_WORDS), 32)
        self.assertLessEqual(len(wc.SOFT_WORDS), 40)
        for phrase in (
            "delve",
            "tapestry",
            "testament",
            "seamless",
            "robust",
            "pivotal",
            "realm",
            "embark",
            "elevate",
            "unleash",
            "game-changer",
            "cutting-edge",
            "in today's fast-paced world",
            "it's important to note",
            "navigate the complexities",
        ):
            self.assertIn(phrase, wc.SOFT_WORDS)

    def test_words_flagged_but_weight_zero(self):
        # source: Door 29, soft words are listed and never move the score
        text = (
            "Please delve into the weekday ordering page and describe the loaf "
            "for the counter staff today."
        )
        hits, weighted, _words = wc.score(text)
        self.assertIn("words", hits)
        self.assertEqual(hits["words"][0]["weight"], 0)
        self.assertEqual(weighted, 0)

    def test_words_clean_sentence(self):
        # source: Door 29, a sentence outside the soft list stays quiet
        text = (
            "Please look into the weekday ordering page and describe the loaf "
            "for the counter staff today."
        )
        self.assertFalse(wc.r_words(text))

    def test_words_off_skips_list(self):
        # source: Door 29, --words off hides the soft list
        text = (
            "Please delve into the weekday ordering page and describe the loaf "
            "for the counter staff today."
        )
        hits, weighted, _words = wc.score(text, words_mode="off")
        self.assertNotIn("words", hits)
        self.assertEqual(weighted, 0)


class HedgeTests(unittest.TestCase):
    def test_hedges_stacked_fire(self):
        # source: Door 29, two or more hedges in one sentence are a hit
        text = "The page might help and it could save time for the Tuesday pickup."
        self.assertTrue(wc.r_hedges(text))

    def test_hedges_single_is_clean(self):
        # source: Door 29, one hedge in a sentence stays quiet
        text = "The page might help the Tuesday pickup at the counter."
        self.assertFalse(wc.r_hedges(text))

    def test_month_may_is_not_a_hedge(self):
        # source: Door 29, the month May must not count as the hedge may
        text = "Orders open in May and the loaf might sell out by Friday morning at the counter."
        self.assertFalse(wc.r_hedges(text))


class UnsourcedNumberTests(unittest.TestCase):
    def test_percent_and_study_fire(self):
        # source: Door 29, a percent or a studies-show claim with no source is a hit
        self.assertTrue(wc.r_unsourced_number(
            "Studies show that 80% of regulars want a page instead of the pad they use before work."
        ))
        self.assertTrue(wc.r_unsourced_number(
            "Experts say the weekday line is shorter now that the page is up."
        ))
        self.assertTrue(wc.r_unsourced_number(
            "Research shows the loaf sells faster once the page is open for weekday orders."
        ))

    def test_multiplier_fires(self):
        # source: Door 29, 3x and ten times are multipliers when nothing sources them
        self.assertTrue(wc.r_unsourced_number(
            "The new page is 3x faster than the paper pad for weekday orders at the counter."
        ))
        self.assertTrue(wc.r_unsourced_number(
            "The new page is ten times faster than the paper pad for weekday orders."
        ))

    def test_link_suppresses(self):
        # source: Door 29, a link in the same sentence keeps a number claim quiet
        text = (
            "Studies show that 80% of regulars want a page instead of the pad "
            "(http://127.0.0.1/survey)."
        )
        self.assertFalse(wc.r_unsourced_number(text))

    def test_citation_and_footnote_suppress(self):
        # source: Door 29, a citation bracket or footnote marker keeps a number claim quiet
        self.assertFalse(wc.r_unsourced_number(
            "Sales rose 40% [1] after the page launched for weekday pickup orders."
        ))
        self.assertFalse(wc.r_unsourced_number(
            "Sales rose 40%[^1] after the page launched for weekday pickup orders."
        ))
        self.assertFalse(wc.r_unsourced_number(
            "Sales rose 40%\u2020 after the page launched for weekday pickup orders."
        ))

    def test_named_source_same_or_next_sentence(self):
        # source: Door 29, a capitalized name before said, found, or reported is a source
        self.assertFalse(wc.r_unsourced_number(
            "The Census Bureau found that 40% of neighbors order ahead for weekday bread."
        ))
        self.assertFalse(wc.r_unsourced_number(
            "About 40% of neighbors order ahead for weekday bread. "
            "The Census Bureau reported the figure in its annual note to bakers."
        ))
        self.assertFalse(wc.r_unsourced_number(
            "The new page is ten times faster than the paper pad. "
            "Mina Cole reported the timing from the counter logs she kept."
        ))
        self.assertFalse(wc.r_unsourced_number(
            "Experts say the weekday line is shorter now that the page is up. "
            "Mina Cole said the same thing at the counter last Friday."
        ))

    def test_never_fires_on_dates_times_prices_versions_or_own_counts(self):
        # source: Door 29, dates, times, prices, versions, and the writer's own counts never fire
        samples = [
            "The page opens on March 3, 2026 for weekday pickup orders at the counter.",
            "Pickup runs from 8:00 AM to 11:00 AM Tuesday through Friday at the counter.",
            "The country loaf costs $6 and the sesame bun costs $3 at the counter each morning.",
            "The ordering page uses version 2.4 of the form and nothing else is required for pickup.",
            "I wrote 12 tests before publishing the ordering page for the bakery counter.",
            "Mina bakes the country loaf 3 times a day for the weekday counter.",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertFalse(wc.r_unsourced_number(text))


class InterfaceTests(unittest.TestCase):
    def _run(self, *args, input_text=None, env=None):
        return subprocess.run(
            [sys.executable, SCRIPT, *args],
            input=input_text,
            text=True,
            capture_output=True,
            env=env,
        )

    def _write(self, directory, name, text):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_rewrite_prompt_shape(self):
        # source: Door 29, the rewrite prompt names the rule and asks for original -> rewrite
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "draft.md", DIRTY)
            proc = self._run("--rewrite-prompt", "--max", "0", path)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(wc.REWRITE_INSTRUCTION, proc.stdout)
        self.assertIn("original -> rewrite", proc.stdout)
        self.assertIn("[filler]", proc.stdout)
        self.assertIn("genuinely incompatible", proc.stdout)

    def test_json_report_fields(self):
        # source: Door 29, --json reports rule id, weight, line, excerpt, and totals
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "draft.md",
                "Title line here for the draft.\n\n" + DIRTY,
            )
            proc = self._run("--json", path)
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertIn("totals", data)
        self.assertIn("results", data)
        for key in ("inputs", "hits", "weighted", "max_rate_per_1k"):
            self.assertIn(key, data["totals"])
        self.assertGreater(data["totals"]["weighted"], 0)
        filler = [item for item in data["results"][0]["items"] if item["rule"] == "filler"]
        self.assertTrue(filler)
        item = filler[0]
        for key in ("rule", "weight", "line", "excerpt"):
            self.assertIn(key, item)
        self.assertEqual(item["rule"], "filler")
        self.assertEqual(item["weight"], 2)
        self.assertEqual(item["line"], 3)
        self.assertIn("genuinely", item["excerpt"])

    def test_stdin_json(self):
        # source: Door 29, --stdin scores text piped into the checker
        proc = self._run("--stdin", "--json", input_text=DIRTY)
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        rules = [item["rule"] for item in data["results"][0]["items"]]
        self.assertIn("filler", rules)

    def test_max_exit_codes(self):
        # source: Door 29, --max exits 1 over the rate and 0 at or under it
        with tempfile.TemporaryDirectory() as tmp:
            clean = self._write(tmp, "clean.md", CLEAN)
            dirty = self._write(tmp, "dirty.md", DIRTY)
            _hits, weighted, count = wc.score(DIRTY)
            self.assertGreater(weighted / float(count) * 1000.0, 15)
            _chits, cweight, _ccount = wc.score(CLEAN)
            self.assertEqual(cweight, 0)
            under = self._run("--max", "15", "--quiet", clean)
            over = self._run("--max", "15", "--quiet", dirty)
            high = self._run("--max", "1000", "--quiet", dirty)
        self.assertEqual(under.returncode, 0)
        self.assertEqual(over.returncode, 1)
        self.assertIn("FAIL", over.stdout)
        self.assertEqual(high.returncode, 0)

    def test_bad_arguments_exit_2(self):
        # source: Door 29, bad arguments exit 2
        missing = self._run()
        self.assertEqual(missing.returncode, 2)
        bad_words = self._run("--words", "sometimes")
        self.assertEqual(bad_words.returncode, 2)
        bad_max = self._run("--max", "abc", "draft.md")
        self.assertEqual(bad_max.returncode, 2)

    def test_quiet_is_one_summary_line(self):
        # source: Door 29, --quiet prints one summary line per input
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "clean.md", CLEAN)
            proc = self._run("--quiet", path)
        self.assertEqual(proc.returncode, 0)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("/1k", lines[0])

    def test_transcript_reader(self):
        # source: Door 29, the transcript reader scores assistant turns and can take the last N
        user = {
            "type": "user",
            "message": {"content": [{"type": "text", "text": "This user turn is genuinely full of filler and should be ignored by the reader."}]},
        }
        early = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "This early assistant turn is genuinely too polished for the notes we keep at the counter during the week."}]},
        }
        late = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "The later turn explains how the weekday ordering page lists the country loaf and the sesame bun for people who stop at the counter."}]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "session.jsonl",
                "\n".join([
                    "this line is not json",
                    json.dumps(user),
                    json.dumps(early),
                    json.dumps(late),
                    "",
                ]),
            )
            only_user = self._write(tmp, "user-only.jsonl", json.dumps(user) + "\n")
            last = self._run("--transcript", path, "--last", "1", "--json")
            full = self._run("--transcript", path, "--json")
            empty = self._run("--transcript", only_user, "--json")
        self.assertEqual(last.returncode, 0, last.stderr)
        last_rules = [item["rule"] for item in json.loads(last.stdout)["results"][0]["items"]]
        self.assertNotIn("filler", last_rules)
        full_rules = [item["rule"] for item in json.loads(full.stdout)["results"][0]["items"]]
        self.assertIn("filler", full_rules)
        self.assertEqual(empty.returncode, 0)
        self.assertIn("had no work", empty.stdout + empty.stderr)

    def test_html_script_is_not_prose(self):
        # source: Door 29, html files are scored as prose with tags stripped
        raw = (
            "<script>Where they are genuinely incompatible, pick one.</script>"
            "<p>The weekday ordering page lists the country loaf and the sesame bun "
            "for people who stop at the counter before work.</p>"
        )
        text = wc.strip_html(raw)
        self.assertNotIn("<p>", text)
        self.assertNotIn("<script>", text)
        self.assertFalse(wc.r_filler_intensifier(text))
        self.assertIn("weekday ordering page", text)

    def test_examples_before_scores_higher_than_after(self):
        # source: Door 29, 11-12: the post promised a checker and the gift was a checklist
        with open(BEFORE, encoding="utf-8") as handle:
            before = handle.read()
        with open(AFTER, encoding="utf-8") as handle:
            after = handle.read()
        for label, text in (("before", before), ("after", after)):
            count = len(text.split())
            self.assertGreaterEqual(count, 150, label)
            self.assertLessEqual(count, 250, label)
        b_hits, b_weight, b_n = wc.score(before)
        a_hits, a_weight, a_n = wc.score(after)
        b_rate = b_weight / float(b_n) * 1000.0
        a_rate = a_weight / float(a_n) * 1000.0
        self.assertGreater(b_rate, a_rate)
        self.assertGreaterEqual(b_rate, 20)
        self.assertLess(a_rate, 5)
        self.assertIn("unsourced_number", b_hits)
        self.assertNotIn("unsourced_number", a_hits)


class HookTests(unittest.TestCase):
    def _transcript(self, directory):
        line = json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "The page is a promise, not a form."}],
            },
        })
        path = os.path.join(directory, "transcript.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(line + "\n")
        _hits, weighted, count = wc.score("The page is a promise, not a form.")
        self.assertGreater(weighted / float(count) * 1000.0, 15)
        return path

    def _hook(self, payload, transcript_ok=True):
        env = os.environ.copy()
        env["WRITING_CHECK_MAX"] = "15"
        return subprocess.run(
            ["sh", HOOK],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
        )

    def test_stop_hook_active_exits_0(self):
        # source: Door 29, stop_hook_active must exit 0 so the hook cannot loop
        with tempfile.TemporaryDirectory() as tmp:
            path = self._transcript(tmp)
            proc = self._hook({
                "stop_hook_active": True,
                "transcript_path": path,
                "hook_event_name": "Stop",
            })
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("/1k", proc.stderr)

    def test_stop_hook_over_max_exits_2(self):
        # source: Door 29, a turn over the max exits 2 and prints the summary
        with tempfile.TemporaryDirectory() as tmp:
            path = self._transcript(tmp)
            proc = self._hook({
                "stop_hook_active": False,
                "transcript_path": path,
                "hook_event_name": "Stop",
            })
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("/1k", proc.stderr)


if __name__ == "__main__":
    unittest.main()
