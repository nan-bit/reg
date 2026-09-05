"""The evidence graph's persistence layer: SQLite schema and write primitives.

    from reg import store
    conn = store.create("runs/contact.sqlite", record_tables=False)
    store.insert_entity(conn, "obs_crate", "crate", geometry=disc)
    cfg_id = store.insert_robot_config(conn, "cfg_0", "0.0,0.0", "0.0,0.0",
                                       base_pose=None, base_pose_source=None)
    edge_id = store.open_edge(conn, "SEPARATION", cfg_id, "obs_crate", t_start=0.0,
                              min_distance=0.41)
    store.extend_edge(conn, edge_id, t_end=2.98)

WHY SQLITE AND WHY WKB
----------------------
docs/plan.md, Phase 5: the tables are small, the queries are interval joins and
chain walks, and `sqlite3` is stdlib. That last part is not convenience — a
single portable file with no external runtime is more credible as a thing handed
to an assessor in three years than a format requiring a specific engine to be
still installed. Geometry is stored as **WKB blobs** and every geometric
operation happens in Python via shapely; SQLite is a container here, not a
spatial database, and no query should ever try to reason about a blob.

THE EDGE TABLE IS ONE TABLE ON PURPOSE
--------------------------------------
Every edge type lands in `edge` with a `type` and a `layer`. Claim 3 is a query
over the layer tag across *all* edges ("which of these answers depend on an
uncertifiable perceiver"), and that query has to be one `WHERE layer = 'B'`
rather than a union over however many tables exist by then. docs/lossiness.md
Retained #9: "an untagged edge is an unusable edge."

The caller never supplies the layer. It is derived from the edge type through
`EDGE_SPECS` below, so a Layer B relationship cannot be written as Layer A by a
caller in a hurry — which is precisely the mistake that would make Claim 3 read
better than the truth.

One edge type is the exception and it proves the rule: `HAS_ENVELOPE`'s layer is
not a property of its type, because an envelope inherits the provenance of the
`Limits` it was computed from and an ISO/TS 15066 speed cap is perception
(issue #84). So its spec carries *both* layers, `open_edge` requires the caller
to state which one — `reg.envelope.envelope_layer(limits)` — and an omission is
a refusal rather than an `A`. The rule is the same rule: no layer tag is ever
written by an omission.

WHAT THE SCHEMA REFUSES
-----------------------
The `CHECK` constraints are not belt and braces; each one is a wrong answer that
would otherwise be indistinguishable from a right one:

* `t_end >= t_start` — a backwards interval matches no time window and would
  silently drop out of every timeline query.
* `layer IN ('A', 'B')` — see above.
* metric presence keyed to edge type — an `INTERSECTS` with no `overlap_area`
  answers "how much overlap" with `NULL`, and `NULL` compares false against every
  threshold, so an incident reads as a non-incident.
* geometry present exactly for entities whose geometry is time-invariant — see
  `insert_entity`.
* an envelope with neither geometry nor a `config_id` — an envelope row that
  stores no polygon and does not say what it was computed from is a row nobody
  can turn back into a region, and `reg.graph.envelope_at` would have to answer
  "no envelope" for a frame that had one. See `insert_envelope`.
* an `outer_radius` with no `config_id` — a radius is a distance about a centre,
  and the configuration is what names the frame that centre is in (issue #166).
  A radius about an unstated centre reads as a measurement and is not one.
* a `base_pose` with no `base_pose_source`, and either of them in an artifact
  that states `meta[base_frame]` — a room-frame pose whose provenance nobody
  stated, and a run claiming both that its base was bolted and that a localizer
  put it somewhere.
* an occurrence outside the vocabulary, or one whose entity or metric does not
  match what its type is — see `OCCURRENCE_SPECS` and `insert_occurrence`.

THE RECORD TABLES STORE WHAT THE RECORD CARRIES, AND NOTHING DERIVED
--------------------------------------------------------------------
`declaration` and `verdict` (issue #45) hold the Milestone 3 records verbatim:
every field, including `prev_hash` and `mac`, exactly as the record was signed.
This module **never re-signs and never re-hashes**. It holds no keys, so it
cannot check a MAC at all — and that is the property that matters, because a
store that could recompute a MAC is a store that can quietly repair a broken
chain, which is precisely what the chain exists to make visible. A record whose
MAC does not match is stored, and `read_declarations` / `read_verdicts` hand back
a record that still fails verification under the key that signed the original.
`tests/test_graph.py` asserts that persistence does not launder it.

Reconstruction is therefore byte-exact by construction: text columns for the
hashes and the ids, `REAL` for the two floats (an IEEE-754 double round-trips
through SQLite unchanged), and the WKB stored as the record's own bytes rather
than re-serialized through shapely — a second rendering of the same polygon is
the same region and a different preimage.

THE OCCURRENCE TABLE IS A SECOND RESOLUTION, NOT A SECOND ARTIFACT
------------------------------------------------------------------
Issue #35 added `occurrence` beside `edge`. It is the same run at DSSAD's
event-level granularity — a flag, a reason, a timestamp good to a stated
resolution, and the software version present at the event (docs/prior-art.md
§9) — and it is **additive**: nothing above it changed, and every query that
read the edge layer before still reads it. `reg.bench --resolution` measures
what each of the two costs and which questions each can still answer, which is
what Claim 1 became after issue #30 refuted its original form.

ENCODING IS NOT RETENTION
-------------------------
Two things here are decisions about *how* the file is written and about nothing
else: `PAGE_SIZE`, and the fact that `RECORD_SCHEMA` is applied only when the
build was handed a record stream (issue #54). Neither changes a column, a row,
an answer or a tolerance docs/lossiness.md advertises, and neither bumps
`SCHEMA_VERSION` — a reader does not have to know either one to read the file.
The line to hold is that the second must not become a retention decision by
accident: "this build was given no record stream" and "a run that produced no
records" are different facts (issue #48), the absent tables say neither of them,
and `meta[attestation_records]` says which — before any reader reaches a row.

NODE IDENTITY IS ONE TABLE, AND JOINS CARRY THE INTEGER (ISSUE #55)
--------------------------------------------------------------------
`node` holds `(node_key, node_id)` and nothing else: the readable identifier
every report cites, and the INTEGER surrogate every join and every index carries.
A `robot_config`, an `envelope`, an `entity`, an `occurrence`, a `declaration`
and a `verdict` row are all keyed on that surrogate, and `edge.src_key` /
`edge.dst_key` are it.

**This is a storage decision, not a retention one, and emphatically not a change
to the wire.** `env_08192d8f17313b39` is 20 B; every edge carries two endpoints
and three indexes carry the same text again, which measured ~128 B/edge of
identifier at 301 frames — and identifier text is what dominates once #54's
fixed costs have amortised away. What the change may not do is cost an
identifier: every function here still takes and still returns the readable id,
`envelope_row` renders the hash back to the hex it was handed, and an incident
report cites `declared_violation-verdict-00150` exactly as it did before. An
artifact whose report cites integers is worse evidence than one that costs a few
more bytes.

WHY IDENTITY IS ITS OWN TABLE RATHER THAN A COLUMN PER KIND. A `FOLLOWS` edge
naming a record this artifact no longer holds is the *second* witness to a
deleted record (`reg.chain._dangling_links`), and it is only evidence if it can
still say **which** record is missing. A surrogate that lived on the record row
would be deleted along with it, and the dangling link would come back naming
nothing — a tamper check that quietly stopped working, which is exactly what an
encoding change is most likely to break. The `node` row survives the payload row,
so the link still names the record that was removed.

`node_id` is unique across every kind, not per table. That is stricter than the
old per-table primary keys and deliberately so: `_insert_node` already refused
two different things sharing one id inside a table, and the same collision across
two tables was previously invisible. It is a loud `StoreError` now.

`envelope_hash` is stored as its 32 raw bytes rather than as 64 hex characters,
for the same reason and under the same rule: `insert_envelope` takes the hex
digest `reg.envelope.envelope_hash` produces, `envelope_row` hands the same hex
back, and only the column between them is narrower. It is also checked — a hash
that is not 32 bytes of lowercase hex is refused rather than stored, because a
truncated digest compares unequal to everything and would read as "this envelope
changed" on every frame.

**The canonical serialization has not moved.** Nothing here touches a MAC
preimage: `reg.chain` canonicalizes the record's own fields, this module stores
those fields as it was handed them, and `read_declarations` / `read_verdicts`
reconstruct the same bytes. `tests/test_graph.py` signs a declaration and a
verdict, persists them, reads them back and verifies — the test that fails if
this paragraph ever stops being true.

DETERMINISM
-----------
Same inserts in the same order produce the same file, byte for byte. Nothing here
writes a clock, a path, a hostname or a `rowid` derived from anything but
insertion order, and `tests/test_graph.py` builds the same stream twice and
compares bytes. If you add a column, add one whose value is a function of the
input stream.

`build_environment` is the one block that is a function of the *machine* rather
than of the stream, and it does not weaken that (issue #200). Two builds on one
machine record the same six strings, which is the whole of what CLAUDE.md rule 2
claims — determinism *within* an architecture — and it is why the record is a
version and a machine class rather than a hostname or a path, both of which
differ between two checkouts on one machine while nothing about the geometry
does. Across machines the values differ, and that is the point: the file says
which machine, so a recomputation that disagrees can be told from one run
somewhere else.
"""

from __future__ import annotations

import os
import platform
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy
import shapely
from shapely.geometry.base import BaseGeometry

from reg.types import Layer, PoseSource

__all__ = [
    "SCHEMA_VERSION",
    "SCHEMA_CHANGES",
    "META_SCHEMA_VERSION",
    "META_FRAME_PERIOD",
    "META_BASE_FRAME",
    "META_ENV_PYTHON",
    "META_ENV_NUMPY",
    "META_ENV_SHAPELY",
    "META_ENV_GEOS",
    "META_ENV_PLATFORM_SYSTEM",
    "META_ENV_PLATFORM_MACHINE",
    "ENVIRONMENT_KEYS",
    "build_environment",
    "HASH_BYTES",
    "PAGE_SIZE",
    "ENVELOPE_SOURCES",
    "POSE_SOURCES",
    "EDGE_SPECS",
    "LAYER_FROM_LIMIT_SOURCE",
    "NODE_TABLES",
    "OCCURRENCE_SPECS",
    "RECORD_KINDS",
    "RECORD_TABLE_NAMES",
    "StoreError",
    "create",
    "connect",
    "drop_nodes",
    "has_record_tables",
    "node_counts",
    "node_key",
    "layer_of",
    "possible_layers",
    "occurrence_layer",
    "put_meta",
    "get_meta",
    "all_meta",
    "insert_declaration",
    "insert_envelope",
    "attach_envelope_geometry",
    "envelope_row",
    "insert_entity",
    "insert_occurrence",
    "insert_robot_config",
    "config_base_pose",
    "insert_verdict",
    "open_edge",
    "extend_edge",
    "read_declarations",
    "read_edges",
    "read_occurrences",
    "read_verdicts",
    "to_wkb",
    "from_wkb",
    "to_hash",
    "from_hash",
]

#: Bumped whenever a table, column or constraint changes. It is written into
#: `meta` so a reader that meets an unfamiliar artifact can say it does not
#: understand it, rather than querying a column that has since changed meaning
#: and getting a confident wrong answer.
#:
#: 2: `envelope.geometry_wkb` became nullable and `envelope.config_id` arrived.
#: A v1 reader meeting a v2 file would read a NULL geometry as "no envelope"
#: rather than as "recompute it" (issue #28, docs/lossiness.md Discarded #9),
#: which is exactly the confident wrong answer the version exists to prevent.
#:
#: 3: the `timestep` table is gone and `HAS_ENVELOPE` runs `RobotConfig ->
#: Envelope` (issue #29, docs/lossiness.md Discarded #10). A v2 reader meeting a
#: v3 file would find `HAS_ENVELOPE` intervals covering only part of the run and
#: read the gaps as "the robot had no envelope then" rather than as "that frame
#: is not retained"; same confident wrong answer, one level up.
#:
#: 4: the `occurrence` table arrived (issue #35) — the DSSAD-aligned event layer,
#: additive beside the edges and replacing none of them. A v3 reader meeting a v4
#: file cannot see it at all, so every question the occurrence layer answers
#: would come back "this artifact records no such thing" rather than "this reader
#: does not understand this artifact".
#:
#: 5: the `declaration` and `verdict` tables arrived with the `DECLARED`,
#: `ADJUDICATED`, `ENFORCED` and `FOLLOWS` edges and the five enforcement
#: occurrence types (issue #45) — Milestone 3's records become queryable
#: evidence. `envelope.horizon` became nullable in the same change, because a
#: clamped bound is the region a verdict applied at an instant and the `Verdict`
#: record states no horizon for it. A v4 reader meeting a v5 file would read
#: `horizon` as always present and would not see the attestation layer at all,
#: so "this run had no verdicts" and "this reader cannot see verdicts" would be
#: the same answer.
#:
#: 6: node identity moved into the `node` table and every join and index carries
#: its INTEGER surrogate, and `envelope.envelope_hash` became a 32-byte BLOB
#: (issue #55). A v5 reader meeting a v6 file would look for `edge.src_id` and
#: `entity.entity_id`, find neither, and — because it would find `edge` and
#: `entity` — have no way to tell "this artifact holds no such relationship"
#: from "these columns are somewhere else now". The readable identifiers are all
#: still in the file and every function in this module still speaks them; it is
#: the *columns* a v5 reader would be wrong about, which is precisely what the
#: version exists to stop.
#:
#: 7: `edge.layer` on a `HAS_ENVELOPE` row stopped being a restatement of the row
#: type (issue #84). It now carries the provenance of the `Limits` the envelope
#: was computed from — `A` for a datasheet bound, `B` for one derived from a
#: perceiver, an ISO/TS 15066 speed cap being the case that matters — and `meta`
#: gained `limits_source` to record which. No table and no column changed, and
#: the bump is not for the key: it is for the *meaning*. A v6 reader derives the
#: layer of a `HAS_ENVELOPE` edge from its type, so on a file built from derived
#: limits it would answer "certifiable" about an answer this file says is not —
#: the confident wrong answer, about the one column Claim 3 is a query over. In
#: the other direction a v7 reader meeting a v6 file cannot tell an artifact
#: whose limits were proprioceptive from one whose provenance nobody recorded,
#: and `connect` refusing it is that could-not-evaluate rather than a default.
#:
#: 8: `occurrence.date` and `occurrence.t_utc` arrived, and `meta` gained
#: `run_start_utc`, `unit_id`, `operator_id` and the `commitment` block (issue
#: #83). A v6 reader meeting a v7 file would see occurrence timestamps and read
#: them as run-relative floats with no wall clock behind them — which is what
#: they were — and would report an artifact as uncommitted because it does not
#: know the key that says otherwise. Both are the confident wrong answer the
#: version exists to prevent, and the second is the worse one: "uncommitted" is
#: a finding about the artifact and "I cannot see the commitment" is not.
#:
#: 9: `envelope.outer_area` and `envelope.outer_radius` arrived (issue #82). A
#: `computed` envelope is an *under*-approximation, and until now the artifact
#: retained nothing that bracketed it from the other side, so "how good is the
#: sampled envelope" was a question only a benchmark could answer and only for a
#: run somebody still had. These two scalars are the horizon-limited **outer**
#: reachable set for the same frame — `reg.envelope.outer_envelope`, area and
#: radius — and they turn the bracket into evidence in the file. The geometry is
#: *not* retained: it is recomputable from the `robot_config` and the horizon
#: this row already names, and a polygon a frame would have put WKB back into a
#: retention figure that the incremental rule spent issues getting down. A v8
#: reader meeting a v9 file sees the inner area and has no way to tell an
#: artifact that brackets it from one that never did, which is the same confident
#: wrong answer every other bump here is about.
#:
#: 10: `robot_config` gained `base_pose` and `base_pose_source`, `meta` gained
#: `base_frame`, and a retained `outer_radius` now requires the `config_id` that
#: states the frame it is measured about (issue #166, docs/mobile-base.md §4
#: item 4). Two things a v9 reader would be confidently wrong about, and they are
#: different failures. **The polygon.** A v9 file's `geometry_wkb` may be NULL
#: because the envelope is a function of the `robot_config` a row names plus four
#: numbers in `meta` — an argument that holds only while the base is bolted down,
#: and a v9 reader meeting a v10 file whose config states a pose would recompute
#: that envelope **at the origin, for a robot that was somewhere else**, and
#: return it as the region in force. **The radius.** `outer_radius` was a radius
#: about a centre nothing in the file named; it was globally known to be the
#: origin, which stops being a fact the moment a row can say otherwise. In the
#: other direction a v10 reader meeting a v9 file cannot tell an artifact whose
#: base was bolted at the origin from one that never said where its radii are
#: measured from, and `connect` refusing it is that could-not-evaluate rather
#: than an origin assumed on the file's behalf.
#:
#: 11: `meta` gained the six environment keys — the interpreter, numpy, shapely,
#: GEOS and the platform's system and machine (issue #200,
#: docs/self-describing.md gap 2). No table and no column changed, and the bump
#: is not for the keys: it is for what a reader does with a NULL
#: `geometry_wkb`. A v10 reader recomputes a discarded polygon and returns it as
#: the region in force, on an argument — *it is a deterministic function of the
#: row and four numbers in `meta`* — that issue #175 measured to be true only
#: **within** an architecture. Meeting a v11 file it would ignore the environment
#: the file records, recompute anyway, and hand back a region whose disagreement
#: with the stored one it cannot attribute; the file contains exactly what would
#: have told it not to. That is the confident wrong answer, and it is the same
#: shape as v10's: a recomputation that is sound under a condition, run where the
#: condition does not hold. In the other direction a v11 reader meeting a v10
#: file cannot tell an artifact built on its own platform from one built
#: somewhere else, and `connect` refusing it is that could-not-evaluate rather
#: than this machine assumed on the file's behalf.
SCHEMA_VERSION = 11

