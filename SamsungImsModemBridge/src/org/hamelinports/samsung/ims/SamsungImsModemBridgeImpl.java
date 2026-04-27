/* SPDX-License-Identifier: Apache-2.0 */
package org.hamelinports.samsung.ims;

import android.os.Binder;
import android.os.IBinder;
import android.os.Parcel;
import android.os.RemoteException;
import android.os.ServiceManager;
import android.util.Log;
import android.util.SparseArray;

import org.hamelinports.ims.modem.IImsModemBridge;
import org.hamelinports.ims.modem.IImsModemBridgeCallback;

import java.nio.charset.StandardCharsets;

/**
 * IImsModemBridge implementation for Samsung A51-class hardware.
 *
 * <p>Tells the Shannon 9611 modem about IMS registration state so
 * the EPC routes MT voice as IMS INVITE rather than CSFB. Uses the
 * proprietary 2-method binder AIDL
 * {@code vendor.samsung.hardware.radio.channel.ISehRadioChannel}
 * hosted by rild, with service name {@code imsd} (slot 0) /
 * {@code imsd2} (slot 1). The on-wire format is the IIL protocol:
 * 5-byte header {@code [len_lo, len_hi, 0x70 main, sub, 0x03 type=EXEC]}
 * followed by the subcommand body.
 *
 * <p>Implements {@code IPC_IIL_REGISTRATION (0x01)} +
 * {@code IPC_IIL_PREFERENCE (0x06)} — the two load-bearing messages
 * for MT routing on Samsung's stack.
 *
 * <p>Slot demux: this Stub serves both slot 0 and slot 1 from a
 * single Service instance. Per-slot binder bindings (to imsd vs
 * imsd2) live in {@link #mSlots}; every call carries an explicit
 * slotId.
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

    /** IIL protocol constants. */
    private static final byte MAIN_IIL          = (byte) 0x70;
    private static final byte TYPE_EXEC         = (byte) 0x03;
    private static final byte SUB_REGISTRATION  = (byte) 0x01;
    private static final byte SUB_PREFERENCE    = (byte) 0x06;

    /** Feature-flags bit positions at body[1] of REGISTRATION. */
    private static final int FLAG_VOLTE  = 0x01;
    private static final int FLAG_SMSIP  = 0x02;
    private static final int FLAG_RCS    = 0x04;
    private static final int FLAG_PSVT   = 0x08;
    private static final int FLAG_CDPN   = 0x20;

    /** FeatureTag bitmap values at body[3] of REGISTRATION. */
    private static final int FTAG_CS     = 0x01;
    private static final int FTAG_SMSIP  = 0x02;
    private static final int FTAG_VOLTE  = 0x04;
    private static final int FTAG_VIDEO  = 0x08;
    private static final int FTAG_MMTEL  = 0x10;

    /** Body is fixed-width regardless of URI length. */
    private static final int BODY_LEN = 0x10C; // 268
    private static final int HEADER_LEN = 5;
    private static final int TOTAL_LEN = HEADER_LEN + BODY_LEN; // 273
    private static final int MAX_URI_UTF8 = 256;

    /** Per-slot state — separate binder + callback pair per imsd
     *  service so dual-SIM dispatch doesn't cross-contaminate. */
    private static final class SlotState {
        final int slotId;
        IBinder binder;
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

    @Override
    public void start(int slotId) {
        Log.i(TAG, "start slot=" + slotId);
        bind(slotId);
    }

    @Override
    public void stop(int slotId) {
        Log.i(TAG, "stop slot=" + slotId);
        synchronized (mLock) {
            SlotState s = mSlots.get(slotId);
            if (s != null) s.binder = null;
        }
    }

    /** Look up the rild-hosted binder for the given slot. Uses
     *  {@code checkService} (non-blocking) so a missing service on a
     *  slot with no SIM doesn't wedge us forever. Returns the live
     *  binder or null. */
    private IBinder bind(int slotId) {
        synchronized (mLock) {
            SlotState s = mSlots.get(slotId);
            if (s == null) {
                s = new SlotState(slotId);
                mSlots.put(slotId, s);
            }
            if (s.binder != null && s.binder.isBinderAlive()) return s.binder;

            String name = DESCRIPTOR + "/" + (slotId == 0 ? "imsd" : "imsd2");
            IBinder b;
            try {
                b = ServiceManager.checkService(name);
            } catch (Throwable t) {
                Log.w(TAG, "checkService threw for " + name, t);
                return null;
            }
            if (b == null) {
                Log.w(TAG, "service not yet declared: " + name);
                return null;
            }
            s.binder = b;
            Log.i(TAG, "slot=" + slotId + " bound to " + name);

            /* Install the per-slot callback so any modem-originated
             * IIL messages on this slot's channel surface as log
             * lines. */
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeStrongBinder(s.callbackStub);
                boolean ok = s.binder.transact(TXN_SET_CALLBACK, data, reply, 0);
                if (ok) {
                    reply.readException();
                    Log.i(TAG, "slot=" + slotId + " setCallback OK");
                } else {
                    Log.w(TAG, "slot=" + slotId + " setCallback transact false");
                }
            } catch (RemoteException | RuntimeException e) {
                Log.w(TAG, "slot=" + slotId + " setCallback failed", e);
            } finally {
                reply.recycle();
                data.recycle();
            }
            return s.binder;
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
            byte[] buf = new byte[TOTAL_LEN];

            /* IIL 5-byte header. Total-length is little-endian u16. */
            buf[0] = (byte) (TOTAL_LEN & 0xFF);
            buf[1] = (byte) ((TOTAL_LEN >> 8) & 0xFF);
            buf[2] = MAIN_IIL;
            buf[3] = SUB_REGISTRATION;
            buf[4] = TYPE_EXEC;

            int bo = HEADER_LEN; // body origin

            buf[bo + 0] = 0; // LimitedMode

            int flags = 0;
            if (registered) {
                if (volte) flags |= FLAG_VOLTE;
                if (smsIp) flags |= FLAG_SMSIP;
            }
            buf[bo + 1] = (byte) flags;

            /* PdnType — 0 maps to "no specific PDN type declared".
             * Empirically accepted on pre-IPv4v6 setups. */
            buf[bo + 2] = 0;

            /* FeatureTag bitmap — capability set for this REGISTER.
             * Only populate when registered; dereg sends zeros. */
            int ftag = 0;
            if (registered) {
                if (smsIp) ftag |= FTAG_SMSIP;
                if (volte) ftag |= FTAG_VOLTE | FTAG_MMTEL;
                if (video) ftag |= FTAG_VIDEO;
            }
            buf[bo + 3] = (byte) ftag;

            buf[bo + 4] = 0; // Ecmp
            buf[bo + 5] = 0; // EpdgMode
            /* [6..7] ErrorCode big-endian u16; 0 = success. */
            buf[bo + 6] = 0;
            buf[bo + 7] = 0;
            /* [8..9] reserved. */
            buf[bo + 8] = 0;
            buf[bo + 9] = 0;

            /* [10] IMPU UTF-8 length + [11..] IMPU UTF-8. */
            byte[] impu = (impuUri != null && registered)
                    ? impuUri.getBytes(StandardCharsets.UTF_8) : new byte[0];
            int impuLen = Math.min(impu.length, MAX_URI_UTF8);
            buf[bo + 10] = (byte) impuLen;
            System.arraycopy(impu, 0, buf, bo + 11, impuLen);

            /* [0x10B] RegiRat. */
            buf[bo + 0x10B] = (byte) (registered ? rat : 0);

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
                            + " flags=0x" + Integer.toHexString(flags)
                            + " ftag=0x" + Integer.toHexString(ftag)
                            + " impuLen=" + impuLen);
                } else {
                    Log.w(TAG, "slot=" + slotId + " transact returned false");
                }
            } finally {
                reply.recycle();
                data.recycle();
            }
        } catch (RemoteException | RuntimeException e) {
            Log.w(TAG, "sendRegistration slot=" + slotId + " failed", e);
            invalidate(slotId);
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
            /* 5-byte header + 14-byte body = 19 total */
            final int PREF_BODY_LEN = 14;
            final int TOTAL = HEADER_LEN + PREF_BODY_LEN;
            byte[] buf = new byte[TOTAL];
            buf[0] = (byte) (TOTAL & 0xFF);
            buf[1] = (byte) ((TOTAL >> 8) & 0xFF);
            buf[2] = MAIN_IIL;
            buf[3] = SUB_PREFERENCE;
            buf[4] = TYPE_EXEC;
            int bo = HEADER_LEN;
            /* [0] SmsFormat — 3GPP TP format. */
            buf[bo + 0] = 0;
            /* [1] SmsOverIms — 1 enables SIP MESSAGE path. */
            buf[bo + 1] = (byte) (smsOverIms ? 1 : 0);
            /* [2] SmsWriteUicc — don't write incoming SMS to SIM. */
            buf[bo + 2] = 0;
            /* [3] SmsFallbackPreference — no CS fallback for SMS. */
            buf[bo + 3] = 0;
            /* [4] EutranDomain — load-bearing byte: 3 = PS-voice-
             * preferred for LTE, drives "IMS Voice over PS Session
             * Indicator" = 1 in the next NAS TAU
             * (3GPP TS 24.301 §9.9.3.30). */
            buf[bo + 4] = (byte) 3;
            /* [5] UtranDomain — 1 = CS preferred on 3G. */
            buf[bo + 5] = (byte) 1;
            /* [6] SsDomain — PS = byte 0. */
            buf[bo + 6] = 0;
            /* [7] UssdDomain — CS = 1 (standard). */
            buf[bo + 7] = (byte) 1;
            /* [8] EccPreference — 0 = CS-preferred emergency. */
            buf[bo + 8] = 0;
            /* [9] SsCsfb — 0 = SS stays on PS if registered. */
            buf[bo + 9] = 0;
            /* [10] ImsSupportType bitmap: bit0=VoLTE bit1=Video. */
            int supportType = 0;
            if (volte) supportType |= 0x01;
            if (video) supportType |= 0x02;
            buf[bo + 10] = (byte) supportType;
            /* [11] SrvccVersion — 0 until negotiated. */
            buf[bo + 11] = 0;
            /* [12] SupportVolteRoaming — 0 = home-only. */
            buf[bo + 12] = 0;
            /* [13] notification type = 3 (post-register notify). */
            buf[bo + 13] = (byte) 3;

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
                        + " supportType=0x" + Integer.toHexString(supportType)
                        + " ok=" + ok);
            } finally {
                reply.recycle();
                data.recycle();
            }
        } catch (RemoteException | RuntimeException e) {
            Log.w(TAG, "sendPreference slot=" + slotId + " failed", e);
            invalidate(slotId);
        }
    }

    /** Drop the cached binder on remote death; next call will
     *  re-bind via ServiceManager.checkService. */
    private void invalidate(int slotId) {
        synchronized (mLock) {
            SlotState s = mSlots.get(slotId);
            if (s != null) s.binder = null;
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
