#
# Copyright (C) 2023 The LineageOS Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

DEVICE_PATH := device/samsung/a51

# Inherit from the common tree
include device/samsung/universal9611-common/BoardConfigCommon.mk
# Inherit optional vendor BoardConfig
-include vendor/samsung/a51/BoardConfigVendor.mk

# OTA Asserts
TARGET_OTA_ASSERT_DEVICE := a51,a51dd,a51nsxx
TARGET_BOARD_INFO_FILE := $(DEVICE_PATH)/board-info.txt

## Releasetools
TARGET_RECOVERY_UPDATER_LIBS := librecovery_updater_a51
TARGET_RELEASETOOLS_EXTENSIONS := $(DEVICE_PATH)/releasetools

## Partitions Sizes
BOARD_BOOTIMAGE_PARTITION_SIZE := 61865984
BOARD_DTBOIMG_PARTITION_SIZE := 8388608
BOARD_RECOVERYIMAGE_PARTITION_SIZE := 71106560
BOARD_CACHEIMAGE_PARTITION_SIZE := 209715200

## Camera
$(call soong_config_set,samsungCameraVars,extra_ids,4,20,23,50,52,54)

## Vintf
ODM_MANIFEST_SKUS := hce hceese hcesim hcesimese disabled
ODM_MANIFEST_NFC_FILE := $(DEVICE_PATH)/configs/nfc/odm_nfc_manifest.xml
ODM_MANIFEST_HCE_FILES := $(ODM_MANIFEST_NFC_FILE)
ODM_MANIFEST_HCEESE_FILES := $(ODM_MANIFEST_NFC_FILE)
ODM_MANIFEST_HCESIM_FILES := $(ODM_MANIFEST_NFC_FILE)
ODM_MANIFEST_HCESIMESE_FILES := $(ODM_MANIFEST_NFC_FILE)
ODM_MANIFEST_DISABLED_FILES := $(DEVICE_PATH)/configs/nfc/odm_nfc_manifest_disabled.xml
DEVICE_FRAMEWORK_COMPATIBILITY_MATRIX_FILE += \
    $(DEVICE_PATH)/configs/vintf/device_framework_matrix.xml

## Filesystem config
include device/samsung/universal9611-common/fsconfig_dynamic.mk