#: What each version changed, one line each, keyed by the version it arrived in.
#: The comment block above is the argument; this is the part a **refusal** can
#: quote, and `connect` quotes it.
#:
#: WHY THE GATE NAMES THE CHANGE. "This build understands version 10" tells a
#: reader that their build is wrong and not *what about the file* they would have
#: been wrong about — and that second half is the only part that says whether the
#: artifact is readable by anything they have. A version gate that cannot say
#: what changed is a refusal a reader can only respond to by upgrading blind.
#: `tests/test_graph.py` asserts every version from 2 up is named here, so a bump
#: that forgets its line fails rather than silently narrowing the message.
SCHEMA_CHANGES: dict[int, str] = {
    2: "envelope.geometry_wkb became nullable and envelope.config_id arrived",
    3: "the timestep table went and HAS_ENVELOPE runs RobotConfig -> Envelope",
    4: "the occurrence table arrived",
    5: "the declaration and verdict tables and the four attestation edges "
    "arrived, and envelope.horizon became nullable",
    6: "node identity moved into the node table and every join carries its "
    "INTEGER surrogate; envelope.envelope_hash became a 32-byte BLOB",
    7: "edge.layer on a HAS_ENVELOPE row follows Limits.source rather than the "
    "row type, and meta gained limits_source",
    8: "occurrence.date and occurrence.t_utc arrived, and meta gained "
    "run_start_utc, unit_id, operator_id and the commitment block",
    9: "envelope.outer_area and envelope.outer_radius arrived",
    10: "robot_config gained base_pose and base_pose_source, meta gained "
    "base_frame, and a retained outer_radius now names the config whose "
    "frame it is measured about — so an envelope is no longer recomputable "
    "from q and qd alone and a radius is no longer a radius about an "
    "unstated centre",
    11: "meta gained the environment the geometry was computed in — the "
    "interpreter, numpy, shapely, GEOS and the platform's system and machine "
    "— so a recomputation that disagrees with a stored polygon can be told "
    "from one run on a different machine",
}

#: `meta` keys this module owns. Everything else in `meta` belongs to whoever
#: wrote it; these are the ones a reader may rely on.
META_SCHEMA_VERSION = "schema_version"
META_FRAME_PERIOD = "frame_period_s"

#: The frame every `robot_config` in this artifact that states **no** base pose
#: is measured in, as `x,y,theta` (issue #166). It is what makes a retained
#: `outer_radius` a radius about a centre somebody named.
#:
#: **A mounting fact, and it is written because a caller stated it.** For every
#: fixture in this repository the base is bolted at the origin and the builder
#: passes `reg.kinematics.ORIGIN_FRAME` — the value `grep ORIGIN_FRAME` lists as
#: the places this repository assumes a base that does not move — so what lands
#: here is that frame written down, not a frame this module chose. Absent is a
#: **could-not-evaluate**: a file whose configs state no pose and whose meta
#: states no frame holds radii about a centre nobody wrote down, and no reader
#: may resolve that to the origin. `reg.graph.envelope_frame` is the reader that
#: refuses.
#:
#: **It is exclusive with a per-config pose.** A run whose base drove has no one
#: frame its configs are measured in, so `insert_robot_config` refuses a
#: `base_pose` in an artifact that states this key. The two are different claims
#: — *the base was bolted here* and *the base was here at this instant, and a
#: localizer says so* — and an artifact making both would leave every reader to
#: pick one.
META_BASE_FRAME = "base_frame"

#: The environment the geometry in this artifact was computed in (issue #200).
#:
#: **This is a buildinfo, and the word is borrowed rather than coined.** The
#: Reproducible Builds project defines a build as reproducible *given the same
#: source, build environment and build instructions* — reproducibility is a
#: property relative to a **stated** environment, not one an artifact has by
#: itself — and the environment record is a **buildinfo**, a plain key–value
#: block naming the dependencies and their versions *as far as the build
#: actually uses them* (docs/prior-art.md §27). C2PA carries the same idea one
#: layer up in `claim_generator_info`, which records a claim generator's name,
#: version and operating system inside the hash-bound manifest (§28). The
#: content below is adopted from that practice and not derived here: a list
#: reasoned out from first principles would be the same list with no provenance
#: and nobody maintaining it.
#:
#: **The deviation, stated as one.** A buildinfo is deliberately *a separate
#: build product*, so that an archive can distribute it beside the artifact to
#: whoever wants to rebuild. These keys go **inside** `meta` instead, and the
#: reason is Claim 2: audit questions are answered from the graph alone, with no
#: access to anything else, which is a stronger requirement than the practice
#: has. The pattern is docs/prior-art.md §5's PROFIsafe deviation — a deliberate
#: departure, stated precisely, with its reason. What it costs is that the
#: environment is inside the thing it describes: it cannot be handed to a
#: rebuilder without the artifact, and it is descriptive `meta` rather than
#: anything the chain signs, so a party who can rewrite the file can rewrite its
#: environment too (docs/self-describing.md §7 question 3 holds that decision).
#:
#: **Why each key and not the others.** The rule is the practice's own: minimise
#: to what the computation depends on rather than enumerate the world. Each one
#: below is here because a change in it can change the geometry:
#:
#: * `env_python_version` — CPython's `math.sin`, `math.cos` and `math.hypot`
#:   place every arc vertex in `reg.envelope`, and `float.__repr__` renders every
#:   number `reg.graph` writes into this table.
#: * `env_numpy_version` — `np.cos` and `np.sin` in
#:   `reg.kinematics.forward_kinematics` place every link endpoint, and numpy's
#:   loops for them have changed between releases.
#: * `env_shapely_version` — the layer that buffers, simplifies and encodes
#:   every polygon in the file.
#: * `env_geos_version` — the C library that actually does the union, the
#:   intersection and the area, and it is **not** implied by the shapely version:
#:   two wheels of one shapely release bundle different GEOS builds.
#: * `env_platform_system` and `env_platform_machine` — the pair issue #175
#:   measured a divergence across. Hex-float tables captured on x86_64 Linux
#:   differ in their last bits on arm64 Darwin, because `sin`, `cos` and a GEOS
#:   build are the platform's and not IEEE-754's.
#:
#: **What is left out, and one omission is load-bearing.** No hostname, no build
#: path, no user, no locale, no timezone, no umask: nothing here reads one — the
#: single absolute time in an artifact is declared by the caller (issue #83) —
#: so recording them would enumerate rather than minimise, and each would vary
#: between two checkouts on one machine without anything about the geometry
#: varying. **The C library version is the omission that would change the
#: geometry and is left out anyway.** `math.sin` is glibc's on Linux, so two
#: builds agreeing on all six keys can still have been linked against different
#: libms; `platform.libc_ver()` cannot be used to close that, because it reports
#: `('', '')` on macOS and under musl, and a key that is empty on some platforms
#: would mean both *this build could not tell* and *this platform has no glibc*
#: — while a build that refused when it came back empty would refuse to write an
#: artifact on those platforms at all. So the hole is stated rather than papered
#: over: matching environments here are a necessary condition for a
#: bit-identical recomputation and not a sufficient one
#: (docs/lossiness.md *Discarded* #9, docs/limitations.md §1).
META_ENV_PYTHON = "env_python_version"
META_ENV_NUMPY = "env_numpy_version"
META_ENV_SHAPELY = "env_shapely_version"
META_ENV_GEOS = "env_geos_version"
META_ENV_PLATFORM_SYSTEM = "env_platform_system"
META_ENV_PLATFORM_MACHINE = "env_platform_machine"

#: The buildinfo's keys, in the order `build_environment` reports them. A reader
#: consults this rather than a second list of its own: an environment block that
#: is missing one key is a could-not-evaluate, and it can only be seen to be
#: missing against a list somebody keeps.
ENVIRONMENT_KEYS = (
    META_ENV_PYTHON,
    META_ENV_NUMPY,
    META_ENV_SHAPELY,
    META_ENV_GEOS,
    META_ENV_PLATFORM_SYSTEM,
    META_ENV_PLATFORM_MACHINE,
)

#: How wide an `envelope_hash` is, in bytes. `reg.envelope.envelope_hash` is a
#: SHA-256, so this is 32 — and it is checked on the way in rather than assumed,
#: because a digest that is not the full width compares unequal to everything and
#: would read as "the envelope changed" on every frame of the run.
HASH_BYTES = 32

#: The SQLite page size every artifact is created with, in bytes (issue #54).
#: **An encoding decision, not a retention one.** It changes no column, no row
#: and no answer; `SCHEMA_VERSION` is deliberately not bumped for it, because a
#: reader does not need to know the page size to read the file — SQLite reads it
#: out of the header.
#:
#: WHY IT IS NOT SQLITE'S 4096 DEFAULT. Most objects in an artifact this size
#: occupy one page whatever they hold, so padding dominates: `sustained_overlap`
#: at 301 frames spread 172 KB over 42 pages, many of them holding a single row.
#: At 1024 the same build is 65% of that, and every scenario fixture measured
#: between 64% and 72%.
#:
#: **AND WHERE IT STOPS PAYING.** The trade reverses as the tables grow past a
#: page, and it was measured until it did: on `long_run`, 1024 is 67% of the
#: default at 301 frames, 85% at 1,000, 97% at 3,000 and **102% — a loss — at
#: 10,000**. 512 reverses harder (104% at 10,000) and 2048 barely moves in
#: either direction. 1024 is chosen because it is the best value at every
#: length once the file is gzipped and never the worst on disk; a run long
#: enough to care is a run whose pages are full, where the whole question stops
#: mattering to within a couple of percent. The full table is in issue #54's PR.
#:
#: WHAT IT IS NOT WORTH. Gzipped, the same change is worth a small fraction of
#: what it is worth on disk at short lengths — 97.5% against 65.5% on
#: `sustained_overlap` — because most of what it removes is padding gzip
#: already removes. The benchmark headline divides gz(CSV) by *on-disk* SQLite,
#: so this flatters the headline more than it helps whoever stores the file.
#: Past a few thousand frames that inverts: on disk it costs a little and
#: gzipped it saves ~6%, which is the number an assessor's disk actually sees.
#:
#: It must be set **before any table is created** — SQLite fixes the page size
#: at file creation, and a `PRAGMA` after the first page is written is silently
#: ignored. `create` reads it back and refuses the file if it did not take.
PAGE_SIZE = 1024

#: Envelope `source` vocabulary, from docs/plan.md Phase 5. Fixed and small, so
#: an out-of-vocabulary source is a detectable fault rather than a new category
#: nobody agreed to. Only `computed` is produced in this milestone; `declared`
#: and `clamped` arrive with `declare/` and `enforce/`, and all three are
#: retained separately because "a clamp is only legible if the declared and the
#: computed bound both survive" (docs/lossiness.md Retained #8).
ENVELOPE_SOURCES = ("computed", "declared", "clamped")

#: The `base_pose_source` vocabulary, derived from `reg.types.PoseSource` rather
#: than written out again — a second list is how the two drift apart, and a
#: provenance the schema accepts but the type does not is a value nothing
#: downstream can read.
#:
#: **Neither member decides a layer, and no function here maps one to a layer.**
#: A room-frame pose is Layer B structurally on both provenances
#: (docs/sufficiency.md §5.6), so what makes an edge resting on a posed config
#: Layer B in `open_edge` is the *presence* of a pose and never its source.
#: `tests/test_layer_boundary.py::test_no_function_in_reg_maps_a_pose_provenance_to_a_layer`
#: is what keeps that true here as well as in `reg.types`.
POSE_SOURCES: tuple[str, ...] = tuple(source.value for source in PoseSource)


#: The node kinds a chain link may join. `FOLLOWS` is the one edge type whose
#: endpoints are polymorphic: declarations chain among themselves under the
#: policy key and verdicts among themselves under the enforcement key, so the
#: same edge type runs `Declaration -> Declaration` in one chain and
#: `Verdict -> Verdict` in the other. A separate edge type per chain would make
#: "walk the record chain" two queries that have to be kept in step.
RECORD_KINDS: frozenset[str] = frozenset({"Declaration", "Verdict"})


#: The layers `HAS_ENVELOPE` may carry, and the reason `EdgeSpec.layer` is not
#: always one value (issue #84).
#:
#: An envelope's layer is not a property of its edge type alone. It is decided by
#: the provenance of the `Limits` it was computed from: proprioceptive bounds
#: give a Layer A region, bounds derived from something perceived — an ISO/TS
#: 15066 speed-and-separation cap on `qd_max` — give a Layer B one.
#: `reg.envelope.envelope_layer` is the single place that mapping lives, and a
#: caller opening one of these edges has to state what it returned. Stating it is
#: the enforcement: an omitted layer is a refusal, so a build that never thought
#: about provenance cannot write a Layer A tag by default.
LAYER_FROM_LIMIT_SOURCE: frozenset[Layer] = frozenset({"A", "B"})


@dataclass(frozen=True)
class EdgeSpec:
    """What one edge type is: its layer, its endpoints, and its metric column.

    This table is the single definition of the edge vocabulary. `open_edge`
    reads the layer and the endpoint kinds off it rather than taking them from
    the caller, so there is no call site at which they can be got wrong.

    An endpoint may be a `frozenset` of kinds instead of one kind, for an edge
    type whose endpoints genuinely vary — `FOLLOWS`, and only `FOLLOWS`. The
    caller then states the kind and `open_edge` refuses anything outside the set.

    The *layer* may be a `frozenset` in the same way, and for one edge type only:
    `HAS_ENVELOPE`, whose layer follows `Limits.source` rather than its type
    (`LAYER_FROM_LIMIT_SOURCE`). A fixed layer is still never the caller's to
    supply, and a varying one has no default to fall back on — those are the same
    rule, which is that no layer tag is ever written by an omission.
    """

    layer: Layer | frozenset[Layer]
    src_kind: str | frozenset[str]
    dst_kind: str | frozenset[str]
    #: The one metric column this edge type carries, or `None` if it carries
    #: none. Presence is enforced both here and by a `CHECK` in the schema.
    metric: str | None


#: The edge vocabulary (docs/plan.md Phase 5, issues #14 and #45).
#:
#: `HAS_ENVELOPE` is Layer A **when the limits it was computed from are** — an
#: envelope is computed from proprioception and actuation limits alone
#: (`reg.envelope`), and the actuation limits are the half that can be derived
#: from a perceiver (`LAYER_FROM_LIMIT_SOURCE`, issue #84). Every artifact this
#: repository builds is Layer A here, because `reg.world.LIMITS` is a datasheet.
#: `INTERSECTS`, `SEPARATION` and `CONTACT` are Layer B without exception,
#: because each one names an entity, and where an entity is comes from perception
#: in any real system.
#:
#: **The four attestation edges are Layer A, every one of them, and not one names
#: an `Entity`.** That is not a coincidence and it is not a convenience: it is
#: the asymmetry docs/sufficiency.md §2 is about. A declaration is a statement
#: the policy made about itself, a verdict is enforcement's finding about a
#: commanded action, the bound in each case is a region computed from `Limits`
#: and proprioception, and the chain link is a fact about the record. None of it
#: needs to know where anybody is standing — so every attestation answer in this
#: artifact survives an uncertifiable perceiver, while every answer about who was
#: near the robot does not. `tests/test_graph.py::
#: test_layer_b_is_exactly_the_entity_naming_edges` holds the line: an edge that
#: names an `Entity` is Layer B whatever its author intended.
#:
#: **AND *NAMES NO ENTITY* IS NOT THE SAME AS *DEPENDS ON NOTHING OUTSIDE THE
#: ROBOT*, WHICH IS ISSUE #166.** Where the base is comes from localization, and
#: a `robot_config` row may now say so (`base_pose`). Nothing in that sentence
#: names an entity, and none of `base_pose`, `x`, `y` or `theta` is a word a
#: world-word check could hold against — so an edge resting on a posed
#: configuration is a Layer A tag on an answer that inherits a perceiver,
#: arriving by a door the paragraph above cannot see. `open_edge` reads the
#: pose off the endpoint and refuses the `A`: `HAS_ENVELOPE`, whose layer is
#: stated, must be stated `B`, and a type whose layer is a fixed `A` is refused
#: outright rather than relabelled, because reclassifying the attestation edges
#: is a change to what this project claims and not a call site's to make
#: (docs/sufficiency.md §5.8).
#:
#: `HAS_ENVELOPE` runs `RobotConfig -> Envelope` and not `Timestep -> Envelope`
#: (issue #29). docs/plan.md Phase 5's table originally said `Timestep`; it now
#: records the change, and so does this line, because it is a decision and not a
#: slip. The envelope is a deterministic function of the configuration it was
#: computed from, so the configuration is the thing it *has an envelope of*, and
#: the edge's own `t_start`/`t_end` are where time lives. A `Timestep` node was a
#: second, denser representation of time sitting beside the interval
#: representation that does the work — one row per frame, which is exactly what
#: the incremental principle forbids.
EDGE_SPECS: dict[str, EdgeSpec] = {
    "HAS_ENVELOPE": EdgeSpec(
        LAYER_FROM_LIMIT_SOURCE, "RobotConfig", "Envelope", None
    ),
    "INTERSECTS": EdgeSpec("B", "Envelope", "Entity", "overlap_area"),
    "SEPARATION": EdgeSpec("B", "RobotConfig", "Entity", "min_distance"),
    "CONTACT": EdgeSpec("B", "RobotConfig", "Entity", None),
    "DECLARED": EdgeSpec("A", "Declaration", "Envelope", None),
    "ADJUDICATED": EdgeSpec("A", "Verdict", "Declaration", None),
    "ENFORCED": EdgeSpec("A", "Verdict", "Envelope", None),
    "FOLLOWS": EdgeSpec("A", RECORD_KINDS, RECORD_KINDS, None),
}


