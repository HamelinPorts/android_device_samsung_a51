/*
 * SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

/*
 * Layout guard for libsecfr_ahandler_compat, together with the two
 * delivery-status entry points it neutralises.
 *
 * Guard and stubs share a translation unit because AHandler keeps its fields
 * private: a member-function body is the only context in which their names are
 * legally visible, and the AOSP header is not ours to edit.
 *
 * Why the guard has to exist: this library is only correct while AHandler's
 * first 0x60 bytes hold exactly the fields the vendor face prebuilt was
 * compiled against. Appending or moving an AHandler field upstream produces no
 * merge conflict and no link error here, so the library would keep building
 * and silently stop being a fix. These assertions turn that drift into a build
 * failure.
 */

#include <media/stagefright/foundation/AHandler.h>

#include <stddef.h>

namespace android {

void AHandler::setDeliveryStatus(bool /* delivering */, uint32_t /* what */,
                                 int64_t /* startUs */) {
    static_assert(sizeof(AHandler) == 152,
                  "AHandler changed size: the vendor face prebuilt places its own "
                  "members at 0x60, so re-check the whole overlap before touching "
                  "this number");
    static_assert(offsetof(AHandler, mVerboseStats) == 0x28,
                  "AHandler::mVerboseStats moved");
    static_assert(offsetof(AHandler, mMessageCounter) == 0x30,
                  "AHandler::mMessageCounter moved");
    static_assert(offsetof(AHandler, mMessages) == 0x38,
                  "AHandler::mMessages moved");
    // The boundary the whole shim rests on: everything the prebuilt shares a
    // view of with us has to end here, because from 0x60 on the prebuilt uses
    // the storage for its own members.
    static_assert(offsetof(AHandler, mLock) == 0x60,
                  "AHandler::mLock moved: the base fields no longer end at "
                  "0x60, so the prebuilt's members and ours overlap somewhere "
                  "new and deliverMessage() has to be re-derived");
}

void AHandler::getDeliveryStatus(bool &delivering, uint32_t &what, int64_t &durationUs) {
    // No delivery is tracked here, so report an idle handler rather than
    // leaving the caller's variables uninitialised.
    delivering = false;
    what = 0;
    durationUs = 0;
}

}  // namespace android
