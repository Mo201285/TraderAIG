"""No real MT5 login may appear as test data.

Split from the engine-URL guard on purpose. The guard is protection that holds
whatever any file contains; this is a claim about the current contents of the
tree, so it can only be committed together with every rename it asks for -- and
one of those renames lives inside an unrelated hunk of a file with a large
uncommitted change in it. Committing this file alone would fail its own check.
"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.mark.parametrize("account_id", ["1787174", "1400167"])
def test_no_known_real_login_is_hardcoded_as_test_data(account_id):
    """A fabricated row must be obvious in a table dump, even if isolation fails.

    Both of these logins are real MT5 accounts on this host, and both were used
    as test fixtures. A row written under a real login is the worst case: it
    lands next to the genuine article in the same table, under an identifier the
    operator already trusts.
    """
    root = Path(__file__).resolve().parents[1] / "tests"
    this_file = Path(__file__).resolve()
    offenders = [str(p.relative_to(root.parent)) for p in root.rglob("*.py")
                 if p.resolve() != this_file
                 and '"%s"' % account_id in p.read_text(encoding="utf-8")]
    assert offenders == [], (
        "%s is a real MT5 login; use a TEST-ACCT-* id instead: %s"
        % (account_id, offenders))