@dataclass(frozen=True)
class OccurrenceSpec:
    """What one occurrence type is: its layer, its subject, and its metric.

    The occurrence vocabulary's single definition, the same way `EDGE_SPECS` is
    the edge vocabulary's. `insert_occurrence` reads the layer off it rather than
    taking it from the caller, so a Layer B event naming an entity cannot be
    written as Layer A by a call site in a hurry.
    """

    layer: Layer
    #: `entity` — the occurrence is about the robot's relationship to one entity
    #: and names it. `run` — it is about the record itself and names none.
    #: Presence of `entity_id` is enforced against this both here and by a
    #: `CHECK`: an `envelope_entered` with no entity says something entered
    #: something, which is not evidence about anything.
    subject: Literal["entity", "run"]
    #: What this occurrence type's `value` column holds, or `None` if it holds
    #: nothing. Presence is enforced both ways, like an edge's metric.
    metric: str | None


#: The occurrence vocabulary (issue #35, docs/prior-art.md §9). **Fixed and
#: small, like `ENVELOPE_SOURCES` and `EDGE_SPECS`**: an out-of-vocabulary
#: occurrence is a detectable fault rather than a new category nobody agreed to.
#:
#: The layers split exactly where the project's does: the run's own ends are
#: Layer A (they are facts about the record), and everything naming an entity is
#: Layer B without exception, because where an entity is comes from perception in
#: any real system.
#:
#: The five enforcement types arrived with issue #45 and are the **first Layer A
#: occurrences that are about something happening**, which is what lets the
#: coarse layer answer an attestation question at all. Issue #35 left them out
#: because no fixture produced a verdict; `reg.enforce` produces them now.
#: `action_clamped` is emitted by the `declared_violation` fixture today; the
#: other four are emitted by verdict streams the enforcer produces but that no
#: *scenario* yet drives, which is issue #46's subject — so they are covered by
#: `tests/test_graph.py` against real signed verdicts rather than by a fixture,
#: and the distinction is written here rather than left to be inferred from a
#: zero count.
OCCURRENCE_SPECS: dict[str, OccurrenceSpec] = {
    "run_began": OccurrenceSpec("A", "run", None),
    "run_ended": OccurrenceSpec("A", "run", None),
    "envelope_entered": OccurrenceSpec("B", "entity", None),
    "envelope_left": OccurrenceSpec("B", "entity", None),
    "contact_began": OccurrenceSpec("B", "entity", None),
    "contact_ended": OccurrenceSpec("B", "entity", None),
    "closest_approach": OccurrenceSpec("B", "entity", "min_distance_m"),
    "declaration_vetoed": OccurrenceSpec("A", "run", None),
    "action_clamped": OccurrenceSpec("A", "run", None),
    "safe_state_entered": OccurrenceSpec("A", "run", None),
    "reintegrated": OccurrenceSpec("A", "run", None),
    "escalation_failed": OccurrenceSpec("A", "run", None),
}

#: Node kind -> (table, surrogate key column). Used to check that an edge's
#: endpoints exist before the edge is written, and to attribute rows to a kind.
#:
#: The second element is the INTEGER surrogate (issue #55), not the readable id:
#: the readable id lives in `node` for every kind at once, and a payload table
#: names it nowhere. Anything wanting to go from an id to a row goes through
#: `node_key`, which is one indexed lookup and the only place that translation
#: happens.
#:
#: `Occurrence` is in here so it is counted, attributed and checked like every
#: other node kind, and **not** because any edge points at one: no `EdgeSpec`
#: names it. The occurrence layer is additive (issue #35) — it sits beside the
#: edges rather than joining them, and giving it an edge type would be inventing
#: a relationship the fixtures do not produce.
NODE_TABLES: dict[str, tuple[str, str]] = {
    "Envelope": ("envelope", "envelope_key"),
    "Entity": ("entity", "entity_key"),
    "RobotConfig": ("robot_config", "config_key"),
    "Occurrence": ("occurrence", "occurrence_key"),
    "Declaration": ("declaration", "declaration_key"),
    "Verdict": ("verdict", "verdict_key"),
}

#: The tables `RECORD_SCHEMA` creates, derived from `NODE_TABLES` rather than
#: written out again — a second list of them is how one of the two gets missed.
RECORD_TABLE_NAMES: frozenset[str] = frozenset(
    NODE_TABLES[kind][0] for kind in RECORD_KINDS
)

_SQL_EDGE_TYPES = ", ".join(f"'{name}'" for name in EDGE_SPECS)
_SQL_NODE_KINDS = ", ".join(f"'{name}'" for name in NODE_TABLES)
_SQL_ENVELOPE_SOURCES = ", ".join(f"'{name}'" for name in ENVELOPE_SOURCES)
_SQL_POSE_SOURCES = ", ".join(f"'{name}'" for name in POSE_SOURCES)
_SQL_OCCURRENCE_TYPES = ", ".join(f"'{name}'" for name in OCCURRENCE_SPECS)
_SQL_OCCURRENCE_ENTITY_TYPES = ", ".join(
    f"'{name}'" for name, spec in OCCURRENCE_SPECS.items() if spec.subject == "entity"
)
_SQL_OCCURRENCE_VALUED_TYPES = ", ".join(
    f"'{name}'" for name, spec in OCCURRENCE_SPECS.items() if spec.metric is not None
)

#: The shape of DSSAD's date element and of an absolute timestamp, checked at
#: the store boundary (issue #83). Shape only — this module cannot know which
#: afternoon a run happened on, and a check that verified the *value* would be a
#: second source for it. What it can refuse is a column that would end up
#: holding two formats, which is a column nobody can sort or hand over. The
#: writers are `reg.identity.RunIdentity.date` and `format_instant`.
_DATE_RE = re.compile(r"\d{4}/\d{2}/\d{2}")
_INSTANT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")

SCHEMA = f"""
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- THERE IS NO `timestep` TABLE. Every edge carries `t_start` and `t_end`, so
-- time is already an interval here; a node per instant would be a second and
-- denser representation of it, one row per frame, which is the thing the
-- incremental principle (docs/plan.md Phase 5) exists to prevent. Nothing in
-- docs/plan.md Phase 7's query set needs a per-frame anchor: the two questions
-- that name frames at all ("frames at risk", "27 frames") divide an interval by
-- `frame_period_s` in `meta`, which is recorded once and checked uniform at
-- build time. Issue #29; docs/lossiness.md Discarded #10.

-- NODE IDENTITY, ONCE, FOR EVERY KIND (issue #55). `node_id` is the readable
-- identifier every report, every doc example and every CLI argument uses;
-- `node_key` is the INTEGER surrogate every join and every index below carries.
-- The readable id is stored here and nowhere else, so an edge costs two small
-- integers rather than two 20-byte strings — and the same two integers again in
-- each of the three edge indexes, which is where the measurement in issue #55
-- said the bytes actually were.
--
-- IT OUTLIVES THE ROW IT NAMES, ON PURPOSE. Deleting a record from the
-- `declaration` table leaves this row behind, which is what lets
-- `reg.chain._dangling_links` say *which* record a FOLLOWS edge has lost. A
-- surrogate that lived on the record row would go with it and the dangling link
-- would come back naming nothing.
--
-- `node_id` is unique across every kind rather than per table. Two different
-- things sharing one identifier is the collision `_insert_node` has always
-- refused inside a table; across two tables it used to be invisible, and an
-- edge resolving to the wrong one would merge two histories into an answer
-- about neither.
CREATE TABLE node (
    node_key INTEGER PRIMARY KEY,
    node_id  TEXT NOT NULL UNIQUE
);

-- Created only when it anchors a retained relationship (docs/lossiness.md
-- Discarded #1), or when an envelope the artifact retains was computed from it.
-- The interpolated path between two of these is gone.
--
-- WHERE THE BASE WAS, AND WHY IT IS ON THIS ROW (issue #166,
-- docs/mobile-base.md §4 item 4). `base_pose` is `x,y,theta` in the **room** and
-- `base_pose_source` is the `reg.types.PoseSource` that produced it. Both NULL
-- means *this artifact records no base pose for this configuration*, which is a
-- could-not-evaluate and never a base at the origin: `meta[base_frame]` is where
-- an artifact says its base was bolted, and it is a different claim.
--
-- Text, and three numbers in one column, for the reason `q` is text: the joint
-- count is a property of the robot rather than of the schema, and the artifact
-- should read back the digits the raw stream carried rather than whatever a
-- REAL column round-trips to. A pose is not variable-length, but it is the same
-- claim about digits, and splitting it into three REALs would make the pose the
-- one thing on this row rendered by SQLite rather than by the writer.
--
-- **This row is where a room-frame statement enters the artifact**, and
-- `open_edge` reads it: an edge resting on a configuration that states a pose
-- may not be written Layer A, whatever its type says, because everything
-- computed from a room-frame pose inherits the perceiver that supplied it
-- (docs/sufficiency.md §5.6, §5.8). That is the first time a Layer A
-- attestation edge could depend on something outside the robot while naming no
-- `Entity`, which is the gap the layer test could not see.
CREATE TABLE robot_config (
    config_key       INTEGER PRIMARY KEY REFERENCES node (node_key),
    q                TEXT NOT NULL,
    qd               TEXT NOT NULL,
    base_pose        TEXT,
    base_pose_source TEXT CHECK (base_pose_source IN ({_SQL_POSE_SOURCES})),
    -- A pose with no provenance is the thing `BasePose` exists to make
    -- impossible, and a provenance with no pose is a failure mode described
    -- about nothing.
    CHECK ((base_pose IS NULL) = (base_pose_source IS NULL))
);

-- A row per envelope the artifact retains, keyed on `envelope_hash`
-- (reg.envelope). NOT one per frame and not one per material change: a moving
-- arm has a materially different envelope on every frame, so "on material
-- change" is "on every frame" for exactly the runs that matter, and it put the
-- node count back in step with the frame count (issue #29). The rule is
-- `reg.graph.ENVELOPE_RETENTION`, it is recorded in `meta`, and it keeps the
-- envelope where it anchors something — where an `INTERSECTS` edge names it,
-- where an entity relationship transitions, and at the two ends of the run.
-- `geometry_wkb` is retained on a second and narrower rule again
-- (docs/lossiness.md Discarded #9, issue #28).
--
-- WHY THE GEOMETRY MAY BE NULL, AND THE CONDITION ON IT (issue #166). The
-- polygon is a deterministic function of `(q, qd, horizon, n_samples,
-- envelope_seed, substep_dt)` — the config this row names plus four numbers in
-- `meta` — so storing it on every frame stores the same information twice, once
-- cheaply and once expensively. It is retained only where it is evidence in its
-- own right: `reg.graph.GEOMETRY_RETENTION` states the rule,
-- `reg.graph.envelope_at` is the reader that makes the absence invisible, and
-- the artifact records the rule in `meta` so nothing has to infer it from the
-- pattern of NULLs.
--
-- **That function is complete only while the base is bolted down.** Every term
-- in it is body-frame; where the body *was* is not in it. For a configuration
-- that states a `base_pose` the same six inputs describe the same arm in a
-- different place, so recomputing from them alone answers about a robot at the
-- origin — which is not a rounding error but a different robot, and the answer
-- would come back looking exactly like a right one. `reg.graph.envelope_at`
-- refuses a posed configuration for that reason rather than recomputing it, and
-- the discard rule above therefore reads: the polygon is recomputable **for a
-- base that did not move**, and a mobile run must retain it. Nothing in this
-- repository writes a posed configuration yet (docs/mobile-base.md §7, Tier 4),
-- so nothing here is currently discarding a polygon it cannot recover.
--
-- `config_key` is what makes that recoverable, so the CHECK requires one or the
-- other: a row with neither stores no region and names nothing to recompute one
-- from, and a query hitting it could only answer "no envelope at t", which is
-- indistinguishable from a frame that genuinely had none.
--
-- `envelope_hash` is the 32 raw bytes of the SHA-256 `reg.envelope.envelope_hash`
-- produces, not its 64 hex characters (issue #55). The digest on the wire is
-- unchanged — `insert_envelope` takes the hex and `envelope_row` returns it —
-- and the CHECK is what keeps a half-width digest out: a truncated hash compares
-- unequal to every other, so every frame would read as a material envelope
-- change and the retention rule would silently stop retaining anything.
--
-- WHY THE HORIZON MAY BE NULL, AND ONLY FOR A CLAMP. A `computed` envelope was
-- integrated over one, and a `declared` envelope carries the declaration's
-- validity window — the interval the policy claimed its body would stay inside
-- the region. A `clamped` envelope has neither: it is the bound enforcement
-- applied to one commanded action at one instant, and the `Verdict` record
-- states no horizon for it (docs/plan.md Phase 4). NULL is that record's silence
-- carried through rather than a plausible number invented at the write.
-- THE OTHER SIDE OF THE BRACKET (issue #82). `area` above is the area of an
-- under-approximation: sampling can only under-cover the true forward reachable
-- set, so it is a lower bound on it and never an upper one. `outer_area` and
-- `outer_radius` are the same frame's horizon-limited **outer** set
-- (`reg.envelope.outer_envelope`), which over-covers. The true reachable set is
-- between them, which is what makes "how good is the sampled envelope" a
-- question this artifact answers rather than one a benchmark answers about a run
-- somebody still has.
--
-- WHY SCALARS AND NOT THE POLYGON. The outer region is a deterministic function
-- of the `robot_config` this row names plus the horizon it stores, so retaining
-- its WKB would store the same information twice — once at 16 bytes a frame and
-- once at several kilobytes. Enforcement computes the region, uses it, and
-- discards it; these two numbers are what survives. The same condition as the
-- geometry above applies to that recomputation, and for the same reason.
--
-- AND A RADIUS IS STORED WITH THE FRAME IT IS MEASURED FROM, OR NOT STORED
-- (issue #166). `outer_radius` is a distance from the base to the furthest point
-- the robot can reach — a radius **about a centre**, and until this version
-- nothing in the file named that centre. It was globally known to be the origin,
-- which is a fact about there being no other possibility rather than about the
-- artifact, and it stops being true the moment a `robot_config` row can say
-- where the base was. So the CHECK below requires a `config_key` beside it: that
-- row states the frame, either as its own `base_pose` or, for a config that
-- states none, as `meta[base_frame]`. A radius with neither is a number in
-- metres about a point nobody can name, which compares against declared regions
-- and bounds as though it meant something.
--
-- Both are present exactly for a `computed` envelope. A `declared` region is the
-- policy's claim and a `clamped` one is the bound a verdict applied; neither is
-- a reachable set, so neither has an outer approximation, and inventing one for
-- them would put a number in the record that nothing computed.
CREATE TABLE envelope (
    envelope_key  INTEGER PRIMARY KEY REFERENCES node (node_key),
    envelope_hash BLOB NOT NULL CHECK (length(envelope_hash) = {HASH_BYTES}),
    area          REAL NOT NULL,
    geometry_wkb  BLOB,
    config_key    INTEGER REFERENCES robot_config (config_key),
    horizon       REAL,
    source        TEXT NOT NULL CHECK (source IN ({_SQL_ENVELOPE_SOURCES})),
    outer_area    REAL,
    outer_radius  REAL,
    UNIQUE (envelope_hash, source, horizon),
    CHECK (geometry_wkb IS NOT NULL OR config_key IS NOT NULL),
    CHECK ((horizon IS NULL) = (source = 'clamped')),
    CHECK ((outer_area IS NOT NULL) = (source = 'computed')),
    CHECK ((outer_radius IS NULL) = (outer_area IS NULL)),
    -- Strictly positive rather than "at least `area`", which is the invariant a
    -- reader actually wants. `area` is the *simplified* inner region quantized
    -- to two significant figures, and simplification may move a boundary by up
    -- to `GEOM_SIMPLIFY_TOL_M` in either direction, so the two columns are not
    -- two measurements of the same units of the same thing. The bracket is
    -- asserted where the two geometries still exist, in tests/test_graph.py; a
    -- CHECK on the rounded pair would be an invariant that fails a build for a
    -- rounding rather than for a fault. Zero, though, is always a failed
    -- computation: an outer bound of no extent contains no declared region.
    CHECK (outer_area IS NULL OR (outer_area > 0.0 AND outer_radius > 0.0)),
    CHECK (outer_radius IS NULL OR config_key IS NOT NULL)
);

-- `geometry_wkb` is the entity's world-frame boundary and is present exactly
-- when that boundary does not move. See `insert_entity` for why a moving
-- entity's per-frame position is not stored rather than stored badly.
CREATE TABLE entity (
    entity_key   INTEGER PRIMARY KEY REFERENCES node (node_key),
    kind         TEXT    NOT NULL,
    is_static    INTEGER NOT NULL CHECK (is_static IN (0, 1)),
    geometry_wkb BLOB,
    CHECK ((is_static = 1) = (geometry_wkb IS NOT NULL))
);

-- `src_key` and `dst_key` are `node.node_key` (issue #55). The *kind* stays as
-- text beside each one and is not derived from the key: it says which table the
-- endpoint's payload is in, `FOLLOWS` genuinely runs between two different
-- kinds in the two chains, and an endpoint whose kind had to be discovered by
-- probing six tables would turn a dangling reference into a slow guess.
CREATE TABLE edge (
    edge_id      INTEGER PRIMARY KEY,
    type         TEXT NOT NULL CHECK (type  IN ({_SQL_EDGE_TYPES})),
    layer        TEXT NOT NULL CHECK (layer IN ('A', 'B')),
    src_kind     TEXT NOT NULL CHECK (src_kind IN ({_SQL_NODE_KINDS})),
    src_key      INTEGER NOT NULL REFERENCES node (node_key),
    dst_kind     TEXT NOT NULL CHECK (dst_kind IN ({_SQL_NODE_KINDS})),
    dst_key      INTEGER NOT NULL REFERENCES node (node_key),
    t_start      REAL NOT NULL,
    t_end        REAL NOT NULL,
    overlap_area REAL,
    min_distance REAL,
    CHECK (t_end >= t_start),
    CHECK ((type = 'INTERSECTS') = (overlap_area IS NOT NULL)),
    CHECK ((type = 'SEPARATION') = (min_distance IS NOT NULL))
);

-- THE OCCURRENCE LAYER (issue #35). An event-level view of the same run, in the
-- shape UN R157's DSSAD mandates for automated driving — the only mandated
-- evidence recorder for autonomy that exists (docs/prior-art.md §9). It is
-- **additive**: the edge layer above is unchanged, every existing query still
-- reads it, and the two are two resolutions of one run rather than two builds.
--
-- The columns are DSSAD's data elements, named so the mapping is legible to a
-- reader who knows the regulation:
--
--   `type`        the occurrence flag — which listed event this is
--   `reason`      DSSAD's "reason for the occurrence, where applicable"
--   `t`           the run-relative timestamp, at the resolution recorded in
--                 meta[occurrence_time_resolution_s]
--   `date`        DSSAD's **date** element, `yyyy/mm/dd` UTC, derived from
--                 meta[run_start_utc] + `t`
--   `t_utc`       the same instant absolutely, so DSSAD's ±1.0 s accuracy is a
--                 statement about a wall clock rather than about a float
--   `recorder_version`
--                 the **recorder's** build: the `reg` version plus a digest
--                 binding the envelope parameters that produced the run, both
--                 of which are also in `meta` in full.
--
-- **DSSAD's R157SWIN element is NOT implemented, and the column above is not it
-- (issue #109).** R157SWIN is "the software version identifier present when the
-- event occurred" — of *the automated driving system whose behaviour is under
-- investigation*, so that an occurrence can be attributed to the build that
-- produced the behaviour. Until issue #109 this column was named `sw_version`
-- and this comment presented it as that element. It never was: it identifies
-- `reg`, the tool that was *watching*, and the parameters it watched with.
-- Those are two different pieces of software, and a mapping that offers one
-- where the regulation asks for the other is worse than a mapping with a gap in
-- it, because a column that reads as satisfied is not looked at twice.
--
-- The gap is not filled, because filling it would be a fiction. `reg`'s
-- simulator has no policy vendor and `reg.declare.Declaration` carries no
-- version field, so there is no policy build here to name; inventing a string
-- for the column is the invented default CLAUDE.md forbids, one layer up from a
-- parameter. A deployment that does have a policy version is where binding one
-- becomes a real requirement, and it would be a required, caller-supplied input
-- there — the shape `--run-start` and the keyring already have — not a value
-- derived from anything in this process. `reg.graph.OCCURRENCE_RETENTION` says
-- the same thing inside the artifact, so a reader holding only the file learns
-- the element is absent rather than inferring it from a column that is not
-- there. See `docs/prior-art.md` §9.
--
-- **The `date` column arrived in issue #83, and it closes a stated deviation.**
-- Until then there was none, on the argument that a wall-clock date is the
-- ambient value that would break byte-reproducibility. That argument did not
-- hold: key material is likewise not derivable from a seed, and the project
-- handles it by making it a **required caller-supplied input**. `--run-start`
-- is the same kind of input, so determinism is preserved exactly — same seed
-- *and* same declared start, same bytes — and the artifact gains the datum
-- DSSAD's ±1.0 s is an accuracy requirement *on*. Nothing here reads a clock.
--
-- `seq` is emission order, and it is what keeps two events inside one resolution
-- quantum two rows. Coarsening the timestamp loses *when* they happened relative
-- to each other, which is the cost being measured; it must not silently lose one
-- of them, which would be a different and much worse thing.
CREATE TABLE occurrence (
    occurrence_key   INTEGER PRIMARY KEY REFERENCES node (node_key),
    seq              INTEGER NOT NULL UNIQUE,
    type             TEXT    NOT NULL CHECK (type IN ({_SQL_OCCURRENCE_TYPES})),
    layer            TEXT    NOT NULL CHECK (layer IN ('A', 'B')),
    reason           TEXT    NOT NULL,
    t                REAL    NOT NULL,
    date             TEXT    NOT NULL,
    t_utc            TEXT    NOT NULL,
    entity_key       INTEGER REFERENCES entity (entity_key),
    value            REAL,
    recorder_version TEXT    NOT NULL,
    CHECK ((type IN ({_SQL_OCCURRENCE_ENTITY_TYPES})) = (entity_key IS NOT NULL)),
    CHECK ((type IN ({_SQL_OCCURRENCE_VALUED_TYPES})) = (value IS NOT NULL))
);

-- Claim 3 is `WHERE layer = ?`; queries 1-4 are `WHERE type = ? AND dst_key = ?`
-- over an interval. Index what the supported question set actually asks. The
-- three edge indexes are the same three they were before issue #55 — none was
-- dropped, because a smaller artifact that answers slower is a different trade
-- and would need measuring rather than assuming. What changed is that each one
-- now carries an integer where it used to carry a 20-byte identifier, three
-- times over.
CREATE INDEX edge_by_layer     ON edge (layer);
CREATE INDEX edge_by_type_dst  ON edge (type, dst_key);
CREATE INDEX edge_by_interval  ON edge (t_start, t_end);

-- The occurrence layer is asked "which events of this type, for this entity",
-- which is the same shape as `edge_by_type_dst` one layer up.
CREATE INDEX occurrence_by_type ON occurrence (type, entity_key);
"""

