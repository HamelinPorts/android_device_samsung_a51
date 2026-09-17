# A51 (Exynos9611) device debug notes

The **kernel-side** debug/recovery infrastructure — PMU INFORM-register routing,
the recovery bouncer, persistent log sinks, and the watchdogs — is documented in
the kernel tree:
[`kernel/samsung/universal9611-next/Documentation/a51-debug-infra.md`](../../../kernel/samsung/universal9611-next/Documentation/a51-debug-infra.md).

Brief overview of the kernel debug components (see that doc for detail):

| Area | Entry point | Kconfig |
|------|-------------|---------|
| Recovery bouncer (`/boot`→`/recovery` on a silent reset) | `a51_inform4_bouncer.S` (zinflate) | `CONFIG_A51_INFORM_BOUNCER` |
| Reboot-reason handler (single INFORM3 writer) | `a51_reboot.c` | — |
| DRAM log sink → `/proc/last_cachedump_kmsg` | `earlycon-ram.c` | `CONFIG_SERIAL_EARLYCON_RAM` |
| Cache-partition log sink (cold-power-off survivor) | `a51_cache_log.c` | `CONFIG_A51_CACHE_TAIL_LOG` |
| Watchdogs (CPU7 / CPU1 / auto-recovery hrtimer) | `a51_cpu7_wd.c` / `a51_cpu1_wd.c` / `a51_auto_recovery.c` | `CONFIG_A51_CPU7_WD` / `_CPU1_WD` / `_AUTO_RECOVERY` (timeouts default off) |
| INFORM register sysfs | `a51_inform4_sysfs.c` | `CONFIG_A51_INFORM4_SYSFS` |
| Secondary-CPU bring-up stamps | `a51_pmu_debug.c` | `CONFIG_A51_SMP_BRINGUP_DEBUG` |

Recovery reads the persisted logs from `/proc/last_cachedump_kmsg` (DRAM) and the
`cache:[192M..200M]` LBA window; INFORM8 shows the last progress marker.

---

## Userspace heap debugging — GWP-ASan on system_server

This is a device/userspace knob (not kernel), so it lives here.

Toggle `A51_GWP_ASAN_SYSTEM_SERVER` in `device/samsung/a51/device.mk` (default on
during the heap-corruptor hunt). When true it injects into `build.prop`:

```
libc.debug.gwp_asan.process_sampling.system_server=1
libc.debug.gwp_asan.sample_rate.system_server=1000
libc.debug.gwp_asan.max_allocs.system_server=8000
```

Catches an external heap overflow in `system_server` (surfaced as a `free()`
abort inside `libdebugstore_cxx.so`, which is itself memory-safe) at write time,
naming the real writer. Verify: `grep -ic GWP-ASan /proc/$(pidof system_server)/maps`.
