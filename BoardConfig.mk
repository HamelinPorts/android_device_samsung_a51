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
TARGET_KERNEL_CONFIG := gki_defconfig
# Disable old-kernel artefacts: dtbo, decon device tree, and the
# in-bootimg dtb. The new tree has none of these yet, so leaving them
# enabled would have the build look for files that don't exist.
BOARD_KERNEL_SEPARATED_DTBO :=
BOARD_INCLUDE_DTB_IN_BOOTIMG :=
BOARD_DTB_CFG :=
BOARD_DTBO_CFG :=
# Rebuild MKBOOTIMG_ARGS without `--dtb_offset` — mkbootimg refuses to
# emit a header v2 boot.img with that offset set unless an actual DTB
# is also passed via `--dtb`. We have no DTB yet at this Phase 2 stage.
# Drop to boot.img header version 1: header v2 mandates a DTB section
# (mkbootimg refuses an empty one), and we don't have a DTB yet. v1 has
# no DTB section. This image won't boot on the BL (which expects v2),
# but Phase 2 only requires "packs into boot.img" — booting is later.
BOARD_BOOTIMG_HEADER_VERSION := 1
BOARD_MKBOOTIMG_ARGS := --base $(BOARD_KERNEL_BASE)
BOARD_MKBOOTIMG_ARGS += --pagesize $(BOARD_KERNEL_PAGESIZE)
BOARD_MKBOOTIMG_ARGS += --kernel_offset $(BOARD_KERNEL_OFFSET)
BOARD_MKBOOTIMG_ARGS += --ramdisk_offset $(BOARD_RAMDISK_OFFSET)
BOARD_MKBOOTIMG_ARGS += --tags_offset $(BOARD_TAGS_OFFSET)
BOARD_MKBOOTIMG_ARGS += --header_version $(BOARD_BOOTIMG_HEADER_VERSION)
BOARD_MKBOOTIMG_ARGS += --second_offset $(BOARD_SECOND_OFFSET)
endif