#: The two record tables, created **only** when the build was handed a record
#: stream (issue #54). A build without `--keyring` used to create them empty,
#: along with their two automatic indexes, and pay for four objects holding zero
#: rows.
#:
#: THEIR ABSENCE IS NOT THE FACT AN ASSESSOR READS. "This build was given no
#: record stream" and "a run that produced no records" are different facts
#: (issue #48), and `meta[attestation_records]` is what separates them — it is
#: written on every build, it says `absent` or `present`, and it is what
#: `reg.chain.verify_chain` and `reg.query`'s attestation queries consult before
#: they read a row. The tables being gone changes no answer: every reader that
#: could have seen an empty table refuses on the meta key first, and it refuses
#: with the same sentence it refused with before. `reg.store.has_record_tables`
#: exists so that a reader which does reach them says *that* rather than raising
#: `no such table: declaration` from somewhere in SQLite.
RECORD_SCHEMA = """
-- THE ATTESTATION RECORDS (issue #45). Milestone 3's `Declaration` and
-- `Verdict`, stored field for field as `reg.declare` and `reg.enforce` signed
-- them. Columns are the dataclass fields, so that reading a row back and
-- reconstructing the record is a rename and nothing else — a store that had to
-- transform a field on the way out would be a store whose output is a different
-- preimage from the one the MAC covers.
--
-- `mac` and `prev_hash` are stored and never recomputed. This module holds no
-- keys; it cannot tell a good MAC from a bad one, and that is the correct
-- capability for it to have. What it must never do is make a bad one verify.
--
-- `seq` is NOT unique here, unlike `occurrence.seq`. Reuse or regression of a
-- declaration's `seq` is the `replay_or_reorder` fault in Phase 4's taxonomy —
-- an artifact that could not hold the record that triggered a fault could not
-- hold the evidence for it either.
--
-- WHY THERE IS NO `CHECK (action_class IN (...))`, AND NONE ON `outcome` OR
-- `fault` BELOW. The three vocabularies are defined once, in
-- `reg.declare.ACTION_CLASSES` and `reg.enforce.OUTCOMES` / `FAULTS`, and
-- restating them here would be a second copy — which is how a value becomes a
-- detectable fault on one side and invisible on the other. Importing them is
-- what this module cannot do: `reg.declare` reaches `reg.stream` through
-- `reg.chain`, `reg.query` imports this module, and Claim 2's "answered from
-- the graph alone" is enforced as a property of the import graph
-- (`tests/test_query.py`). So the vocabulary check lives at both ends of the
-- record's life instead: the dataclasses refuse an out-of-vocabulary value at
-- construction, and `read_declarations` / `read_verdicts` refuse to reconstruct
-- a row carrying one. A value that reached these columns without passing a
-- record — which means raw SQL, which means tampering — is a loud
-- could-not-evaluate on the way out and never a quietly accepted row.
CREATE TABLE declaration (
    declaration_key       INTEGER PRIMARY KEY REFERENCES node (node_key),
    seq                   INTEGER NOT NULL CHECK (seq >= 0),
    t_issued              REAL    NOT NULL,
    horizon               REAL    NOT NULL CHECK (horizon > 0),
    action_class          TEXT    NOT NULL,
    declared_envelope_wkb BLOB    NOT NULL,
    prev_hash             TEXT    NOT NULL,
    mac                   TEXT    NOT NULL
);

-- `declaration_key` is nullable and its absence is a *finding*, not a gap: it is
-- what `no_declaration` and `watchdog_expiry` look like in the record. A verdict
-- that does name one names a declaration this artifact holds — `insert_verdict`
-- refuses a dangling reference, because an `ADJUDICATED` edge pointing at
-- nothing is an audit answer nobody can check.
--
-- It is the declaration's surrogate and not its readable id, and the record read
-- back is unaffected: `read_verdicts` joins `node` to put the id back, so the
-- reconstructed `Verdict` carries the same `declaration_id` the MAC was taken
-- over. The join is the whole difference.
CREATE TABLE verdict (
    verdict_key          INTEGER PRIMARY KEY REFERENCES node (node_key),
    declaration_key      INTEGER REFERENCES declaration (declaration_key),
    seq                  INTEGER NOT NULL CHECK (seq >= 0),
    t                    REAL    NOT NULL,
    outcome              TEXT    NOT NULL,
    fault                TEXT,
    clamped_envelope_wkb BLOB,
    prev_hash            TEXT    NOT NULL,
    mac                  TEXT    NOT NULL,
    -- The two invariants `Verdict.__post_init__` enforces, restated where the
    -- rows live: a PERMIT with a fault says "allowed, and here is what went
    -- wrong", and a CLAMP with no bound says "I limited it to nothing in
    -- particular". Both are could-not-evaluate wearing a decision's clothes.
    -- These name two outcomes rather than enumerating the four — the invariant
    -- is what is being stated, not the vocabulary, which is `reg.enforce`'s.
    CHECK ((outcome = 'PERMIT') = (fault IS NULL)),
    CHECK ((outcome = 'CLAMP') = (clamped_envelope_wkb IS NOT NULL))
);
"""


class StoreError(Exception):
    """A write the schema or the edge vocabulary refuses.

    Distinct from `sqlite3.IntegrityError` only in that it names what the caller
    got wrong. Both are failures; neither is recoverable by retrying with a
    substituted value.
    """


def possible_layers(edge_type: str) -> frozenset[Layer]:
    """Every layer an edge of this type may carry. Refuses an unknown type.

    One layer for every type whose layer is a property of the type, and both for
    `HAS_ENVELOPE`, whose layer follows the provenance of the `Limits` the
    envelope was computed from (`LAYER_FROM_LIMIT_SOURCE`, issue #84). This is
    the vocabulary-level question — *could an edge of this type ever be Layer
    B?* — and it is the one a check over a whole artifact wants; `layer_of` is
    the stricter question and refuses to answer it where the type cannot.
    """
    spec = EDGE_SPECS.get(edge_type)
    if spec is None:
        raise StoreError(
            f"{edge_type!r} is not an edge type. Known types: "
            f"{sorted(EDGE_SPECS)}. Adding one means deciding its layer, its "
            "endpoints and its metric in reg.store.EDGE_SPECS — Claim 3 is a "
            "query over the layer tag, so an edge nobody tagged is unusable."
        )
    return frozenset({spec.layer}) if isinstance(spec.layer, str) else spec.layer


def layer_of(edge_type: str) -> Layer:
    """The layer an edge type belongs to. Refuses a type not in the vocabulary.

    There is no "unknown layer" and no default. An edge whose layer nobody can
    state is exactly the unusable edge docs/lossiness.md Retained #9 rules out,
    so a new edge type is a decision recorded in `EDGE_SPECS`, not something a
    call site can improvise.

    It also refuses a type whose layer *is not a property of the type* — which is
    `HAS_ENVELOPE` and, at present, only `HAS_ENVELOPE`. Answering "A" for it
    would be the exact mislabelling of issue #84: an envelope computed from an
    ISO/TS 15066 speed cap is Layer B, and a function that reads the type alone
    cannot know that. Read the stored `edge.layer` column, which was written from
    the provenance that build actually had, or ask `possible_layers`.
    """
    spec = EDGE_SPECS.get(edge_type)
    if spec is None:
        possible_layers(edge_type)  # raises with the full vocabulary
        raise AssertionError  # pragma: no cover - possible_layers always raises
    if not isinstance(spec.layer, str):
        raise StoreError(
            f"the layer of a {edge_type} edge is not a property of its type: it "
            f"is {sorted(spec.layer)} depending on Limits.source (issue #84), so "
            "there is no single answer here and a plausible one would be the "
            "mislabelling this refusal exists to prevent. Read edge.layer off "
            "the row, or reg.envelope.envelope_layer(limits) for an edge about "
            "to be written."
        )
    return spec.layer


def occurrence_layer(occurrence_type: str) -> Layer:
    """The layer an occurrence type belongs to. Refuses one not in the vocabulary.

    The same rule as `layer_of`, for the same reason, plus one specific to this
    layer: the occurrence vocabulary is the artifact's claim about *what kinds of
    event it would have recorded had they happened*. A type invented at a call
    site makes the absence of that event unreadable — nobody can tell "it did not
    happen" from "this build had no name for it".
    """
    spec = OCCURRENCE_SPECS.get(occurrence_type)
    if spec is None:
        raise StoreError(
            f"{occurrence_type!r} is not an occurrence type. Known types: "
            f"{sorted(OCCURRENCE_SPECS)}. The vocabulary is fixed and small on "
            "purpose (docs/prior-art.md §9): an out-of-vocabulary occurrence is "
            "a detectable fault, not a new row type. Adding one means deciding "
            "its layer, its subject and its metric in "
            "reg.store.OCCURRENCE_SPECS — and having a fixture that produces it."
        )
    return spec.layer


# --------------------------------------------------------------------------
# Opening and creating
# --------------------------------------------------------------------------


