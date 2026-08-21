"""The four quantization constants — and the only place any of them is assigned.

docs/lossiness.md, "Quantization tolerances", is normative and says this
explicitly:

> `reg/tolerances.py` holds these four names as module-level constants and is the
> *only* place any of them may be assigned. Every module — graph construction,
> query, benchmark, test — imports them from there; a literal `0.01` in graph or
> query code is a defect even when it is the right number, because the next
> person to change the tolerance will not find it.

`tests/test_tolerances.py` parses the table out of `docs/lossiness.md` and
compares it to what is below, so an edit to either side that is not mirrored in
the other fails CI. That is the whole point: the tolerances are the quantitative
content of a *contract*, and a contract whose code and prose can drift apart is
not one.

**Changing a value here changes what the project claims.** docs/lossiness.md:
"Disagreement outside tolerance is a bug in the graph, not a tolerance to widen."
If a check goes red, fix the graph or change the document and say why — editing a
constant to make a red test green is the one move the contract exists to forbid.

WHY THE QUANTIZERS LIVE HERE TOO
--------------------------------
A constant without its rounding rule is only half a definition: `DISTANCE_TOL_M`
means nothing until you say whether 0.105 m rounds up or down and whether two
values a hair apart count as the same. The graph's incremental rule is *exactly*
"did the quantized value change", so the quantizer is the operational meaning of
the constant and belongs beside it.

The invariant every one of these rounding functions is chosen to give — and that
`tests/test_graph.py` and `tests/test_tolerances.py` both assert — is:

    |a - b| > quantum   =>   bucket(a) != bucket(b)

That is what makes the negative test possible. A relationship that moves by more
than the tolerance *cannot* be collapsed into the previous interval, whatever the
two values happened to be. Rounding to the nearest multiple gives it: if two
values share a bucket they are each within half a quantum of its centre, so they
are within one quantum of each other.

The converse does not hold and is not claimed: two values closer than the quantum
may still straddle a boundary and emit a new interval. That direction errs toward
emitting *more* rows than strictly needed, which costs compression and never
costs an answer. docs/lossiness.md Retained #3 says transitions are recorded when
a metric "crossed a quantization boundary", so this is the specified behaviour
rather than an artefact of the implementation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import shapely
from shapely.geometry.base import BaseGeometry

__all__ = [
    "DISTANCE_TOL_M",
    "AREA_QUANT_SIGFIGS",
    "TIME_TOL_S",
    "GEOM_SIMPLIFY_TOL_M",
    "TIME_BASE_MAX_RATE_HZ",
    "addressable_instants",
    "distance_bucket",
    "quantize_distance",
    "time_bucket",
    "quantize_time",
    "quantize_area",
    "simplify_geometry",
    "time_base_resolves_frames",
]

#: Separation and all distance-valued edges. 1 cm.
DISTANCE_TOL_M: float = 0.01

#: Significant figures kept for envelope `area` and `overlap_area`. Relative, not
#: absolute — worst case ~5% near the bottom of a decade, ~0.5% near the top.
#: Quote the relative figure; an absolute area tolerance that happens to hold for
#: one scenario's numbers is a fabricated digit for the next one.
AREA_QUANT_SIGFIGS: int = 2

#: Transition timestamps and interval endpoints. 10 ms.
#:
#: This is a *quantum, not a promise of resolution*, and it cuts both ways.
#: **Below 100 Hz** transitions are only locatable to the frame period; the graph
#: records the frame period in its provenance (`reg.store.META_FRAME_PERIOD`) and
#: nothing downstream may report finer than it. **Above 100 Hz** the quantum is
#: coarser than the frame period, several frames quantize onto one instant, and
#: the artifact can no longer address them separately — see
#: `TIME_BASE_MAX_RATE_HZ` and docs/limitations.md §5. That half went unsaid until
#: issue #77 measured it.
TIME_TOL_S: float = 0.010

#: `shapely.simplify()` on stored geometry. 5 mm, and it is half of
#: `DISTANCE_TOL_M` for a derived reason rather than by taste: Douglas–Peucker
#: displaces a boundary by up to the tolerance and cm-quantization of a distance
#: contributes up to half a quantum, and those errors add.
#:
#:     GEOM_SIMPLIFY_TOL_M + DISTANCE_TOL_M / 2  <=  DISTANCE_TOL_M
#:     0.005               + 0.005               =   0.010
#:
#: Raising this to 1 cm would mean reported distances are good to 1.5 cm while
#: the artifact advertises 1 cm. The budget has room for exactly one simplified
#: boundary per distance, which is why `reg.graph` simplifies entity geometry and
#: leaves the robot body exact.
GEOM_SIMPLIFY_TOL_M: float = 0.005

#: **The domain of validity of the four above, in Hz. Derived, not chosen** —
#: `1 / TIME_TOL_S`, which is 100 Hz. It is not a fifth tolerance and there is
#: nothing to tune here: change `TIME_TOL_S` and this moves with it, which is the
#: whole reason it is written as an expression rather than as `100.0`.
#:
#: What it bounds. Every interval endpoint in the artifact is `quantize_time`d, so
#: the artifact's time base has exactly `1 / TIME_TOL_S` addressable instants per
#: second **whatever rate the control loop ran at**. At or below this rate the
#: quantized frame times are distinct and every frame has its own address; above
#: it they are not, several frames collapse onto one instant, and a per-frame
#: value read back out of the artifact is the value of whichever of them opened
#: the covering interval. Measured on `near_miss` at seed 0 (docs/lossiness.md,
#: "The rate range these hold in"): 1 kHz puts 11 frames on one instant and the
#: per-frame `separation_timeline` predicate misses its own 1 cm budget by up to
#: 0.0140 m.
#:
#: **This is not permission to widen `TIME_TOL_S`.** Widening it would move the
#: line rather than the behaviour, which is the one move docs/lossiness.md exists
#: to forbid; it would also make this rate *lower*. The honest response is the one
#: taken: state the range, record in every artifact whether that artifact is
#: inside it (`reg.graph.TIME_BASE_DOMAIN`), and say in docs/limitations.md §5
#: that a 1 kHz run is outside it.
TIME_BASE_MAX_RATE_HZ: float = 1.0 / TIME_TOL_S


class ToleranceError(ValueError):
    """A value could not be quantized, so no quantized value is returned.

    Never a clamp and never a substituted zero: a non-finite distance absorbed
    into `0.0` reads downstream as *contact*, and a negative area absorbed into
    `0.0` reads as *no overlap*. Both are could-not-evaluate resolving to a
    confident wrong answer, which is the failure this project is about.
    """


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToleranceError(f"{name} must be a number, got {value!r}.")
    out = float(value)
    if not math.isfinite(out):
        raise ToleranceError(
            f"{name} is {out!r}. A non-finite value has no quantum; quantizing it "
            "would produce a number no comparison downstream can reject."
        )
    return out


def _bucket(value: float, quantum: float, name: str) -> int:
    """Index of the nearest multiple of `quantum`. Integer, so `==` is exact.

    Returned as an `int` on purpose. The graph's incremental rule compares "is
    this the same quantized value as last frame", and comparing the *floats*
    `round(d / q) * q` would make that comparison depend on floating-point
    reassociation. Comparing bucket indices cannot.
    """
    out = _finite(value, name)
    # round() is banker's rounding, so an exact half goes to the even bucket.
    # Which way a tie falls does not matter; that it falls the same way in every
    # process does, because two runs of the same command must agree bit for bit.
    return int(round(out / quantum))


def distance_bucket(distance: float) -> int:
    """Which `DISTANCE_TOL_M` bucket a distance falls in. Refuses a negative one."""
    out = _finite(distance, "distance")
    if out < 0.0:
        raise ToleranceError(
            f"distance is {out!r}. Distances between geometries are non-negative; "
            "a negative one means the caller computed something else (a signed "
            "clearance, say) and it must not be recorded as a separation."
        )
    return _bucket(out, DISTANCE_TOL_M, "distance")


def quantize_distance(distance: float) -> float:
    """A distance rounded to the nearest `DISTANCE_TOL_M`. The stored value."""
    return distance_bucket(distance) * DISTANCE_TOL_M


def time_bucket(t: float) -> int:
    """Which `TIME_TOL_S` bucket an instant falls in. Negative times are allowed.

    Nothing here says a stream must start at zero, and refusing `t < 0` would be
    inventing a convention the raw stream does not state.
    """
    return _bucket(t, TIME_TOL_S, "t")


def quantize_time(t: float) -> float:
    """An instant rounded to the nearest `TIME_TOL_S`. What `t_start`/`t_end` hold."""
    return time_bucket(t) * TIME_TOL_S


def addressable_instants(times: Sequence[float]) -> int:
    """How many **distinct** instants `quantize_time` can place `times` at.

    The size of the artifact's time base for a run sampled at `times`. Every
    interval endpoint is quantized, so two frames sharing a bucket share an
    address: nothing downstream can ask for one of them and not the other, and a
    per-frame read-back returns one value for both.

    Counted over the *actual* frame times rather than derived from the frame
    period, and the difference is not pedantry. `quantize_time` rounds to the
    nearest multiple with a banker's tie-break, so whether a period of exactly
    `TIME_TOL_S` separates every frame depends on the stream's phase — frames at
    0.015 s and 0.025 s are one quantum apart and both round to 0.02. A predicate
    on the period alone would report a run as resolved that is not. This measures
    the run in hand.

    Raises:
        ToleranceError: `times` is empty, or holds a value with no bucket. An
            empty run would make the count and the frame count both zero and the
            comparison in `time_base_resolves_frames` vacuously true — silence
            resolving to a pass, which is the failure mode this project is about.
    """
    if len(times) == 0:
        raise ToleranceError(
            "addressable_instants was given no frame times. A run of no frames "
            "has no time base to size, and reporting zero instants for zero "
            "frames would read as 'every frame is addressable'."
        )
    return len({time_bucket(t) for t in times})


def time_base_resolves_frames(times: Sequence[float]) -> bool:
    """Whether every frame of a run sampled at `times` has its own address.

    `True` iff `addressable_instants(times) == len(times)`. That is the condition
    under which docs/lossiness.md's per-frame agreement predicates hold — a value
    stored against an instant is a value about one frame — and it fails for every
    run sampled faster than `TIME_BASE_MAX_RATE_HZ`.

    `False` is **not** a build failure and this function does not raise on it.
    The artifact is still built, still holds every interval it would otherwise
    hold, and still answers every question in the supported set; what it cannot do
    is meet the per-frame budget on a run it cannot address frame by frame.
    `reg.graph` records the answer in every artifact's `meta` table so that a
    reader holding only the file can tell which case they have.
    """
    return addressable_instants(times) == len(times)


def quantize_area(area: float) -> float:
    """An area kept to `AREA_QUANT_SIGFIGS` significant figures.

    Relative rather than absolute, so it behaves the same for a 0.25 m² envelope
    and a 0.0004 m² sliver of overlap. Exactly zero is returned unchanged: it is
    not "a very small area", it is the absence of one, and giving it an exponent
    would be inventing a magnitude.
    """
    out = _finite(area, "area")
    if out < 0.0:
        raise ToleranceError(
            f"area is {out!r}. shapely areas are non-negative; a negative one "
            "means a ring orientation was lost somewhere upstream, and rounding "
            "it here would bury that."
        )
    if out == 0.0:
        return 0.0
    exponent = math.floor(math.log10(out))
    scale = 10.0 ** (AREA_QUANT_SIGFIGS - 1 - exponent)
    return round(out * scale) / scale


def simplify_geometry(geometry: BaseGeometry) -> BaseGeometry:
    """Douglas–Peucker at `GEOM_SIMPLIFY_TOL_M`, topology preserved.

    Every boundary the artifact *stores* — envelope and entity — passes through
    here, and so does every boundary a stored metric is *computed from*, because
    an `overlap_area` measured on a finer boundary than the one in the file is a
    number the artifact cannot be checked against.

    Topology is preserved (shapely's default) rather than allowed to collapse: a
    self-intersecting simplification of an envelope has an area that is not the
    area of any region, and it would be stored as though it were.

    Raises `ToleranceError` if the input is empty or invalid, or if simplifying
    made it so. An empty envelope clears every separation test downstream and an
    invalid one has no meaningful area, so neither may pass silently.
    """
    if not isinstance(geometry, BaseGeometry):
        raise ToleranceError(
            f"simplify_geometry takes a shapely geometry, got "
            f"{type(geometry).__name__}."
        )
    if geometry.is_empty:
        raise ToleranceError(
            "simplify_geometry was given an empty geometry. That is a "
            "could-not-evaluate, not a region of zero extent: stored as one it "
            "reads as 'nothing was there'."
        )
    if not geometry.is_valid:
        raise ToleranceError(
            f"simplify_geometry was given an invalid geometry: "
            f"{shapely.is_valid_reason(geometry)}."
        )

    out = shapely.simplify(geometry, GEOM_SIMPLIFY_TOL_M)

    if out.is_empty:
        raise ToleranceError(
            f"simplifying at {GEOM_SIMPLIFY_TOL_M} m emptied a geometry whose "
            f"area was {geometry.area}. The tolerance is larger than the feature; "
            "recording the empty result would delete a region that existed."
        )
    if not out.is_valid:
        raise ToleranceError(
            f"simplifying at {GEOM_SIMPLIFY_TOL_M} m produced an invalid "
            f"geometry: {shapely.is_valid_reason(out)}. Its area is not the area "
            "of any region and must not be stored as one."
        )
    return out
