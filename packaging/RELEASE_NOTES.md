Iro is a Windows Fujifilm recipe library with a native desktop interface and read-only X-E5 custom-bank access through the installed Windows Portable Devices driver.

Download **Iro-0.3.1-x64.msi** to install for the current Windows user. Python and the native camera helper are included. The accompanying `.sha256` file contains the installer's SHA-256 checksum. The installer is unsigned.

- Recipe library with validation, search, JSON import/export, deletion and undo.
- Washi light and sumi dark themes, with a transparent Fuji/sun logo.
- Live X-E5 C1–C7 bank reads, raw property inspection and snapshot export.
- Verified bank-selector restoration and separate local simulated slots.

Hardware validation: X-E5 firmware 1.12. Reading temporarily selects each bank and restores the original selector; recipe values are not written. Grain code 6 remains unmapped and is preserved exactly. Affected snapshots cannot be imported as editable recipes without resolving that field. FS1–FS3 dial recipes, camera recipe writes and DAT editing are not supported.

MIT licensed. Independent of Fujifilm; see the repository's third-party notices for protocol attribution.
