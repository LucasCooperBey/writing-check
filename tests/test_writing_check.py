#!/usr/bin/env python3
"""Known-positive, known-clean, and interface tests for writing_check.py."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import atexit
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import writing_check as wc

BEFORE = os.path.join(ROOT, "examples", "before.md")
AFTER = os.path.join(ROOT, "examples", "after.md")
HOOK = os.path.join(ROOT, "hooks", "claude-code-stop-hook.sh")
PRECOMMIT = os.path.join(ROOT, "hooks", "pre-commit")
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
        long_over = DIRTY * 4 + CLEAN * 10
        with tempfile.TemporaryDirectory() as tmp:
            clean = self._write(tmp, "clean.md", CLEAN)
            dirty = self._write(tmp, "dirty.md", long_over)
            _hits, weighted, count = wc.score(DIRTY)
            self.assertGreater(weighted / float(count) * 1000.0, 15)
            _lhits, lweight, lcount = wc.score(long_over)
            self.assertGreaterEqual(lcount, 80)
            self.assertGreater(lweight / float(lcount) * 1000.0, 15)
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
        # The floor exempts a short turn, so this sample stays long enough that --max still applies.
        text = "The page is a promise, not a form. " * 16
        line = json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            },
        })
        path = os.path.join(directory, "transcript.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(line + "\n")
        _hits, weighted, count = wc.score(text)
        self.assertGreaterEqual(count, 80)
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

    def test_stop_hook_does_not_import_cwd_json(self):
        # source: 11-12 finding, the Stop hook imported json.py from its working folder
        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, "json-marker.txt")
            with open(os.path.join(tmp, "json.py"), "w", encoding="utf-8") as handle:
                handle.write("open(%r, 'w').write('ran\\n')\n" % marker)
            transcript = os.path.join(tmp, "transcript.jsonl")
            turn = (
                "The weekday ordering page lists the country loaf and the sesame bun "
                "for people who stop at the counter before work."
            )
            with open(transcript, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": turn}]},
                }) + "\n")
            env = os.environ.copy()
            env["WRITING_CHECK_MAX"] = "15"
            proc = subprocess.run(
                ["sh", HOOK],
                input=json.dumps({
                    "stop_hook_active": False,
                    "transcript_path": transcript,
                    "hook_event_name": "Stop",
                }),
                text=True,
                capture_output=True,
                cwd=tmp,
                env=env,
            )
            # Checked inside the with block: the folder and any marker are gone once it exits.
            self.assertFalse(os.path.exists(marker), proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


class ReviewFindingTests(unittest.TestCase):
    def _run(self, *args, input_text=None):
        return subprocess.run(
            [sys.executable, SCRIPT, *args],
            input=input_text,
            text=True,
            capture_output=True,
        )

    def _write(self, directory, name, text):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_short_reply_max_does_not_fail(self):
        # source: 11-12 finding, a 10-word sentence tripped solo-para and --max blocked it
        text = "This is the whole point of the page now friend.\n"
        self.assertEqual(len(wc._words(text)), 10)
        self.assertTrue(wc.r_solo_para(text))
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "reply.md", text)
            proc = self._run("--max", "15", "--quiet", path)
            raw = self._run("--max", "15", "--json", path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("/1k", proc.stdout)
        self.assertIn(
            "short: under 80 words, rate counted over 80 words, structure rules off",
            proc.stdout,
        )
        self.assertNotIn("FAIL", proc.stdout + proc.stderr)
        self.assertEqual(raw.returncode, 0, raw.stderr)
        self.assertTrue(json.loads(raw.stdout)["results"][0]["short"])

    def test_long_draft_over_max_still_exits_1(self):
        # source: 11-12 finding, the 80-word floor must not hide a long draft over the max
        hit = (
            "The weekday counter is genuinely ready for the morning loaf "
            "and the sesame bun today. "
        )
        pad = (
            "The weekday ordering page lists the country loaf and the sesame bun "
            "for people who stop at the counter before work. "
        )
        text = hit * 4 + pad * 8
        _hits, weighted, count = wc.score(text)
        self.assertGreaterEqual(count, 200)
        self.assertGreater(weighted / float(count) * 1000.0, 15)
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "draft.md", text)
            proc = self._run("--max", "15", "--quiet", path)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("FAIL", proc.stdout)
        self.assertNotIn("short: under 80 words", proc.stdout)

    def test_latin1_file_scores_without_traceback(self):
        # source: 11-12 finding, a non-UTF-8 file raised UnicodeDecodeError and blocked the commit
        raw = (
            b"The weekday ordering page lists the country loaf and the sesame bun "
            b"for people who stop at the counter before work.\n"
            b"Cafe\xe9 opens early.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "draft.md")
            with open(path, "wb") as handle:
                handle.write(raw)
            proc = self._run("--quiet", path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("/1k", proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("UnicodeDecodeError", proc.stderr + proc.stdout)

    def test_unexpected_exception_exits_3(self):
        # source: 11-12 finding, an uncaught exception exited 1 and the Stop hook read it as over the max
        def boom(_text):
            raise RuntimeError("boom")

        old = wc.RULES
        patched = []
        for rid, weight, desc, fn in old:
            if rid == "dash":
                patched.append((rid, weight, desc, boom))
            else:
                patched.append((rid, weight, desc, fn))
        wc.RULES = tuple(patched)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = self._write(tmp, "draft.md", CLEAN)
                err = io.StringIO()
                out = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = wc.main([path])
        finally:
            wc.RULES = old
        self.assertEqual(code, 3)
        self.assertEqual(err.getvalue().strip(), "could not do it: RuntimeError: boom")
        self.assertNotIn("Traceback", err.getvalue())
        self.assertNotIn("Traceback", out.getvalue())

    def test_dash_inside_code_fence_is_not_a_hit(self):
        # source: 11-12 finding, a dash inside a code fence was a hit over a smaller word count
        text = "The counter opens before work.\n\n```\nkeep \u2014 the dash\n```\n\nThe loaf is ready.\n"
        self.assertEqual(wc.r_dash(text), [])

    def test_two_dashes_ten_characters_apart_both_count(self):
        # source: 11-12 finding, the dash pattern consumed the next dash inside a 28-character window
        text = "Alpha \u2014" + "0123456789" + "\u2014 omega continues past the second dash.\n"
        self.assertEqual(len(wc.r_dash(text)), 2)

    def test_experts_found_is_not_a_named_source(self):
        # source: 11-12 finding, a capitalized sentence opener was treated as a named source
        text = "Experts found 80% of teams ship the page before the counter opens on Monday."
        self.assertFalse(wc._named_source(text))
        self.assertFalse(wc._sourced(text))
        kept = "Gallup found 80% of teams ship the page before the counter opens on Monday."
        self.assertTrue(wc._named_source(kept))
        self.assertTrue(wc._sourced(kept))

    def test_repeated_sentence_reports_each_line(self):
        # source: 11-12 finding, a repeated sentence reported the first line for every hit
        sentence = "Where they are genuinely incompatible, pick one and explain the choice."
        text = "\n".join([
            "Intro stays on line one.",
            "",
            sentence,
            "",
            "Middle stays on line five.",
            "",
            "",
            "",
            sentence,
        ])
        hits, _weighted, _count = wc.score(text)
        found = sorted(item["line"] for item in hits["filler"])
        self.assertEqual(found, [3, 9])

    def test_last_rejects_zero_and_negative(self):
        # source: 11-12 finding, --last accepted 0 and negative numbers
        early = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "The early turn lists the country loaf for the weekday counter."}]},
        }
        late = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "The later turn lists the sesame bun for the weekday counter."}]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "session.jsonl",
                json.dumps(early) + "\n" + json.dumps(late) + "\n",
            )
            zero = self._run("--transcript", path, "--last", "0", "--quiet")
            neg = self._run("--transcript", path, "--last", "-1", "--quiet")
        self.assertEqual(zero.returncode, 2, zero.stdout + zero.stderr)
        self.assertEqual(neg.returncode, 2, neg.stdout + neg.stderr)
        self.assertIn("1 or more", zero.stderr)
        self.assertIn("1 or more", neg.stderr)
        self.assertNotIn("/1k", zero.stdout)
        self.assertNotIn("/1k", neg.stdout)


class Round3ReviewTests(unittest.TestCase):
    def _run(self, *args, input_bytes=None, env=None):
        kwargs = {"capture_output": True, "env": env}
        if input_bytes is None:
            kwargs["text"] = True
        return subprocess.run([sys.executable, SCRIPT, *args], input=input_bytes, **kwargs)

    def _git_env(self):
        env = os.environ.copy()
        for key in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_PREFIX",
            "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR",
            "WRITING_CHECK",
            "WRITING_CHECK_MAX",
        ):
            env.pop(key, None)
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_AUTHOR_NAME"] = "Writing Check"
        env["GIT_AUTHOR_EMAIL"] = "writing-check@example.com"
        env["GIT_COMMITTER_NAME"] = "Writing Check"
        env["GIT_COMMITTER_EMAIL"] = "writing-check@example.com"
        return env

    def _init_repo(self, tmp):
        env = self._git_env()
        init = subprocess.run(
            ["git", "init", "-q", "-b", "main"],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        hook = os.path.join(tmp, ".git", "hooks", "pre-commit")
        shutil.copy(PRECOMMIT, hook)
        os.chmod(hook, 0o755)
        return env

    def _git(self, tmp, env, *args):
        return subprocess.run(
            ["git", *args],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_short_em_dash_exceeds_max(self):
        # source: 11-12 review of a7f7ca8, a draft under 80 words is exempt from --max
        dash = chr(0x2014)
        text = "The weekday counter lists the loaf " + dash + " and the bun for pickup now.\n"
        self.assertEqual(len(wc._words(text)), 12)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "draft.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            proc = self._run("--max", "15", "--quiet", path)
        self.assertIn("37.5/1k", proc.stdout)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_short_filler_exceeds_max(self):
        # source: 11-12 review of a7f7ca8, a draft under 80 words is exempt from --max
        text = "The weekday counter is genuinely ready for the morning loaf today friend.\n"
        self.assertEqual(len(wc._words(text)), 12)
        self.assertTrue(wc.r_filler_intensifier(text))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "draft.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            proc = self._run("--max", "15", "--quiet", path)
        self.assertIn("25.0/1k", proc.stdout)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_short_clean_stays_under_max(self):
        # source: 11-12 review of a7f7ca8, a draft under 80 words is exempt from --max
        text = "The weekday counter lists the loaf and the bun for pickup now.\n"
        self.assertEqual(len(wc._words(text)), 12)
        self.assertTrue(wc.r_solo_para(text))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "draft.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            proc = self._run("--max", "15", "--quiet", path)
        self.assertIn("  0.0/1k", proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_stdin_utf8_replace_under_c_locale(self):
        # source: 11-12 review of a7f7ca8, --stdin reads with the locale encoding
        # Under LC_ALL=C, Python 3.7 and later read stdin as UTF-8 with surrogateescape,
        # so the old read only raised under a UTF-8 locale. Each locale is checked.
        for locale_name in ("C", "C.UTF-8", "en_US.UTF-8"):
            with self.subTest(locale=locale_name):
                env = os.environ.copy()
                env["LC_ALL"] = locale_name
                env.pop("PYTHONIOENCODING", None)
                env.pop("PYTHONUTF8", None)
                proc = self._run(
                    "--stdin",
                    "--quiet",
                    input_bytes=b"caf\xe9 is open late tonight.",
                    env=env,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn(b"/1k", proc.stdout)
                self.assertNotIn(b"UnicodeDecodeError", proc.stderr)
                self.assertNotIn(b"Traceback", proc.stderr)

    def test_stdin_drops_a_utf8_bom(self):
        # source: 11-12 review of db69a1e, a UTF-8 BOM on stdin stayed as U+FEFF in the first word
        text = "The weekday counter is genuinely ready for the morning loaf today friend."
        plain = self._run("--stdin", "--json", input_bytes=text.encode("utf-8"))
        bom = self._run("--stdin", "--json", input_bytes=b"\xef\xbb\xbf" + text.encode("utf-8"))
        self.assertEqual(bom.returncode, 0, bom.stderr)
        self.assertEqual(json.loads(bom.stdout.decode("utf-8")), json.loads(plain.stdout.decode("utf-8")))

    def test_precommit_latin1_does_not_block(self):
        # source: 11-12 review of a7f7ca8, a staged Latin-1 file blocks the commit
        with tempfile.TemporaryDirectory() as tmp:
            env = self._init_repo(tmp)
            env["WRITING_CHECK"] = SCRIPT
            with open(os.path.join(tmp, "note.md"), "wb") as handle:
                handle.write(
                    b"Cafe\xe9 is open late tonight for the weekday counter crowd.\n"
                )
            added = self._git(tmp, env, "add", "note.md")
            self.assertEqual(added.returncode, 0, added.stderr)
            proc = self._git(tmp, env, "commit", "-m", "add note")
        combined = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, combined)
        self.assertIn("/1k", combined)
        self.assertNotIn("could not do it", combined)

    def test_precommit_renamed_em_dash_blocks(self):
        # source: 11-12 review of a7f7ca8, a renamed and edited file is not scored
        dash = chr(0x2014)
        clean = "The weekday counter lists the loaf and the bun for pickup now.\n"
        dirty = "The weekday counter lists the loaf " + dash + " and the bun for pickup now.\n"
        self.assertEqual(len(wc._words(dirty)), 12)
        with tempfile.TemporaryDirectory() as tmp:
            env = self._init_repo(tmp)
            env["WRITING_CHECK"] = SCRIPT
            with open(os.path.join(tmp, "note.md"), "w", encoding="utf-8") as handle:
                handle.write(clean * 6)
            added = self._git(tmp, env, "add", "note.md")
            self.assertEqual(added.returncode, 0, added.stderr)
            first = self._git(tmp, env, "commit", "-m", "add note")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            moved = self._git(tmp, env, "mv", "note.md", "page.md")
            self.assertEqual(moved.returncode, 0, moved.stderr)
            with open(os.path.join(tmp, "page.md"), "w", encoding="utf-8") as handle:
                handle.write(clean * 5 + dirty)
            staged = self._git(tmp, env, "add", "--", "page.md")
            self.assertEqual(staged.returncode, 0, staged.stderr)
            status = self._git(tmp, env, "diff", "--cached", "--name-status")
            self.assertTrue(status.stdout.startswith("R"), status.stdout)
            blocked = self._git(tmp, env, "commit", "-m", "rename page")
        combined = blocked.stdout + blocked.stderr
        self.assertEqual(blocked.returncode, 1, combined)
        self.assertIn("37.5/1k", combined)

    def test_precommit_checker_error_exits_0(self):
        # source: 11-12 review of a7f7ca8, the hook exits with the checker status when it is neither 0 nor 1
        with tempfile.TemporaryDirectory() as tmp:
            env = self._init_repo(tmp)
            standin = os.path.join(tmp, "standin.py")
            with open(standin, "w", encoding="utf-8") as handle:
                handle.write("import sys\nsys.exit(3)\n")
            env["WRITING_CHECK"] = standin
            with open(os.path.join(tmp, "note.md"), "w", encoding="utf-8") as handle:
                handle.write("The weekday counter lists the loaf and the bun for pickup now.\n")
            added = self._git(tmp, env, "add", "note.md")
            self.assertEqual(added.returncode, 0, added.stderr)
            hook = os.path.join(tmp, ".git", "hooks", "pre-commit")
            for shell in ("/bin/sh", "/bin/dash"):
                if not os.path.exists(shell):
                    continue
                proc = subprocess.run(
                    [shell, hook],
                    cwd=tmp,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, 0, shell + "\n" + proc.stderr)
                self.assertIn("could not do it", proc.stderr)
                self.assertIn("note.md", proc.stderr)

    def test_precommit_does_not_import_repo_json(self):
        # source: 11-12 review of a7f7ca8, python3 puts the repository root first on the module path
        with tempfile.TemporaryDirectory() as tmp:
            env = self._init_repo(tmp)
            marker = os.path.join(tmp, "json-marker.txt")
            with open(os.path.join(tmp, "json.py"), "w", encoding="utf-8") as handle:
                handle.write("open(%r, 'w').write('ran\\n')\n" % marker)
            shutil.copy(SCRIPT, os.path.join(tmp, "writing_check.py"))
            with open(os.path.join(tmp, "note.md"), "w", encoding="utf-8") as handle:
                handle.write("The weekday counter lists the loaf and the bun for pickup now.\n")
            added = self._git(tmp, env, "add", "note.md")
            self.assertEqual(added.returncode, 0, added.stderr)
            hook = os.path.join(tmp, ".git", "hooks", "pre-commit")
            proc = subprocess.run(
                ["sh", hook],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertIn("/1k", proc.stdout, proc.stderr)
            self.assertFalse(os.path.exists(marker), proc.stderr + proc.stdout)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_repeated_filler_keeps_its_sentence(self):
        # source: 11-12 review of a7f7ca8, _sentence_containing returns the first sentence holding the fragment
        first = "The morning loaf is genuinely warm on the weekday counter."
        second = "The evening bun is genuinely fresh for the late pickup."
        text = first + "\n" + second + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "draft.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            proc = self._run("--json", path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        fillers = [
            item
            for item in json.loads(proc.stdout)["results"][0]["items"]
            if item["rule"] == "filler"
        ]
        self.assertEqual(len(fillers), 2)
        self.assertIn("morning loaf", fillers[0]["sentence"])
        self.assertIn("evening bun", fillers[1]["sentence"])
        self.assertNotEqual(fillers[0]["sentence"], fillers[1]["sentence"])
        self.assertNotIn("evening", fillers[0]["sentence"])
        self.assertNotIn("morning", fillers[1]["sentence"])


if __name__ == "__main__":
    unittest.main()
