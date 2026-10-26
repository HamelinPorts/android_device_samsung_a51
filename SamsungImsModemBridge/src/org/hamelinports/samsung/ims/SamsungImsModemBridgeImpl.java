/* SPDX-License-Identifier: Apache-2.0 */
package org.hamelinports.samsung.ims;

import android.os.Binder;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Parcel;
import android.os.RemoteException;
import android.os.ServiceManager;
import android.util.Log;
import android.util.SparseArray;

import org.hamelinports.ims.modem.IImsModemBridge;
import org.hamelinports.ims.modem.IImsModemBridgeCallback;

import java.util.NoSuchElementException;

/**
 * IImsModemBridge implementation for Samsung A51-class hardware.
 *
 * <p>Tells the Shannon 9611 modem about IMS registration state so
 * the EPC routes MT voice as IMS INVITE rather than CSFB. Uses the
 * proprietary 2-method binder AIDL
 * {@code vendor.samsung.hardware.radio.channel.ISehRadioChannel}
 * hosted by rild, with service name {@code imsd} (slot 0) /
 * {@code imsd2} (slot 1). The on-wire format is the IIL protocol;
 * {@link IilFrame} encodes the frames.
 *
 * <p>Implements {@code IPC_IIL_REGISTRATION (0x01)} +
 * {@code IPC_IIL_PREFERENCE (0x06)}.
 *
 * <p>Slot demux: this Stub serves both slot 0 and slot 1 from a
 * single Service instance. Per-slot binder bindings (to imsd vs
 * imsd2) live in {@link #mSlots}; every call carries an explicit
 * slotId.
 *
 * <p>rild keeps the channel callback only for the lifetime of its
 * process. A death recipient on each channel re-acquires the service
 * after a rild restart and installs the callback again; without it
 * the new rild has no callback and drops modem-to-IMS indications.
 */
final class SamsungImsModemBridgeImpl extends IImsModemBridge.Stub {

    private static final String TAG = "SamsungImsModemBridge";

    /** ISehRadioChannel AIDL descriptor + transaction codes. */
    private static final String DESCRIPTOR =
            "vendor.samsung.hardware.radio.channel.ISehRadioChannel";
    private static final String CALLBACK_DESCRIPTOR =
            "vendor.samsung.hardware.radio.channel.ISehRadioChannelCallback";
    private static final int TXN_SET_CALLBACK = IBinder.FIRST_CALL_TRANSACTION;     // 0x01
    private static final int TXN_SEND         = IBinder.FIRST_CALL_TRANSACTION + 1; // 0x02
    private static final int CB_TXN_RECEIVE   = IBinder.FIRST_CALL_TRANSACTION;     // 0x01

    /** Re-bind backoff after losing a channel or a refused setCallback:
     *  0.5 s doubling to 8 s, ~2 min in total, which covers a rild +
     *  modem restart. Past that the next send re-binds lazily. */
    private static final long REBIND_INITIAL_DELAY_MS = 500;
    private static final long REBIND_MAX_DELAY_MS = 8_000;
    private static final int REBIND_MAX_ATTEMPTS = 20;

