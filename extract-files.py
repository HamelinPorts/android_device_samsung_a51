#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2025 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

import re

from extract_utils.fixups_blob import (
    blob_fixup,
    blob_fixups_user_type,
)
from extract_utils.fixups_lib import (
    lib_fixups,
    lib_fixup_remove,
    lib_fixups_user_type,
)
from extract_utils.main import (
    ExtractUtils,
    ExtractUtilsModule,
)

namespace_imports = [
    'device/samsung/universal9611-common',
    'hardware/samsung_slsi-linaro/exynos',
    'hardware/samsung_slsi-linaro/graphics',
    'vendor/samsung/universal9611-common',
]

# FaceDisplayManager::getANativeWindow() builds an
# android::hardware::graphics::bufferqueue::V1_0::utils::H2BGraphicBufferProducer
# in place and stores its three sub-table pointers as fixed displacements from
# the vtable symbol. Our IGraphicBufferProducer declares two virtual functions
# more than the one it was built against, so both secondary sub-tables sit 0x10
# higher than the displacements it uses:
#
#   add x10, x9, #0x250 -> #0x260   RefBase virtual-base sub-table
#   add  x8, x9,  #0x18             primary sub-table, correct as is
#   add  x9, x9, #0x190 -> #0x1a0   BBinder sub-table
#
# The untouched middle instruction is part of the pattern on purpose: on its
# own, 'add x8, x9, #0x18' occurs six times in this blob, so an anchor without
# it would not identify the site. The offsets on the right cannot be checked
# here -- extraction runs long before libgui_vendor.so exists -- so they are
# asserted against the built library by libface_blob_abi_guard.
FACE_H2B_SUB_VTABLE_VENDOR = bytes.fromhex('2a410991' '28610091' '29410691')
FACE_H2B_SUB_VTABLE_CORRECTED = bytes.fromhex('2a810991' '28610091' '29810691')

blob_fixups: blob_fixups_user_type = {
    (
        'vendor/lib/sensors.inputvirtual.so',
        'vendor/lib/sensors.sensorhub.so',
        'vendor/lib64/sensors.inputvirtual.so',
        'vendor/lib64/sensors.sensorhub.so',
    ): blob_fixup()
        .remove_needed('libhidltransport.so'),
    (
        'vendor/lib/libsensorlistener.so',
        'vendor/lib64/libsensorlistener.so',
    ): blob_fixup()
        .add_needed('libshim_sensorndkbridge.so'),
    # libFaceService.so subclasses android::AHandler and puts its own members at
    # offset 0x60, where the current AOSP class keeps mLock and the three
    # delivery-status fields. libsecfr_ahandler_compat.so supplies an
    # AHandler::deliverMessage that stays below 0x60.
    #
    # Both the service binary and the library have to name the shim. The binary
    # pulls libstagefright_foundation.so itself, so that library is loaded and
    # BIND_NOW-relocated at process start, long before the binary dlopen()s
    # libFaceService.so; the JUMP_SLOT for AHandler::deliverMessage inside the
    # foundation is bound at that point and never revisited. Only a shim that is
    # already in the lookup list at process start can take it, and the lookup
    # list puts a direct DT_NEEDED of the binary ahead of the foundation, which
    # the shim in turn pulls in one level deeper.
    'vendor/bin/hw/vendor.samsung.hardware.biometrics.face-service': blob_fixup()
        .replace_needed(
            'libstagefright_foundation.so', 'libsecfr_ahandler_compat.so'
        ),
    # The V3 entry resolves no symbol in this blob, but libcamera2ndk_vendor
    # pulls android.hardware.graphics.common at V7 and Soong rejects two
    # versions of one aidl_interface in a single dependency graph. Dropping it
    # is also required at runtime: only V7 ships in /vendor/lib64, so a
    # surviving V3 entry would fail the service's dlopen of this library.
    'vendor/lib64/libFaceService.so': blob_fixup()
        .remove_needed('android.hardware.graphics.common-V3-ndk.so')
        .replace_needed(
            'libstagefright_foundation.so', 'libsecfr_ahandler_compat.so'
        )
        # The pattern has to be escaped: three of its bytes are 0x2a, 0x28 and
        # 0x29, which are regex metacharacters. The replacement needs no
        # escaping, as it contains no backslash.
        .binary_regex_replace(
            re.escape(FACE_H2B_SUB_VTABLE_VENDOR),
            FACE_H2B_SUB_VTABLE_CORRECTED,
        ),
} # fmt: skip

module = ExtractUtilsModule(
    'a51',
    'samsung',
    namespace_imports=namespace_imports,
    blob_fixups=blob_fixups,
)

if __name__ == '__main__':
    utils = ExtractUtils.device_with_common(
        module, 'universal9611-common', module.vendor
    )
    utils.run()
