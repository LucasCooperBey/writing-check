#!/usr/bin/env python3
"""writing_check.py: score performed-craft shapes in a draft.

Not a vocabulary scrubber. A word ban strips a writer's real words (measured in
one writer's corpus: "leverage" 1,132 times, "look" 4,832 times). This detects
shapes. The fix is to say the sentence plainly.

High precision over coverage. A noisy detector gets ignored, and an ignored
detector is worse than none because it looks like coverage.

Usage:
  writing_check.py FILE...
  writing_check.py --stdin
  writing_check.py --transcript FILE.jsonl [--last N]
  writing_check.py --rewrite-prompt FILE
  writing_check.py --json FILE
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-z'\u2019]+")
_DASH_RE = re.compile(".{0,28}([\u2014\u2013]).{0,28}")

# A heading or a bullet with no terminal punctuation would let one sentence run
# across blocks. Antithesis and tailing negation read one block at a time.
# Splitting list items would make an ordinary bulleted list look like a
# staccato run, so only those two rules use blocks.
BLOCK_SPLIT = re.compile(r"\n\s*\n|\n(?=[ \t]*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|\|))")

_METAPHOR_NOUNS = (
    r"(testament|currency|language|architecture|heart|soul|engine|backbone|"
    r"art|poetry|music|dna|lifeblood|cornerstone|essence|shape|price|cost)"
)

_IDENT = re.compile(r"^(?:[0-9a-f]{6,}|\d+)$", re.I)

SOFT_WORDS = (
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
    "multifaceted",
    "underscore",
    "foster",
    "holistic",
    "synergy",
    "paradigm",
    "transformative",
    "groundbreaking",
    "meticulous",
    "intricate",
    "plethora",
    "myriad",
    "nestled",
    "bustling",
    "furthermore",
    "moreover",
    "streamline",
    "ever-evolving",
    "in today's fast-paced world",
    "it's important to note",
    "navigate the complexities",
    "it's worth noting",
    "at the end of the day",
)

REWRITE_INSTRUCTION = (
    "Rewrite only these sentences in plain words. Keep every fact, number, "
    "name and link. Do not add new claims. Return each as: original -> rewrite."
)

# On a designed HTML page, short labels and captions are layout. HTML mode
# skips these two so those labels do not swamp the prose signal.
HTML_EXCLUDE = {"solo-para", "punchline"}

_PERCENT_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)"
    r"\s*-?\s*(?:%|percent)\b",
    re.I,
)
_MULT_X_RE = re.compile(r"\b\d+(?:\.\d+)?x\b", re.I)
_MULT_TIMES_RE = re.compile(
    r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\s+times\b"
    r"(?!\s+(?:a|an|per|each|every|daily|weekly|monthly|yearly)\b)",
    re.I,
)
_STUDY_RE = re.compile(r"\b(?:studies show|research shows|experts say)\b", re.I)
_CITE_RE = re.compile(r"\[[^\]]+\]|\u2020|\u2021")
_LINK_RE = re.compile(r"https?://\S+|\bwww\.\S+|\[[^\]]*\]\([^)]+\)", re.I)
_NAMED_SOURCE_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9.&'-]*(?:\s+(?:of|the|and|for|&)\s+[A-Z][A-Za-z0-9.&'-]*|"
    r"\s+[A-Z][A-Za-z0-9.&'-]*){0,4})"
    r"\s+(?:(?:has|have|recently|later|also|then)\s+){0,2}"
    r"(?:said|found|reported)\b"
)
_NAME_SKIP = {
    "I", "We", "They", "He", "She", "It", "This", "That", "These", "Those",
    "There", "My", "Our", "The", "A", "An", "And", "But", "Or", "For", "Of",
}
_HEDGE_RES = (
    re.compile(r"\bto some extent\b", re.I),
    re.compile(r"\bit seems\b", re.I),
    re.compile(r"\bmight\b", re.I),
    re.compile(r"\bcould\b", re.I),
    re.compile(r"\bperhaps\b", re.I),
    re.compile(r"\bpossibly\b", re.I),
    re.compile(r"\barguably\b", re.I),
    re.compile(r"\bpotentially\b", re.I),
    re.compile(r"\bsomewhat\b", re.I),
    re.compile(r"\bmay\b"),  # lowercase only: the month May is not a hedge
)


def _phrase_re(phrase):
    bits = []
    for word in phrase.split(" "):
        esc = re.escape(word).replace("\\'", "['\u2019]")
        bits.append(esc)
    return re.compile(r"\b" + r"\s+".join(bits) + r"\b", re.I)


_WORD_RES = tuple((phrase, _phrase_re(phrase)) for phrase in SOFT_WORDS)


def _claim_text(text):
    """Drop code, quotes, and tables. Keep links so a citation can still count."""
    t = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    t = re.sub(r"`[^`]*`", " ", t)
    t = re.sub(r"^\s*>.*$", " ", t, flags=re.M)
    t = re.sub(r"^\s*[|+].*$", " ", t, flags=re.M)
    return t


def _quoted_stripped(text):
    """Remove everything that is not the writer's own prose.

    Code, blockquotes, table rows, and URLs are not evidence of this writer's
    style. A turn can quote another document verbatim, and that quote cannot
    count as performed craft. URLs are removed here so a long link does not
    inflate the word count. The unsourced-number rule uses _claim_text instead,
    because it has to see the link.
    """
    return re.sub(r"https?://\S+", " ", _claim_text(text))


def _sentences(text):
    return [s.strip() for s in SENT_SPLIT.split(_quoted_stripped(text)) if s.strip()]


def _block_sentences(text):
    out = []
    for block in BLOCK_SPLIT.split(_quoted_stripped(text)):
        out.extend(s.strip() for s in SENT_SPLIT.split(block) if s.strip())
    return out


def _words(s):
    return _WORD_RE.findall(s)


def _one_line(s):
    return " ".join((s or "").split())


def _hit(detail, excerpt, anchor=None, sentence=None):
    shown = _one_line(excerpt)
    if len(shown) > 180:
        shown = shown[:177] + "..."
    sent = _one_line(sentence if sentence is not None else excerpt)
    return {
        "detail": detail,
        "excerpt": shown,
        "sentence": sent,
        "anchor": anchor if anchor is not None else (excerpt or shown),
    }


def _sentence_containing(text, fragment):
    frag = (fragment or "").strip()
    if not frag:
        return ""
    for sent in _block_sentences(text):
        if frag in sent:
            return _one_line(sent)
    idx = text.find(frag)
    if idx < 0:
        return _one_line(frag)
    left = text.rfind("\n", 0, idx)
    left = 0 if left < 0 else left + 1
    right = text.find("\n", idx)
    if right < 0:
        right = len(text)
    return _one_line(text[left:right])


def _line_of(text, fragment):
    if not fragment:
        return 1
    idx = text.find(fragment)
    if idx < 0:
        idx = text.lower().find(fragment.lower())
    if idx < 0:
        return 1
    return text.count("\n", 0, idx) + 1


def r_dash(text):
    out = []
    for m in _DASH_RE.finditer(text):
        if m.group(1) == "\u2013":
            # An en dash that joins a numeric or date range is typography.
            i = m.start(1)
            if re.search(r"\d ?$", text[max(0, i - 3):i]):
                continue
            # An en dash between two inline code spans is an identifier range.
            if text[max(0, i - 1):i] == "`" and text[i + 1:i + 2] == "`":
                continue
        window = m.group(0)
        sent = _sentence_containing(text, m.group(1))
        out.append(_hit("em/en dash: ...%s..." % window, sent or window, anchor=window, sentence=sent or window))
    return out


def r_antithesis(text):
    """Manufactured symmetry: a semicolon closer, an 'X, not Y' closer, or a fragment."""
    out = []
    for s in _block_sentences(text):
        if re.search(
            r";\s*\w[^;]{0,70}\b(does not|do not|cannot|is not|are not|never|not)\b[^;]{0,30}$",
            s,
            re.I,
        ):
            out.append(_hit("antithetical semicolon: %s" % s[:110], s, anchor=s[:80], sentence=s))
        elif re.search(
            r"\b(is|was|are|were|means|becomes)\b[^,.;]{2,50},\s*not\s+\w[^.]{0,40}\.$",
            s,
            re.I,
        ):
            out.append(_hit("'X, not Y' closer: %s" % s[:110], s, anchor=s[:80], sentence=s))
        elif re.search(r"^[A-Z][^,.;:]{1,45}, not [^,.;]{1,35}[.!]$", s) and len(_words(s)) <= 9:
            # A short verbless fragment with ", not" is the same shape as the closer.
            out.append(_hit("verbless ', not Y' fragment: %s" % s[:110], s, anchor=s[:80], sentence=s))
    return out


def r_aphorism(text):
    """Metaphor formulas. Y must be a metaphor noun, and one sentence yields one hit."""
    out = []
    for s in _sentences(text):
        if re.search(r"\bis (the|a) " + _METAPHOR_NOUNS + r" of \w+", s, re.I) and len(_words(s)) < 22:
            out.append(_hit("aphorism 'X is the Y of Z': %s" % s[:110], s, anchor=s[:80], sentence=s))
        elif re.search(r"\bnot (a|an|just|merely|only)\b[^.]{3,60}\b(but|it'?s)\b", s, re.I):
            out.append(_hit("correlative 'not just X but Y': %s" % s[:110], s, anchor=s[:80], sentence=s))
        elif re.search(r"\bthe " + _METAPHOR_NOUNS + r" of\b", s, re.I):
            out.append(_hit("aphorism formula: %s" % s[:110], s, anchor=s[:80], sentence=s))
    return out


def r_staccato(text):
    """Three or more consecutive short sentences, or a very short paragraph-final punchline."""
    out = []
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    paras = [
        p for p in text.split("\n\n")
        if p.strip() and not p.strip().startswith(("|", "```", "- ", "* ", "#"))
    ]
    for para in paras:
        if any(l.lstrip().startswith(("-", "*", "|", ">", "#")) for l in para.split("\n")[1:]):
            continue
        sents = _sentences(para)
        if len(sents) < 2:
            continue
        run = 0
        for s in sents:
            run = run + 1 if len(_words(s)) <= 6 else 0
            if run >= 3:
                flat = _one_line(para)
                anchor = sents[0][:60]
                out.append(_hit(
                    "staccato run (3+ short sentences): %s" % flat[:110],
                    flat,
                    anchor=anchor,
                    sentence=flat,
                ))
                break
        last = sents[-1]
        if len(sents) >= 2 and len(_words(last)) <= 7 and not last.rstrip().endswith(":"):
            out.append(_hit(
                'short punchline closer: "%s"' % last[:80],
                last,
                anchor=last[:80],
                sentence=last,
            ))
    return out


def r_solo_para(text):
    """A one-sentence paragraph used as a drop-the-mic beat."""
    out = []
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    paras = [p.strip() for p in text.split("\n\n")]
    for p in paras:
        if not p or p.startswith(("|", "```", "#", "- ", "* ", ">")) or re.match(r"^\d+\.", p):
            continue
        lines = p.split("\n")
        if re.match(r"^\*\*[^*\n]+\*\*:?$", lines[0].strip()):
            continue
        if any(l.lstrip().startswith(("-", "*", "|", ">", "#")) for l in lines[1:]):
            continue
        s = _sentences(p)
        if len(s) == 1 and 3 <= len(_words(p)) <= 14 and not p.rstrip().endswith((":", "?")):
            flat = _one_line(p)
            out.append(_hit(
                'one-line paragraph as a beat: "%s"' % flat[:90],
                flat,
                anchor=flat[:80],
                sentence=flat,
            ))
    return out


def r_rule_of_three(text):
    """Exactly three coordinated items closing a sentence.

    Four or more items are an inventory, not a cadence. Identifiers and bare
    numbers are not prose, so both are skipped.
    """
    out = []
    for s in _sentences(text):
        m = re.search(r"\b(\w+(?:\s\w+)?), (\w+(?:\s\w+)?), and (\w+(?:\s\w+)?)\b[.;]", s)
        if not m:
            continue
        if re.search(r",\s*$", s[:m.start()]):
            continue
        if all(_IDENT.match(g.split()[-1]) for g in m.groups()):
            continue
        out.append(_hit("rule of three: %s" % s[:110], s, anchor=m.group(0), sentence=s))
    return out


def r_tailing_negation(text):
    out = []
    for s in _block_sentences(text):
        if re.search(r",\s*(no|not)\s+\w+(ing|s)?\.$", s, re.I):
            out.append(_hit("tailing negation: %s" % s[:110], s, anchor=s[:80], sentence=s))
    return out


def r_signpost(text):
    pats = (
        r"(let's dive in|let's explore|here's what you need to know|without further ado|"
        r"let's break this down|the real question is|at its core|what really matters|"
        r"the deeper issue)"
    )
    out = []
    for m in re.finditer(pats, text, re.I):
        sent = _sentence_containing(text, m.group(0))
        out.append(_hit(
            "signpost/authority trope: %s" % m.group(0),
            sent or m.group(0),
            anchor=m.group(0),
            sentence=sent or m.group(0),
        ))
    return out


def r_inline_header_bullets(text):
    hits = list(re.finditer(r"(?m)^\s*[-*]\s+\*\*[^*\n]{2,40}:\*\*", text))
    if len(hits) < 3:
        return []
    lines = []
    for m in hits:
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if line_end < 0:
            line_end = len(text)
        lines.append(text[line_start:line_end].strip())
    blob = " ".join(lines)
    first = hits[0].group(0).strip()
    return [_hit(
        "inline-header bullet list (%d items)" % len(hits),
        blob,
        anchor=first,
        sentence=blob,
    )]


def r_filler_intensifier(text):
    """Empty intensifiers that perform sincerity instead of stating the fact.

    Only the adverbial filler use is flagged. Code, quotes, and tables are
    stripped first so a list of these words is not scored as a performance.
    """
    pats = (
        r"\b(genuinely|truly|honestly|frankly|remarkably|surprisingly|"
        r"undeniably|unmistakably|profoundly|deeply satisfying|"
        r"quite simply|simply put|make no mistake)\b"
    )
    stripped = _quoted_stripped(text)
    out = []
    for m in re.finditer(pats, stripped, re.I):
        sent = _sentence_containing(text, m.group(0))
        out.append(_hit(
            "filler intensifier: %s" % m.group(0),
            sent or m.group(0),
            anchor=m.group(0),
            sentence=sent or m.group(0),
        ))
    return out


def r_words(text):
    """Soft list. Weight is applied by score(); this only finds the phrases."""
    stripped = _quoted_stripped(text)
    spans = []
    for phrase, cre in _WORD_RES:
        for m in cre.finditer(stripped):
            spans.append((m.start(), m.end(), m.group(0), phrase))
    spans.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
    chosen = []
    occupied = []
    for start, end, frag, phrase in spans:
        if any(not (end <= s or start >= e) for s, e in occupied):
            continue
        occupied.append((start, end))
        chosen.append((start, frag, phrase))
    chosen.sort(key=lambda item: item[0])
    out = []
    for _start, frag, _phrase in chosen:
        sent = _sentence_containing(text, frag)
        out.append(_hit("soft word: %s" % frag, frag, anchor=frag, sentence=sent or frag))
    return out


def r_hedges(text):
    """Two or more hedges inside one sentence."""
    out = []
    for s in _sentences(text):
        count = 0
        for cre in _HEDGE_RES:
            count += len(cre.findall(s))
        if count >= 2:
            out.append(_hit("stacked hedges (%d): %s" % (count, s[:110]), s, anchor=s[:80], sentence=s))
    return out


def _has_link(text):
    return _LINK_RE.search(text) is not None


def _has_citation(text):
    return _CITE_RE.search(text) is not None


def _named_source(text):
    for m in _NAMED_SOURCE_RE.finditer(text):
        tokens = [tok for tok in m.group(1).split() if tok]
        content = [
            tok for tok in tokens
            if tok not in _NAME_SKIP and tok.lower() not in {"of", "the", "and", "for", "&"}
        ]
        if content:
            return True
    return False


def _sourced(text):
    return _has_link(text) or _has_citation(text) or _named_source(text)


def _numeric_claim(sentence):
    if _STUDY_RE.search(sentence):
        return True
    if _PERCENT_RE.search(sentence):
        return True
    if _MULT_X_RE.search(sentence):
        return True
    if _MULT_TIMES_RE.search(sentence):
        return True
    return False


def r_unsourced_number(text):
    """A percent, a multiplier, or a study claim with no source nearby.

    Dates, times, prices, version numbers, and counts of the writer's own
    things are not claims of this kind, so a sentence that only has those
    never matches. A link, a citation bracket, a footnote marker, or a
    capitalized name before said/found/reported in this sentence or the next
    one keeps the sentence quiet.
    """
    raw = _claim_text(text)
    parts = [s.strip() for s in SENT_SPLIT.split(raw) if s.strip()]
    out = []
    for i, sent in enumerate(parts):
        if not _numeric_claim(sent):
            continue
        nxt = parts[i + 1] if i + 1 < len(parts) else ""
        if _sourced(sent + " " + nxt):
            continue
        flat = _one_line(sent)
        out.append(_hit("unsourced number: %s" % flat[:110], flat, anchor=flat[:80], sentence=flat))
    return out


RULES = [
    ("dash", 3, "em/en dashes", r_dash),
    ("filler", 2, "filler intensifiers", r_filler_intensifier),
    ("antithesis", 3, "manufactured antithesis", r_antithesis),
    ("aphorism", 3, "aphorism formulas", r_aphorism),
    ("punchline", 2, "staccato / punchline closer", r_staccato),
    ("solo-para", 2, "one-line paragraph beats", r_solo_para),
    ("three", 1, "rule of three", r_rule_of_three),
    ("tail-neg", 2, "tailing negation", r_tailing_negation),
    ("signpost", 2, "signposting", r_signpost),
    ("bullets", 1, "inline-header bullets", r_inline_header_bullets),
    ("hedges", 1, "stacked hedges", r_hedges),
    ("unsourced_number", 1, "unsourced number or study claim", r_unsourced_number),
    ("words", 0, "soft word list", r_words),
]


def strip_html(text):
    """Score HTML as prose: drop style, script, and tags, then decode entities."""
    text = re.sub(r"<(style|script)\b.*?</\1>", " ", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def score(text, exclude=None, words_mode="warn"):
    """Return (hits_by_rule, weighted, word_count).

    The denominator matches what the rules scan, so a long quotation does not
    dilute the rate. Soft-list hits use weight 0 and never move `weighted`.
    """
    skipped = set(exclude or ())
    if words_mode == "off":
        skipped.add("words")
    hits = {}
    weighted = 0
    for rid, weight, _desc, fn in RULES:
        if rid in skipped:
            continue
        found = fn(text) or []
        if not found:
            continue
        normalized = []
        for item in found:
            if isinstance(item, str):
                item = _hit(item, item)
            else:
                item = dict(item)
            item["rule"] = rid
            item["weight"] = weight
            item["line"] = _line_of(text, item.get("anchor") or item.get("excerpt") or "")
            normalized.append(item)
        hits[rid] = normalized
        weighted += weight * len(normalized)
    n = max(len(_words(_quoted_stripped(text))), 1)
    return hits, weighted, n


def _verdict(rate):
    if rate < 4:
        return "CLEAN"
    if rate < 10:
        return "WATCH"
    return "PERFORMED"


def analyze(text, label, exclude=None, words_mode="warn"):
    hits, weighted, n = score(text, exclude=exclude, words_mode=words_mode)
    rate = weighted / float(n) * 1000.0
    items = []
    for rid, _weight, _desc, _fn in RULES:
        items.extend(hits.get(rid, []))
    return {
        "label": label,
        "words": n,
        "hit_count": len(items),
        "weighted": weighted,
        "rate": rate,
        "verdict": _verdict(rate),
        "hits": hits,
        "items": items,
    }


def format_human(rep, quiet=False):
    line = "[%s] %5.1f/1k  %3d hits  %5d words  %s" % (
        "%-9s" % rep["verdict"],
        rep["rate"],
        rep["hit_count"],
        rep["words"],
        rep["label"],
    )
    if quiet:
        return line
    lines = [line]
    for rid, weight, desc, _fn in RULES:
        group = rep["hits"].get(rid)
        if not group:
            continue
        lines.append("    %-11s x%-3d (%s, weight %s)" % (rid, len(group), desc, weight))
        for item in group[:4]:
            lines.append("       - %s" % item["detail"])
        extra = len(group) - 4
        if extra > 0:
            lines.append("       ... %d more" % extra)
    return "\n".join(lines)


def format_rewrite(reports):
    lines = []
    multi = len(reports) > 1
    any_hit = False
    for rep in reports:
        items = sorted(rep["items"], key=lambda item: (item.get("line") or 1, item.get("rule") or ""))
        seen = set()
        block = []
        for item in items:
            sentence = item.get("sentence") or item.get("excerpt") or ""
            sentence = _one_line(sentence)
            if not sentence:
                continue
            key = (item.get("rule"), sentence)
            if key in seen:
                continue
            seen.add(key)
            block.append("[%s] %s" % (item.get("rule"), sentence))
        if not block:
            continue
        any_hit = True
        if multi:
            lines.append("File: %s" % rep["label"])
        lines.extend(block)
        lines.append("")
    if not any_hit:
        lines.append("No sentences were flagged.")
        lines.append("")
    lines.append(REWRITE_INSTRUCTION)
    return "\n".join(lines).rstrip() + "\n"


def format_json(reports):
    results = []
    total_hits = 0
    total_weighted = 0
    max_rate = 0.0
    for rep in reports:
        items = []
        for item in rep["items"]:
            items.append({
                "rule": item["rule"],
                "weight": item["weight"],
                "line": item["line"],
                "excerpt": item["excerpt"],
            })
        total_hits += rep["hit_count"]
        total_weighted += rep["weighted"]
        if rep["rate"] > max_rate:
            max_rate = rep["rate"]
        results.append({
            "label": rep["label"],
            "words": rep["words"],
            "hit_count": rep["hit_count"],
            "weighted": rep["weighted"],
            "rate_per_1k": round(rep["rate"], 4),
            "verdict": rep["verdict"],
            "items": items,
        })
    payload = {
        "results": results,
        "totals": {
            "inputs": len(results),
            "hits": total_hits,
            "weighted": total_weighted,
            "max_rate_per_1k": round(max_rate, 4),
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


def assistant_turns(path, last=None):
    out = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                data = json.loads(line)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") != "assistant":
                continue
            content = (data.get("message") or {}).get("content")
            if isinstance(content, list):
                txt = "\n\n".join(
                    c.get("text", "")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                )
                if txt.strip():
                    out.append(txt)
    return out[-last:] if last else out


def _display_path(path):
    home = os.path.expanduser("~")
    if home and home != "~" and path.startswith(home):
        return "~" + path[len(home):]
    return path


def _load_inputs(args):
    inputs = []
    if args.transcript:
        path = os.path.expanduser(args.transcript)
        if not os.path.isfile(path):
            print("writing-check: could not do it (transcript not found)", file=sys.stderr)
            return None, 2
        turns = assistant_turns(path, args.last)
        if not turns:
            if not args.stdin and not args.files:
                print("writing-check: had no work (no assistant text turns)")
                return None, 0
            print("writing-check: had no work (no assistant text turns)", file=sys.stderr)
        else:
            label = "%d assistant turn%s (combined)" % (len(turns), "" if len(turns) == 1 else "s")
            inputs.append((label, "\n\n".join(turns), set()))
    if args.stdin:
        inputs.append(("<stdin>", sys.stdin.read(), set()))
    for name in args.files:
        path = os.path.expanduser(name)
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as err:
            print("writing-check: could not do it (%s)" % err.strerror, file=sys.stderr)
            return None, 2
        exclude = set()
        if path.lower().endswith((".html", ".htm")):
            text = strip_html(text)
            exclude = set(HTML_EXCLUDE)
        inputs.append((_display_path(path), text, exclude))
    if not inputs:
        print(
            "writing-check: could not do it (nothing to score: give FILE, --stdin, or --transcript)",
            file=sys.stderr,
        )
        return None, 2
    return inputs, None


def _parser():
    ap = argparse.ArgumentParser(
        prog="writing_check.py",
        description="Score performed-craft shapes in a draft. Standard library only.",
    )
    ap.add_argument("files", nargs="*")
    ap.add_argument("--stdin", action="store_true", help="score stdin")
    ap.add_argument("--transcript", help="score assistant turns in a JSONL transcript")
    ap.add_argument("--last", type=int, help="only the last N assistant turns")
    ap.add_argument("--quiet", action="store_true", help="one summary line per input")
    ap.add_argument("--max", type=float, default=None, help="exit 1 when the rate exceeds N")
    ap.add_argument("--words", choices=("off", "warn"), default="warn", help="soft word list (default: warn)")
    ap.add_argument("--rewrite-prompt", action="store_true", help="print a rewrite prompt and exit 0")
    ap.add_argument("--json", action="store_true", help="print a machine-readable report")
    return ap


def main(argv=None):
    ap = _parser()
    args = ap.parse_args(argv)
    inputs, early = _load_inputs(args)
    if early is not None:
        return early
    reports = [
        analyze(text, label, exclude=exclude, words_mode=args.words)
        for label, text, exclude in inputs
    ]
    if args.rewrite_prompt:
        sys.stdout.write(format_rewrite(reports))
        return 0
    if args.json:
        sys.stdout.write(format_json(reports))
    else:
        for rep in reports:
            print(format_human(rep, quiet=args.quiet))
    if args.max is not None:
        worst = max(rep["rate"] for rep in reports)
        if worst > args.max:
            msg = "writing-check: FAIL. %.1f/1k exceeds --max %s" % (worst, args.max)
            if args.json:
                print(msg, file=sys.stderr)
            else:
                print("\n" + msg)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
