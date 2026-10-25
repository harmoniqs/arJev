# arJev v0.5.3

**The one-line version:** the week-in-review ranked papers by Jev's certainty in
*whatever* label it picked — so papers Jev was 100% sure were irrelevant led
"The Buried". Fixed.

## What's fixed

The journal keeps only (top label, confidence in it). The review now orders by
label first, then confidence within it, and "The Buried" holds only papers Jev
judged must-read or worth-reading that the top-N cap dropped — the section's
actual meaning. The Divergences use the same ordering. Lines now print the label
next to the number (`jev must-read 0.59`), so a bare "1.0" can never read as
relevance again. The digest itself was unaffected: it always ranked by
must-read + worth-reading mass.
