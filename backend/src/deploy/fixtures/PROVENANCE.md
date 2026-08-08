# Synthetic RAR5 probe fixture provenance

- Created: 2026-08-08
- Generator: locally installed WinRAR `Rar.exe` 7.20.0
- Command mode: `a -ma5 -m0 -ep -idq`
- Archive payload: `archive-runtime-smoke.txt`
- Payload content: synthetic ASCII test data only; no project or business data
- Payload size: 40 bytes
- Payload SHA-256: `6eaab97fc311dcba726775b8aa04165069688caa965df2fde9e12813cb74802f`
- Decoded RAR5 size: 129 bytes
- Decoded RAR5 SHA-256: `b0c3ccb16412f5215da3ae12f8bafd6fa4524ff44831283a7963b3afc792a886`

The repository stores the 129-byte archive as Base64 text so the fixture remains
reviewable and reproducible in text-only patch workflows. No WinRAR executable,
library, installer, license material, or other WinRAR binary is distributed.
