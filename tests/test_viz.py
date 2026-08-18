"""The single-frame render: does it write a picture, and is the picture honest?

Three kinds of test, and only the first is about matplotlib working.

*It renders.* A non-empty PNG lands on disk, with and without an envelope, and
two renders of the same frame are byte-identical — a figure in an audit artifact
is subject to the same determinism rule as everything else here.

*It does not lie about the layers.* The envelope is Layer A and cannot see the
human; the human and the obstacles are Layer B. Every legend entry has to say
which, Layer B has to be dashed, the palette entries have to stay distinct so a
later phase cannot quietly reuse the computed envelope's colour for the declared
one, and the envelope's label has to keep the word "under-approx.".

*It says what it could not draw.* The negative tests: no `Limits` means no robot
body, no `World` means no room and no human, `envelope=None` means no overlay —
each is reported on the axes and returned to the caller rather than rendered as
an empty scene. An empty or invalid envelope is refused outright, because a
failed computation drawn as "no overlay" is indistinguishable from a caller who
never asked for one.

The `Agg` backend is selected before anything imports pyplot so the suite runs
headless in CI. `reg.viz` itself never touches the global backend — it builds a
`Figure` and attaches an Agg canvas by hand — but a test that assumed that would
break the moment someone adds a pyplot call here.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.path import Path as MplPath  # noqa: E402
from shapely.geometry import LinearRing, Polygon  # noqa: E402

from reg.envelope import compute_envelope  # noqa: E402
from reg.scenarios import scenario  # noqa: E402
from reg.types import Obstacle, ProprioState, StateFrame  # noqa: E402
from reg.viz import (  # noqa: E402
    COLOR_OBSTACLE,
    COLOR_ROBOT,
    ELEMENT_LAYER,
    LAYER_A_LINESTYLE,
    LAYER_B_LINESTYLE,
    NOT_DRAWN_PREFIX,
    PALETTE,
    draw_frame,
    render_frame,
)
from reg.world import DEMO_WORLD  # noqa: E402

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: Deliberately coarse: these tests are about the picture, not the envelope, and
#: the defaults union ~20 000 polygons. Both are stated rather than inherited.
ENVELOPE_SAMPLES = 8
ENVELOPE_SUBSTEP_DT = 0.05


def a_frame() -> StateFrame:
    """A mid-run frame of `near_miss`: arm out, human close, three obstacles."""
    frames = list(scenario("near_miss").states(seed=0))
    return frames[len(frames) // 2]


def an_envelope(frame: StateFrame) -> Polygon:
    return compute_envelope(
        frame.proprio(),
        DEMO_WORLD.limits,
        horizon=0.2,
        n_samples=ENVELOPE_SAMPLES,
        seed=0,
        substep_dt=ENVELOPE_SUBSTEP_DT,
    )


def new_axes():
    fig = Figure()
    return fig.add_subplot(1, 1, 1)


def patch_by_label(ax, needle: str):
    """The one patch whose legend label contains `needle`."""
    found = [p for p in ax.patches if isinstance(p.get_label(), str) and needle in p.get_label()]
    assert found, f"no patch labelled {needle!r}; labels were {[p.get_label() for p in ax.patches]}"
    return found[0]


def count_by_colour(ax, colour: str) -> int:
    """Patches drawn in `colour`. Only the first patch of a repeated element
    carries a legend label, so the colour is what identifies the rest."""
    want = to_rgba(colour)[:3]  # RGB only: the alpha carries the fill, not the identity
    return sum(1 for p in ax.patches if tuple(p.get_edgecolor())[:3] == want)


def pixel_at(fig, ax, x: float, y: float, pixels: np.ndarray) -> np.ndarray:
    """The RGBA pixel a data-space point landed on, in a drawn Agg figure."""
    px, py = ax.transData.transform((x, y))
    row = pixels.shape[0] - 1 - int(round(py))  # the buffer's origin is top-left
    return pixels[row, int(round(px))]


# --------------------------------------------------------------------------
# It renders
# --------------------------------------------------------------------------


def test_render_frame_writes_a_non_empty_png(tmp_path) -> None:
    frame = a_frame()
    out = tmp_path / "nested" / "frame.png"

    path = render_frame(frame, an_envelope(frame), DEMO_WORLD.limits, out, world=DEMO_WORLD)

    assert path == out
    data = out.read_bytes()
    assert data.startswith(PNG_MAGIC), "the file is not a PNG"
    assert len(data) > 1000, f"a {len(data)}-byte PNG is not a picture of anything"


def test_render_frame_works_without_an_envelope(tmp_path) -> None:
    """`envelope=None` is a supported call, not an error — and it is reported."""
    frame = a_frame()
    out = tmp_path / "no_envelope.png"

    render_frame(frame, None, DEMO_WORLD.limits, out, world=DEMO_WORLD)

    assert out.read_bytes().startswith(PNG_MAGIC)


def test_two_renders_of_the_same_frame_are_byte_identical(tmp_path) -> None:
    """Determinism is not optional here (CLAUDE.md): same call, same bytes."""
    frame = a_frame()
    envelope = an_envelope(frame)

    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    render_frame(frame, envelope, DEMO_WORLD.limits, first, world=DEMO_WORLD)
    render_frame(frame, envelope, DEMO_WORLD.limits, second, world=DEMO_WORLD)

    assert first.read_bytes() == second.read_bytes(), (
        "two renders of the same frame differ. Something time-, path- or "
        "version-dependent is reaching the PNG."
    )


def test_rendering_does_not_mutate_the_frame(tmp_path) -> None:
    """The frame is evidence. A renderer that edits it has edited the record."""
    frame = StateFrame(
        t=1.25,
        q=np.array([0.3, 0.7]),
        qd=np.array([0.1, -0.2]),
        human_pos=np.array([1.1, 0.4]),
        human_vel=np.array([-0.3, 0.0]),
        objects=DEMO_WORLD.obstacles,
    )
    before = {
        name: np.array(getattr(frame, name), copy=True)
        for name in ("q", "qd", "human_pos", "human_vel")
    }

    render_frame(
        frame,
        an_envelope(frame),
        DEMO_WORLD.limits,
        tmp_path / "frame.png",
        world=DEMO_WORLD,
    )

    for name, original in before.items():
        assert np.array_equal(getattr(frame, name), original), f"frame.{name} was mutated"
    assert frame.t == 1.25
    assert frame.objects is DEMO_WORLD.obstacles


def test_the_scene_is_drawn_to_scale() -> None:
    """Unequal axes would show the human as an ellipse and every clearance in
    the picture as a number other than the one it is."""
    ax = new_axes()
    frame = a_frame()

    draw_frame(ax, frame, an_envelope(frame), DEMO_WORLD.limits, DEMO_WORLD)

    assert ax.get_aspect() == 1.0


def test_one_patch_per_link_and_one_per_obstacle_is_drawn() -> None:
    ax = new_axes()
    frame = a_frame()

    draw_frame(ax, frame, None, DEMO_WORLD.limits, DEMO_WORLD)

    n_links = len(DEMO_WORLD.limits.link_lengths)
    assert count_by_colour(ax, COLOR_ROBOT) == n_links, (
        f"{count_by_colour(ax, COLOR_ROBOT)} body patches for a {n_links}-link "
        "arm; a link missing from the picture is a piece of the robot the "
        "viewer never sees"
    )
    assert count_by_colour(ax, COLOR_OBSTACLE) == len(frame.objects)


def test_an_envelope_hole_stays_a_hole() -> None:
    """A hole filled in is the picture claiming coverage the envelope lacks.

    Checked in pixels rather than in the path object: Agg carves the hole out
    with the non-zero winding rule, which only works while the interior ring
    winds against the exterior one. `Path.contains_point` does not apply that
    rule, so it would pass whether or not the picture is right.

    Both rings are wound the same way on purpose. Shapely guarantees nothing
    about ring orientation, and a polygon that arrives like this is exactly the
    one whose hole silently fills in.
    """
    ccw_shell = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    ccw_hole = [(-0.4, -0.4), (0.4, -0.4), (0.4, 0.4), (-0.4, 0.4)]
    annulus = Polygon(ccw_shell, [ccw_hole])
    assert annulus.is_valid and annulus.exterior.is_ccw == LinearRing(ccw_hole).is_ccw
    fig = Figure(figsize=(3.0, 3.0), dpi=100)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(1, 1, 1)

    draw_frame(ax, a_frame(), annulus)  # envelope only: nothing to draw over it

    path = patch_by_label(ax, "computed envelope").get_path()
    n_subpaths = int(np.sum(path.codes == MplPath.MOVETO))
    assert n_subpaths == 2, f"the hole is not a separate subpath ({n_subpaths} rings drawn)"

    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-1.2, 1.2)
    fig.canvas.draw()
    pixels = np.asarray(fig.canvas.buffer_rgba())
    background = pixel_at(fig, ax, 1.15, 1.15, pixels)
    assert not np.array_equal(pixel_at(fig, ax, 0.7, 0.0, pixels), background), (
        "the annulus itself was not drawn, so this test proves nothing"
    )
    assert np.array_equal(pixel_at(fig, ax, 0.0, 0.0, pixels), background), (
        "the hole is filled in: the picture claims coverage the envelope lacks"
    )


# --------------------------------------------------------------------------
# It does not lie about the layers
# --------------------------------------------------------------------------


def test_every_legend_entry_states_its_layer() -> None:
    ax = new_axes()
    frame = a_frame()

    draw_frame(ax, frame, an_envelope(frame), DEMO_WORLD.limits, DEMO_WORLD)

    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert len(labels) == 5, f"expected room, envelope, obstacle, human, robot; got {labels}"
    for label in labels:
        assert label.endswith("(Layer A)") or label.endswith("(Layer B)"), (
            f"legend entry {label!r} does not say which layer it came from. The "
            "picture puts a Layer A envelope and a Layer B human in one frame; "
            "without the tag it reads as though the envelope knew about them."
        )


def test_the_envelope_is_labelled_an_under_approximation() -> None:
    """reg/envelope.py: say "under-approximation" out loud wherever it is
    reported. A shaded region otherwise reads as a boundary, and it is not one."""
    ax = new_axes()
    frame = a_frame()

    draw_frame(ax, frame, an_envelope(frame), DEMO_WORLD.limits, DEMO_WORLD)

    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert any("under-approx" in label for label in labels), labels


def test_layer_b_is_dashed_and_layer_a_is_not() -> None:
    ax = new_axes()
    frame = a_frame()

    draw_frame(ax, frame, an_envelope(frame), DEMO_WORLD.limits, DEMO_WORLD)

    for needle in ("room bounds", "static obstacle", "human"):
        style = patch_by_label(ax, needle).get_linestyle()
        assert style == LAYER_B_LINESTYLE, f"{needle} is Layer B and must be dashed, got {style!r}"
    for needle in ("computed envelope", "robot body"):
        style = patch_by_label(ax, needle).get_linestyle()
        assert style == LAYER_A_LINESTYLE, f"{needle} is Layer A and must be solid, got {style!r}"


def test_palette_colours_are_pairwise_distinct() -> None:
    """Phase 3 adds a declared envelope and Phase 4 a CLAMP marker. If either
    reuses a colour already in use, the one artifact whose job is to keep the
    layers apart conflates two of them."""
    assert len(set(PALETTE.values())) == len(PALETTE), PALETTE


def test_every_drawable_element_has_a_colour_and_a_layer() -> None:
    assert set(ELEMENT_LAYER) <= set(PALETTE), set(ELEMENT_LAYER) - set(PALETTE)
    assert set(ELEMENT_LAYER.values()) <= {"A", "B"}


# --------------------------------------------------------------------------
# It says what it could not draw
# --------------------------------------------------------------------------


def test_nothing_is_omitted_silently_when_everything_is_supplied() -> None:
    ax = new_axes()
    frame = a_frame()

    omissions = draw_frame(ax, frame, an_envelope(frame), DEMO_WORLD.limits, DEMO_WORLD)

    assert omissions == ()
    assert not [t for t in ax.texts if t.get_text().startswith(NOT_DRAWN_PREFIX)]


def test_missing_limits_and_world_are_announced_rather_than_guessed() -> None:
    """The negative test for the picture's own completeness: a frame drawn with
    no robot and no human must not look like a frame in which neither was
    there."""
    ax = new_axes()

    omissions = draw_frame(ax, a_frame())

    joined = " | ".join(omissions)
    assert "robot body" in joined
    assert "room bounds" in joined
    assert "human" in joined
    assert "envelope" in joined
    notes = [t.get_text() for t in ax.texts if t.get_text().startswith(NOT_DRAWN_PREFIX)]
    assert len(notes) == 1, "the omissions are not written on the picture itself"
    for omission in omissions:
        assert omission in notes[0]


def test_a_missing_envelope_alone_is_still_announced() -> None:
    ax = new_axes()

    omissions = draw_frame(ax, a_frame(), None, DEMO_WORLD.limits, DEMO_WORLD)

    assert omissions == ("computed envelope (none supplied)",)


def test_an_empty_envelope_is_refused() -> None:
    """An empty envelope is a failed computation. Drawn as "no overlay" it is
    indistinguishable from a caller who passed None on purpose."""
    with pytest.raises(ValueError, match="empty"):
        draw_frame(new_axes(), a_frame(), Polygon(), DEMO_WORLD.limits, DEMO_WORLD)


def test_an_invalid_envelope_is_refused() -> None:
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    assert not bowtie.is_valid
    with pytest.raises(ValueError, match="valid"):
        draw_frame(new_axes(), a_frame(), bowtie, DEMO_WORLD.limits, DEMO_WORLD)


def test_a_non_geometry_envelope_is_refused() -> None:
    with pytest.raises(TypeError, match="Polygon"):
        draw_frame(
            new_axes(),
            a_frame(),
            [(0, 0), (1, 0), (1, 1)],  # coordinates, not a geometry
            DEMO_WORLD.limits,
            DEMO_WORLD,
        )


def test_a_propriostate_is_not_a_scene() -> None:
    """Layer A alone has no human and no objects; drawing it as a frame would
    produce a room with nobody in it and no way to tell that from the truth."""
    state = ProprioState(t=0.0, q=np.array([0.1, 0.2]), qd=np.array([0.0, 0.0]))
    with pytest.raises(TypeError, match="StateFrame"):
        draw_frame(new_axes(), state, None, DEMO_WORLD.limits, DEMO_WORLD)


def test_a_non_axes_target_is_refused() -> None:
    with pytest.raises(TypeError, match="Axes"):
        draw_frame(Figure(), a_frame(), None, DEMO_WORLD.limits, DEMO_WORLD)


def test_wrong_typed_limits_and_world_are_refused() -> None:
    frame = a_frame()
    with pytest.raises(TypeError, match="Limits"):
        draw_frame(new_axes(), frame, None, DEMO_WORLD, DEMO_WORLD)
    with pytest.raises(TypeError, match="World"):
        draw_frame(new_axes(), frame, None, DEMO_WORLD.limits, DEMO_WORLD.limits)


def test_a_frame_whose_joints_do_not_match_the_limits_is_refused() -> None:
    """numpy would broadcast a one-joint q across a two-link arm; the picture
    would show a robot nobody described."""
    frame = StateFrame(
        t=0.0,
        q=np.array([0.2]),
        qd=np.array([0.0]),
        human_pos=np.array([1.0, 0.0]),
        human_vel=np.array([0.0, 0.0]),
        objects=(Obstacle("obs_0", "box", 1.5, 1.5, 0.2),),
    )
    with pytest.raises(ValueError, match="entries but there are 2 links"):
        draw_frame(new_axes(), frame, None, DEMO_WORLD.limits, DEMO_WORLD)


def test_out_path_is_required() -> None:
    frame = a_frame()
    with pytest.raises(TypeError, match="out_path"):
        render_frame(frame, None, DEMO_WORLD.limits, None, world=DEMO_WORLD)
