/* SPDX-License-Identifier: Apache-2.0 */
package org.hamelinports.samsung.ims;

import java.nio.charset.StandardCharsets;

/**
 * Encoder for the IIL frames the bridge sends to rild over
 * {@code ISehRadioChannel}.
 *
 * <p>Frame: a 7-byte header {@code [len_lo, len_hi, mseq, aseq, main,
 * sub, type]} followed by the sub-command body. {@code len} is the
 * little-endian total length, header included. The AP leaves both
 * sequence bytes at 0; rild logs the stock IMS frames as
 * {@code m:00 a:00}.
 *
 * <p>Field values follow the frames the stock IMS stack sends on this
 * device (rild hexdumps, 2026-04-18). Pure Java, so a host test can
 * compare the encoded bytes with those hexdumps.
 */
final class IilFrame {

    static final int HEADER_LEN = 7;

    static final byte MAIN_IIL         = (byte) 0x70;
    static final byte SUB_REGISTRATION = (byte) 0x01;
    static final byte SUB_PREFERENCE   = (byte) 0x06;
    /** rild decodes 0x03 as {@code (T)NOTI}. */
    static final byte TYPE_NOTI        = (byte) 0x03;

    /** Radio technologies on the bridge AIDL ({@code IImsModemBridge.RAT_*},
     *  RIL_RADIO_TECHNOLOGY values). */
    static final int RIL_RAT_LTE   = 14;
    static final int RIL_RAT_IWLAN = 18;
    static final int RIL_RAT_NR    = 20;

    /** The modem's RAT encoding: {@code TelephonyManager.NETWORK_TYPE_*}. */
    private static final int NETWORK_TYPE_UNKNOWN = 0;
    private static final int NETWORK_TYPE_LTE     = 13;
    private static final int NETWORK_TYPE_IWLAN   = 18;
    private static final int NETWORK_TYPE_NR      = 20;

    /* ---- REGISTRATION (sub 0x01), fixed 268-byte body ---- */
    static final int REG_BODY_LEN = 0x10C;
    private static final int REG_STATE        = 0;
    private static final int REG_FEATURES     = 1;
    private static final int REG_PDN_TYPE     = 2;
    private static final int REG_IMPU_LEN     = 10;
    private static final int REG_IMPU         = 11;
    private static final int REG_RAT          = 0x10B;
    /** The field spans 256 bytes, but its length is a single byte. */
    static final int MAX_IMPU_UTF8 = 0xFF;

    /** Feature bits at body[1]. */
    private static final int FEATURE_VOLTE = 0x01;
    private static final int FEATURE_SMSIP = 0x02;
    private static final int FEATURE_PSVT  = 0x08;

    /** The IMS PDN, as the legacy network type
     *  {@code ConnectivityManager.TYPE_MOBILE_IMS}. Stock sends it on
     *  registration and deregistration alike. */
    private static final byte PDN_TYPE_IMS = 11;

    /* ---- PREFERENCE (sub 0x06), 14-byte body ---- */
    static final int PREF_BODY_LEN = 14;
    private static final byte SMS_FORMAT_3GPP     = 0;
    private static final byte UNSET               = (byte) 0xFF; // -1
    private static final byte DOMAIN_PS_PREFERRED = 3;
    private static final byte DOMAIN_CS_PREFERRED = 1;
    private static final byte ECC_CS_PREFERRED    = 0;
    private static final int  SUPPORT_VOLTE       = 0x01;
    private static final int  SUPPORT_VIDEO       = 0x02;
    /** SRVCC capability level; stock reports 10. */
    private static final byte SRVCC_VERSION       = 10;
    /** Notification type after a successful REGISTER. */
    private static final byte NOTI_REGISTERED     = 3;

    private IilFrame() {}

    /** Maps a bridge RAT to the modem's encoding; unknown values map to 0. */
    static int modemRat(int rilRat) {
        switch (rilRat) {
            case RIL_RAT_LTE:   return NETWORK_TYPE_LTE;
            case RIL_RAT_IWLAN: return NETWORK_TYPE_IWLAN;
            case RIL_RAT_NR:    return NETWORK_TYPE_NR;
            default:            return NETWORK_TYPE_UNKNOWN;
        }
    }

