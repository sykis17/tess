"""Scenario registry."""

from __future__ import annotations

from . import (
    s01_kill_primary,
    s02_pause_primary,
    s03_partition_primary_etcd,
    s04_partition_primary_redis,
    s05_partition_standby_etcd,
    s06_etcd_down,
    s07_redis_cas_bump,
    s08_empty_blob,
    s09_zombie_second_provider,
)

SCENARIOS = {
    s01_kill_primary.ID: s01_kill_primary,
    s02_pause_primary.ID: s02_pause_primary,
    s03_partition_primary_etcd.ID: s03_partition_primary_etcd,
    s04_partition_primary_redis.ID: s04_partition_primary_redis,
    s05_partition_standby_etcd.ID: s05_partition_standby_etcd,
    s06_etcd_down.ID: s06_etcd_down,
    s07_redis_cas_bump.ID: s07_redis_cas_bump,
    s08_empty_blob.ID: s08_empty_blob,
    s09_zombie_second_provider.ID: s09_zombie_second_provider,
}

ORDER = [
    s01_kill_primary.ID,
    s02_pause_primary.ID,
    s03_partition_primary_etcd.ID,
    s04_partition_primary_redis.ID,
    s05_partition_standby_etcd.ID,
    s06_etcd_down.ID,
    s07_redis_cas_bump.ID,
    s08_empty_blob.ID,
    s09_zombie_second_provider.ID,
]
