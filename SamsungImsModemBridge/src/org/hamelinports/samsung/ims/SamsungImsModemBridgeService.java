/* SPDX-License-Identifier: Apache-2.0 */
package org.hamelinports.samsung.ims;

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.util.Log;

import org.hamelinports.ims.modem.IImsModemBridge;

/**
 * Android Service host for the Samsung IIL→modem bridge. Returns a
 * single shared {@link SamsungImsModemBridgeImpl} instance to every
 * binder. Per-slot state inside the impl is keyed off the slotId
 * passed to {@link IImsModemBridge#start(int)}.
 */
public final class SamsungImsModemBridgeService extends Service {
    private static final String TAG = "SamsungImsModemBridge";

    private SamsungImsModemBridgeImpl mImpl;

    @Override
    public void onCreate() {
        super.onCreate();
        mImpl = new SamsungImsModemBridgeImpl();
        Log.i(TAG, "service onCreate");
    }

    @Override
    public IBinder onBind(Intent intent) {
        Log.i(TAG, "service onBind " + (intent != null ? intent.getAction() : "null"));
        return mImpl;
    }

    @Override
    public void onDestroy() {
        Log.i(TAG, "service onDestroy");
        super.onDestroy();
    }
}
