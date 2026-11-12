# Security review (source-level)

This review covers the experimental patch set, not the main lenOS 1.0 series. Nothing here has
been built or booted. It records the threat model, the deliberate non-goals, and the issues found
while reviewing the patches at source level. A passing test is not a runtime security proof.

## Method

* Read every added framework, Settings, SetupWizard, bionic and `LenosOpsec` source file.
* Checked exported manifest components, signature/platform permissions and every call that writes a
  setting, system property or AppOp.
* Checked that the OPSEC app has no `INTERNET` permission and no socket/HTTP code.
* Checked that no patch flashes, wipes, relocks or changes verified boot.
* Ran the independent `git apply --check` series and an additional in-order Settings-series apply.
* Reviewed `--reset` behavior so test artifacts cannot survive into a later build.

## Findings

| Area | Finding | Status |
|---|---|---|
| Settings patch series | Five patches inserted at the same end-of-file anchors. Each passed alone, but 0002 failed after 0001. | **Fixed.** Distinct anchors, in-order sandbox test added. |
| Reset driver | Rename destinations (the Seedvault `app.grapheneos` tree) survived `--reset`. | **Fixed.** Rename/copy destinations and empty parents are removed; regression test added. |
| ENF-1 / #23 | This is a global opt-in dumpable-bit clear, not per-app native-debugging policy. Root/`CAP_SYS_PTRACE` and existing processes are exempt. If app seccomp rejects `prctl`, the helper logs and does nothing. An app that deliberately calls
`prctl(PR_SET_DUMPABLE, 1)` can undo its own bit; this is a hardening primitive, not a sandbox. | Deliberate limitation; documented and marked unbuilt. |
| #17 crash logs | `READ_LOGS` is signature-level; entries stay local and sharing is explicit. The viewer does not upload. | Acceptable for a platform Settings app; runtime test pending. |
| #27 Seedvault | Internal prefix migration can make old backups unreadable by the new app id. | Documented; restore-migration test required. |
| #28 SetupWizard | Shows a warning when verified boot is not green; does not block setup, unlock, or relock. | Acceptable; first-boot states still need testing. |
| OPS-1 / OPS-5 | Both are exported share targets. They process only after a user action, cap image count at 20, re-encode images, and never resolve/open links. | Intentional export; no network. |
| OPS-2 Offline tile | Requires `NETWORK_SETTINGS`, `WRITE_SECURE_SETTINGS` and `BLUETOOTH_PRIVILEGED`; the tile service is protected by `BIND_QUICK_SETTINGS_TILE`. The app is platform-signed. | High privilege is necessary for a radio kill switch; no extra permission beyond that. |
| OPS-3 / OPS-4 | Settings writes the secure clipboard setting and the existing `OP_READ_CLIPBOARD` AppOp. OPS-4 cannot override the global Secure Paste policy. | Acceptable; no new AppOp or permission. |
| HTS-1 thread stacks | The bionic mapping is selected only by the exact read-only property `ro.lenos.hardened_thread_stacks=1`, added by the experimental product fragment (`LENOS_EXPERIMENTAL=1`). `__allocate_thread_mapping` remains unchanged for the absent/false case. The random gap stays `PROT_NONE`; `pthread_internal_t` is in its own page. The main thread and existing threads keep their old layout. | Stable/default build keeps the stock mapping; source-level tests pass. Full bionic build, boot, thread stress and app compatibility required. |
| HTS-1 and MTE stack | Bionic's existing `__pthread_internal_remap_stack_with_mte` remaps the whole `mmap_base_unguarded` range for existing threads. If stack MTE is activated after hardened threads exist, that remap may make the random gap writable for those threads. HTS-1 does not enable MTE, and the target build does not claim MTE support. | Documented limitation; do not combine with stack MTE without a follow-up bionic change and validation. |
| #32 kernel | Additive config fragment only; no vendor/GKI option is disabled. It is not a runtime validation. | Needs boot, `/proc/config.gz`, `dmesg_restrict` and performance checks. |

## Deliberate non-goals

* ENF-1 does not claim to stop root, kernel, `debuggerd`, or a process with `CAP_SYS_PTRACE`.
* The share targets do not sanitize arbitrary file formats; unsupported images fail rather than
  silently pass through.
* The Settings log viewer does not guarantee deletion of logs held by other system components.
* HTS-1 is a stack-layout change, not a memory-safety proof or a sandbox. It does not stop
  arbitrary memory corruption, replace `hardened_malloc`, enable MTE/TBI or change BTI/PAC,
  seccomp, ART or JIT policy. Its memory/performance cost and app compatibility are unmeasured.
* No signing key, recovery image, bootloader state or verified-boot chain is modified by these
  patches.

## Required before promotion

1. Build every project with the experimental series applied in order.
2. Boot `asteroids`, check SELinux denial logs and the hidden-API build check.
3. Run the checks in `verification.md`, including a same-UID ptrace attempt, a Seedvault restore,
   a Setup Wizard first boot with green and non-green verified-boot properties, and HTS-1
   thread-creation/app-compatibility/memory checks against a control build. Do not promote HTS-1
   on source-level tests alone.
4. Promote only the features that pass. ENF-1 remains experimental until the per-app policy or an
   explicit product decision replaces it.
