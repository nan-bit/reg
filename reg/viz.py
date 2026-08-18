"""Single-frame rendering: the robot, its computed envelope, and the scene.

This is the still frame the Phase 10 GIF is built from (docs/plan.md: "that
single image is the whole argument"). Static matplotlib only — no UI, no
animation, no interactivity, and none should arrive here.

THE RENDERING CONVENTION, AND WHY IT IS NOT COSMETIC
---------------------------------------------------
The envelope is **Layer A**: `reg.envelope.compute_envelope` computes it from
proprioception and actuation limits alone and structurally cannot see where the
human is (`reg/types.py`). The human, the obstacles and the room are **Layer B**:
simulator ground truth standing in for a perception stack.

A picture that draws all of them the same way invites exactly the wrong reading —
that the envelope stops short of the human because it *knows about* the human.
So the layers are drawn differently and the difference is stated in the legend:

    Layer A (envelope, robot body)        solid outline   `LAYER_A_LINESTYLE`
    Layer B (room, obstacles, human)      dashed outline  `LAYER_B_LINESTYLE`

Every legend entry carries its layer tag, and the envelope's entry says
"under-approx." because `reg/envelope.py` requires that word wherever the polygon
is reported: sampling can only under-cover the true reachable set, so there are
reachable configurations outside the shaded region.

WHAT IS NOT DRAWN IS SAID IN THE PICTURE
----------------------------------------
`draw_frame` cannot invent what it was not given. Without `limits` there are no
link lengths and therefore no robot body; without a `World` there is no room
rectangle and no human radius. Rather than silently omitting them — a picture
with no human reads as "nobody was there" — the omissions are written onto the
axes (`NOT_DRAWN_PREFIX`) and returned to the caller, so a programmatic caller
can refuse to ship a frame that is missing a layer.

DETERMINISM
-----------
`render_frame` writes PNG bytes that do not vary between two runs of the same
call: matplotlib's `Software` metadata key (which carries its version string) is
stripped, and nothing here reads a clock, a path or an environment variable.
`tests/test_viz.py` renders twice and compares bytes.

COLOURS
-------
One constant per element at module level, collected in `PALETTE`. Later phases
extend this rather than re-picking: `COLOR_ENVELOPE_DECLARED` (Phase 3's declared
envelope) and `COLOR_CLAMP` (Phase 4's CLAMP verdict) are already reserved and
must stay distinct from everything else — `tests/test_viz.py` asserts it, because
two elements sharing a colour would conflate two layers in the one artifact whose
job is to keep them apart.
"""

from __future__ import annotations

import os
from pathlib import Path as FilePath

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Circle, PathPatch
from matplotlib.path import Path as MplPath
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

from reg.kinematics import link_polygons
from reg.types import Limits, StateFrame
from reg.world import World

__all__ = [
    "COLOR_ROOM",
    "COLOR_OBSTACLE",
    "COLOR_HUMAN",
    "COLOR_ROBOT",
    "COLOR_ENVELOPE",
    "COLOR_ENVELOPE_DECLARED",
    "COLOR_CLAMP",
    "COLOR_NOTE",
    "PALETTE",
    "ELEMENT_LAYER",
    "LAYER_A_LINESTYLE",
    "LAYER_B_LINESTYLE",
    "NOT_DRAWN_PREFIX",
    "FIGURE_SIZE_INCHES",
    "FIGURE_DPI",
    "PLOT_MARGIN_M",
    "draw_frame",
    "render_frame",
]

# --------------------------------------------------------------------------
# Palette. One constant per element, defined once.
# --------------------------------------------------------------------------

#: Room bounds. Layer B — the room is simulator ground truth like everything
#: else in `reg/world.py`, even though it reads as the frame of the picture.
COLOR_ROOM = "#5c5c5c"

#: Static obstacles. Layer B.
COLOR_OBSTACLE = "#8c6d31"

#: The human. Layer B, and the one the whole argument is about.
COLOR_HUMAN = "#d95f02"

#: The robot's own body from forward kinematics. Layer A.
COLOR_ROBOT = "#1a1a1a"

#: The computed forward reachable set. Layer A, and an under-approximation.
COLOR_ENVELOPE = "#1f78b4"

#: RESERVED for Phase 3's declared envelope — nothing here draws it yet. It is
#: named now so that phase extends this palette instead of picking a colour that
#: collides with the computed envelope it has to be told apart from.
COLOR_ENVELOPE_DECLARED = "#6a3d9a"

#: RESERVED for Phase 4's CLAMP verdict marker. Not drawn here.
COLOR_CLAMP = "#e31a1c"

#: The "not drawn" note. Not an element of the scene; a statement about the
#: picture's own completeness, so it gets its own colour and its own entry.
COLOR_NOTE = "#8b0000"

