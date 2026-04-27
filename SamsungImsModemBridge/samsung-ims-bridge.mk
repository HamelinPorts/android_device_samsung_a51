# Samsung IMS-to-modem bridge bundle.
#
# Inherit from a Samsung-Shannon device's device.mk after the generic
# HamelinPortsImsService bundle:
#
#     $(call inherit-product, packages/apps/HamelinPortsImsService/hamelinports-ims.mk)
#     $(call inherit-product, device/samsung/<dev>/SamsungImsModemBridge/samsung-ims-bridge.mk)
#
# Adds the per-device IImsModemBridge implementation that HamelinPortsImsService
# binds to via the org.hamelinports.ims.modem.action.BIND_BRIDGE intent. Carries
# Samsung's proprietary IIL bytes (sub=0x01 IPC_IIL_REGISTRATION,
# sub=0x06 IPC_IIL_PREFERENCE) over ISehRadioChannel/imsd so the EPC routes
# MT voice as IMS rather than CSFB.
#
# IIL byte layouts have shifted between Shannon generations — verify the
# subcommand IDs and body offsets in SamsungImsModemBridgeImpl.java match
# the target modem before reusing this bundle on another device.

PRODUCT_PACKAGES += \
    SamsungImsModemBridge \
    privapp-permissions-org.hamelinports.samsung.ims