def create(
    path: str | os.PathLike[str], *, record_tables: bool
) -> sqlite3.Connection:
    """Create a fresh artifact at `path` and return an open connection.

    An existing file is **replaced**, matching `reg.sim`: re-running a build over
    its own output is the normal case, and merging new rows into a stale schema
    would produce an artifact describing two runs at once. Parent directories are
    created — the caller named the path, this only makes it writable.

    Args:
        record_tables: whether to create `declaration` and `verdict`
            (`RECORD_SCHEMA`). **Required, with no default in either direction.**
            A caller that did not say would either pay for two empty tables it
            will never write to or, worse, get a `no such table` from the middle
            of a build that did have records to store. It is one boolean and the
            caller always knows it: it is `records is not None` in
            `reg.graph.build`, and it is exactly `meta[attestation_records]`.

    Raises:
        StoreError: the page size did not take. SQLite fixes it at file creation
            and *ignores* a `PRAGMA` that arrives late rather than failing, so
            the value is read back — an artifact silently written at the default
            would still be correct, but the measurement in `PAGE_SIZE` would be
            about a file nobody produced.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Before the first table: the page size is a property of the file header and
    # is fixed by the first page written.
    conn.execute(f"PRAGMA page_size = {int(PAGE_SIZE)}")
    conn.executescript(SCHEMA)
    if record_tables:
        conn.executescript(RECORD_SCHEMA)

    actual = int(conn.execute("PRAGMA page_size").fetchone()[0])
    if actual != int(PAGE_SIZE):
        conn.close()
        raise StoreError(
            f"{path} was created with a page size of {actual} B, not the "
            f"{int(PAGE_SIZE)} B reg.store.PAGE_SIZE asks for. SQLite fixes the "
            "page size at file creation and ignores a PRAGMA that arrives after "
            "the first page, so this means something wrote to the file before "
            "the schema did."
        )

    put_meta(conn, META_SCHEMA_VERSION, str(SCHEMA_VERSION))
    conn.commit()
    return conn


def has_record_tables(conn: sqlite3.Connection) -> bool:
    """Whether this artifact holds the two record tables at all (issue #54).

    **Not the same question as "did this run produce records".** A build handed
    no record stream does not create the tables, and one handed an empty stream
    creates them and stores nothing in them; `meta[attestation_records]` is what
    separates those two facts, and it is what every reader consults first. This
    is the narrower, purely structural question, and it exists so that a reader
    which does reach a record table can say what is missing rather than let
    `no such table: declaration` out of SQLite.

    Raises:
        StoreError: one table is present and the other is not. That is neither
            state, so it is a could-not-evaluate: every verdict in a file with no
            `declaration` table names a declaration nobody can look up, and a
            walk over half a record layer would report a shorter chain with no
            break in it.
    """
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
        f"({', '.join(repr(name) for name in sorted(RECORD_TABLE_NAMES))})"
    ).fetchall()
    present = {str(row["name"]) for row in rows}
    if present == RECORD_TABLE_NAMES:
        return True
    if not present:
        return False
    raise StoreError(
        f"this artifact holds {sorted(present)} but not "
        f"{sorted(RECORD_TABLE_NAMES - present)}. The record layer is both "
        "tables or neither: a verdict whose declaration table is gone names a "
        "record nobody can look up, and a chain walked over half a layer comes "
        "back shorter with no break in it."
    )


def _require_record_tables(conn: sqlite3.Connection, doing: str) -> None:
    """Refuse `doing` on an artifact created without the record tables."""
    if has_record_tables(conn):
        return
    raise StoreError(
        f"this artifact has no declaration and verdict tables, so {doing} is a "
        "could-not-evaluate rather than an empty result. It was created with "
        "`create(..., record_tables=False)` — the build was handed no record "
        "stream — and meta[attestation_records] says so. That is a different "
        "fact from a run that produced no records, and an empty answer here "
        "would be indistinguishable from one."
    )


def node_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Rows per node kind, every kind in `NODE_TABLES` present.

    A kind whose table this artifact does not create counts **0**, and that is
    the honest number: it is the count of rows written, and no row was written.
    The fact this does *not* carry — whether the build was handed a record
    stream at all — is not carried by a row count in either version of the
    schema, because an empty table counts zero too. It lives in
    `meta[attestation_records]`, and `reg.chain.verify_chain` and `reg.query`'s
    attestation queries read it there before they read a row.

    Every key is present even at zero, for the same reason `BuildResult.edges`
    keeps all four edge types: a missing key is indistinguishable from a
    genuine zero, and a summary should not have to be read alongside the
    argument list of the build that produced it.
    """
    has_records = has_record_tables(conn)
    counts: dict[str, int] = {}
    for kind, (table, _) in NODE_TABLES.items():
        if kind in RECORD_KINDS and not has_records:
            counts[kind] = 0
            continue
        counts[kind] = int(
            conn.execute(
                f"SELECT count(*) AS n FROM {table}"  # noqa: S608
            ).fetchone()["n"]
        )
    return counts


def connect(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open an existing artifact read-write. Refuses a file that is not one.

    "Not one" means: no `meta` table, or a `schema_version` this build does not
    understand. Both are could-not-evaluate — reading a v2 artifact with v1's
    column meanings returns numbers, and they are the wrong numbers.
    """
    path = Path(path)
    if not path.exists():
        raise StoreError(f"{path}: no such file. Nothing was created.")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        version = get_meta(conn, META_SCHEMA_VERSION)
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise StoreError(
            f"{path} is not a reg evidence graph: {exc}."
        ) from exc
    if version is None:
        conn.close()
        raise StoreError(
            f"{path} has no {META_SCHEMA_VERSION} in its meta table, so it does "
            "not say which schema it was written against. Refusing to guess."
        )
    if version != str(SCHEMA_VERSION):
        conn.close()
        raise StoreError(
            f"{path} was written against schema version {version}; this build "
            f"understands version {SCHEMA_VERSION}. The column meanings may have "
            "changed, and a query against the wrong ones returns answers rather "
            f"than errors. {_schema_change_summary(version)}"
        )
    return conn


def _schema_change_summary(version: str) -> str:
    """What changed between the file's version and this build's, named.

    The refusal above says a reader cannot read the file. This says **what about
    it** they would have got wrong, which is the half that tells them whether
    anything they have can read it and what to go and look at.

    Three-valued, like everything else that gates: a version this build cannot
    place — not an integer, or one from a future build whose changes are not in
    `SCHEMA_CHANGES` — is a could-not-evaluate and says so, rather than
    describing a span it cannot see the ends of.
    """
    try:
        found = int(version)
    except (TypeError, ValueError):
        return (
            f"This build cannot say what changed: {version!r} is not a version "
            "number it can place against SCHEMA_CHANGES."
        )
    span = [v for v in sorted(SCHEMA_CHANGES) if min(found, SCHEMA_VERSION) < v
            <= max(found, SCHEMA_VERSION)]
    if not span:
        return (
            f"This build cannot say what changed between {found} and "
            f"{SCHEMA_VERSION}: SCHEMA_CHANGES names no version in that span, "
            "so the file was written by a build newer than this one."
        )
    direction = "since" if found < SCHEMA_VERSION else "after"
    changes = "; ".join(f"v{v}: {SCHEMA_CHANGES[v]}" for v in span)
    return f"What changed {direction} v{found} — {changes}."


# --------------------------------------------------------------------------
# Geometry codec
# --------------------------------------------------------------------------


def to_wkb(geometry: BaseGeometry) -> bytes:
    """A geometry as a WKB blob. Refuses empty and invalid input.

    An empty geometry stored as an entity boundary reads downstream as "nothing
    was there", and an invalid one has an area that is not the area of any
    region. Neither is a small mistake with a loud symptom; both are silent.
    """
    if not isinstance(geometry, BaseGeometry):
        raise StoreError(
            f"to_wkb takes a shapely geometry, got {type(geometry).__name__}."
        )
    if geometry.is_empty:
        raise StoreError(
            "refusing to store an empty geometry. Read back it is a region of no "
            "extent, which clears every intersection test that meets it."
        )
    if not geometry.is_valid:
        raise StoreError(
            f"refusing to store an invalid geometry: "
            f"{shapely.is_valid_reason(geometry)}."
        )
    return shapely.to_wkb(geometry)


def from_wkb(blob: bytes) -> BaseGeometry:
    """A WKB blob back to a shapely geometry. The exact inverse of `to_wkb`."""
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise StoreError(
            f"from_wkb takes a WKB blob, got {type(blob).__name__}. A NULL "
            "geometry column is an entity whose boundary was never stored, "
            "which is a could-not-evaluate and not an empty polygon."
        )
    return shapely.from_wkb(bytes(blob))


# --------------------------------------------------------------------------
# Envelope hash codec (issue #55)
#
# The digest on the wire is `reg.envelope.envelope_hash`'s lowercase hex and does
# not change; the column holds its 32 raw bytes. Both directions are checked,
# because the failure a silent codec produces is not a crash — it is an envelope
# whose hash matches nothing, which reads as a material change on every frame and
# quietly turns the retention rule off.
# --------------------------------------------------------------------------


def to_hash(digest: str) -> bytes:
    """A hex envelope digest as the raw bytes the column stores.

    Refuses anything that is not exactly `HASH_BYTES` bytes of **lowercase** hex.
    Lowercase because `from_hash` renders lowercase, and a codec whose round trip
    changes the string would make two spellings of one digest compare unequal —
    which is the same wrong answer as a truncated hash, arrived at differently.
    """
    if not isinstance(digest, str):
        raise StoreError(
            f"an envelope hash must be the hex digest str "
            f"reg.envelope.envelope_hash returns, got "
            f"{type(digest).__name__}."
        )
    try:
        raw = bytes.fromhex(digest)
    except ValueError:
        raise StoreError(
            f"envelope hash {digest!r} is not hex. It is stored as its raw bytes "
            "and read back as hex, so a value that is not a digest could not "
            "survive the round trip."
        ) from None
    if len(raw) != HASH_BYTES:
        raise StoreError(
            f"envelope hash {digest!r} is {len(raw)} bytes; "
            f"reg.envelope.envelope_hash is a SHA-256, which is {HASH_BYTES}. A "
            "narrower digest compares unequal to every full one, so every frame "
            "would read as a material envelope change."
        )
    if raw.hex() != digest:
        raise StoreError(
            f"envelope hash {digest!r} is not lowercase hex. It reads back "
            f"as {raw.hex()!r}, and two spellings of one digest that compare "
            "unequal is the fault this codec exists to prevent."
        )
    return raw


def from_hash(blob: bytes) -> str:
    """Raw digest bytes back to hex. The exact inverse of `to_hash`."""
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise StoreError(
            f"from_hash takes the raw digest bytes, got {type(blob).__name__}. A "
            "NULL envelope_hash is an envelope whose digest was never stored, "
            "which is a could-not-evaluate and not an empty string."
        )
    raw = bytes(blob)
    if len(raw) != HASH_BYTES:
        raise StoreError(
            f"an envelope_hash column holds {len(raw)} bytes, not {HASH_BYTES}. "
            "The schema CHECKs the width, so this row was not written by this "
            "module."
        )
    return raw.hex()


# --------------------------------------------------------------------------
# meta
# --------------------------------------------------------------------------


def put_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Record one provenance fact. Values are text; interpreting them is the
    reader's decision, exactly as in `reg.sim.parse_provenance`.

    Re-writing a key with a *different* value is refused. Provenance describes
    one run; a key that changed during the build means two runs are being
    conflated, and the last writer would win silently.
    """
    if not isinstance(key, str) or not key:
        raise StoreError(f"meta key must be a non-empty str, got {key!r}.")
    if not isinstance(value, str):
        raise StoreError(
            f"meta[{key!r}] must be a str, got {type(value).__name__}. Values are "
            "text so that reading them back is never a silent coercion."
        )
    existing = get_meta(conn, key)
    if existing is not None and existing != value:
        raise StoreError(
            f"meta[{key!r}] is already {existing!r} and would be overwritten with "
            f"{value!r}. One artifact describes one run."
        )
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """One provenance fact, or `None` if the artifact does not state it.

    `None` means the artifact is silent, which is a could-not-evaluate for every
    question about that fact. It never means "the usual value was used".
    """
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def all_meta(conn: sqlite3.Connection) -> dict[str, str]:
    """The whole provenance block, in key order."""
    rows = conn.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
    return {str(r["key"]): str(r["value"]) for r in rows}


def _geos_version_text() -> str:
    """`shapely.geos_version` as `major.minor.patch`.

    The tuple rather than `shapely.geos_capi_version_string`: the CAPI string
    names the ABI, and two GEOS releases whose arithmetic differs can share one.
    A tuple that is not three integers is a refusal — a GEOS this build cannot
    name is exactly the thing the key exists to record.
    """
    version = shapely.geos_version
    if not isinstance(version, tuple) or len(version) != 3:
        raise StoreError(
            f"shapely.geos_version is {version!r}, not a three-part version "
            "tuple. This build cannot say which GEOS computed its geometry."
        )
    try:
        return ".".join(str(int(part)) for part in version)
    except (TypeError, ValueError) as exc:
        raise StoreError(
            f"shapely.geos_version is {version!r}, whose parts are not "
            "integers. This build cannot say which GEOS computed its geometry."
        ) from exc


def build_environment() -> dict[str, str]:
    """The environment this interpreter would compute geometry in (issue #200).

    A **buildinfo** in the Reproducible Builds sense — see `ENVIRONMENT_KEYS`
    above for what is in it, why each key is there, why the placement in `meta`
    is a stated deviation from that practice, and which omission is load-bearing.

    Every value is read from the **running interpreter**. Nothing here is a
    parameter and nothing may become one: an environment passed in is an
    environment a caller can state wrongly, and the whole use of the record is
    to be compared against the environment of whoever recomputes. It is also why
    there is no default anywhere below.

    This function does not decide anything. It records. Deciding is
    `reg.graph.envelope_at`'s, which since issue #201 refuses to recompute a
    discarded polygon where the running environment differs from the one written
    here on `reg.graph.RECOMPUTE_ENVIRONMENT_KEYS` — four of the six below, and
    that function is where the difference between the two lists is argued.

    Returns:
        `ENVIRONMENT_KEYS` to their values, in that order, every key present.

    Raises:
        StoreError: a probe raised, or reported something that is not a non-empty
            string. That is a could-not-evaluate and it is loud: an artifact
            recording five of six keys, or one recording an empty string for the
            machine, would read as an environment somebody stated. The failure
            names the key and the expression that could not answer, because
            "the environment could not be read" does not tell whoever sees it
            what to go and look at.
    """
    probes: tuple[tuple[str, str, Callable[[], object]], ...] = (
        (META_ENV_PYTHON, "platform.python_version()", platform.python_version),
        (META_ENV_NUMPY, "numpy.__version__", lambda: numpy.__version__),
        (META_ENV_SHAPELY, "shapely.__version__", lambda: shapely.__version__),
        (META_ENV_GEOS, "shapely.geos_version", _geos_version_text),
        (META_ENV_PLATFORM_SYSTEM, "platform.system()", platform.system),
        (META_ENV_PLATFORM_MACHINE, "platform.machine()", platform.machine),
    )
    recorded: dict[str, str] = {}
    for key, expression, probe in probes:
        try:
            value = probe()
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(
                f"meta[{key!r}] cannot be written: {expression} raised "
                f"{type(exc).__name__}: {exc}. The environment a geometry was "
                "computed in is not a thing to guess at."
            ) from exc
        if not isinstance(value, str) or not value.strip():
            raise StoreError(
                f"meta[{key!r}] cannot be written: {expression} reported "
                f"{value!r}. This interpreter cannot say what it computes "
                "geometry with, which is a could-not-evaluate — and an artifact "
                "stating no environment must say so by having no environment "
                "block at all, not by carrying an empty one that reads as a "
                "fact somebody recorded."
            )
        recorded[key] = value
    return recorded


# --------------------------------------------------------------------------
# Nodes
#
# Every insert is "insert, or verify what is already there is identical". The
# graph builder derives node ids from a hash of the node's contents, so a
# collision between two different nodes would merge two histories into an answer
# about neither -- the same failure `reg.world` refuses duplicate entity ids for.
# --------------------------------------------------------------------------


def node_key(conn: sqlite3.Connection, node_id: str) -> int | None:
    """The INTEGER surrogate for a readable node id, or `None` if unknown.

    The one place an identifier becomes a key. `None` is "this artifact has never
    held a node with that id" — it is not zero, and callers must not treat it as
    one: `0` is a perfectly good `node_key` in SQLite and an id that silently
    resolved to it would attach an edge to whichever node happened to be first.
    """
    row = conn.execute(
        "SELECT node_key FROM node WHERE node_id = ?", (str(node_id),)
    ).fetchone()
    return None if row is None else int(row["node_key"])


def node_id_of(conn: sqlite3.Connection, key: int) -> str | None:
    """The readable id for a surrogate key, or `None` if the artifact has none.

    The inverse of `node_key`, and the reason `node` outlives the rows it names:
    a record deleted from `declaration` still has an identity here, so the
    `FOLLOWS` edge left pointing at it can say what is missing.
    """
    row = conn.execute(
        "SELECT node_id FROM node WHERE node_key = ?", (int(key),)
    ).fetchone()
    return None if row is None else str(row["node_id"])


def _intern(conn: sqlite3.Connection, node_id: str) -> int:
    """The surrogate for `node_id`, allocating one on first sight.

    Allocation is `rowid` order, so it is a function of the insertion order and
    of nothing else — the determinism the module header promises survives it.
    """
    existing = node_key(conn, node_id)
    if existing is not None:
        return existing
    cursor = conn.execute("INSERT INTO node (node_id) VALUES (?)", (str(node_id),))
    key = cursor.lastrowid
    if key is None:  # pragma: no cover - sqlite3 always sets it on INSERT
        raise StoreError(f"sqlite did not return a node_key for {node_id!r}.")
    return int(key)


def _kind_holding(conn: sqlite3.Connection, key: int) -> str | None:
    """Which node kind's table holds the payload row for `key`, if any.

    Walked only when an id is already interned and the kind being written has no
    row for it — which is either a cross-kind id collision or a node whose
    payload was removed. Both are rare and both need naming, so the six probes
    buy an error message rather than being paid on the common path.
    """
    for kind, (table, key_column) in NODE_TABLES.items():
        if kind in RECORD_KINDS and not has_record_tables(conn):
            continue
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE {key_column} = ?",  # noqa: S608
            (int(key),),
        ).fetchone()
        if row is not None:
            return kind
    return None


def _insert_node(
    conn: sqlite3.Connection,
    kind: str,
    node_id: str,
    row: dict[str, object],
) -> str:
    """Intern `node_id`, write `row` under its surrogate, and return the id.

    Still "insert, or verify what is already there is identical", and still keyed
    on the readable id — the surrogate is how the row is *found*, not what makes
    two writes the same node.
    """
    table, key_column = NODE_TABLES[kind]
    node_id = str(node_id)
    key = _intern(conn, node_id)

    existing = conn.execute(
        f"SELECT * FROM {table} WHERE {key_column} = ?", (int(key),)  # noqa: S608
    ).fetchone()
    if existing is not None:
        clash = {
            column: (existing[column], value)
            for column, value in row.items()
            if existing[column] != value
        }
        if clash:
            raise StoreError(
                f"{table} already holds {node_id!r} with different contents: "
                f"{clash}. Node ids are content-derived, so this is "
                "either a hash collision or two different things given one id; "
                "either way the two histories would merge into an answer about "
                "neither."
            )
        return node_id

    held_by = _kind_holding(conn, key)
    if held_by is not None:
        raise StoreError(
            f"{node_id!r} is already the id of a {held_by} in this artifact, and "
            f"a {kind} cannot share it. Node ids are unique across every kind "
            "(reg.store.SCHEMA, the node table): an edge endpoint resolves an id "
            "to one key, and two different things behind one key would merge two "
            "histories into an answer about neither."
        )

    columns = ", ".join((key_column, *row))
    placeholders = ", ".join("?" for _ in range(len(row) + 1))
    conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",  # noqa: S608
        (int(key), *row.values()),
    )
    return node_id


