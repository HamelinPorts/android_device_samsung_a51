/*
 * SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <utils/RefBase.h>
#include <utils/StrongPointer.h>

/*
 * The vendor-facing seam of the Samsung face closure: the engine that talks to
 * the SEC_FR trusted application (libsecfr_engine.so) and the capture-model
 * description it consumes (libsecfr_model.so).
 *
 * Samsung ships no headers for these two libraries, so this file declares the
 * minimum needed to call them. Every declaration below is matched against the
 * libraries' own exported symbols by verify-seam.py, which fails the check if a
 * name or a parameter list drifts.
 *
 * Two rules keep this safe:
 *
 *   - Nothing here is ever allocated by us except FaceEngine, and that one goes
 *     into an explicitly sized arena (see SecfrProbe.cpp), so a class being
 *     larger here than the probe believes cannot corrupt anything.
 *   - Only RefBase is inherited, and only because its layout is the ABI these
 *     libraries were built against: they hand back sp<> and call
 *     RefBase::incStrong on the objects they return, so the reference counting
 *     has to be the real one.
 */

/*
 * Opaque challenge record produced by the trusted application. The probe needs
 * storage to hand over and something to dump; it never interprets a field, so
 * the only requirement is that this is comfortably larger than the record the
 * engine writes.
 */
struct sec_fr_generated_challenge {
    unsigned char opaque[256];
};

namespace android {

class SurfaceInfo : public RefBase {
  public:
    unsigned int getRotation();

    /* Logs the capture geometry: format, resolution, stride, slice height,
     * buffer size and count. There are no getters for those, so this is the
     * only way to see them. */
    void printData();

  protected:
    ~SurfaceInfo() override;
};

class CameraInfo : public RefBase {
  public:
    unsigned int getCurrentCameraType();
    unsigned int getRotation();
    unsigned int getSurfaceCount();
    sp<SurfaceInfo> getSurfaceInfo(unsigned int index);
    void printData();

  protected:
    ~CameraInfo() override;
};

class Configuration : public RefBase {
  public:
    unsigned int getCameraCount();
    sp<CameraInfo> getCameraInfoIdx(unsigned int index);
    void printData();

  protected:
    ~Configuration() override;
};

/*
 * Not reference counted, unlike everything it hands out: the library owns the
 * single instance for the lifetime of the process and never destroys it.
 */
class Model {
  public:
    static Model* getInstance();

    sp<Configuration> getConfig();
};

class FaceEngine : public RefBase {
  public:
    FaceEngine();

    int init();
    int loadTA();
    int unloadTA();
    int release();

    int getSecurityLevel(unsigned int& level);

    /*
     * The two scalars are forwarded verbatim into the trusted application's
     * request. Nothing available to us names them, so the probe leaves both at
     * zero and exposes them on the command line instead of inventing a meaning
     * for them.
     */
    int generateChallenge(unsigned int taParam0, unsigned int taParam1,
                          sec_fr_generated_challenge& challenge);

  protected:
    ~FaceEngine() override;
};

}  // namespace android
