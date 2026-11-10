# X-E5 connection notes

## Verified locally

On 2026-11-10, a connected X-E5 reported firmware **1.12** through both WPD and PTP DeviceInfo. In USB RAW CONV./BACKUP RESTORE mode, all seven bank selectors could be selected and read through the installed Windows Portable Devices driver. The original selector C1 was restored and verified. No camera recipe values were written.

All seven banks returned blank names and equivalent Provia / DR100 / auto WB / zero-tone settings in the captured scan. That is the observed USB response, not a claim that the banks are unused or that FS1–FS3 dial recipes are empty. Grain property D195 returned **6**, which remains explicitly unmapped. The raw bytes are retained and automatic editor import is disabled for these banks until the required values are known.

## Windows transport

`native/wpd_bridge.cpp` uses IPortableDeviceManager and IPortableDeviceFTM. The Windows driver owns the PTP session; Iro does not reset the device, change its driver, or send its own OpenSession/CloseSession commands. A named mutex prevents two Iro helper processes from using the camera simultaneously. Multiple Fujifilm devices require an explicit WPD identifier rather than selecting the first device.

Reads use SendCommand and the documented WPD MTP extension data-transfer APIs. Transfer sizes are bounded at 64 KiB; PTP datasets, strings and array counts are checked before decoding. Iro does not retain the device serial number in camera snapshots. WPD requests read/write access because the bank selector uses a PTP data-out transaction; this does not expose general camera-setting writes in the helper.

The bridge exposes only `info`, `ptp-info`, `get D18C..D1A5`, `describe D18C..D1A5`, `select 1..7`, `restore`, and `quit`. `--list` inventories Fujifilm WPD identifiers. No general PTP opcode, file deletion, capture, firmware or recipe-property write interface exists.

## Bank scan

1. Verify manufacturer/model using a fresh PTP DeviceInfo response. Only X-E5 bank reads are currently enabled; other models can be identified without selecting banks.
2. Check that the camera advertises Get/SetDevicePropValue and preset properties D18C/D18D. Reject card-reader mode with connection instructions.
3. Read and preserve the original D18C bank selector. Abort before selection if it is outside 1..7.
4. Select each bank through SetDevicePropValue **only for D18C**, allow it to settle, and verify the selector readback.
5. Read the name D18D and preset properties D18E..D1A5. Preserve exact bytes and unknown fields. Unsupported properties are retained as explicit errors; connection errors abort the scan.
6. Restore D18C in a Python finally block and verify the original value. The native helper has a second restoration guard on EOF/normal exit. A hard process termination or physically disconnected camera can prevent restoration; this is reported as unverified, never success.

Snapshots mark `complete` (all seven banks scanned) separately from `selector_restored`. Each bank has raw properties, partial decoded values, warnings and either a fully validated portable `recipe` or `null`. A complete scan does not imply every property encoding has been decoded. Sentinel and unknown values are never silently replaced with zero or another default.

The portable editor schema intentionally covers a subset of camera settings. Monochrome adjustments, image size/quality, smooth skin, long-exposure NR, color space and unknown fields remain in the raw snapshot even when the portable recipe can be imported. Export a snapshot to preserve camera-only fields.

## Primary references

- [Microsoft: supporting MTP extensions](https://learn.microsoft.com/en-us/windows/win32/wpd_sdk/supporting-mtp-extensions)
- [Microsoft: issuing GetDevicePropValue](https://learn.microsoft.com/en-us/windows/win32/wpd_sdk/issuing-the-getdevicepropvalue-command)
- [FilmKit preset scan](https://github.com/eggricesoy/filmkit/blob/9e3bbcf858b1f9dc522e90adf7e385554f5969e2/src/ptp/session.ts)
- [FilmKit property constants](https://github.com/eggricesoy/filmkit/blob/9e3bbcf858b1f9dc522e90adf7e385554f5969e2/src/ptp/constants.ts)
- [X-E5 network/USB settings](https://fujifilm-dsc.com/en/manual/x-e5/connections/network_usb_menu/)
- [X-E5 custom settings and film-simulation dial](https://fujifilm-dsc.com/en-int/manual/x-e5/menu_shooting/image_quality_setting/)