def drop_nodes(conn: sqlite3.Connection, kind: str) -> None:
    """Delete every node of `kind`, identity included (issue #55).

    For `reg.bench`, which builds coarser *views* of an artifact by emptying the
    tables a level does not hold. The identity row has to go with the payload
    row: a view that kept `node` rows for envelopes it no longer holds would
    measure as larger than the view actually is, and the whole point of the
    resolution curve is that each point costs what that level costs.

    This is the one place identity is deliberately removed, and it is not the
    same operation `reg.chain.tamper --delete` performs: that one removes a
    record and *leaves* its identity, because a dangling link naming nothing is
    a tamper nobody can read.
    """
    if kind not in NODE_TABLES:
        raise StoreError(
            f"{kind!r} is not a node kind. Known kinds: {sorted(NODE_TABLES)}."
        )
    table, key_column = NODE_TABLES[kind]
    conn.execute(
        f"DELETE FROM node WHERE node_key IN (SELECT {key_column} FROM {table})"  # noqa: S608
    )
    conn.execute(f"DELETE FROM {table}")  # noqa: S608


def insert_envelope(
    conn: sqlite3.Connection,
    envelope_id: str,
    *,
    envelope_hash: str,
    area: float,
    geometry: BaseGeometry | None,
    config_id: str | None,
    horizon: float | None,
    source: str,
    outer_area: float | None,
    outer_radius: float | None,
) -> str:
    """An envelope the artifact retains. Idempotent on `envelope_id`.

    `area` is expected already quantized (`reg.tolerances.quantize_area`) and the
    geometry already simplified — this module stores what it is given and does
    not quantize on the caller's behalf, because a store that silently rounds
    makes the tolerance in force a property of the writer rather than of the
    contract.

    `geometry` and `config_id` are both required arguments and either may be
    `None`, but not both. Neither has a default: "store the polygon" and
    "recompute it from this configuration" are different retention decisions with
    different costs, and a caller that did not state which one it made would have
    the schema make it silently. Passing both is normal — the geometry is what a
    reader gets, the config is what makes the *next* build able to check it.

    `horizon` is `None` for exactly one source: `clamped`. The `Verdict` record
    states no horizon for the bound it applied, so there is none to store, and
    the schema's `CHECK` ties the two together in both directions — a clamped
    bound carrying a horizon would be reporting a validity window nobody wrote
    down, and a computed or declared envelope missing one would be silently
    dropping the interval its region is a claim about.

    `outer_area` and `outer_radius` are the other side of the bracket (issue
    #82): the area and radius of the horizon-limited **outer** reachable set for
    the same frame, against an `area` column that holds an under-approximation.
    Both are required arguments and both are `None` for exactly one thing — an
    envelope that is not a `computed` one. A declared region is the policy's
    claim and a clamped bound is what a verdict applied; neither is a reachable
    set, so neither has an outer approximation, and a number invented for them
    here would be indistinguishable downstream from one something computed.

    An `outer_radius` requires a `config_id` beside it (issue #166): the radius is
    measured from the base, and the configuration is the only thing in the file
    that names which frame the base was in — its own `base_pose`, or
    `meta[base_frame]` for a configuration that states none. A radius about an
    unstated centre is not a measurement of anything.

    Re-inserting an id whose row already exists fills in a geometry or a
    `config_id` the first insert left `NULL`, and refuses a *different* value for
    any scalar column. A second `config_id` for a row that already has one is
    kept out rather than refused: the id is derived from the envelope hash, so
    two configurations reaching it produce the same polygon to
    `reg.envelope.HASH_COORD_PRECISION`, and recomputation from either yields it.
    """
    if source not in ENVELOPE_SOURCES:
        raise StoreError(
            f"envelope source {source!r} is not in the vocabulary "
            f"{ENVELOPE_SOURCES}. docs/plan.md Phase 5 fixes it; an unrecognised "
            "source would make a clamped bound indistinguishable from a declared "
            "one."
        )
    if geometry is None and config_id is None:
        raise StoreError(
            f"envelope {envelope_id!r} would be stored with neither geometry nor "
            "a config_id. Then it holds no region and names nothing to recompute "
            "one from, so every query for the envelope in force at that time "
            "answers 'there was none' — which is what a frame with no envelope "
            "at all looks like."
        )
    if (outer_area is None) != (outer_radius is None):
        raise StoreError(
            f"envelope {envelope_id!r} has outer_area={outer_area!r} and "
            f"outer_radius={outer_radius!r}. They are two projections of one "
            "region and are written together or not at all; one without the "
            "other is half a bracket, which reads as a bracket."
        )
    if (outer_area is None) == (source == "computed"):
        raise StoreError(
            f"envelope {envelope_id!r} has source={source!r} and "
            f"outer_area={outer_area!r}. The outer reachable set belongs to a "
            "computed envelope and to nothing else: a declared region is the "
            "policy's claim and a clamped bound is what a verdict applied, and "
            "neither is a set the robot can reach. A computed envelope missing "
            "it would be an under-approximation with nothing bracketing it, "
            "which is the state issue #82 is about."
        )
    if outer_radius is not None and config_id is None:
        raise StoreError(
            f"envelope {envelope_id!r} would store outer_radius={outer_radius!r} "
            "with no config_id. The radius is measured from the base, and the "
            "configuration is what names the frame the base was in — its own "
            f"base_pose, or meta[{META_BASE_FRAME!r}] for a configuration that "
            "states none. Without it this is a length in metres about a point "
            "nobody can name, which still compares against every declared "
            "region and every bound as though it meant something (issue #166)."
        )
    if (horizon is None) != (source == "clamped"):
        raise StoreError(
            f"envelope {envelope_id!r} has source={source!r} and "
            f"horizon={horizon!r}. A clamped bound is the region applied to one "
            "commanded action and the Verdict record states no horizon for it, so "
            "it is stored as NULL; a computed or a declared envelope has one and "
            "storing it without would drop the interval its region is a claim "
            "about. Neither direction is a value to invent here."
        )

    envelope_id = str(envelope_id)
    digest = to_hash(envelope_hash)
    # Keyed by the *hex*, because `envelope_row` renders the column back to hex
    # and this dict is compared against a row from it. The raw bytes go in at
    # the insert below and nowhere else.
    scalars = {
        "envelope_hash": digest.hex(),
        "area": float(area),
        "horizon": None if horizon is None else float(horizon),
        "source": str(source),
        "outer_area": None if outer_area is None else float(outer_area),
        "outer_radius": None if outer_radius is None else float(outer_radius),
    }
    # The configuration has to be in the artifact, because what is stored is its
    # surrogate. That is stricter than the old text column, and in the same
    # direction as `insert_verdict`: an envelope naming a `robot_config` nobody
    # holds is a row `reg.graph.envelope_at` can only answer "not in this
    # artifact" for, and a refusal at the write says so where somebody can fix
    # it.
    config_key = (
        None
        if config_id is None
        else _require_node(conn, "RobotConfig", str(config_id))
    )

    existing = envelope_row(conn, envelope_id)
    if existing is None:
        _insert_node(
            conn,
            "Envelope",
            envelope_id,
            {
                **scalars,
                "envelope_hash": digest,
                "geometry_wkb": None if geometry is None else to_wkb(geometry),
                "config_key": config_key,
            },
        )
        return envelope_id

    key = existing["envelope_key"]
    clash = {
        column: (existing[column], value)
        for column, value in scalars.items()
        if existing[column] != value
    }
    if clash:
        raise StoreError(
            f"envelope {envelope_id!r} already exists with different "
            f"contents: {clash}. Node ids are content-derived, so this is either "
            "a hash collision or two different things given one id; either way "
            "the two histories would merge into an answer about neither."
        )
    if config_key is not None and existing["config_key"] is None:
        conn.execute(
            "UPDATE envelope SET config_key = ? WHERE envelope_key = ?",
            (config_key, key),
        )
    if geometry is not None:
        attach_envelope_geometry(conn, envelope_id, geometry)
    return envelope_id


def attach_envelope_geometry(
    conn: sqlite3.Connection, envelope_id: str, geometry: BaseGeometry
) -> None:
    """Store the polygon on an envelope row that was written without one.

    The retention rule (`reg.graph.GEOMETRY_RETENTION`) marks a frame as evidence
    for a reason that is only known one frame later — an interval ends at the
    last instant it held — so the row is written when the envelope changes and
    the geometry is attached when the run turns out to need it. Doing it the
    other way round would mean holding the whole stream in memory to decide.

    Refuses an unknown id, and refuses to *replace* a geometry that is already
    stored. Two different polygons under one content-derived id is a collision;
    overwriting would leave the artifact holding whichever one was written last,
    with nothing to say the other existed.
    """
    envelope_id = str(envelope_id)
    row = envelope_row(conn, envelope_id)
    if row is None:
        raise StoreError(
            f"no envelope with envelope_id={envelope_id!r} to attach geometry to. "
            "An envelope row is written when the envelope changes; attaching to "
            "an id that was never written means the geometry belongs to a frame "
            "the artifact has no record of."
        )
    blob = to_wkb(geometry)
    if row["geometry_wkb"] is not None:
        if bytes(row["geometry_wkb"]) != blob:
            raise StoreError(
                f"envelope {envelope_id!r} already stores a different geometry. "
                "The id is derived from the envelope hash, so two distinct "
                "polygons under it is a collision, not an update."
            )
        return
    conn.execute(
        "UPDATE envelope SET geometry_wkb = ? WHERE envelope_key = ?",
        (blob, row["envelope_key"]),
    )


#: `envelope`, with the two identifiers a reader speaks put back (issue #55):
#: `envelope_id` and `config_id` off `node`, and `envelope_hash` rendered back to
#: the lowercase hex `insert_envelope` was handed. The columns a caller sees are
#: the columns it saw before the surrogate keys arrived, plus the keys
#: themselves — the storage narrowed and the reader's view did not.
_ENVELOPE_SELECT = """
SELECT e.envelope_key              AS envelope_key,
       n.node_id                   AS envelope_id,
       lower(hex(e.envelope_hash)) AS envelope_hash,
       e.area                      AS area,
       e.geometry_wkb              AS geometry_wkb,
       e.config_key                AS config_key,
       c.node_id                   AS config_id,
       e.horizon                   AS horizon,
       e.source                    AS source,
       e.outer_area                AS outer_area,
       e.outer_radius              AS outer_radius,
       rc.base_pose                AS base_pose,
       rc.base_pose_source         AS base_pose_source
FROM envelope e
JOIN node n ON n.node_key = e.envelope_key
LEFT JOIN node c ON c.node_key = e.config_key
LEFT JOIN robot_config rc ON rc.config_key = e.config_key
"""


def envelope_row(
    conn: sqlite3.Connection, envelope_id: str
) -> sqlite3.Row | None:
    """One envelope row, or `None` if the artifact has no such envelope.

    `None` is a could-not-evaluate — the artifact holds no envelope under that
    id — and is never an empty region. Readers get the row rather than the
    geometry because `geometry_wkb` being `NULL` is a fact about *how the
    artifact was written*, and the decision of what to do about it belongs to
    `reg.graph.envelope_at`, which can recompute.
    """
    return conn.execute(
        f"{_ENVELOPE_SELECT} WHERE n.node_id = ?", (str(envelope_id),)
    ).fetchone()


def insert_entity(
    conn: sqlite3.Connection,
    entity_id: str,
    kind: str,
    *,
    geometry: BaseGeometry | None,
) -> str:
    """An entity in the entity set. `geometry=None` means it moves.

    WHY A MOVING ENTITY STORES NO GEOMETRY. docs/lossiness.md enumerates what is
    Retained, and an entity's absolute position per frame is not on the list: the
    supported question set asks for separations, overlaps, intersection intervals
    and set membership, all of which are edge attributes here. Storing one frame's
    disc as though it were the entity's boundary would answer "where was the
    human at t?" with a number that is right once and wrong everywhere else,
    which is worse than the refusal `NULL` produces. Discarded #8 covers it.

    "Absence of an entity from the graph is not evidence of its absence from the
    room" (Unanswerable #2) — an entity has to be *declared* into the entity set
    to leave any trace at all, which is what this call does.
    """
    return _insert_node(
        conn,
        "Entity",
        entity_id,
        {
            "kind": str(kind),
            "is_static": 1 if geometry is not None else 0,
            "geometry_wkb": None if geometry is None else to_wkb(geometry),
        },
    )