    /** Per-slot state — separate binder + callback pair per imsd
     *  service so dual-SIM dispatch doesn't cross-contaminate. */
    private static final class SlotState {
        final int slotId;
        IBinder binder;
        IBinder.DeathRecipient deathRecipient;
        /** rild holds our callback on {@link #binder}. */
        boolean callbackInstalled;
        /** Set by {@code stop()}: a lost channel is not re-bound. */
        boolean stopped;
        /** Current re-bind attempt; 0 while no re-bind is pending. */
        int rebindAttempt;
        final Binder callbackStub;
        SlotState(int slotId) {
            this.slotId = slotId;
            this.callbackStub = new Binder() {
                {
                    attachInterface(null, CALLBACK_DESCRIPTOR);
                }
                @Override
                protected boolean onTransact(int code, Parcel data, Parcel reply, int flags)
                        throws RemoteException {
                    if (code == INTERFACE_TRANSACTION) {
                        reply.writeString(CALLBACK_DESCRIPTOR);
                        return true;
                    }
                    if (code == CB_TXN_RECEIVE) {
                        data.enforceInterface(CALLBACK_DESCRIPTOR);
                        byte[] bytes = data.createByteArray();
                        int n = bytes != null ? bytes.length : 0;
                        if (n < 5) {
                            Log.i(TAG, "<-- rild slot=" + slotId + ": " + n + " bytes (short)");
                        } else {
                            int len = (bytes[0] & 0xFF) | ((bytes[1] & 0xFF) << 8);
                            int main = bytes[2] & 0xFF;
                            int sub  = bytes[3] & 0xFF;
                            int type = bytes[4] & 0xFF;
                            StringBuilder hex = new StringBuilder();
                            for (int i = 0; i < Math.min(n, 64); i++) {
                                hex.append(String.format(" %02x", bytes[i]));
                            }
                            if (n > 64) hex.append(" …");
                            Log.i(TAG, "<-- rild slot=" + slotId
                                    + " len=" + n
                                    + " hdr_len=" + len
                                    + String.format(" main=0x%02x sub=0x%02x type=0x%02x",
                                            main, sub, type)
                                    + " hex:" + hex);
                        }
                        return true;
                    }
                    return super.onTransact(code, data, reply, flags);
                }
            };
        }
    }

    private final Object mLock = new Object();
    private final SparseArray<SlotState> mSlots = new SparseArray<>();

    /** Re-binds run off the main thread: this service shares the IMS
     *  process, and a re-bind makes a synchronous call into rild. */
    private final HandlerThread mRebindThread = new HandlerThread(TAG + "-rebind");
    private final Handler mRebindHandler;

    /** Reports the death of one specific channel binder. */
    private final class ChannelDeathRecipient implements IBinder.DeathRecipient {
        private final int mSlotId;
        private final IBinder mChannel;

        ChannelDeathRecipient(int slotId, IBinder channel) {
            mSlotId = slotId;
            mChannel = channel;
        }

        @Override
        public void binderDied() {
            synchronized (mLock) {
                SlotState s = mSlots.get(mSlotId);
                /* Ignore a death that arrives after the slot moved on
                 * to a newer binder. */
                if (s == null || s.binder != mChannel) return;
                loseChannelLocked(s, "rild died");
            }
        }
    }

    SamsungImsModemBridgeImpl() {
        mRebindThread.start();
        mRebindHandler = new Handler(mRebindThread.getLooper());
    }

    /** Drops every channel and stops the re-bind thread. */
    void shutdown() {
        synchronized (mLock) {
            for (int i = 0; i < mSlots.size(); i++) {
                SlotState s = mSlots.valueAt(i);
                s.stopped = true;
                s.rebindAttempt = 0;
                dropChannelLocked(s);
            }
            mRebindHandler.removeCallbacksAndMessages(null);
        }
        mRebindThread.quitSafely();
    }

    @Override
    public void start(int slotId) {
        Log.i(TAG, "start slot=" + slotId);
        synchronized (mLock) {
            SlotState s = slotLocked(slotId);
            s.stopped = false;
            connectLocked(s, true);
        }
    }

    @Override
    public void stop(int slotId) {
        Log.i(TAG, "stop slot=" + slotId);
        synchronized (mLock) {
            SlotState s = mSlots.get(slotId);
            if (s == null) return;
            s.stopped = true;
            s.rebindAttempt = 0;
            mRebindHandler.removeCallbacksAndMessages(s);
            dropChannelLocked(s);
        }
    }

    /** Returns the live channel binder for the slot, binding it on
     *  demand; null if rild does not serve it right now. */
    private IBinder bind(int slotId) {
        synchronized (mLock) {
            return connectLocked(slotLocked(slotId), true);
        }
    }

    private SlotState slotLocked(int slotId) {
        SlotState s = mSlots.get(slotId);
        if (s == null) {
            s = new SlotState(slotId);
            mSlots.put(slotId, s);
        }
        return s;
    }

    private static String serviceName(int slotId) {
        return DESCRIPTOR + "/" + (slotId == 0 ? "imsd" : "imsd2");
    }

