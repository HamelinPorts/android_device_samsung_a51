/*
 * panic_to_recovery — early-init helper that routes the next reboot to
 * Lineage recovery whenever bootstat reports the previous boot ended in
 * kernel panic.
 *
 * Design: bootstat already reads /sys/fs/pstore at boot, decodes the
 * kernel-panic reason, and exposes it as `sys.boot.reason`. We just
 * read that property and, if it starts with "kernel_panic", request a
 * recovery reboot via `sys.powerctl=reboot,recovery`. Android init
 * catches that property change, writes the bootloader_message ("BCB")
 * to /dev/block/by-name/misc, and reboots — bypassing the SELinux
 * walls around direct misc-block-device writes from custom domains.
 *
 * Bring-up infrastructure for the kernel rebase plan
 * (project_a51_kernel_aosp_rebase_plan, Phase 1d).
 */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/system_properties.h>

int main(void) {
    /* We read `sys.boot.reason` (system-side, system_boot_reason_prop)
     * rather than `ro.boot.bootreason` (bootloader_boot_reason_prop)
     * because the latter is read-restricted by an AOSP neverallow to
     * a tight allowlist (bootstat, init, system_server, etc.) that we
     * are deliberately not joining.
     *
     * Our init trigger is `on property:sys.boot.reason=*`, which fires
     * after bootstat refines the property — so the value is reliably
     * populated when we run. */
    char reason[PROP_VALUE_MAX] = {0};
    __system_property_get("sys.boot.reason", reason);

    if (strncmp(reason, "kernel_panic", 12) != 0) {
        /* Clean boot — any non-panic bootreason ends up here. */
        return 0;
    }

    fprintf(stderr,
            "panic_to_recovery: prior-boot panic (%s); requesting recovery\n",
            reason);

    if (__system_property_set("sys.powerctl", "reboot,recovery") != 0) {
        fprintf(stderr, "panic_to_recovery: failed to set sys.powerctl\n");
        return 1;
    }

    /* Init handles the BCB write + reboot. Sleep until init kills us as
     * part of the reboot sequence. */
    sleep(120);
    return 0;
}