def insert_occurrence(
    conn: sqlite3.Connection,
    occurrence_id: str,
    *,
    seq: int,
    occurrence_type: str,
    reason: str,
    t: float,
    date: str,
    t_utc: str,
    entity_id: str | None,
    value: float | None,
    recorder_version: str,
) -> str:
    """One DSSAD-shaped occurrence. Every element required, none defaulted.

    `entity_id` and `value` are required *arguments* and either may be `None`
    where the type says so — `insert_envelope`'s discipline, for the same reason:
    "this event names no entity" and "I forgot to say which entity" must not be
    the same call.

    `layer` is never taken from the caller; it comes from `OCCURRENCE_SPECS`.

    Args:
        seq: emission order, unique within the artifact. It is what keeps two
            events inside one timestamp quantum two rows.
        reason: DSSAD's reason element, as prose. Non-empty: an occurrence whose
            reason is blank records that something happened and nothing about
            what, which is the row an assessor cannot use.
        t: the timestamp, **already rounded to the artifact's occurrence
            resolution by the caller**. This module stores what it is given and
            does not quantize on anyone's behalf, exactly as it does not round
            `area` — a store that silently coarsens makes the resolution in force
            a property of the writer rather than of the record.
        date: DSSAD's date element, `yyyy/mm/dd`. **Required, no default.** It
            is derived by the caller from the run's declared start
            (`reg.identity.RunIdentity.date`), never read off a clock here: an
            ambient date would be indistinguishable downstream from a declared
            one and would make the artifact non-reproducible.
        t_utc: the same instant absolutely, as `reg.identity.format_instant`
            writes it. **Required, no default**, and stored beside `t` rather
            than instead of it — the run-relative float is what every edge and
            every query in the artifact is expressed in, and dropping it would
            re-base the whole file on a datum only this column carries.
        recorder_version: the **recorder's** build — `reg`'s version plus the
            envelope-parameter digest (`reg.graph.recorder_version`). It is
            **not** DSSAD's `R157SWIN`, which names the system under
            investigation; that element is unimplemented here and the schema
            comment above says why. Non-empty for the same reason `reason` is:
            an occurrence nobody can attribute to a build of the recorder cannot
            be checked against the parameters in `meta`.

    Raises:
        StoreError: an unknown type, a blank reason, `date`, `t_utc` or
            `recorder_version`, an entity named by a type that has no subject
            (or missing from one that does), a value on a type that carries none
            (or missing from one that does), or an `entity_id` no `entity` row
            matches.
    """
    spec = OCCURRENCE_SPECS.get(occurrence_type)
    if spec is None:
        occurrence_layer(occurrence_type)  # raises with the full vocabulary
        raise AssertionError  # pragma: no cover - occurrence_layer always raises

    if not isinstance(reason, str) or not reason.strip():
        raise StoreError(
            f"a {occurrence_type} occurrence was written with reason={reason!r}. "
            "DSSAD records the reason for an occurrence alongside the flag; a "
            "blank one leaves a row saying an event happened and nothing about "
            "which condition produced it."
        )
    if not isinstance(recorder_version, str) or not recorder_version.strip():
        raise StoreError(
            f"a {occurrence_type} occurrence was written with "
            f"recorder_version={recorder_version!r}. That is the recorder's own "
            "build and envelope digest — not DSSAD's R157SWIN, which this "
            "artifact does not implement — and an occurrence carrying none "
            "cannot be checked against the envelope parameters in meta, so "
            "nothing downstream can tell which build's envelope produced it."
        )
    if not isinstance(date, str) or not _DATE_RE.fullmatch(date):
        raise StoreError(
            f"a {occurrence_type} occurrence was written with date={date!r}. "
            "That is DSSAD's date element and it is yyyy/mm/dd. Refusing rather "
            "than storing what was given: a date column half of whose rows are "
            "in another format cannot be compared, sorted or handed over, and "
            "nothing downstream would report it."
        )
    if not isinstance(t_utc, str) or not _INSTANT_RE.fullmatch(t_utc):
        raise StoreError(
            f"a {occurrence_type} occurrence was written with t_utc={t_utc!r}. "
            "An absolute timestamp here is UTC with six fractional digits and a "
            "trailing Z (reg.identity.format_instant) — a local time, or one "
            "with no offset, is an instant only for a reader who already knows "
            "which zone the operator was in."
        )

    entity_key: int | None = None
    if spec.subject == "entity":
        if entity_id is None:
            raise StoreError(
                f"a {occurrence_type} occurrence names an entity and none was "
                "supplied. It is an event *about* something, and one that names "
                "nothing says something happened to somebody."
            )
        entity_key = _require_node(conn, "Entity", str(entity_id))
    elif entity_id is not None:
        raise StoreError(
            f"a {occurrence_type} occurrence is about the run and names no "
            f"entity, but entity_id={entity_id!r} was supplied. Recording it "
            "would put an event in that entity's history that is not about it."
        )

    if spec.metric is not None and value is None:
        raise StoreError(
            f"a {occurrence_type} occurrence carries {spec.metric} and none was "
            "supplied. Writing it as NULL would answer every question about the "
            "quantity with 'no', not with 'unknown'."
        )
    if spec.metric is None and value is not None:
        raise StoreError(
            f"a {occurrence_type} occurrence carries no value, but {value!r} was "
            "supplied. A number in a column nobody can name the units of is not "
            "evidence."
        )

    return _insert_node(
        conn,
        "Occurrence",
        occurrence_id,
        {
            "seq": int(seq),
            "type": str(occurrence_type),
            "layer": spec.layer,
            "reason": str(reason),
            "t": float(t),
            "date": str(date),
            "t_utc": str(t_utc),
            "entity_key": entity_key,
            "value": None if value is None else float(value),
            "recorder_version": str(recorder_version),
        },
    )


#: `occurrence`, with `occurrence_id` and `entity_id` put back off `node`. The
#: entity join is a LEFT one: an occurrence about the run names no entity, and a
#: row that vanished because its subject could not be resolved would be an event
#: this artifact holds and no reader can see.
_OCCURRENCE_SELECT = """
SELECT o.*,
       n.node_id AS occurrence_id,
       en.node_id AS entity_id
FROM occurrence o
JOIN node n ON n.node_key = o.occurrence_key
LEFT JOIN node en ON en.node_key = o.entity_key
"""


