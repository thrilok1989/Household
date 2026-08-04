"""Every deployed dependency is bounded.

`requirements.txt` had thirteen lines and thirteen `>=` with no cap, so
Streamlit Cloud re-resolved the tree on every rebuild and could cross a major
version without anything asking. The visible symptom was the front end:

    TypeError: Failed to fetch dynamically imported module:
    https://…streamlit.app/~/+/static/js/

Streamlit serves hash-named JS chunks; a rebuild onto a different Streamlit
writes different chunk names, and a browser holding the previous `index.html`
requests files that no longer exist.

An unbounded requirement is a deploy that cannot be reproduced, and a test
suite whose result describes a tree no deployment necessarily had. These tests
are cheap and they are the only thing that keeps a `>=` from creeping back.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
REQ = ROOT / "requirements.txt"

#: The one whose version IS the asset the browser downloads.
FRONT_END = "streamlit"


def _requirements():
    """(name, spec) per real requirement line — comments and blanks dropped."""
    out = []
    for raw in REQ.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", line)
        assert m, f"unparsable requirement: {raw!r}"
        out.append((m.group(1).lower(), m.group(2).strip()))
    return out


def test_the_file_has_requirements_in_it():
    """A parser that silently matches nothing would make every test below
    pass on an empty file."""
    assert len(_requirements()) >= 10


@pytest.mark.parametrize("name,spec", _requirements())
def test_every_requirement_has_an_upper_bound(name, spec):
    """`~=`, `==` or an explicit `<` — never a bare `>=`.

    `~=1.2.3` allows 1.2.x and stops before 1.3; `~=1.2` allows 1.x and stops
    before 2. Both cap; a bare `>=` caps nothing.
    """
    assert spec, f"{name} has no version specifier at all"
    bounded = spec.startswith("~=") or spec.startswith("==") or "<" in spec
    assert bounded, (f"{name}{spec} is unbounded — a rebuild can cross a major "
                     f"version with nothing asking")


def test_the_front_end_is_pinned_exactly():
    """Not `~=`. A minor Streamlit bump changes the served JS chunk names, and
    that is the whole failure being prevented — the cap has to be exact."""
    spec = dict(_requirements())[FRONT_END]
    assert spec.startswith("=="), (
        f"{FRONT_END}{spec} — the front end must be an exact pin")


def test_the_pinned_front_end_is_the_one_the_suite_runs_against():
    """A pin that disagrees with the test environment means the deployed app
    and the tested app are different programs."""
    import importlib.metadata as md
    try:
        installed = md.version(FRONT_END)
    except md.PackageNotFoundError:
        pytest.skip(f"{FRONT_END} is not installed in this environment")
    pinned = dict(_requirements())[FRONT_END].lstrip("=").strip()
    assert installed == pinned, (
        f"requirements pins {FRONT_END}=={pinned} but the suite is running "
        f"against {installed}")


def test_untested_dependencies_are_not_claimed_as_verified():
    """The file splits verified from unverified, and the split must be true.

    Five packages are not installed here, so nothing in this suite exercises
    them. Listing one under the verified heading would be a claim the test run
    does not support.
    """
    import importlib.metadata as md

    text = REQ.read_text()
    marker = "NOT installed in the test environment"
    assert marker in text, "the unverified section was removed"
    unverified_block = text.split(marker, 1)[1]

    for name, _ in _requirements():
        # `\b` would be wrong here: a hyphen is a word boundary, so
        # `^streamlit\b` matches the `streamlit-autorefresh` line and reports
        # the wrong package as misfiled. The name must be followed by a
        # version specifier or the end of the line.
        listed_unverified = re.search(
            rf"^{re.escape(name)}\s*(?=[<>=~!]|$)",
            unverified_block, re.M) is not None
        try:
            md.version(name)
            installed = True
        except md.PackageNotFoundError:
            installed = False
        if installed and listed_unverified:
            pytest.fail(f"{name} is installed but filed as unverified")
        if not installed and not listed_unverified:
            pytest.fail(f"{name} is NOT installed but filed as verified — "
                        f"nothing here has exercised it")
