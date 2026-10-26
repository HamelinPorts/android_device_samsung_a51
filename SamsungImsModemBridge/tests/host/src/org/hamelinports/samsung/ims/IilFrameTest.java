/* SPDX-License-Identifier: Apache-2.0 */
package org.hamelinports.samsung.ims;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;

import org.junit.Test;

/**
 * Compares the encoded IIL frames with the frames rild logged from the
 * stock IMS stack on this device ({@code [I] RX: (M)IIL_CMD ...},
 * 2026-04-18). rild prints the header fields and at most 30 body bytes.
 */
public final class IilFrameTest {

    /** rild: {@code (S)IIL_PREFERENCE (T)NOTI l:15 m:00 a:00}, body in full. */
    private static final String STOCK_PREFERENCE =
            "15 00 00 00 70 06 03"
            + " 00 01 00 FF 03 01 03 01 00 FF 03 0A 01 03";

    /** rild: {@code (S)IIL_REGISTRATION (T)NOTI l:113 m:00 a:00}, body[0..10]
     *  of a registration on LTE; body[11..] is the IMPU. */
    private static final String STOCK_REGISTRATION_HEAD =
            "13 01 00 00 70 01 03"
            + " 01 0B 0B 00 00 00 00 00 00 00 35";

    /** The same frame after a requested deregistration (SIP 200), body[0..29]. */
    private static final String STOCK_DEREGISTRATION_HEAD =
            "13 01 00 00 70 01 03"
            + " 00 00 0B 00 00 00 00 02 00 C8 00 00 00 00 00 00 00 00 00 00"
            + " 00 00 00 00 00 00 00 00 00 00";

    /** Stock logs {@code rat=13} for both REGISTRATION frames. */
    private static final int STOCK_RAT = 13;

    /** Stock fills the IMPU with its IMSI-derived identity (53 bytes). This
     *  one has the same shape on the test PLMN 001/01. */
    private static final String IMSI_DERIVED_IMPU =
            "sip:001010123456789@ims.mnc001.mcc001.3gppnetwork.org";

    private static final int HDR = IilFrame.HEADER_LEN;
    private static final int RAT_OFFSET = HDR + 0x10B;

    @Test
    public void preferenceMatchesStock() {
        byte[] frame = IilFrame.preference(/*volte=*/ true, /*video=*/ true,
                /*smsOverIms=*/ true);
        assertArrayEquals(hex(STOCK_PREFERENCE), frame);
    }

    @Test
    public void preferenceWithoutVideoOnlyClearsTheVideoBit() {
        byte[] expected = hex(STOCK_PREFERENCE);
        expected[HDR + 10] = 0x01;
        assertArrayEquals(expected, IilFrame.preference(true, false, true));
    }

    @Test
    public void registrationMatchesStock() {
        byte[] frame = IilFrame.registration(/*registered=*/ true,
                IilFrame.RIL_RAT_LTE, /*volte=*/ true, /*smsIp=*/ true,
                /*video=*/ true, IMSI_DERIVED_IMPU);

        byte[] impu = IMSI_DERIVED_IMPU.getBytes(StandardCharsets.US_ASCII);
        byte[] expected = new byte[HDR + IilFrame.REG_BODY_LEN];
        byte[] head = hex(STOCK_REGISTRATION_HEAD);
        System.arraycopy(head, 0, expected, 0, head.length);
        System.arraycopy(impu, 0, expected, head.length, impu.length);
        expected[RAT_OFFSET] = (byte) STOCK_RAT;

        assertEquals(0x35, impu.length);
        assertArrayEquals(expected, frame);
    }

    @Test
    public void registrationWithoutVideoOnlyClearsThePsvtBit() {
        byte[] withVideo = IilFrame.registration(true, IilFrame.RIL_RAT_LTE,
                true, true, true, IMSI_DERIVED_IMPU);
        byte[] expected = withVideo.clone();
        expected[HDR + 1] = 0x03;
        assertArrayEquals(expected, IilFrame.registration(true,
                IilFrame.RIL_RAT_LTE, true, true, false, IMSI_DERIVED_IMPU));
    }

    /** Stock also carries 0x0002 at body[6..7] and SIP 200 at body[8..9];
     *  the bridge AIDL has no field for either, so those stay 0. */
    @Test
    public void deregistrationMatchesStockApartFromTheCause() {
        byte[] frame = IilFrame.registration(/*registered=*/ false,
                IilFrame.RIL_RAT_LTE, false, false, false, null);

        byte[] head = hex(STOCK_DEREGISTRATION_HEAD);
        head[HDR + 7] = 0;
        head[HDR + 9] = 0;
        assertArrayEquals(head, Arrays.copyOf(frame, head.length));
        assertEquals(STOCK_RAT, frame[RAT_OFFSET]);
        for (int i = head.length; i < RAT_OFFSET; i++) {
            assertEquals("byte " + i, 0, frame[i]);
        }
    }

    @Test
    public void deregistrationDropsTheImpu() {
        byte[] frame = IilFrame.registration(false, IilFrame.RIL_RAT_LTE,
                true, true, true, IMSI_DERIVED_IMPU);
        assertEquals(0, IilFrame.impuLength(frame));
        assertEquals(0, frame[HDR + 1]);
        assertEquals(0, frame[HDR + 11]);
    }

    @Test
    public void headerLengthCountsTheWholeFrame() {
        byte[] reg = IilFrame.registration(true, IilFrame.RIL_RAT_LTE,
                true, true, false, IMSI_DERIVED_IMPU);
        byte[] pref = IilFrame.preference(true, false, true);
        assertEquals(275, reg.length);
        assertEquals(21, pref.length);
        assertEquals(reg.length, u16le(reg));
        assertEquals(pref.length, u16le(pref));
    }

    @Test
    public void modemRatUsesTheNetworkType() {
        assertEquals(13, IilFrame.modemRat(IilFrame.RIL_RAT_LTE));
        assertEquals(18, IilFrame.modemRat(IilFrame.RIL_RAT_IWLAN));
        assertEquals(20, IilFrame.modemRat(IilFrame.RIL_RAT_NR));
        assertEquals(0, IilFrame.modemRat(0));
        assertEquals(0, IilFrame.modemRat(13));
    }

    @Test
    public void iwlanRegistrationCarriesRat18() {
        byte[] frame = IilFrame.registration(true, IilFrame.RIL_RAT_IWLAN,
                true, true, false, IMSI_DERIVED_IMPU);
        assertEquals(18, frame[RAT_OFFSET]);
    }

    @Test
    public void overlongImpuIsTruncatedBeforeTheRat() {
        String impu = "sip:" + "a".repeat(400) + "@x";
        byte[] frame = IilFrame.registration(true, IilFrame.RIL_RAT_LTE,
                true, true, false, impu);
        assertEquals(HDR + IilFrame.REG_BODY_LEN, frame.length);
        assertEquals(IilFrame.MAX_IMPU_UTF8, IilFrame.impuLength(frame));
        assertEquals(13, frame[RAT_OFFSET]);
    }

    private static int u16le(byte[] b) {
        return (b[0] & 0xFF) | ((b[1] & 0xFF) << 8);
    }

    private static byte[] hex(String s) {
        String[] parts = s.trim().split("\\s+");
        byte[] out = new byte[parts.length];
        for (int i = 0; i < parts.length; i++) {
            out[i] = (byte) Integer.parseInt(parts[i], 16);
        }
        return out;
    }
}