def read_occurrences(
    conn: sqlite3.Connection,
    *,
    occurrence_type: str | None = None,
    entity_id: str | None = None,
    layer: Literal["A", "B"] | None = None,
) -> list[sqlite3.Row]:
    """Occurrences matching the filters, ordered by `(t, seq)`.

    `t` alone is not a total order at this layer and is much further from being
    one than at the edge layer: the whole point of the occurrence timestamp is
    that it is coarse, so several events routinely share one. `seq` breaks the
    tie by emission order so two reads of one artifact agree — without implying
    that the tie-break carries timing information the record does not have.
    """
    if occurrence_type is not None:
        occurrence_layer(occurrence_type)  # refuses an unknown type, not []
    clauses: list[str] = []
    params: list[object] = []
    if entity_id is not None:
        key = node_key(conn, str(entity_id))
        if key is None:
            # An id this artifact has never held matches no occurrence, which is
            # the answer it gave before the surrogate keys arrived. Whether an
            # empty list is evidence is the caller's question — `reg.query`
            # refuses an undeclared entity before it ever reaches this.
            return []
        clauses.append("o.entity_key = ?")
        params.append(key)
    for column, value in (("o.type", occurrence_type), ("o.layer", layer)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return list(
        conn.execute(
            f"{_OCCURRENCE_SELECT}{where} ORDER BY o.t, o.seq",  # noqa: S608
            params,
        ).fetchall()
    )


# --------------------------------------------------------------------------
# The attestation records (issue #45).
#
# Two functions in and two out, and the only thing that happens in between is a
# rename. Everything that could make a stored record differ from the record that
# was signed — a re-serialized polygon, a reformatted float, a recomputed MAC —
# is a thing this module deliberately does not do. See the module header.
# --------------------------------------------------------------------------


def _record_types() -> tuple[type, type]:
    """`(Declaration, Verdict)`, imported here and not at module scope.

    `reg.declare` reaches `reg.stream` through `reg.chain` — the canonical
    serialization commits floats at the raw stream's own precision, deliberately
    (`reg/chain.py`). `reg.query` imports *this* module, and Claim 2's "answered
    from the graph alone" is held as a property of the import graph rather than
    as a promise: `tests/test_query.py` fails if `import reg.query` puts the
    stream reader in `sys.modules` by any route, including this one.

    So the record classes are imported where they are used. It is the same move
    `reg.graph._resolve_world` makes for the same kind of reason, and it costs
    one dict lookup per call.
    """
    from reg.declare import Declaration
    from reg.enforce import Verdict

    return Declaration, Verdict


def insert_declaration(conn: sqlite3.Connection, declaration: object) -> str:
    """Store one `Declaration` verbatim. Idempotent on `declaration_id`.

    **This does not check the MAC, and it cannot.** The store holds no keys. A
    declaration whose MAC does not match is stored exactly as it arrived and
    comes back out of `read_declarations` still failing verification under the
    key that signed the original — persistence is not an opportunity to launder
    a record, and a store able to recompute a MAC is a store able to repair a
    chain nobody should be able to repair.

    Raises:
        StoreError: the argument is not a `Declaration`, or an id already in the
            artifact carries different contents. The second is either a hash
            collision or two records given one id, and either way the two
            histories would merge into an answer about neither.
    """
    _require_record_tables(conn, "storing a declaration")
    declaration_type, _ = _record_types()
    if not isinstance(declaration, declaration_type):
        raise StoreError(
            f"insert_declaration takes a reg.declare.Declaration, got "
            f"{type(declaration).__name__}. The record is what is stored; an "
            "object that resembles one has not been through the validation that "
            "makes it a record."
        )
    return _insert_node(
        conn,
        "Declaration",
        declaration.declaration_id,
        {
            "seq": int(declaration.seq),
            "t_issued": float(declaration.t_issued),
            "horizon": float(declaration.horizon),
            "action_class": declaration.action_class,
            "declared_envelope_wkb": declaration.declared_envelope,
            "prev_hash": declaration.prev_hash,
            "mac": declaration.mac,
        },
    )


def insert_verdict(conn: sqlite3.Connection, verdict: object) -> str:
    """Store one `Verdict` verbatim. Idempotent on `verdict_id`.

    A verdict naming a declaration is refused unless that declaration is already
    in the artifact: an `ADJUDICATED` edge to a record nobody holds is an audit
    answer nobody can check, and the join that would read it returns nothing —
    which is indistinguishable from "this declaration was never adjudicated".
    Store the declarations of a run before its verdicts.

    A verdict naming *no* declaration is stored as it stands. `None` there is a
    finding rather than a gap: it is what `no_declaration` and `watchdog_expiry`
    look like in the record.

    Like `insert_declaration`, this checks no MAC and recomputes no hash.

    Raises:
        StoreError: the argument is not a `Verdict`, it names a declaration this
            artifact does not hold, or an id already present carries different
            contents.
    """
    _require_record_tables(conn, "storing a verdict")
    _, verdict_type = _record_types()
    if not isinstance(verdict, verdict_type):
        raise StoreError(
            f"insert_verdict takes a reg.enforce.Verdict, got "
            f"{type(verdict).__name__}."
        )
    declaration_key = (
        None
        if verdict.declaration_id is None
        else _require_node(conn, "Declaration", verdict.declaration_id)
    )
    return _insert_node(
        conn,
        "Verdict",
        verdict.verdict_id,
        {
            "declaration_key": declaration_key,
            "seq": int(verdict.seq),
            "t": float(verdict.t),
            "outcome": verdict.outcome,
            "fault": verdict.fault,
            "clamped_envelope_wkb": verdict.clamped_envelope,
            "prev_hash": verdict.prev_hash,
            "mac": verdict.mac,
        },
    )


def _record_bytes(value: object, column: str, record_id: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise StoreError(
            f"{column} of record {record_id!r} is a {type(value).__name__}, not a "
            "WKB blob. The record's geometry is bytes and is stored as the bytes "
            "it was signed with; anything else here means the row was not written "
            "by this module."
        )
    return bytes(value)


def read_declarations(conn: sqlite3.Connection) -> list:
    """Every stored declaration, reconstructed, ordered by `(seq, declaration_id)`.

    `seq` is the chain's own order and is what the record commits to; the id
    breaks a tie, because a replayed `seq` is a fault this artifact is required
    to be able to hold rather than a state it may refuse. The order is total, so
    two reads of one artifact agree.

    What comes back is the record as it was signed, so
    `reg.declare.verify_declaration` gives the same answer it gave before the
    record was written. That round trip is the whole reason the columns are the
    dataclass fields.

    Raises:
        StoreError: a row cannot be reconstructed — a malformed MAC, an
            unreadable envelope, a value outside a vocabulary. Each is a
            could-not-evaluate about a record this artifact holds, and it is
            raised rather than skipped: a reader that silently dropped it would
            report a shorter chain with no break in it.
    """
    _require_record_tables(conn, "reading the declarations back")
    declaration_type, _ = _record_types()
    rows = conn.execute(
        """
        SELECT d.*, n.node_id AS declaration_id
        FROM declaration d
        JOIN node n ON n.node_key = d.declaration_key
        ORDER BY d.seq, n.node_id
        """
    ).fetchall()
    out: list = []
    for row in rows:
        record_id = str(row["declaration_id"])
        try:
            out.append(
                declaration_type(
                    declaration_id=record_id,
                    seq=int(row["seq"]),
                    t_issued=float(row["t_issued"]),
                    horizon=float(row["horizon"]),
                    action_class=str(row["action_class"]),
                    declared_envelope=_record_bytes(
                        row["declared_envelope_wkb"],
                        "declared_envelope_wkb",
                        record_id,
                    ),
                    prev_hash=str(row["prev_hash"]),
                    mac=str(row["mac"]),
                )
            )
        except ValueError as exc:
            raise StoreError(
                f"declaration row {record_id!r} cannot be reconstructed as the "
                f"record it claims to be: {exc}"
            ) from None
    return out


def read_verdicts(conn: sqlite3.Connection) -> list:
    """Every stored verdict, reconstructed, ordered by `(seq, verdict_id)`.

    The same contract as `read_declarations`, under the enforcement key. Note
    that this is **not** one row per declaration: a verdict is per commanded
    action, so one declaration is adjudicated repeatedly and a run routinely
    holds tens of verdicts naming the same `declaration_id` with different
    outcomes (`reg.enforce`, module header).
    """
    _require_record_tables(conn, "reading the verdicts back")
    _, verdict_type = _record_types()
    # The declaration join is a LEFT one and reaches `node`, not `declaration`:
    # a verdict naming no declaration is a finding rather than a gap, and a
    # verdict whose declaration row was *removed* still named it when it was
    # signed. Reading the id off the record table would silently rewrite the
    # record to say it named nothing, and its MAC would then fail for a reason
    # nobody could trace to a deletion.
    rows = conn.execute(
        """
        SELECT v.*, n.node_id AS verdict_id, dn.node_id AS declaration_id
        FROM verdict v
        JOIN node n ON n.node_key = v.verdict_key
        LEFT JOIN node dn ON dn.node_key = v.declaration_key
        ORDER BY v.seq, n.node_id
        """
    ).fetchall()
    out: list = []
    for row in rows:
        record_id = str(row["verdict_id"])
        clamped = row["clamped_envelope_wkb"]
        try:
            out.append(
                verdict_type(
                    verdict_id=record_id,
                    declaration_id=(
                        None
                        if row["declaration_id"] is None
                        else str(row["declaration_id"])
                    ),
                    seq=int(row["seq"]),
                    t=float(row["t"]),
                    outcome=str(row["outcome"]),
                    fault=None if row["fault"] is None else str(row["fault"]),
                    clamped_envelope=(
                        None
                        if clamped is None
                        else _record_bytes(
                            clamped, "clamped_envelope_wkb", record_id
                        )
                    ),
                    prev_hash=str(row["prev_hash"]),
                    mac=str(row["mac"]),
                )
            )
        except ValueError as exc:
            raise StoreError(
                f"verdict row {record_id!r} cannot be reconstructed as the record "
                f"it claims to be: {exc}"
            ) from None
    return out


def insert_robot_config(
    conn: sqlite3.Connection,
    config_id: str,
    q: str,
    qd: str,
    *,
    base_pose: str | None,
    base_pose_source: str | None,
) -> str:
    """A joint configuration that anchors a retained relationship, or an envelope.

    "Or an envelope" is issue #28: an envelope whose geometry was discarded is
    recomputed from the configuration it was computed from, so that configuration
    has to survive. It is the cheaper half of the same information — a few dozen
    characters of joint text against a WKB polygon.

    `q` and `qd` are text, formatted by the caller. Text rather than a float
    column per joint because the joint count is a property of the robot and not
    of the schema, and because the artifact should read back exactly the digits
    the raw stream carried rather than whatever a float column round-trips to.

    `base_pose` is `x,y,theta` in the room and `base_pose_source` is a
    `reg.types.PoseSource` value; both are **required arguments with no default**
    and both are `None` for a configuration whose base pose this artifact does
    not record (issue #166). That is the `Limits.source` discipline applied to
    the field it was written for: `None` here says *nobody recorded where the
    base was*, and a default would make that indistinguishable from a run whose
    base was known to be at the origin. It is also the same text argument as `q`
    — the digits the raw stream carried, not what a REAL column renders.

    Writing a pose into an artifact that states `meta[base_frame]` is refused.
    Those are two different claims about the same run — *the base was bolted
    here*, a mounting fact, and *the base was there at this instant*, a room-frame
    estimate that inherits a perceiver — and an artifact making both leaves every
    reader of a retained `outer_radius` to choose which centre it is about.
    """
    base_pose = None if base_pose is None else str(base_pose)
    base_pose_source = (
        None if base_pose_source is None else str(base_pose_source)
    )
    if (base_pose is None) != (base_pose_source is None):
        raise StoreError(
            f"robot_config {config_id!r} has base_pose={base_pose!r} and "
            f"base_pose_source={base_pose_source!r}. A room-frame pose whose "
            "provenance nobody stated is what reg.types.BasePose exists to make "
            "impossible, and a provenance with no pose describes the failure "
            "modes of nothing. Both, or neither — and neither says this "
            "artifact records no pose, which is not the same as a base at the "
            "origin."
        )
    if base_pose_source is not None and base_pose_source not in POSE_SOURCES:
        raise StoreError(
            f"base_pose_source={base_pose_source!r} is not in the vocabulary "
            f"{POSE_SOURCES}. It is a reg.types.PoseSource value: what the pose "
            "inherits and over what horizon — integration from a last known "
            "pose, or a map. An unrecognised string is a provenance nobody can "
            "read, and it decides no layer either way."
        )
    if base_pose is not None:
        bolted = get_meta(conn, META_BASE_FRAME)
        if bolted is not None:
            raise StoreError(
                f"robot_config {config_id!r} states base_pose={base_pose!r}, but "
                f"this artifact states meta[{META_BASE_FRAME!r}]={bolted!r} — "
                "that its base does not move and is bolted at that frame. Those "
                "are two different claims about one run, and every retained "
                "outer_radius would then be a radius about whichever centre the "
                "reader picked. An artifact whose base drove states no "
                f"meta[{META_BASE_FRAME!r}]."
            )
    return _insert_node(
        conn,
        "RobotConfig",
        config_id,
        {
            "q": str(q),
            "qd": str(qd),
            "base_pose": base_pose,
            "base_pose_source": base_pose_source,
        },
    )


def config_base_pose(
    conn: sqlite3.Connection, config_id: str
) -> tuple[str, str] | None:
    """The `(base_pose, base_pose_source)` a configuration states, or `None`.

    `None` is *this artifact records no base pose for that configuration*, and it
    is not an answer about where the base was. `reg.graph.envelope_frame` is what
    turns the two cases into a frame or into a refusal.
    """
    row = conn.execute(
        "SELECT c.base_pose AS base_pose, c.base_pose_source AS source "
        "FROM robot_config c JOIN node n ON n.node_key = c.config_key "
        "WHERE n.node_id = ?",
        (str(config_id),),
    ).fetchone()
    if row is None:
        raise StoreError(
            f"no RobotConfig node with id {config_id!r}. A pose read off a "
            "configuration this artifact does not hold would be a pose about "
            "nothing."
        )
    if row["base_pose"] is None:
        return None
    return (str(row["base_pose"]), str(row["source"]))


def _room_frame_endpoint(
    conn: sqlite3.Connection, kind: str, node_key: int
) -> tuple[str, str] | None:
    """The posed configuration one edge endpoint rests on, or `None` (issue #166).

    `(config_id, base_pose)` for an endpoint that is a `RobotConfig` stating a
    pose, or an `Envelope` computed from one. `None` for every other kind, and
    for a configuration that states no pose.

    **This is a taint, and it travels through the envelope on purpose.** An
    envelope row names the configuration it was computed from precisely so the
    polygon can be recomputed and so its `outer_radius` has a centre; if that
    configuration is in the room, then so is the region, and so is anything a
    reader concludes from an edge naming it. Reading the pose off the endpoint
    rather than trusting the caller is the same rule the layer column has always
    been under: no layer tag is ever written by an omission, and nobody has to
    remember this one either.

    It reads *whether* there is a pose and never which `PoseSource` produced it.
    Both are Layer B (docs/sufficiency.md §5.6), so a mapping from provenance to
    layer would have nothing to say and would be the mislabelling
    `tests/test_layer_boundary.py` scans for.
    """
    if kind == "RobotConfig":
        row = conn.execute(
            "SELECT n.node_id AS config_id, c.base_pose AS base_pose "
            "FROM robot_config c JOIN node n ON n.node_key = c.config_key "
            "WHERE c.config_key = ?",
            (int(node_key),),
        ).fetchone()
    elif kind == "Envelope":
        row = conn.execute(
            "SELECT n.node_id AS config_id, c.base_pose AS base_pose "
            "FROM envelope e "
            "JOIN robot_config c ON c.config_key = e.config_key "
            "JOIN node n ON n.node_key = c.config_key "
            "WHERE e.envelope_key = ?",
            (int(node_key),),
        ).fetchone()
    else:
        return None
    if row is None or row["base_pose"] is None:
        return None
    return (str(row["config_id"]), str(row["base_pose"]))


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------


def _require_node(conn: sqlite3.Connection, kind: str, node_id: str) -> int:
    """The surrogate key for a node of `kind`, or a `StoreError` naming what is
    missing.

    One statement, not two: the id is resolved and the payload row is checked in
    the same join, because "this artifact has never held that id" and "that id is
    a node of some other kind" are both this refusal and neither is worth a
    second round trip on a path that runs twice per edge.
    """
    if kind in RECORD_KINDS:
        _require_record_tables(conn, f"an edge to the {kind} {node_id!r}")
    table, key_column = NODE_TABLES[kind]
    row = conn.execute(
        f"SELECT n.node_key AS node_key FROM node n "  # noqa: S608
        f"JOIN {table} t ON t.{key_column} = n.node_key WHERE n.node_id = ?",
        (str(node_id),),
    ).fetchone()
    if row is None:
        raise StoreError(
            f"no {kind} node with id {node_id!r}. An edge to a node that does not "
            "exist is a dangling reference: every join over it returns nothing, "
            "and nothing is indistinguishable from 'the relationship never held'."
        )
    return int(row["node_key"])


def _endpoint_kind(
    spec_kind: str | frozenset[str], given: str | None, edge_type: str, side: str
) -> str:
    """The node kind for one end of an edge. From the spec unless it says to ask.

    A fixed kind is not the caller's to state: passing one that disagrees is
    refused rather than honoured, because the spec is the vocabulary's single
    definition. A polymorphic one — `FOLLOWS`, and only `FOLLOWS` — must be
    stated, and must be inside the set. There is no fallback to a first or a
    likeliest kind: an edge stored against the wrong table is a dangling
    reference that every join reads as "the relationship never held".
    """
    if isinstance(spec_kind, str):
        if given is not None and given != spec_kind:
            raise StoreError(
                f"a {edge_type} edge always runs from a {spec_kind} on the "
                f"{side} side, but {given!r} was supplied. The endpoint kinds "
                "come from EDGE_SPECS, not from the call site."
            )
        return spec_kind
    if given is None:
        raise StoreError(
            f"a {edge_type} edge joins any of {sorted(spec_kind)} on the {side} "
            f"side, so {side}_kind has to be stated and there is no default to "
            "fall back on. A chain link stored against the wrong table points at "
            "nothing, and a join over it returns nothing — which reads as 'these "
            "records do not follow one another'."
        )
    if given not in spec_kind:
        raise StoreError(
            f"a {edge_type} edge cannot run from a {given!r} on the {side} side; "
            f"the record kinds are {sorted(spec_kind)}."
        )
    return given


def _edge_layer(
    spec_layer: Layer | frozenset[Layer], given: Layer | None, edge_type: str
) -> Layer:
    """The layer one edge carries. From the spec unless the spec says to ask.

    The same shape as `_endpoint_kind`, and for a stronger reason. A fixed layer
    is not the caller's to state and disagreeing with it is refused. A layer that
    varies — `HAS_ENVELOPE`, whose provenance decides it (issue #84) — must be
    stated, and there is no fallback: falling back to `A` would tag an envelope
    computed from a perception-derived speed cap as certifiable evidence, which
    is precisely the failure that has no other detector. Claim 3 is a query over
    this column, so an omission here is an answer nobody wrote.
    """
    if isinstance(spec_layer, str):
        if given is not None and given != spec_layer:
            raise StoreError(
                f"a {edge_type} edge is always layer {spec_layer}, but "
                f"{given!r} was supplied. The layer comes from EDGE_SPECS, not "
                "from the call site."
            )
        return spec_layer
    if given is None:
        raise StoreError(
            f"a {edge_type} edge may be layer {sorted(spec_layer)} and which one "
            "it is depends on where its Limits came from, so the layer has to be "
            "stated and there is no default to fall back on (issue #84). "
            "reg.envelope.envelope_layer(limits) is the answer: proprioceptive "
            "bounds give 'A', bounds derived from a perceiver — an ISO/TS 15066 "
            "speed cap — give 'B'. Defaulting to 'A' here would let a Layer B "
            "envelope be quoted as certifiable evidence."
        )
    if given not in spec_layer:
        raise StoreError(
            f"a {edge_type} edge cannot be layer {given!r}; its layers are "
            f"{sorted(spec_layer)}."
        )
    return given


def open_edge(
    conn: sqlite3.Connection,
    edge_type: str,
    src_id: str,
    dst_id: str,
    t_start: float,
    *,
    t_end: float | None = None,
    overlap_area: float | None = None,
    min_distance: float | None = None,
    src_kind: str | None = None,
    dst_kind: str | None = None,
    layer: Layer | None = None,
) -> int:
    """Insert an edge and return its `edge_id`. `t_end` defaults to `t_start`.

    That default is not an invented value: an interval observed at exactly one
    instant *is* `[t, t]`, and `extend_edge` is how it grows. It is the only
    honest starting point — an open-ended `t_end` would have to be `NULL` or an
    invented horizon, and both read as "still true" long after the relationship
    stopped holding.

    The layer comes from `EDGE_SPECS` and never from the caller — except for the
    one edge type whose layer is not a property of its type. `layer` is required
    for `HAS_ENVELOPE`, whose region is Layer A or Layer B according to
    `reg.envelope.envelope_layer(limits)` (issue #84), and refused for every
    other type. The endpoint kinds work the same way: `src_kind` and `dst_kind`
    are required for `FOLLOWS`, which joins two declarations in one chain and two
    verdicts in the other, and are refused for every other type.

    The metric argument for the edge type is required and the other one must be
    absent: an `INTERSECTS` with no `overlap_area` answers "how much" with
    `NULL`, which compares false against every threshold and turns an incident
    into a non-incident.
    """
    spec = EDGE_SPECS.get(edge_type)
    if spec is None:
        possible_layers(edge_type)  # raises with the full vocabulary
        raise AssertionError  # pragma: no cover - possible_layers always raises

    resolved_src = _endpoint_kind(spec.src_kind, src_kind, edge_type, "src")
    resolved_dst = _endpoint_kind(spec.dst_kind, dst_kind, edge_type, "dst")
    resolved_layer = _edge_layer(spec.layer, layer, edge_type)

    metrics = {"overlap_area": overlap_area, "min_distance": min_distance}
    for name, value in metrics.items():
        if name == spec.metric:
            if value is None:
                raise StoreError(
                    f"a {edge_type} edge carries {name} and none was supplied. "
                    "Writing it as NULL would answer every question about the "
                    "quantity with 'no', not with 'unknown'."
                )
        elif value is not None:
            raise StoreError(
                f"a {edge_type} edge does not carry {name}, but {value!r} was "
                f"supplied. Its metric is {spec.metric!r}."
            )

    src_key = _require_node(conn, resolved_src, str(src_id))
    dst_key = _require_node(conn, resolved_dst, str(dst_id))

    # THE ROOM-FRAME TAINT (issue #166). Every rule above derives the layer from
    # the edge *type*, and one derives it from the provenance of the `Limits`
    # (issue #84). Neither can see this one: a base pose reaches an edge through
    # a value on a row it names, under field names — `base_pose`, `x`, `y`,
    # `theta` — that no word check would ever hold against the world, and the
    # edge it reaches names no `Entity`. That is what makes it the first way a
    # Layer A attestation edge could depend on something outside the robot,
    # docs/sufficiency.md §5.6 and §5.8.
    #
    # The layer is checked first and the rows are read only for an `A`, which is
    # not an optimisation dressed as a rule: a `B` edge is already tagged with
    # the dependency, so there is nothing for the pose to change about it. Every
    # entity-naming edge takes that path and never touches the two lookups.
    if resolved_layer == "A" and (
        posed := _room_frame_endpoint(conn, resolved_src, src_key)
        or _room_frame_endpoint(conn, resolved_dst, dst_key)
    ):
        config_id, pose = posed
        varies = not isinstance(spec.layer, str)
        raise StoreError(
            f"a {edge_type} edge would be written layer 'A', but it rests on "
            f"robot_config {config_id!r}, which states base_pose={pose!r} — a "
            "pose in the room. A room-frame pose is a statement about the "
            "robot's relationship to a map, landmarks or a frame somebody "
            "defined, and no localizer of any kind moves it to Layer A "
            "(docs/sufficiency.md §5.6); everything computed from it inherits "
            "whatever supplied it. "
            + (
                "State layer 'B'."
                if varies
                else f"A {edge_type} edge is always layer 'A' by its type, so "
                "there is no layer to state instead and this write is refused "
                "rather than relabelled: reclassifying the attestation edges is "
                "a change to what this project claims (docs/sufficiency.md §2) "
                "and not something a call site decides. Retain the region "
                "rather than a bound over a base that moved."
            )
        )

    t_start = float(t_start)
    t_end = t_start if t_end is None else float(t_end)
    if t_end < t_start:
        raise StoreError(
            f"{edge_type} edge would span [{t_start}, {t_end}], which runs "
            "backwards. A backwards interval matches no time window, so it "
            "disappears from every timeline query instead of erroring."
        )

    cursor = conn.execute(
        """
        INSERT INTO edge (type, layer, src_kind, src_key, dst_kind, dst_key,
                          t_start, t_end, overlap_area, min_distance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            edge_type,
            resolved_layer,
            resolved_src,
            src_key,
            resolved_dst,
            dst_key,
            t_start,
            t_end,
            overlap_area,
            min_distance,
        ),
    )
    edge_id = cursor.lastrowid
    if edge_id is None:  # pragma: no cover - sqlite3 always sets it on INSERT
        raise StoreError("sqlite did not return an edge_id for the inserted edge.")
    return int(edge_id)


def extend_edge(conn: sqlite3.Connection, edge_id: int, t_end: float) -> None:
    """Extend an edge's interval to `t_end`. This is the incremental principle.

    Refuses to move `t_end` **backwards**. Shrinking an interval would silently
    delete time in which the relationship was observed to hold, and there is no
    situation in the incremental rule that calls for it — a relationship that
    stops holding gets a *new* edge, it does not retract the old one.
    """
    row = conn.execute(
        "SELECT t_start, t_end FROM edge WHERE edge_id = ?", (int(edge_id),)
    ).fetchone()
    if row is None:
        raise StoreError(f"no edge with edge_id={edge_id}.")

    t_end = float(t_end)
    if t_end < float(row["t_end"]):
        raise StoreError(
            f"edge {edge_id} already spans [{row['t_start']}, {row['t_end']}] and "
            f"extending it to {t_end} would move t_end backwards, discarding time "
            "in which the relationship was observed to hold."
        )
    conn.execute(
        "UPDATE edge SET t_end = ? WHERE edge_id = ?", (t_end, int(edge_id))
    )


#: `edge`, with `src_id` and `dst_id` put back off `node` (issue #55). Two
#: integer-primary-key lookups per row, and the columns a caller reads are the
#: ones it read before — plus `src_key` and `dst_key`, which `reg.bench` needs to
#: copy an edge without going back through an identifier.
#:
#: **LEFT joins, and it matters.** An edge whose endpoint has no `node` row is a
#: broken artifact, and it has to come back *visibly* broken — with a NULL id a
#: reader can refuse on — rather than silently disappear from the result. An
#: inner join would turn a damaged file into a quiet one, which is the failure
#: mode every three-state check in this project exists to prevent.
_EDGE_SELECT = """
SELECT e.edge_id      AS edge_id,
       e.type         AS type,
       e.layer        AS layer,
       e.src_kind     AS src_kind,
       e.src_key      AS src_key,
       sn.node_id     AS src_id,
       e.dst_kind     AS dst_kind,
       e.dst_key      AS dst_key,
       dn.node_id     AS dst_id,
       e.t_start      AS t_start,
       e.t_end        AS t_end,
       e.overlap_area AS overlap_area,
       e.min_distance AS min_distance
FROM edge e
LEFT JOIN node sn ON sn.node_key = e.src_key
LEFT JOIN node dn ON dn.node_key = e.dst_key
"""


def read_edges(
    conn: sqlite3.Connection,
    *,
    edge_type: str | None = None,
    layer: Literal["A", "B"] | None = None,
    dst_id: str | None = None,
) -> list[sqlite3.Row]:
    """Edges matching the filters, ordered by `(t_start, edge_id)`.

    Ordering is total and deterministic: `t_start` alone is not, because several
    relationships can transition in the same time quantum and docs/lossiness.md
    Unanswerable #5 says their *order* is not retained. `edge_id` breaks the tie
    by insertion order so that two reads of one artifact agree, without implying
    the tie-break means anything about time.
    """
    if edge_type is not None:
        # The vocabulary check, not the layer: `possible_layers` refuses an
        # unknown type rather than returning [], and unlike `layer_of` it can
        # answer for a type whose layer varies with its Limits (issue #84).
        possible_layers(edge_type)
    clauses: list[str] = []
    params: list[object] = []
    if dst_id is not None:
        key = node_key(conn, str(dst_id))
        if key is None:
            # No node has ever carried that id, so no edge can name it. The same
            # empty list this returned before the surrogate keys arrived — and,
            # as then, whether an empty list is evidence is a question for the
            # caller: `reg.query._require_entity` refuses an undeclared entity
            # rather than letting one reach here.
            return []
        # The filter is on the surrogate, which is what `edge_by_type_dst`
        # indexes; the readable id is resolved once, here, rather than once per
        # candidate row.
        clauses.append("e.dst_key = ?")
        params.append(key)
    for column, value in (("e.type", edge_type), ("e.layer", layer)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return list(
        conn.execute(
            f"{_EDGE_SELECT}{where} ORDER BY e.t_start, e.edge_id",  # noqa: S608
            params,
        ).fetchall()
    )
