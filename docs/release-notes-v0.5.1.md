# arJev v0.5.1

**The one-line version:** the first live who-line run caught the author blob —
arXiv RSS emits one comma-joined creator element, and until now names were
never split, so the who-line showed the whole blob and the author lane could
only fire on a list's last surname.

## What's fixed

**Names split at parse (the normalize-at-parse doctrine).** The feed parser
splits the creator blob into individual authors — comma forms, "and" forms,
single names. This fixes both surfaces downstream: the who-line's first-three
+ `+N` cap and tracked-people ⭐ hits (the live 2026-10-21 run rendered a
tracked co-author with no star), and the author-signal lane itself (issue #66),
which had been nearly blind in production — the weekly review's "Your People"
section can now match mid-list authors.

**The affiliation marker class** also strips list punctuation (`)`, brackets)
left behind by superscript-adjacent author blocks.
