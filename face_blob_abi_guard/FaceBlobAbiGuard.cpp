/*
 * SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

/*
 * Build guard for the libgui ABI that vendor/lib64/libFaceService.so has baked
 * into its own code.
 *
 * FaceDisplayManager::getANativeWindow() builds an
 * android::hardware::graphics::bufferqueue::V1_0::utils::H2BGraphicBufferProducer
 * by hand: it stores three sub-table pointers taken as fixed displacements from
 * the vtable symbol, into fixed offsets of a fixed-size allocation. Those
 * displacements are corrected for our libgui by the binary_regex_replace in
 * device/samsung/a51/extract-files.py. That fixup runs at extraction time, when
 * no libgui_vendor.so exists yet, so it cannot verify its own constants -- this
 * file does it instead, against the library that was actually built.
 *
 * The measured side comes from face_blob_abi_guard.h, which
 * derive_face_blob_abi.py generates out of the built libgui_vendor.so. The
 * expected side is here, and only here.
 *
 * Why a build guard and not a review note: extendSlotCount() is compiled in
 * behind the read-only aconfig flag
 * COM_ANDROID_GRAPHICS_LIBGUI_FLAGS(WB_UNLIMITED_SLOTS)
 * (frameworks/native/libs/gui/libgui_flags.aconfig). Flipping that flag adds a
 * virtual function, which shifts every secondary sub-table, with no source
 * diff, no merge conflict and no link error. Nothing else in the build would
 * notice; the crash would land on the device.
 */

#include <face_blob_abi_guard.h>

namespace a51::face_blob_abi {

/*
 * The three displacements the patched blob uses. Each is the offset from the
 * H2BGraphicBufferProducer vtable symbol to one sub-table's first function
 * pointer.
 */
static_assert(kH2BPrimaryVTableOffset == 0x18,
              "H2BGraphicBufferProducer primary vtable moved: re-derive the "
              "add immediates patched into libFaceService.so");
static_assert(kH2BBBinderVTableOffset == 0x1a0,
              "H2BGraphicBufferProducer BBinder sub-vtable moved: the "
              "'add x9, x9, #0x1a0' patched into libFaceService.so is now "
              "wrong, and the HAL will fault on the first incStrong()");
static_assert(kH2BRefBaseVTableOffset == 0x260,
              "H2BGraphicBufferProducer RefBase sub-vtable moved: the "
              "'add x10, x9, #0x260' patched into libFaceService.so is now "
              "wrong, and the HAL will fault on the first incStrong()");

/*
 * Where the blob stores those pointers. It writes the BBinder vptr at
 * object + 8 and the RefBase vptr at object + 104, so the base subobjects have
 * to sit exactly there.
 */
static_assert(kH2BBBinderSubobjectOffset == 8,
              "BBinder no longer starts at offset 8 of "
              "H2BGraphicBufferProducer");
static_assert(kH2BRefBaseSubobjectOffset == 104,
              "the RefBase virtual base no longer starts at offset 104 of "
              "H2BGraphicBufferProducer");

/*
 * And how much room it reserves for the whole object. The subobject offsets
 * above pin where the bases start; this pins where the object ends.
 */
static_assert(kH2BSize == 120,
              "H2BGraphicBufferProducer changed size: it no longer fits the "
              "fixed allocation libFaceService.so constructs it in");

/*
 * The blob's own constructor drives its remaining vptr writes off VTT indices
 * rather than displacements, so it stays correct only while the VTT has the
 * same 20 entries in the same order.
 */
static_assert(kH2BVttSize == 160,
              "H2BGraphicBufferProducer VTT changed size: the index-driven "
              "vptr writes in libFaceService.so no longer line up");

/*
 * The blob allocates a fixed 8168 bytes and constructs a Surface in it. We have
 * no way to correct that number, so all that can be done is to notice before it
 * becomes a heap overflow on the device.
 */
static_assert(kSurfaceSize <= 8168,
              "android::Surface outgrew the fixed 8168-byte allocation "
              "libFaceService.so makes for it");

}  // namespace a51::face_blob_abi
