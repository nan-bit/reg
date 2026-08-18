"""The tolerance constants, tested against the document that specifies them.

docs/lossiness.md says of `reg/tolerances.py`: "`tests/test_tolerances.py`
asserts the module's values equal the table above, so an edit to either side that
is not mirrored in the other fails CI."

So this file **parses the table out of the markdown** rather than restating the
numbers. A test that hardcoded `0.01` would go green after someone edited the
document and the module together in a way that disagreed with the derivation, and
it would go green after someone edited only the document. Neither is the check
the contract asks for.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, Polygon

from reg import tolerances
from reg.tolerances import (
    AREA_QUANT_SIGFIGS,
    DISTANCE_TOL_M,
    GEOM_SIMPLIFY_TOL_M,
    TIME_TOL_S,
    ToleranceError,
    distance_bucket,
    quantize_area,
    quantize_distance,
    quantize_time,
    simplify_geometry,
)

LOSSINESS = Path(__file__).resolve().parents[1] / "docs" / "lossiness.md"

#: `| `NAME` | `VALUE` (aside) | governs |` — the shape of the rows in the
#: "Quantization tolerances" table.
_ROW = re.compile(
    r"^\|\s*`(?P<name>[A-Z_]+)`\s*\|\s*`(?P<value>[0-9.]+)`", re.MULTILINE
)


def _documented() -> dict[str, str]:
    """The tolerance table as the document states it. Empty is a failure."""
    text = LOSSINESS.read_text(encoding="utf-8")
    section = text.split("## Quantization tolerances", 1)
    assert len(section) == 2, (
        f"{LOSSINESS} has no '## Quantization tolerances' section. The constants "
        "are the quantitative content of the lossiness contract; if the section "
        "is gone, the module below is unspecified, not merely undocumented."
    )
    found = {m["name"]: m["value"] for m in _ROW.finditer(section[1])}
    assert found, (
        f"{LOSSINESS}: parsed no rows out of the tolerance table. An empty parse "
        "is a could-not-evaluate and must not read as agreement — this assertion "
        "is what stops the whole file from passing vacuously."
    )
    return found


def test_the_document_states_exactly_the_four_constants() -> None:
    assert set(_documented()) == {
        "DISTANCE_TOL_M",
        "AREA_QUANT_SIGFIGS",
        "TIME_TOL_S",
        "GEOM_SIMPLIFY_TOL_M",
    }


@pytest.mark.parametrize(
    "name",
    ["DISTANCE_TOL_M", "AREA_QUANT_SIGFIGS", "TIME_TOL_S", "GEOM_SIMPLIFY_TOL_M"],
)
def test_module_matches_the_document(name: str) -> None:
    """Edit either side without the other and this is what goes red."""
    documented = float(_documented()[name])
    assert float(getattr(tolerances, name)) == documented, (
        f"reg.tolerances.{name} is {getattr(tolerances, name)} but "
        f"docs/lossiness.md says {documented}. Changing a tolerance changes what "
        "this project claims — change both, and say why in the document."
    )


def test_the_simplification_budget_derivation_still_closes() -> None:
    """The one constant docs/lossiness.md derives rather than imports.

    `GEOM_SIMPLIFY_TOL_M + DISTANCE_TOL_M / 2 <= DISTANCE_TOL_M`. If someone
    raises the simplification tolerance to 1 cm, reported distances are good to
    1.5 cm while the artifact advertises 1 cm — the exact failure the contract is
    written to prevent, and it would not otherwise show up as a red test.
    """
    assert GEOM_SIMPLIFY_TOL_M + DISTANCE_TOL_M / 2 <= DISTANCE_TOL_M


# --------------------------------------------------------------------------
# The invariant the incremental rule's negative test rests on
# --------------------------------------------------------------------------


@pytest.mark.parametrize("base", [0.0, 0.004, 0.005, 0.1234, 0.85, 3.0, 12.345])
@pytest.mark.parametrize("delta", [0.0101, 0.011, 0.02, 0.25, 1.0])
def test_a_change_larger_than_the_quantum_always_changes_bucket(
    base: float, delta: float
) -> None:
    """|a - b| > DISTANCE_TOL_M => different bucket. Never collapsible.

    This is what `tests/test_graph.py`'s negative test stands on: a relationship
    that moved by more than the tolerance *cannot* be folded into the previous
    interval, whatever the two values happened to be.
    """
    assert distance_bucket(base) != distance_bucket(base + delta)


@pytest.mark.parametrize("base", [0.0, 0.1234, 0.85, 12.345])
def test_values_sharing_a_bucket_are_within_one_quantum(base: float) -> None:
    """The converse direction, stated as what it actually is.

    Sharing a bucket implies closeness; being close does *not* imply sharing a
    bucket. The code errs toward emitting extra rows, which costs compression and
    never costs an answer.
    """
    for delta in (0.0, 0.001, 0.004):
        if distance_bucket(base) == distance_bucket(base + delta):
            assert abs(delta) <= DISTANCE_TOL_M


def test_quantize_distance_lands_on_a_multiple_of_the_quantum() -> None:
    for raw in (0.0, 0.0049, 0.0051, 0.847, 2.0):
        quantized = quantize_distance(raw)
        assert abs(quantized - raw) <= DISTANCE_TOL_M / 2 + 1e-12
        assert math.isclose(
            quantized / DISTANCE_TOL_M, round(quantized / DISTANCE_TOL_M), abs_tol=1e-9
        )


def test_quantize_time_is_a_multiple_of_the_quantum() -> None:
    for raw in (0.0, 0.02, 0.019, 5.994):
        assert abs(quantize_time(raw) - raw) <= TIME_TOL_S / 2 + 1e-12


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.0, 0.0),
        (0.2522, 0.25),
        (0.25499, 0.25),
        (1234.0, 1200.0),
        (0.00012345, 0.00012),
    ],
)
def test_quantize_area_keeps_two_significant_figures(
    raw: float, expected: float
) -> None:
    assert quantize_area(raw) == pytest.approx(expected, rel=1e-12)


def test_quantize_area_is_relative_not_absolute() -> None:
    """Two sig figs must behave the same across decades, or the doc's warning
    about quoting an absolute area tolerance is not implemented."""
    for magnitude in (1e-6, 1e-3, 1.0, 1e3):
        value = 1.234 * magnitude
        assert abs(quantize_area(value) - value) / value < 0.05


def test_quantize_area_is_stable_across_a_decade_boundary() -> None:
    """Two areas in one bucket must produce the *same float*, not merely a close
    one — the graph compares these for equality to decide whether to emit a row."""
    assert quantize_area(0.0999) == quantize_area(0.1004)


# --------------------------------------------------------------------------
# Negative tests: could-not-evaluate must never resolve to a value
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_input_is_refused_not_absorbed(bad: float) -> None:
    """A NaN distance quantized to 0.0 reads downstream as contact."""
    with pytest.raises(ToleranceError):
        distance_bucket(bad)
    with pytest.raises(ToleranceError):
        quantize_area(bad)
    with pytest.raises(ToleranceError):
        quantize_time(bad)


def test_a_negative_distance_is_refused() -> None:
    with pytest.raises(ToleranceError, match="non-negative"):
        distance_bucket(-0.01)


def test_a_negative_area_is_refused() -> None:
    with pytest.raises(ToleranceError, match="non-negative"):
        quantize_area(-1.0)


def test_a_non_number_is_refused() -> None:
    with pytest.raises(ToleranceError, match="must be a number"):
        distance_bucket("0.5")  # type: ignore[arg-type]


def test_simplify_preserves_area_within_the_stated_budget() -> None:
    disc = Point(0.0, 0.0).buffer(0.25)
    simplified = simplify_geometry(disc)
    # Douglas-Peucker moves the boundary by at most the tolerance, so the area
    # cannot move by more than perimeter * tolerance.
    assert abs(simplified.area - disc.area) <= disc.length * GEOM_SIMPLIFY_TOL_M


def test_simplify_refuses_an_empty_geometry() -> None:
    """The negative test: an empty region stored as a boundary reads as
    'nothing was there' and clears every intersection test that meets it."""
    with pytest.raises(ToleranceError, match="could-not-evaluate"):
        simplify_geometry(Polygon())


def test_simplify_refuses_an_invalid_geometry() -> None:
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    assert not bowtie.is_valid
    with pytest.raises(ToleranceError, match="invalid"):
        simplify_geometry(bowtie)


def test_simplify_does_not_collapse_a_feature_thinner_than_the_tolerance() -> None:
    """Topology preservation, tested as the property it is there for.

    A sliver a hundred times thinner than the tolerance is exactly what a
    non-topology-preserving Douglas-Peucker deletes. Deleting it would remove a
    region that existed from the artifact, and the artifact has no way to say
    that happened — so the survival of this sliver is load-bearing, not
    incidental. (`simplify_geometry` still refuses an empty result, for the case
    where a future shapely makes this collapse.)
    """
    sliver = LineString([(0, 0), (1, 0)]).buffer(GEOM_SIMPLIFY_TOL_M / 100)
    assert not simplify_geometry(sliver).is_empty


def test_simplify_refuses_a_non_geometry() -> None:
    with pytest.raises(ToleranceError, match="shapely geometry"):
        simplify_geometry("POLYGON EMPTY")  # type: ignore[arg-type]