# UDFPS
TARGET_ADDITIONAL_GRALLOC_10_USAGE_BITS := 0x2000U | 0x400000000LL
$(call soong_config_set,surfaceflinger,udfps_lib,//$(DEVICE_PATH):libudfps_extension.a51)

## SELinux
SYSTEM_EXT_PRIVATE_SEPOLICY_DIRS += $(DEVICE_PATH)/sepolicy/private
BOARD_VENDOR_SEPOLICY_DIRS += $(DEVICE_PATH)/sepolicy/vendor

## Prop
TARGET_VENDOR_PROP += $(DEVICE_PATH)/vendor.prop

# Phase 2 of the kernel rebase plan: USE_KERNEL_NEXT=true on the build
# command-line switches the kernel source from the legacy 4.14-openela
# tree (kernel/samsung/universal9611) to the AOSP common-android16-6.12
# tree (kernel/samsung/universal9611-next). Doesn't yet boot — the goal
# at this phase is "compiles + packs into boot.img"; vendor-platform
# code (decon, modem, SCSC WLAN, FIMC-IS, FMP, tzdev, …) all stubbed.
#
# Daily-driver builds leave USE_KERNEL_NEXT unset → existing kernel.
ifeq ($(USE_KERNEL_NEXT),true)
TARGET_KERNEL_SOURCE := kernel/samsung/universal9611-next
TARGET_KERNEL_CONFIG := gki_defconfig exynos9611-a51.config
# Phase 3 Tier 1: include the minimal exynos9611-a51 DTB in boot.img
# (mainline pattern, single .dtb concatenated into the boot.img DTB
# section). The 4.14 tree's per-revision dtbo overlays are NOT yet
# carried over, so dtbo packing stays disabled. BOARD_DTB_CFG also
# stays empty — that variable points at the legacy dtbo manifest.
BOARD_KERNEL_SEPARATED_DTBO :=
BOARD_DTBO_CFG :=
# Use Samsung's mkdtboimg-cfg-format DTB image (single-entry table with
# custom0/custom1 board-revision keys). The Samsung bootloader rejects
# a raw concatenated .dtb in the boot.img DTB section with `DT LOAD
# Fail / header check fail`; it expects the table header. Verified on
# A51 BL A515FXXU8HVI3, 2026-05-03.
BOARD_DTB_CFG := $(DEVICE_PATH)/configs/kernel/exynos9611-next.cfg
BOARD_INCLUDE_DTB_IN_BOOTIMG := true
TARGET_DTB_LIST_WILDCARD := exynos/exynos9610
# Header v2 is what the A51 bootloader expects. Now that we have a
# DTB to pass, mkbootimg's empty-DTB rejection no longer triggers and
# we can stay on v2.
BOARD_BOOTIMG_HEADER_VERSION := 2

# Phase 3 Tier 4 / ramboot adb: pack recovery's ramdisk into boot.img
# so the new 6.12 kernel boots straight into a recovery-style
# userspace that already has adbd + the USB CDC gadget composition.
# Without this, USE_KERNEL_NEXT=true builds boot a kernel with an
# empty bring-up ramdisk (no adbd) -> no way to talk to the device
# from a host.
#
# BOARD_USES_RECOVERY_AS_BOOT=true makes the build system pack the
# recovery ramdisk as the boot.img ramdisk -- same mechanism Pixel
# devices use for A/B boot.  Only the USE_KERNEL_NEXT path opts in;
# daily-driver builds (USE_KERNEL_NEXT unset) continue to ship the
# normal split boot.img + recovery.img pair.
BOARD_USES_RECOVERY_AS_BOOT := true
# We don't pack a recovery DTBO (BOARD_DTBO_CFG and
# BOARD_KERNEL_SEPARATED_DTBO are empty above for the same reason
# — the legacy 4.14 dtbo overlays are not forward-ported).  The
# parent BoardConfigCommon.mk for universal9611-common sets
# BOARD_INCLUDE_RECOVERY_DTBO := true unconditionally, and
# build/make/core/Makefile gates the --recovery_dtbo mkbootimg flag
# on `ifdef BOARD_INCLUDE_RECOVERY_DTBO` — which is truthy as long
# as the variable is defined to anything (including "false"!).
# Clearing to empty makes `ifdef` evaluate false (GNU Make: ifdef
# is true only for non-empty values).  `undefine` directive is not
# supported by kati so plain assignment to empty is the portable
# form.  Confirmed correct: kati passes the empty value back through
# product configuration; the --recovery_dtbo flag is then skipped.
BOARD_INCLUDE_RECOVERY_DTBO :=

# earlycon=ram drives the RAM-backed earlycon at 0xF9010000, the
# Samsung debug-snapshot,log_kernel reserved region.  This is the
# active log_kernel writer for the kernel rebase: single-writer
# (no race with sec_log_kernel which is compiled but not registered),
# NC mapping (writes hit DRAM directly so warm-reset → 4.14 recovery
# /proc/last_kmsg sees them), activates at parse_early_param so we
# capture printk from very early in boot.  Size 0x40000 (256 KiB) is
# the max early_memremap() will accept on arm64 (NR_FIX_BTMAPS).
BOARD_KERNEL_CMDLINE += earlycon=ram,mmio32,0xF9010000,0x40000

# Phase 3 bring-up: disable secondary CPU bringup entirely.  smp_init()
# hangs after CPU1/CPU3 fail to come online (PSCI / cal-if / clocks not
# fully wired up yet).  Boot CPU0-only so we can reach userspace; revisit
# secondary CPU bringup in a later phase once cal-if + PSCI are sound.
BOARD_KERNEL_CMDLINE += nosmp

# Phase 3 bring-up: bypass `loglevel=4` injected by the bootloader/DT
# chosen bootargs.  GKI's `loglevel=4` filters everything below
# KERN_WARNING out of the registered consoles (incl. our earlycon-ram),
# which silences the entire SCSI/sd subsystem (`scsi 0:0:0:0:
# Direct-Access ...`, `sd 0:0:0:0: [sda] ...`) -- those prints are
# KERN_NOTICE (level 5) and KERN_INFO (level 6).  Without them in
# /proc/last_kmsg we can't tell why /dev/sda doesn't appear and init
# wedges on missing /dev/block/by-name/*.  `ignore_loglevel` makes
# every printk reach every console regardless of level; revert once
# bring-up stabilises.
BOARD_KERNEL_CMDLINE += ignore_loglevel

# Phase 3 diagnostic: turn on every dev_dbg / pr_debug at boot so we
# can see which step of the SCSI bringup chain stalls.  Verbose, but
# the log_kernel buffer is 2 MiB so it absorbs the volume.  Pairs with
# CONFIG_DYNAMIC_DEBUG=y in the kernel fragment.  Drop once /dev/sda
# is reliably exposed and partitions mount.  Single token (no spaces /
# quotes / semicolons) to keep soong's variables-file JSON parsing
# happy when this gets serialised through PRODUCT_BOARD_KERNEL_CMDLINE.
BOARD_KERNEL_CMDLINE += dyndbg=+p
endif
