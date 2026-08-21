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
    TIME_BASE_MAX_RATE_HZ,
    TIME_TOL_S,
    ToleranceError,
    addressable_instants,
    distance_bucket,
    quantize_area,
    quantize_distance,
    quantize_time,
    simplify_geometry,
    time_base_resolves_frames,
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
# The domain of validity (issue #77). The tolerances above are numbers; this is
# the range of control rates in which they mean what the document says they
# mean, and it went unstated until a benchmark ran at 1 kHz.
# --------------------------------------------------------------------------

#: `**`1 / TIME_TOL_S` = 100 Hz**` — how the document states the bound, in the
#: section that states it. Parsed rather than restated for the same reason the
#: tolerance table is: a test that hardcoded `100` would go green after somebody
#: changed the quantum and the prose together but not the code.
_RATE = re.compile(r"`1 / TIME_TOL_S`\s*=\s*(?P<rate>[0-9.]+)\s*Hz")

_RANGE_HEADING = "### The rate range these hold in"


def test_the_document_states_the_rate_range_the_tolerances_hold_in() -> None:
    """The defect issue #77 found was the *silence*, so the section is the fix.

    A contract that is silent about its own domain of validity cannot be checked
    against a deployment, and this asserts the section exists and states a rate.
    An empty parse is a could-not-evaluate and fails rather than passing.
    """
    text = LOSSINESS.read_text(encoding="utf-8")
    section = text.split(_RANGE_HEADING, 1)
    assert len(section) == 2, (
        f"{LOSSINESS} has no '{_RANGE_HEADING}' section. The four tolerances hold "
        "only at or below 1/TIME_TOL_S and a document that does not say so is the "
        "defect issue #77 reported — not the number."
    )
    found = _RATE.search(section[1])
    assert found is not None, (
        f"{LOSSINESS}: the '{_RANGE_HEADING}' section states no rate. A section "
        "with a heading and no bound is silence with a title on it."
    )
    assert float(found["rate"]) == TIME_BASE_MAX_RATE_HZ, (
        f"docs/lossiness.md says the tolerances hold to {found['rate']} Hz and "
        f"reg.tolerances.TIME_BASE_MAX_RATE_HZ is {TIME_BASE_MAX_RATE_HZ}. Both "
        "are meant to be 1/TIME_TOL_S; change the quantum and both move."
    )


def test_the_max_rate_is_the_reciprocal_of_the_time_quantum() -> None:
    """Derived, not chosen. Widening `TIME_TOL_S` *lowers* this rate.

    Written as an assertion rather than left to the expression in the module,
    because the number that matters downstream is the rate and somebody replacing
    it with a literal `100.0` would break nothing else.
    """
    assert TIME_BASE_MAX_RATE_HZ == 1.0 / TIME_TOL_S
    assert TIME_BASE_MAX_RATE_HZ * TIME_TOL_S == pytest.approx(1.0)


def test_a_run_sampled_at_the_max_rate_has_an_address_for_every_frame() -> None:
    """The positive: at 1/TIME_TOL_S every frame quantizes to its own instant."""
    times = [i / TIME_BASE_MAX_RATE_HZ for i in range(200)]
    assert addressable_instants(times) == len(times)
    assert time_base_resolves_frames(times)


@pytest.mark.parametrize("rate_hz", [101.0, 125.0, 250.0, 1000.0])
def test_a_run_sampled_above_the_max_rate_loses_addresses(rate_hz: float) -> None:
    """**THE NEGATIVE.** Faster than the quantum and frames start sharing an
    instant — which is what a per-frame answer then cannot distinguish.

    The count is asserted against the run's *duration*, not against a magic
    number: however many frames a second holds, the artifact can address
    `TIME_BASE_MAX_RATE_HZ` of them.
    """
    seconds = 2.0
    times = [i / rate_hz for i in range(int(seconds * rate_hz) + 1)]
    assert not time_base_resolves_frames(times)
    assert addressable_instants(times) < len(times)
    assert addressable_instants(times) == int(seconds * TIME_BASE_MAX_RATE_HZ) + 1


def test_addressable_instants_is_measured_on_the_times_not_on_the_period() -> None:
    """Two frames exactly one quantum apart can still share an instant.

    `quantize_time` rounds to the nearest multiple and breaks ties to even, so
    0.015 s and 0.025 s — a period of exactly `TIME_TOL_S` — both land on 0.02 s.
    A predicate on the frame period alone would call this run resolved. This is
    why `reg.graph` measures the frames it was handed rather than dividing.
    """
    times = [0.015, 0.025]
    assert quantize_time(times[0]) == quantize_time(times[1])
    assert not time_base_resolves_frames(times)


def test_addressable_instants_refuses_a_run_with_no_frames() -> None:
    """Silence must not resolve to a pass: zero instants for zero frames would
    compare equal and report the empty run as fully addressable."""
    with pytest.raises(ToleranceError, match="no frame times"):
        addressable_instants([])


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