    /** Bind the slot's channel and install the callback. Returns the
     *  live binder, or null if rild does not serve the slot right now.
     *
     *  <p>A binder that refused setCallback is still returned, so sends
     *  go out, but the slot counts as re-bound only once rild holds the
     *  callback; until then the bounded re-bind retries it. */
    private IBinder connectLocked(SlotState s, boolean logMissing) {
        if (s.binder != null && !s.binder.isBinderAlive()) {
            /* Dead, but the death notice has not been delivered yet. */
            loseChannelLocked(s, "rild died");
        }
        if (s.binder == null && !acquireLocked(s, logMissing)) return null;
        if (s.callbackInstalled) return s.binder;

        s.callbackInstalled = installCallbackLocked(s);
        if (!s.callbackInstalled) {
            /* A pending re-bind reschedules itself in rebind(). */
            if (!s.stopped && s.rebindAttempt == 0) scheduleRebindLocked(s);
            return s.binder;
        }
        if (s.rebindAttempt != 0) {
            Log.i(TAG, "slot=" + s.slotId + " re-bound " + serviceName(s.slotId)
                    + " (attempt " + s.rebindAttempt + ")");
            s.rebindAttempt = 0;
            mRebindHandler.removeCallbacksAndMessages(s);
        }
        return s.binder;
    }

    /** Look up the rild-hosted binder for the slot and watch it for
     *  death. Uses {@code checkService} (non-blocking) so a missing
     *  service on a slot with no SIM doesn't wedge us forever. */
    private boolean acquireLocked(SlotState s, boolean logMissing) {
        String name = serviceName(s.slotId);
        IBinder b;
        try {
            b = ServiceManager.checkService(name);
        } catch (Throwable t) {
            Log.w(TAG, "checkService threw for " + name, t);
            return false;
        }
        if (b == null) {
            if (logMissing) Log.w(TAG, "service not yet declared: " + name);
            return false;
        }

        IBinder.DeathRecipient recipient = new ChannelDeathRecipient(s.slotId, b);
        try {
            b.linkToDeath(recipient, 0);
        } catch (RemoteException e) {
            loseChannelLocked(s, name + " died while binding");
            return false;
        }
        s.binder = b;
        s.deathRecipient = recipient;
        Log.i(TAG, "slot=" + s.slotId + " bound to " + name);
        return true;
    }

    /** Install the per-slot callback so any modem-originated IIL
     *  messages on this slot's channel surface as log lines. Returns
     *  whether rild accepted it. */
    private static boolean installCallbackLocked(SlotState s) {
        Parcel data = Parcel.obtain();
        Parcel reply = Parcel.obtain();
        try {
            data.writeInterfaceToken(DESCRIPTOR);
            data.writeStrongBinder(s.callbackStub);
            if (s.binder.transact(TXN_SET_CALLBACK, data, reply, 0)) {
                reply.readException();
                Log.i(TAG, "slot=" + s.slotId + " setCallback OK");
                return true;
            }
            Log.w(TAG, "slot=" + s.slotId + " setCallback transact false");
        } catch (RemoteException | RuntimeException e) {
            Log.w(TAG, "slot=" + s.slotId + " setCallback failed", e);
        } finally {
            reply.recycle();
            data.recycle();
        }
        return false;
    }

    /** Forget the slot's binder without scheduling anything. */
    private static void dropChannelLocked(SlotState s) {
        if (s.binder != null && s.deathRecipient != null) {
            try {
                s.binder.unlinkToDeath(s.deathRecipient, 0);
            } catch (NoSuchElementException ignored) {
                /* Already unlinked by the binder's death. */
            }
        }
        s.binder = null;
        s.deathRecipient = null;
        s.callbackInstalled = false;
    }

    /** Forget the slot's binder and, unless the slot is stopped or a
     *  re-bind is already pending, start re-binding it. */
    private void loseChannelLocked(SlotState s, String reason) {
        dropChannelLocked(s);
        if (s.stopped || s.rebindAttempt != 0) return;
        Log.w(TAG, "slot=" + s.slotId + " channel lost (" + reason + "), re-binding");
        scheduleRebindLocked(s);
    }

