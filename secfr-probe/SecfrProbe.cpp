/*
 * SPDX-FileCopyrightText: 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

/*
 * a51-secfr-probe — is the SEC_FR trusted application reachable from
 * libsecfr_engine.so alone?
 *
 * The face closure splits in two. libsecfr_engine.so plus libsecfr_model.so
 * hold the trusted-application client and the capture-model description;
 * libFaceService.so holds the camera and preview plumbing on top of them. This
 * binary exercises the lower half on its own, so the answer to "can the upper
 * half be replaced" stops being an inference drawn from symbol tables and
 * becomes a measurement.
 *
 * It therefore links against the lower half and nothing else. No camera, no
 * surface compositing, no media foundation — if any of those ever became
 * necessary to get this far, the split would not be real, and the build would
 * say so.
 *
 * Diagnostic only. Not installed, not part of any image.
 */

#define LOG_TAG "a51-secfr-probe"

#include <log/log.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <new>

#include "SecfrSeam.h"

namespace {

using android::CameraInfo;
using android::Configuration;
using android::FaceEngine;
using android::Model;
using android::sp;
using android::SurfaceInfo;

/*
 * The trusted application narrates its own progress to the log, so the probe's
 * findings have to land in the same stream to be readable next to it. They also
 * go to stdout, because whoever runs this is watching a terminal.
 */
void report(const char* fmt, ...) __attribute__((format(printf, 1, 2)));

void report(const char* fmt, ...) {
    char line[512];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);

    ALOGI("%s", line);
    printf("%s\n", line);
    fflush(stdout);
}

/*
 * FaceEngine is constructed by us but sized, laid out and written only by the
 * vendor library, and we have no header that states how big it is. The probe
 * therefore gives it a page instead of a fitted allocation: that is far beyond
 * anything the class can plausibly occupy, and the cost of being wrong in this
 * direction is a few unused bytes rather than a heap overflow.
 *
 * It has to come from operator new: the engine's own teardown path releases the
 * object with the matching operator delete once the last reference goes.
 */
constexpr size_t kFaceEngineArenaBytes = 4096;

/* RefBase pairs incStrong with decStrong by owner identity, so the probe needs
 * one address that outlives every frame that uses it. */
const char kProbeOwner[] = LOG_TAG;

FaceEngine* createFaceEngine() {
    void* arena = ::operator new(kFaceEngineArenaBytes, std::nothrow);
    if (arena == nullptr) {
        return nullptr;
    }
    memset(arena, 0, kFaceEngineArenaBytes);

    FaceEngine* engine = new (arena) FaceEngine();

    /*
     * The engine hands references to itself around internally. Without a
     * reference of our own the first one it drops would take the object with
     * it, so claim one for the probe and hold it until the end.
     */
    engine->incStrong(kProbeOwner);
    return engine;
}

/* Show every byte the engine touched. The record is zeroed before the call, so
 * a trailing run of zeroes carries no information and is not worth printing. */
void dumpChallengeRecord(const sec_fr_generated_challenge& challenge) {
    size_t used = sizeof(challenge.opaque);
    while (used > 0 && challenge.opaque[used - 1] == 0) {
        used--;
    }

    if (used == 0) {
        report("  challenge record: all %zu bytes still zero", sizeof(challenge.opaque));
        return;
    }

    report("  challenge record: %zu of %zu bytes written", used, sizeof(challenge.opaque));
    for (size_t offset = 0; offset < used; offset += 16) {
        char hex[16 * 3 + 1];
        size_t width = 0;

        for (size_t i = offset; i < used && i < offset + 16; i++) {
            width += snprintf(hex + width, sizeof(hex) - width, "%02x ", challenge.opaque[i]);
        }
        report("    %04zx  %s", offset, hex);
    }
}

/*
 * What the stock face service is known to be configured with on this device.
 * The probe checks the scalars it can read and prints the rest next to the log
 * lines the library emits, so a configuration that has quietly changed shows up
 * as a mismatch here instead of being discovered later by a camera layer that
 * was written against the wrong geometry.
 */
constexpr unsigned int kExpectedCameraCount = 1;
constexpr unsigned int kExpectedSurfaceCount = 1;
constexpr unsigned int kExpectedRotation = 270;

/* Checks a scalar against the stock configuration and says so either way. */
bool expectScalar(const char* what, unsigned int actual, unsigned int expected) {
    if (actual == expected) {
        report("PASS  %s = %u", what, actual);
        return true;
    }
    report("DIFF  %s = %u, stock configuration has %u", what, actual, expected);
    return false;
}