#: Element name to colour. Every colour a later phase might want lives here, and
#: they are required to be pairwise distinct.
PALETTE: dict[str, str] = {
    "room": COLOR_ROOM,
    "obstacle": COLOR_OBSTACLE,
    "human": COLOR_HUMAN,
    "robot": COLOR_ROBOT,
    "envelope": COLOR_ENVELOPE,
    "envelope_declared": COLOR_ENVELOPE_DECLARED,
    "clamp": COLOR_CLAMP,
    "note": COLOR_NOTE,
}

#: Which layer each drawable element belongs to. This drives the linestyle and
#: the legend tag; it is data rather than a `if element == "human"` somewhere,
#: so adding an element without deciding its layer fails rather than defaults.
ELEMENT_LAYER: dict[str, str] = {
    "room": "B",
    "obstacle": "B",
    "human": "B",
    "robot": "A",
    "envelope": "A",
    "envelope_declared": "A",
    "clamp": "A",
}

#: What each element is called in the legend, before its layer tag is appended.
#: The envelope says "under-approx." because `reg/envelope.py` requires that
#: word wherever the polygon is reported — a shaded region reads as a boundary,
#: and this one is not: the true reachable set extends past it.
ELEMENT_LABEL: dict[str, str] = {
    "room": "room bounds",
    "obstacle": "static obstacle",
    "human": "human",
    "robot": "robot body",
    "envelope": "computed envelope, under-approx.",
    "envelope_declared": "declared envelope",
    "clamp": "CLAMP",
}

#: Layer A is solid, Layer B is dashed. See the module docstring.
LAYER_A_LINESTYLE = "-"
LAYER_B_LINESTYLE = "--"

#: Fills. Presentation only: an opaque envelope would hide the robot inside it,
#: which is the one spatial relationship in the picture that matters.
ENVELOPE_ALPHA = 0.30
HUMAN_ALPHA = 0.35
OBSTACLE_ALPHA = 0.30

#: Prefix of the note listing what this picture does not show. A constant so a
#: caller (and the test suite) can look for it without matching prose.
NOT_DRAWN_PREFIX = "not drawn: "

#: Figure geometry. Presentation choices, not physical parameters — stated once
#: here so a caller who needs a different size says so and it is visible.
FIGURE_SIZE_INCHES: tuple[float, float] = (7.0, 5.0)
FIGURE_DPI = 150

#: Metres of blank space left around the room so its dashed boundary is visible
#: rather than clipped by the axes. Also presentation only.
PLOT_MARGIN_M = 0.15

#: Stripped from the PNG. matplotlib writes its own version string into this key
#: by default, which would make two identical renders differ byte-for-byte across
#: matplotlib versions — the artifact would then record the plotting library
#: rather than the run.
_PNG_METADATA: dict[str, None] = {"Software": None}


def _legend_label(element: str) -> str:
    """`"<name> (Layer X)"`. Every legend entry states the layer it came from."""
    return f"{ELEMENT_LABEL[element]} (Layer {ELEMENT_LAYER[element]})"


def _linestyle(element: str) -> str:
    return LAYER_A_LINESTYLE if ELEMENT_LAYER[element] == "A" else LAYER_B_LINESTYLE


def _checked_envelope(envelope: object) -> tuple[Polygon, ...]:
    """The polygons to shade, or a loud refusal. `None` is handled by the caller.

    An empty or invalid envelope is a could-not-evaluate. Drawing nothing for it
    would produce a picture indistinguishable from `envelope=None`, i.e. a failed
    computation rendered as "no overlay was asked for".
    """
    if isinstance(envelope, Polygon):
        parts: tuple[Polygon, ...] = (envelope,)
    elif isinstance(envelope, MultiPolygon):
        parts = tuple(envelope.geoms)
    else:
        raise TypeError(
            f"envelope must be a shapely Polygon or MultiPolygon, got "
            f"{type(envelope).__name__}. `reg.envelope.compute_envelope` returns "
            "a Polygon; pass None to state that no envelope was supplied."
        )
    if envelope.is_empty:
        raise ValueError(
            "the envelope is empty. Rendering it as a picture with no overlay "
            "would be indistinguishable from envelope=None — a failed "
            "computation shown as 'nothing was asked for'."
        )
    if not envelope.is_valid:
        raise ValueError(
            "the envelope is not a valid geometry; its rendered area would not "
            "correspond to any region. Fix it upstream rather than shading it."
        )
    return parts