    private void scheduleRebindLocked(SlotState s) {
        if (s.rebindAttempt >= REBIND_MAX_ATTEMPTS) {
            Log.e(TAG, "slot=" + s.slotId + " re-bind gave up after "
                    + s.rebindAttempt + " attempts; the next send retries");
            s.rebindAttempt = 0;
            return;
        }
        s.rebindAttempt++;
        long delay = Math.min(REBIND_INITIAL_DELAY_MS << Math.min(s.rebindAttempt - 1, 16),
                REBIND_MAX_DELAY_MS);
        final int slotId = s.slotId;
        mRebindHandler.removeCallbacksAndMessages(s);
        mRebindHandler.postDelayed(() -> rebind(slotId), s, delay);
    }

    private void rebind(int slotId) {
        synchronized (mLock) {
            SlotState s = mSlots.get(slotId);
            if (s == null || s.stopped || s.rebindAttempt == 0) return;
            connectLocked(s, false);
            if (!s.callbackInstalled) scheduleRebindLocked(s);
        }
    }

    @Override
    public void sendRegistration(int slotId, boolean registered, int rat,
                                 boolean volte, boolean smsIp,
                                 boolean video, String impuUri) {
        IBinder binder = bind(slotId);
        if (binder == null) {
            Log.w(TAG, "sendRegistration slot=" + slotId + ": not bound, dropping");
            return;
        }
        try {
            byte[] buf = IilFrame.registration(registered, rat, volte, smsIp, video, impuUri);

            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeByteArray(buf);
                boolean ok = binder.transact(TXN_SEND, data, reply,
                        IBinder.FLAG_ONEWAY);
                if (ok) {
                    Log.i(TAG, "REGISTRATION sent slot=" + slotId
                            + " reg=" + registered
                            + " rat=" + rat
                            + " modemRat=" + IilFrame.modemRat(rat)
                            + " flags=0x" + Integer.toHexString(IilFrame.registrationFeatures(
                                    registered, volte, smsIp, video))
                            + " impuLen=" + IilFrame.impuLength(buf)
                            + " len=" + buf.length);
                } else {
                    Log.w(TAG, "slot=" + slotId + " transact returned false");
                }
            } finally {
                reply.recycle();
                data.recycle();
            }
        } catch (RemoteException | RuntimeException e) {
            Log.w(TAG, "sendRegistration slot=" + slotId + " failed", e);
            invalidate(slotId, binder);
        }
    }

    @Override
    public void sendPreference(int slotId, boolean volte, boolean video,
                               boolean smsOverIms) {
        IBinder binder = bind(slotId);
        if (binder == null) {
            Log.w(TAG, "sendPreference slot=" + slotId + ": not bound, dropping");
            return;
        }
        try {
            byte[] buf = IilFrame.preference(volte, video, smsOverIms);

            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeByteArray(buf);
                boolean ok = binder.transact(TXN_SEND, data, reply,
                        IBinder.FLAG_ONEWAY);
                Log.i(TAG, "PREFERENCE sent slot=" + slotId
                        + " volte=" + volte + " video=" + video
                        + " smsIp=" + smsOverIms
                        + " supportType=0x" + Integer.toHexString(
                                IilFrame.imsSupportType(volte, video))
                        + " ok=" + ok);
            } finally {
                reply.recycle();
                data.recycle();
            }
        } catch (RemoteException | RuntimeException e) {
            Log.w(TAG, "sendPreference slot=" + slotId + " failed", e);
            invalidate(slotId, binder);
        }
    }

    /** Drop a binder whose send failed and re-bind the slot. A newer
     *  binder bound meanwhile is kept. */
    private void invalidate(int slotId, IBinder failed) {
        synchronized (mLock) {
            SlotState s = mSlots.get(slotId);
            if (s == null || s.binder != failed) return;
            loseChannelLocked(s, "send failed");
        }
    }

    @Override
    public void registerCallback(IImsModemBridgeCallback cb) {
        /* Modem-originated indications would surface here. Today
         * the per-slot receive() callbacks above only log; future
         * work can forward selected events to LineageImsService. */
    }

    @Override
    public void unregisterCallback(IImsModemBridgeCallback cb) {}
}
