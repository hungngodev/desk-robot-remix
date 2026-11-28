"""Bounded snapshot work and equivalent freshness/expiry on qualified evidence."""

from desk_robot.spatial_grid import RangeCellBatch, SpatialGrid


class CountingReferences(dict):
    scans = 0

    def values(self):
        self.scans += 1
        return super().values()


def populate(grid_type=SpatialGrid, batch_type=RangeCellBatch):
    grid = grid_type("r", 7, "o", "a", "c", 64, 64)
    for seq in range(1, 17):
        cells = tuple((x, y) for y in range(4 * (seq - 1), 4 * seq) for x in range(64))
        sample = seq * 1000
        for lane, kind in ((0, "floor_supported"), (4, "obstacle_clear")):
            grid.record(batch_type(
                "r", 7, "o", 0, "c", lane, seq, sample, 1_000_000 + sample,
                kind, cells, True,
            ), now_us=1_000_000 + sample)
    return grid


def test_dense_snapshot_scans_shared_clock_reference_only_once():
    grid = populate()
    references = CountingReferences(grid._clock_reference)
    grid._clock_reference = references
    snapshot = grid.snapshot(now_us=1_016_000)
    assert references.scans == 1
    assert snapshot.support == ("safe",) * (64 * 64)
    assert snapshot.expires_at_us == 2_001_000
    assert snapshot.anchored is False


def test_sparse_snapshot_preserves_cell_order_and_refreshes_clock_offset():
    grid = SpatialGrid("r", 7, "o", "a", "c", 64, 64)
    for lane, kind in ((0, "floor_supported"), (4, "obstacle_clear")):
        grid.record(RangeCellBatch(
            "r", 7, "o", 0, "c", lane, 1, 100_000, 1_000_000,
            kind, ((3, 7),), True,
        ), now_us=1_000_000)
    first = grid.snapshot(now_us=1_000_000)
    assert first.support[7 * 64 + 3] == "safe"
    assert first.support.count("unknown") == 4095
    # A later lane establishes a better offset, exposing the previous sample's lag.
    grid.record(RangeCellBatch(
        "r", 7, "o", 0, "c", 5, 1, 800_000, 1_300_000,
        "obstacle_hit", ((4, 8),), True,
    ), now_us=1_300_000)
    second = grid.snapshot(now_us=1_300_000)
    assert second.support[7 * 64 + 3] == "stale"
    assert second.support == tuple(
        grid.state(x, y, now_us=1_300_000) for y in range(64) for x in range(64)
    )
    grid.invalidate_calibration("new")
    third = grid.snapshot(now_us=1_300_000)
    assert third.support[7 * 64 + 3] == "unsafe"
    assert third.support[8 * 64 + 4] == "unsafe"
    assert third.support.count("unknown") == 4094