def _polygon_patch(poly: Polygon, **kwargs: object) -> PathPatch:
    """A patch for one shapely polygon, holes included.

    Holes matter: the union of swept link bodies can enclose a region the robot
    cannot occupy, and filling it in would make the picture claim coverage the
    envelope does not have. Agg fills with the non-zero winding rule, so a hole
    only reads as a hole if its ring winds against the exterior — shapely makes
    no such guarantee, hence the `orient`. This returns a new geometry; the
    caller's polygon is not touched.
    """
    poly = orient(poly, sign=1.0)
    vertices: list[np.ndarray] = []
    codes: list[int] = []
    for ring in (poly.exterior, *poly.interiors):
        coords = np.asarray(ring.coords, dtype=float)
        vertices.append(coords)
        # Shapely rings repeat the first point last, so `len(coords)` codes are
        # MOVETO, LINETO * (n - 2), CLOSEPOLY.
        codes.append(MplPath.MOVETO)
        codes.extend([MplPath.LINETO] * (len(coords) - 2))
        codes.append(MplPath.CLOSEPOLY)
    return PathPatch(MplPath(np.concatenate(vertices), codes), **kwargs)


def draw_frame(
    ax: Axes,
    frame: StateFrame,
    envelope: Polygon | MultiPolygon | None = None,
    limits: Limits | None = None,
    world: World | None = None,
) -> tuple[str, ...]:
    """Draw one frame onto `ax`. Returns what it could not draw.

    Args:
        ax: a matplotlib `Axes`. Set to an equal aspect ratio here — a scene
            drawn with unequal axes shows the human as an ellipse and every
            clearance in the picture as a different number than it is.
        frame: the ground-truth `StateFrame`. Read only; nothing here mutates it
            or the arrays inside it.
        envelope: the Layer A envelope from `reg.envelope.compute_envelope`, or
            `None` for "none was supplied" — which is reported in the picture,
            not silently rendered as a scene with no reachable region. An empty
            or invalid geometry is refused outright.
        limits: the robot's `Limits`. Without them there are no link lengths, so
            the body cannot be drawn; it is *not* guessed, and the omission is
            reported. Note that a `World` also carries `Limits` — they are not
            taken from it, because which robot the picture claims to draw should
            be stated at the call site.
        world: the Layer B `World`, supplying the room rectangle and the human's
            radius. Without it neither is drawn, and both omissions are reported.
            Obstacles come from `frame.objects` and do not need it.

    Returns:
        A tuple of human-readable descriptions of what was not drawn — empty when
        everything was supplied. The same text is written onto the axes prefixed
        with `NOT_DRAWN_PREFIX`. Callers assembling a figure programmatically
        should treat a non-empty tuple as a could-not-evaluate rather than as a
        picture of an empty scene.

    Raises:
        TypeError: `ax` is not an `Axes`, `frame` is not a `StateFrame`, or an
            argument is of the wrong type. A `ProprioState` is refused: it is
            Layer A and has no human or objects to draw, so accepting one would
            silently produce a scene with the Layer B half missing.
        ValueError: the envelope is empty or invalid, or the frame's joint vector
            does not match `limits` (from `reg.kinematics`).
    """
    if not isinstance(ax, Axes):
        raise TypeError(f"ax must be a matplotlib Axes, got {type(ax).__name__}.")
    if not isinstance(frame, StateFrame):
        raise TypeError(
            f"draw_frame takes a StateFrame, got {type(frame).__name__}. The "
            "scene is Layer B — the human and the objects live on the frame — so "
            "a ProprioState cannot be drawn as one; it would render as a room "
            "with nobody in it."
        )
    if limits is not None and not isinstance(limits, Limits):
        raise TypeError(f"limits must be a Limits, got {type(limits).__name__}.")
    if world is not None and not isinstance(world, World):
        raise TypeError(f"world must be a World, got {type(world).__name__}.")

    parts = _checked_envelope(envelope) if envelope is not None else ()

    omissions: list[str] = []
    handles: list[object] = []

    # Room, first and underneath: it is the frame everything else sits in.
    if world is not None:
        room = world.room
        handles.append(
            ax.add_patch(
                _rectangle_patch(
                    room.x_min,
                    room.y_min,
                    room.x_max,
                    room.y_max,
                    element="room",
                    zorder=1,
                )
            )
        )
        ax.set_xlim(room.x_min - PLOT_MARGIN_M, room.x_max + PLOT_MARGIN_M)
        ax.set_ylim(room.y_min - PLOT_MARGIN_M, room.y_max + PLOT_MARGIN_M)
    else:
        omissions.append("room bounds (no World supplied)")

    # The envelope, under the robot: the body it was computed from must stay
    # visible inside it.
    for i, part in enumerate(parts):
        patch = _polygon_patch(
            part,
            facecolor=COLOR_ENVELOPE,
            edgecolor=COLOR_ENVELOPE,
            alpha=ENVELOPE_ALPHA,
            linestyle=_linestyle("envelope"),
            linewidth=1.5,
            zorder=2,
            label=_legend_label("envelope") if i == 0 else None,
        )
        ax.add_patch(patch)
        if i == 0:
            handles.append(patch)
    if envelope is None:
        omissions.append("computed envelope (none supplied)")

    for i, obs in enumerate(frame.objects):
        patch = Circle(
            (obs.cx, obs.cy),
            obs.radius,
            facecolor=COLOR_OBSTACLE,
            edgecolor=COLOR_OBSTACLE,
            alpha=OBSTACLE_ALPHA,
            linestyle=_linestyle("obstacle"),
            linewidth=1.2,
            zorder=3,
            label=_legend_label("obstacle") if i == 0 else None,
        )
        ax.add_patch(patch)
        if i == 0:
            handles.append(patch)

    # The human. `world.human_polygon` is the world's own definition of their
    # extent and it validates the position, so the picture shows the same disc
    # every downstream intersection is computed against.
    if world is not None:
        patch = _polygon_patch(
            world.human_polygon(np.asarray(frame.human_pos, dtype=float)),
            facecolor=COLOR_HUMAN,
            edgecolor=COLOR_HUMAN,
            alpha=HUMAN_ALPHA,
            linestyle=_linestyle("human"),
            linewidth=1.5,
            zorder=4,
            label=_legend_label("human"),
        )
        ax.add_patch(patch)
        handles.append(patch)
    else:
        omissions.append("human (no World supplied: no radius)")

    # The robot, on top and opaque.
    if limits is not None:
        for i, body in enumerate(link_polygons(np.asarray(frame.q, dtype=float), limits)):
            patch = _polygon_patch(
                body,
                facecolor=COLOR_ROBOT,
                edgecolor=COLOR_ROBOT,
                linestyle=_linestyle("robot"),
                linewidth=1.0,
                zorder=5,
                label=_legend_label("robot") if i == 0 else None,
            )
            ax.add_patch(patch)
            if i == 0:
                handles.append(patch)
    else:
        omissions.append("robot body (no Limits supplied: no link lengths)")

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.text(
        0.02,
        0.98,
        f"t = {frame.t:.3f} s",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        zorder=6,
        # Boxed: the room boundary runs along the top of the axes and the frame
        # time is the one label a reader has to be able to trust at a glance.
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 2},
    )
    if handles:
        ax.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.9)
    if omissions:
        ax.text(
            0.5,
            0.02,
            NOT_DRAWN_PREFIX + "; ".join(omissions),
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=8,
            color=COLOR_NOTE,
            zorder=6,
        )
    return tuple(omissions)


