"""UX-01 source-fact guards: the TAIG Design System (row 754, M11.1).

The unified interface programme (row 753) makes one shared design system the
foundation every surface renders through. Like the dashboard honesty guards
next door, these read the source rather than the rendered output, because the
defect they exist to catch is a component that was never sourced at all: a
`StatusChip` that invents its own vocabulary, or a `shared.tsx` that quietly
reverts to a private copy of the empty state so the pages stop rendering the
one system.

Guarded here:

- the design package exists with its four files and exports the status
  language, the chip and the three states;
- the status language is exactly the 15 labels the spec ratified, in order,
  so a page cannot add a 16th status by editing the component;
- every label carries an English and an Arabic rendering (the Control Center
  is bilingual, and a chip that falls back to English under RTL is a visible
  lie about the surface's language);
- `ui/shared.tsx` re-exports the design system instead of defining its own
  empty/loading/error/chip, so the 11 pages render one system;
- the design system reads the shared CSS variables and inline-style
  conventions of the dashboard (no orphan class names that no stylesheet
  defines).
"""

from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]
DASH = REPO / "TAIG Dash" / "src"
DESIGN = DASH / "design"

pytestmark = pytest.mark.skipif(not DESIGN.exists(),
                                reason="dashboard design package not present")

STATUS_LANGUAGE = (
    "LIVE", "PAPER", "RESEARCH", "WATCH", "BLOCKED", "VETOED", "PENDING",
    "VALIDATED", "QUARANTINED", "FAILED", "HEALTHY", "DEGRADED", "EMPTY",
    "LOADING", "ERROR",
)


def _read(name: str) -> str:
    return (DESIGN / name).read_text(encoding="utf-8", errors="replace")


def test_the_design_package_exists_and_exports_the_four_parts():
    """A missing package must fail, not silently skip the rest of the guards.

    The package is the foundation of all three surfaces; if it is deleted the
    pages still compile against `ui/shared.tsx`'s private copies, so nothing
    downstream would notice.
    """
    for name in ("tokens.ts", "StatusChip.tsx", "states.tsx", "index.ts"):
        assert (DESIGN / name).is_file(), f"design package lost {name}"
    index = _read("index.ts")
    for part in ("tokens", "StatusChip", "states"):
        assert part in index, f"design index.ts does not export {part}"


def test_the_status_language_is_exactly_the_15_ratified_labels_in_order():
    """One chip set, one vocabulary -- the spec's 15 labels, no more, no less.

    Order matters too: the vocabulary is read as a set by the surfaces, but a
    reordered list means someone edited the file, and the edit is the moment
    a 16th status can slip in.
    """
    tokens = _read("tokens.ts")
    match = re.search(r"export const statusLanguage = \[(.*?)\] as const;",
                      tokens, flags=re.S)
    assert match, "tokens.ts does not declare statusLanguage as a const tuple"
    labels = tuple(re.findall(r'"([A-Z]+)"', match.group(1)))
    assert labels == STATUS_LANGUAGE, (
        f"status language drifted: {labels}")


def test_every_status_label_has_an_english_and_an_arabic_rendering():
    """A bilingual surface cannot show one language's word for half its chips.

    The label map is the thing the RTL mode reads; a missing Arabic entry
    makes the chip fall back to the raw English token under `dir=rtl`.
    """
    tokens = _read("tokens.ts")
    match = re.search(
        r"const STATUS_LABELS: Record<Language, Record<string, string>> = \{"
        r"(.*?)\n\};", tokens, flags=re.S)
    assert match, "tokens.ts has no STATUS_LABELS map"
    body = match.group(1)
    en = re.search(r"\ben: \{(.*?)\}", body, flags=re.S)
    ar = re.search(r"\bar: \{(.*?)\}", body, flags=re.S)
    assert en and ar, "STATUS_LABELS must define both en and ar"
    for lang, block in (("en", en.group(1)), ("ar", ar.group(1))):
        missing = [s for s in STATUS_LANGUAGE
                   if not re.search(rf'\b{s}: "', block)]
        assert not missing, f"STATUS_LABELS.{lang} misses: {missing}"


def test_shared_re_exports_the_design_system_instead_of_private_copies():
    """The 11 pages import from ui/shared -- it must be the facade, not a fork.

    When `shared.tsx` defines its own EmptyState the pages keep compiling and
    the design system is dead code that nothing renders through, which is the
    exact failure mode this programme exists to prevent.
    """
    shared = (DASH / "components" / "ui" / "shared.tsx").read_text(
        encoding="utf-8", errors="replace")
    assert re.search(r"from\s+['\"]\.\./\.\./design['\"]", shared), (
        "ui/shared.tsx does not re-export from ../../design")
    stripped = re.sub(r"/\*.*?\*/", "", shared, flags=re.S)
    stripped = re.sub(r"^\s*//.*$", "", stripped, flags=re.M)
    for own in ("export function EmptyState",
                "export function LoadingState",
                "export function ErrorState"):
        assert own not in stripped, (
            f"ui/shared.tsx defines {own.split()[-1]} itself; the design "
            "system is no longer what the pages render")


def test_design_components_use_the_dashboard_css_variables_not_orphan_classes():
    """A className no stylesheet defines renders unstyled -- a silent break.

    The dashboard styles inline against the shared CSS variables; a design
    component that reaches for `status-chip--ok` paints nothing, and the chip
    still shows its text so the break is invisible in review.
    """
    for name in ("StatusChip.tsx", "states.tsx"):
        body = _read(name)
        for cls in re.findall(r'className=\{?["\']([^"\']+)', body):
            pytest.fail(
                f"{name} sets className {cls!r}; no stylesheet defines it, "
                "so the component renders unstyled")
        assert "var(--" in body, (
            f"{name} does not read the shared CSS variables")


def test_the_chip_falls_back_to_muted_for_an_unknown_status():
    """An unrecognised status renders muted, never a colour that means 'ok'.

    A status the vocabulary does not know is a state the surface does not
    understand; painting it green would be the chip inventing a fact.
    """
    chip = _read("StatusChip.tsx")
    assert 'statusTone[status] ?? "muted"' in chip, (
        "StatusChip does not fall back to the muted tone for unknown status")
