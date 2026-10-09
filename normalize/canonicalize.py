"""Conservative product-name canonicalization.

Goal: collapse obvious VL/OCR character-confusion variants (so the same product
gets one product_norm) WITHOUT merging genuinely different products (strawberry
vs raspberry, mild vs sharp).

Strategy: a small, hand-audited list of safe substitutions applied to the
normalized name. We only fix *character-level* confusions that are
near-unambiguous in a Spanish/English grocery context. We never touch whole
distinguishing words (flavors, varieties, sizes).
"""
import re

# safe character/bigram confusions common in VL OCR of shopper images.
# applied as whole-token or substring replacements that are very unlikely to
# change meaning. Keep this list SHORT and conservative.
_SUBS = [
    (r"forflex", "forceflex"),
    (r"bady", "body"),
    (r"snooth", "smooth"),
    (r"2n1", "2in1"),
    (r"3n1", "3in1"),
    (r"0z", "oz"),          # zero -> o in unit
    (r"lb", "lb"),
    (r"\s{2,}", " "),
]

# tokens that are almost always VL noise at word boundaries and safe to drop
# when isolated (e.g. stray single letters introduced by the model). Applied
# only when they stand alone between two real words.
_DROP_ISOLATED = {"l", "o"}  # rarely meaningful alone in these contexts


def canon(product_norm: str) -> str:
    if not product_norm:
        return product_norm
    t = product_norm.strip().lower()
    for pat, rep in _SUBS:
        t = re.sub(pat, rep, t)
    # collapse double spaces introduced by subs
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t