def _rectangle_patch(
    x_min: float, y_min: float, x_max: float, y_max: float, element: str, zorder: int
) -> PathPatch:
    """The room outline: unfilled, so nothing sits on top of the whole scene."""
    ring = np.array(
        [
            [x_min, y_min],
            [x_max, y_min],
            [x_max, y_max],
            [x_min, y_max],
            [x_min, y_min],
        ],
        dtype=float,
    )
    codes = [MplPath.MOVETO, MplPath.LINETO, MplPath.LINETO, MplPath.LINETO, MplPath.CLOSEPOLY]
    return PathPatch(
        MplPath(ring, codes),
        facecolor="none",
        edgecolor=PALETTE[element],
        linestyle=_linestyle(element),
        linewidth=1.2,
        zorder=zorder,
        label=_legend_label(element),
    )


def render_frame(
    frame: StateFrame,
    envelope: Polygon | MultiPolygon | None,
    limits: Limits | None,
    out_path: str | os.PathLike[str],
    world: World | None = None,
    title: str | None = None,
) -> FilePath:
    """Render one frame to a PNG at `out_path`. Returns the path written.

    `envelope`, `limits` and `out_path` are all positional and none has a
    default: a render is a claim about a specific frame of a specific robot, and
    the only argument that can be left implicit is what is missing from it —
    which `draw_frame` writes onto the picture and returns.

    Parent directories are created (as `reg.sim.simulate` does); an existing file
    at `out_path` is overwritten. The bytes are deterministic: two calls with the
    same arguments produce the same file.
    """
    if out_path is None:
        raise TypeError(
            "out_path is required and has no default. A rendered frame written "
            "to a path nobody named is how figures get lost."
        )
    if title is not None and not isinstance(title, str):
        raise TypeError(f"title must be a string or None, got {type(title).__name__}.")

    fig = Figure(figsize=FIGURE_SIZE_INCHES, dpi=FIGURE_DPI)
    # Attach an Agg canvas explicitly rather than going through pyplot: no global
    # figure registry to leak, and no dependence on whatever backend the calling
    # process happens to have selected, which is what makes this run headless.
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(1, 1, 1)
    draw_frame(ax, frame, envelope=envelope, limits=limits, world=world)
    if title is not None:
        ax.set_title(title)
    fig.tight_layout()

    path = FilePath(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, format="png", metadata=_PNG_METADATA)
    return path
