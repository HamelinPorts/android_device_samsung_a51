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
# section).
#
# 2026-05-19 update: the A51 dtbo overlay source files are now
# forward-ported into universal9611-next/arch/arm64/boot/dts/exynos/
# (commit landing alongside this BoardConfig change), so dtbo build
# under USE_KERNEL_NEXT=true is RE-ENABLED.  We inherit BOARD_DTBO_CFG
# and BOARD_KERNEL_SEPARATED_DTBO from BoardConfigCommon.mk (the
# device/samsung/universal9611-common/configs/kernel/a51.cfg manifest
# lists the four EUR_OPEN per-revision .dtbo entries + custom0/custom1
# board-revision keys).
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

# Foundation F5 attempted Image.gz to fit a KASAN-inflated kernel into
# the 61 MB boot partition.  The Samsung A515FXXU8HVI3 BL rejected
# the gzipped image: device went silent, no earlycon-ram recovery
# fired (kernel never started), required odin4 to recover.  Revert
# to uncompressed Image until we either (a) confirm a different
# compression mode the BL accepts (lz4? lzma?), or (b) shrink the
# kernel via lighter KASAN config.
# BOARD_KERNEL_IMAGE_NAME := Image.gz

# 2026-05-18 Phase 5.1: dropped BOARD_USES_RECOVERY_AS_BOOT.
#
# Earlier (Phase 3 Tier 4) we packed the recovery ramdisk into
# boot.img to get adbd + USB CDC gadget up in the bring-up window.
# That's now redundant — Phase 5.3's IO path works (FMP SMC
# handshake + 4 KiB DMA constraints + BROKEN_OCS_FATAL_ERROR strip
# landed in universal9611-next 2026-05-18) so first-stage init can
# attempt to mount /metadata, /system, /vendor, and we'd like to
# observe how far it actually gets before hitting the next blocker.
#
# With this set to false, the build produces a regular boot.img
# with the first-stage init ramdisk (not recovery's), and a
# separate recovery.img.  If first-stage init hangs before adbd
# comes up, the CPU7 watchdog (60 s) + bouncer chain still routes
# /boot → /recovery and 4.14 captures /proc/last_cachedump_kmsg
# for inspection.
BOARD_USES_RECOVERY_AS_BOOT := false
# We don't pack a recovery DTBO.  The main dtbo (a51.cfg) is built
# from the forward-ported overlays in universal9611-next as of
# 2026-05-19, but recovery still runs the 4.14 kernel which has its
# own dtbo handling — we don't need a recovery-specific dtbo entry.
#
# The parent BoardConfigCommon.mk for universal9611-common sets
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

# 2026-05-20: kernel cmdline lives in the dts chosen.bootargs +
# CONFIG_CMDLINE_FROM_BOOTLOADER=y (see exynos9611-a51.config).  The
# Samsung A515 BL doesn't relay boot.img header BOARD_KERNEL_CMDLINE
# to the kernel — additions here are silently dropped.  Keeping any
# BOARD_KERNEL_CMDLINE += line in the legacy boot.img header is just
# documentation drift, so the active earlycon/console/watchdog args
# moved into universal9611-next/arch/arm64/boot/dts/exynos/exynos9610.dts.


# hardware/samsung_slsi-linaro/config/BoardConfig9610.mk hardcodes
# TARGET_LINUX_KERNEL_VERSION := 4.14, which gates two things:
#  - hardware/samsung_slsi-linaro/exynos/kernel-$(VER)-headers/ — the
#    UAPI headers exposed to vendor blobs
#  - hardware/samsung_slsi-linaro/config/openmax.mk — sets the soong
#    config flag MAINLINE_FEATURE_IN_SINCE_4_19=true when the kernel
#    is >= 4.19, which guards the vendor's exynos_mfc_media.h against
#    redefining V4L2_CID_MPEG_VIDEO_HEVC_*/v4l2_mpeg_video_hevc_* enums
#    that mainline 6.12 already provides via linux/v4l2-controls.h.
#
# openmax.mk is included from samsung_slsi-linaro's BoardConfigCommon.mk
# *during* the BoardConfig9610.mk include chain, so by the time control
# returns here the soong_config flag has already been frozen to "false"
# (because TARGET_LINUX_KERNEL_VERSION was 4.14 at that moment).  Set
# both the variable for any later evaluations *and* re-publish the
# soong_config flag explicitly here.  6.1 is the closest kernel-headers
# tree shipped under hardware/samsung_slsi-linaro/exynos/kernel-*-headers/.
TARGET_LINUX_KERNEL_VERSION := 6.1
TARGET_BOARD_KERNEL_HEADERS := hardware/samsung_slsi-linaro/exynos/kernel-$(TARGET_LINUX_KERNEL_VERSION)-headers/kernel-headers
$(call soong_config_set_bool,openmax,MAINLINE_FEATURE_IN_SINCE_4_19,true)
endif