void dumpCaptureModel() {
    Model* model = Model::getInstance();
    if (model == nullptr) {
        report("FAIL  Model::getInstance() returned nothing");
        return;
    }

    sp<Configuration> config = model->getConfig();
    if (config == nullptr) {
        report("FAIL  Model::getConfig() returned nothing — the library could not");
        report("      match this chipset, so no capture configuration was built.");
        report("      Compare ro.hardware.chipname and ro.soc.model against the");
        report("      names the library recognises before reading anything else.");
        return;
    }

    report("PASS  capture model built");
    expectScalar("camera count", config->getCameraCount(), kExpectedCameraCount);

    /* Logs every camera's identity, tags and metadata. */
    config->printData();

    /* The per-surface geometry is not part of that dump, so walk it separately. */
    unsigned int cameras = config->getCameraCount();
    for (unsigned int c = 0; c < cameras; c++) {
        sp<CameraInfo> camera = config->getCameraInfoIdx(c);
        if (camera == nullptr) {
            report("FAIL  camera[%u] not retrievable", c);
            continue;
        }

        report("      camera[%u]: type %u", c, camera->getCurrentCameraType());
        expectScalar("camera rotation", camera->getRotation(), kExpectedRotation);
        expectScalar("surface count", camera->getSurfaceCount(), kExpectedSurfaceCount);
        camera->printData();

        unsigned int surfaces = camera->getSurfaceCount();
        for (unsigned int s = 0; s < surfaces; s++) {
            sp<SurfaceInfo> surface = camera->getSurfaceInfo(s);
            if (surface == nullptr) {
                report("FAIL  camera[%u] surface[%u] not retrievable", c, s);
                continue;
            }
            expectScalar("surface rotation", surface->getRotation(), kExpectedRotation);
            surface->printData();
        }
    }

    report("      the geometry itself is in the sec_fr_SurfaceInfo log line just");
    report("      emitted; the stock configuration is format 35, 640x480,");
    report("      stride 640, sliceHeight 480, bufferSize 460800, bufferCnt 4");
}

/* Exit codes double as a report of how far the probe got. */
enum ProbeResult {
    kOk = 0,
    kEngineAllocFailed = 1,
    kInitFailed = 2,
    kLoadTaFailed = 3,
    kGenerateChallengeFailed = 4,
    kGetSecurityLevelFailed = 5,
};

unsigned int parseScalar(const char* text) {
    return static_cast<unsigned int>(strtoul(text, nullptr, 0));
}

}  // namespace

int main(int argc, char** argv) {
    unsigned int taParam0 = 0;
    unsigned int taParam1 = 0;

    if (argc > 1) {
        taParam0 = parseScalar(argv[1]);
    }
    if (argc > 2) {
        taParam1 = parseScalar(argv[2]);
    }

    report("---- a51-secfr-probe ----");
    report("reaching the SEC_FR trusted application through libsecfr_engine.so only");

    FaceEngine* engine = createFaceEngine();
    if (engine == nullptr) {
        report("FAIL  could not allocate the engine arena");
        return kEngineAllocFailed;
    }
    report("PASS  FaceEngine constructed in a %zu byte arena", kFaceEngineArenaBytes);

    int status = engine->init();
    if (status != 0) {
        report("FAIL  FaceEngine::init() = %d", status);
        return kInitFailed;
    }
    report("PASS  FaceEngine::init()");

    status = engine->loadTA();
    if (status != 0) {
        report("FAIL  FaceEngine::loadTA() = %d", status);
        report("      the trusted application was not reachable; check the log for");
        report("      an SELinux denial on /dev/tzdev before reading anything else");
        return kLoadTaFailed;
    }
    report("PASS  FaceEngine::loadTA() — the trusted application is loaded");

    sec_fr_generated_challenge challenge = {};
    status = engine->generateChallenge(taParam0, taParam1, challenge);
    if (status != 0) {
        report("FAIL  FaceEngine::generateChallenge(%u, %u) = %d", taParam0, taParam1, status);
        return kGenerateChallengeFailed;
    }
    report("PASS  FaceEngine::generateChallenge(%u, %u)", taParam0, taParam1);
    dumpChallengeRecord(challenge);

    unsigned int securityLevel = 0;
    status = engine->getSecurityLevel(securityLevel);
    if (status != 0) {
        report("FAIL  FaceEngine::getSecurityLevel() = %d", status);
        return kGetSecurityLevelFailed;
    }
    report("PASS  FaceEngine::getSecurityLevel() — the application reports %u", securityLevel);

    dumpCaptureModel();

    engine->unloadTA();
    engine->release();
    engine->decStrong(kProbeOwner);

    report("---- done ----");
    return kOk;
}
