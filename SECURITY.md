# Security policy

## Reporting

Open a private GitHub security advisory (Repository → Security → Advisories →
New draft advisory) rather than a public issue. Include the pinned revision
you reviewed and, where relevant, the patch number.

## What this project is, security-wise

lenOS is a **source-distribution**: there are no published binaries. The
security model depends on you building from pinned source:

- Every external artifact (avbroot, ReSukiSU manager, OEMUnlockOnBoot,
  Cromite) is pinned by sha256 in `config/VERSIONS.sh`; the pipeline refuses
  to run with mismatched downloads.
- Every patched repository is pinned by revision in
  `manifest/lenos-asteroids.xml` and re-verified before each integrate.
- The 13 core hardening patches are adapted from GrapheneOS with provenance
  recorded per patch; the duress implementation is byte-identical upstream
  code.

## Known limits (do not skip)

- A solo, unaudited project: treat the patch set as reviewable source, not as
  audited code. The intended workflow is that you read the diffs — they are
  small and self-contained by design.
- Root (ReSukiSU) is part of the design; it weakens the platform by
  definition. Relocking with your own AVB key restores verified boot, and the
  BFU reboot timer lives in init so data-at-rest survives a compromised
  system_server.
- Per-builder signing certificates are app-visible; that is a fingerprint
  documented in DESIGN.md with mitigations.
- Carrier/radio identity cannot be hidden by any OS.
