/*
 * SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

/*
 * android::AHandler::deliverMessage() for the vendor face closure.
 *
 * The face prebuilt derives from AHandler and puts its own first member at
 * offset 0x60, which is where the current AOSP class keeps mLock and the three
 * delivery-status fields. Locking mLock there mutates the subclass' own state
 * and then blocks forever on it, so the handler never dispatches at all.
 *
 * This is upstream's deliverMessage() with every access at or beyond offset
 * 0x60 removed. The dispatch and the statistics below that offset are kept
 * verbatim, because the prebuilt's view of AHandler covers them.
 */

#include <media/stagefright/foundation/AHandler.h>
#include <media/stagefright/foundation/AMessage.h>

namespace android {

void AHandler::deliverMessage(const sp<AMessage> &msg) {
    onMessageReceived(msg);
    mMessageCounter++;

    if (mVerboseStats) {
        uint32_t what = msg->what();
        ssize_t idx = mMessages.indexOfKey(what);
        if (idx < 0) {
            mMessages.add(what, 1);
        } else {
            mMessages.editValueAt(idx)++;
        }
    }
}

}  // namespace android