    /** IPC_IIL_REGISTRATION. A deregistration ({@code registered} false)
     *  clears the features and the IMPU but keeps the RAT and PDN type. */
    static byte[] registration(boolean registered, int rilRat, boolean volte,
                               boolean smsIp, boolean video, String impuUri) {
        byte[] buf = frame(SUB_REGISTRATION, REG_BODY_LEN);
        int bo = HEADER_LEN;

        buf[bo + REG_STATE] = (byte) (registered ? 1 : 0);
        buf[bo + REG_FEATURES] = (byte) registrationFeatures(registered, volte, smsIp, video);
        buf[bo + REG_PDN_TYPE] = PDN_TYPE_IMS;
        /* [3..9] stay 0: no feature tag, no ECMP, not over ePDG, no
         * error code. */

        byte[] impu = (registered && impuUri != null)
                ? impuUri.getBytes(StandardCharsets.UTF_8) : new byte[0];
        int impuLen = Math.min(impu.length, MAX_IMPU_UTF8);
        buf[bo + REG_IMPU_LEN] = (byte) impuLen;
        System.arraycopy(impu, 0, buf, bo + REG_IMPU, impuLen);

        buf[bo + REG_RAT] = (byte) modemRat(rilRat);
        return buf;
    }

    /** IMPU length carried by a frame from {@link #registration}. */
    static int impuLength(byte[] registrationFrame) {
        return registrationFrame[HEADER_LEN + REG_IMPU_LEN] & 0xFF;
    }

    /** Feature bits sent at body[1]; 0 on deregistration. */
    static int registrationFeatures(boolean registered, boolean volte,
                                    boolean smsIp, boolean video) {
        if (!registered) return 0;
        int features = 0;
        if (volte) features |= FEATURE_VOLTE;
        if (smsIp) features |= FEATURE_SMSIP;
        if (video) features |= FEATURE_PSVT;
        return features;
    }

    /** IPC_IIL_PREFERENCE, as sent after a successful REGISTER. */
    static byte[] preference(boolean volte, boolean video, boolean smsOverIms) {
        byte[] buf = frame(SUB_PREFERENCE, PREF_BODY_LEN);
        int bo = HEADER_LEN;

        buf[bo + 0]  = SMS_FORMAT_3GPP;
        buf[bo + 1]  = (byte) (smsOverIms ? 1 : 0);
        buf[bo + 2]  = 0;                    // do not write SMS to the UICC
        buf[bo + 3]  = UNSET;                // SMS fallback
        /* EUTRAN PS-preferred makes the next TAU set "IMS voice over
         * PS session" (3GPP TS 24.301 §9.9.3.30). */
        buf[bo + 4]  = DOMAIN_PS_PREFERRED;  // EUTRAN voice domain
        buf[bo + 5]  = DOMAIN_CS_PREFERRED;  // UTRAN voice domain
        buf[bo + 6]  = DOMAIN_PS_PREFERRED;  // SS domain
        buf[bo + 7]  = DOMAIN_CS_PREFERRED;  // USSD domain
        buf[bo + 8]  = ECC_CS_PREFERRED;
        buf[bo + 9]  = UNSET;                // SS CSFB
        buf[bo + 10] = (byte) imsSupportType(volte, video);
        buf[bo + 11] = SRVCC_VERSION;
        buf[bo + 12] = 1;                    // VoLTE while roaming
        buf[bo + 13] = NOTI_REGISTERED;
        return buf;
    }

    /** IMS support bitmap at PREFERENCE body[10]. */
    static int imsSupportType(boolean volte, boolean video) {
        int type = 0;
        if (volte) type |= SUPPORT_VOLTE;
        if (video) type |= SUPPORT_VIDEO;
        return type;
    }

    /** A zeroed frame with the header filled in. */
    private static byte[] frame(byte sub, int bodyLen) {
        int total = HEADER_LEN + bodyLen;
        byte[] buf = new byte[total];
        buf[0] = (byte) (total & 0xFF);
        buf[1] = (byte) ((total >> 8) & 0xFF);
        buf[2] = 0; // mseq
        buf[3] = 0; // aseq
        buf[4] = MAIN_IIL;
        buf[5] = sub;
        buf[6] = TYPE_NOTI;
        return buf;
    }
}
