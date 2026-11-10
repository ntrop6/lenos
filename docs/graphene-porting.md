# Porting notes: GrapheneOS → lenOS

Rough notes from mapping GrapheneOS features to this build. This is not a
support matrix or a promise that a feature will be finished.

**Port status (2026-11):** the series now targets **LineageOS 24.0 / Android 17**.
These notes were originally written while the port targeted 23.2 / Android 16; the
analysis below has been updated to the 24.0 tree, and the shipped patches are rebased
to it.

Scope: every feature on https://grapheneos.org/features, mapped to GrapheneOS branch `17` source (their
Android 17 / QPR-era tree), with portability analysis against lenOS = LineageOS 24.0 / Android 17 on
Nothing Phone (3a)/3a Pro ("asteroids", **Qualcomm SM7635 "Snapdragon 7s Gen 3"**). Corrected 2026-10:
the device is Qualcomm, not MediaTek. Kernel: vendor kernel 6.6 built from source in the lenOS tree
(`device/nothing/asteroids/BoardConfig.mk:129-131`: `BOARD_USES_GENERIC_KERNEL_IMAGE := true`,
`TARGET_KERNEL_SOURCE := kernel/nothing/sm7635`), so kernel patches are *theoretically possible* in a
build, but none of the GrapheneOS kernel hardening is a patch-level port; vendor firmware (modem/ISP,
USB-PD, charger, touch, bootloader/AVB trust root) remains closed and immutable for us. Hardware
judgements below have been re-checked for SM7635 (eSIM: supported; USB-C: vendor Qualcomm USB HAL).

Evidence sources:
- GrapheneOS `platform_frameworks_base` @ branch 17 (blobless and full shallow clones kept
  outside this repository).
- GrapheneOS `system_core`, `packages_apps_Settings`, `modules_Permission`, `modules_Connectivity`,
  `opt_telephony`, `system_sepolicy`, `external_seedvault`, `providers_ContactsProvider`,
  `platform_system_extras`, `platform_system_ca-certificates` @ 17.
- the lenOS stable series in `patches/` (**54 patches** across 18 projects), documented in
  `docs/features.md` (kept in sync). Status 2026-10: ExtSettings infrastructure
  (frameworks_base/0006), the init-based auto-reboot port (system_core/0001 + frameworks_base/0003), the
  GrapheneOS-design quick-tile unlock gating (frameworks_base/0004), the duress feature incl. eSIM
  wipe (frameworks_base/0005+0007, frameworks_opt_telephony/0001), the GrapheneOS-faithful Wi-Fi privacy
  defaults (packages_modules_Wifi/0001), the GrapheneOS PIN scrambling port
  (frameworks_base/0008 + packages_apps_Settings/0001), the LTE-only / 5G-only Settings port, the
  GNSS SUPL/PSDS privacy toggles (frameworks_base/0021 + packages_apps_Settings/0001), the
  package-update enabled-state preservation (frameworks_base/0022), the MediaProvider
  directory-listing restriction (packages_providers_MediaProvider/0001), the
  prototype-device warning + bootloader-version visibility (frameworks_base/0023 +
  packages_apps_Settings/0001), the memory hygiene on lock (frameworks_base/0024), the
  user-installed app disabling (packages_apps_Settings/0002), the network permission
  (frameworks_base/0025 + packages_modules_Connectivity/0002 + packages_modules_Permission/0002) and
  the sensors permission (frameworks_base/0025/0026 + frameworks_native/0001) are all **done**;
  sections 1–3 below carry status notes. §18 audits the current patch set.

Caveat: lenOS and GrapheneOS both target Android 17 (LineageOS 24.0 vs GrapheneOS branch 17), but they
are different forks, so APIs and surrounding code still drift. Remaining deltas are called out per
feature. Line numbers/paths are branch-17 paths unless a section says otherwise.

Legend for size: S (<200 LOC), M (200–800 LOC), L (800–3000 LOC), XL (>3000 LOC or new subsystem).

---

## 0. Executive summary of the biggest findings

- **ExtSettings is plain `Settings.Global` / `Settings.Secure` + sysprops.** No custom ContentProvider,
  no database. `ExtSettings.java` is only 120 lines; the whole `android.ext.settings` package is ~1.6k
  lines and is *self-contained infrastructure* that can be ported nearly wholesale. Storage keys are
  added to AOSP's `android.provider.Settings` (a handful of constants), defaults come from
  `core/res/res/values/config_ext.xml` resources. **Status: DONE** — lenOS patch
  `frameworks_base/0006-lenos-ext-settings.patch` ("android.ext.settings" package + ExtSettings subset +
  `config_ext.xml` defaults) has landed; the constants already seeded there include AUTO_REBOOT_TIMEOUT,
  WIFI/BLUETOOTH/NFC_AUTO_OFF, SCREENSHOT_TIMESTAMP_EXIF, AUTO_GRANT_OTHER_SENSORS_PERMISSION,
  ALLOW_CLIPBOARD_READ_BY_DEFAULT, dyn-code-loading and MEMTAG defaults, PIN/SIM-PIN scramble (wired and
  shipped via the redo — see §14) — several of the *other* constants have *no behavior wired behind them
  yet* (see §14).
- **GrapheneOS auto reboot is enforced by `init`** (`system/core/init/property_service.cpp`), not by a
  system_server alarm. **Status: DONE** — lenOS has replaced its AlarmManager service with the faithful
  init-based port: `system_core/0001-lenos-auto-reboot-init.patch` + `frameworks_base/0003-lenos-auto-reboot.patch`
  (`AutoReboot.java`, hooked from `KeyguardServiceDelegate.onShowingStateChanged`). Key is the GrapheneOS
  key `Settings.Global.settings_reboot_after_timeout` (default 18 h); the old key/boot-seed/RRO are gone.
  See §2.
- **Duress eSIM wipe** needed a *second* small patch beyond `EuiccWipe.java`: the `flags` parameter in
  `EuiccCardManager.resetMemory()`, the `IEuiccCardController.aidl` signature and
  `EuiccCardController.resetMemory()` (skips the carrier removal notification). **Status: DONE** —
  lenOS landed `frameworks_base/0007` + `frameworks_opt_telephony/0001` (2026 redo); with the backend
  (`frameworks_base/0005`) the duress feature is complete (see §3).
- **Network permission** is enforced in the **Connectivity module + netd eBPF firewall**, with UI in
  Settings/PermissionController; it is the largest single high-value port (multi-repo,
  M–L — AOSP 17/LineageOS 24.0 already contains most of the underlying eBPF/permission machinery, see §5).
  **Status: DONE** — lenOS patch set `frameworks_base/0025` + `packages_modules_Connectivity/0002` +
  `packages_modules_Permission/0002` ports GrapheneOS's "special runtime permissions" mechanism with
  `INTERNET` as the only member (auto-grant on new install, internet-compat mode on revoke, self-check
  spoofing, 32 ConnectivityManager gates, NSD stub; the install-time toggle assumed here turned out not
  to exist in GrapheneOS either — their installer has no SRT references, so no installer patch).
- **USB-C port control** needs the vendor USB HAL and kernel to support disabling the data lines at the
  hardware level. On SM7635 the OS-side piece (mode setting + HAL interception of `IUsb.enableUsbData`)
  is portable *if* Nothing's Qualcomm USB HAL implements AOSP's `enableUsbData`; the hardware data-line
  and alternate-mode (DisplayPort) disable are vendor/kernel features we cannot add → not feasible in
  full today, partial port worth prototyping (see §10).
- **Vanadium** is a whole Chromium product (~2 GB source build or a prebuilt APEX/WebView decision);
  realistically `port later / app-level bundle`, not a patch (see §13).
- **FBE filename padding 16→32 bytes** is a genuine one-line GrapheneOS change in `system/extras`
  (`libfscrypt/fscrypt.cpp:247-248`) — cheapest at-rest privacy win in this inventory (see §11;
  **done**: `system_extras/0001`).

---

## 1. ExtSettings subsystem (special investigation #1)

**What it is.** A tiny typed-settings library in `frameworks/base` that wraps three storage scopes and
adds defaults/observers. It is *not* a settings provider.

**Files** (`frameworks/base/core/java/android/ext/settings/`, ~1.6k lines total; sizes in lines):

| File | LOC | Role |
|---|---|---|
| `Setting.java` | 179 | abstract base: Scope = SYSTEM_PROPERTY / GLOBAL (`Settings.Global`) / PER_USER (`Settings.Secure`); get/put raw, ContentObserver registration, sysprop observer deliberately unsupported |
| `BoolSetting.java` / `IntSetting.java` / `StringSetting.java` | 76/111/72 | typed get/put + resource-based defaults |
| `BoolSysProperty.java` / `IntSysProperty.java` / `StringSysProperty.java` | 32/39/22 | sysprop-backed settings |
| `ExtSettings.java` | 120 | the registry of settings (AUTO_REBOOT_TIMEOUT, ALLOW_CLIPBOARD_READ_BY_DEFAULT, SCREENSHOT_TIMESTAMP_EXIF, SCRAMBLE_*, dyn-code-loading defaults, MEMTAG, USB port security, conn checks, etc.) |
| `UsbPortSecurity.java`, `ConnChecksSetting.java`, `GnssSettings.java`, `NetworkLocationSettings.java`, `GeocoderSettings.java`, `RemoteKeyProvisioningSettings.java`, `WidevineProvisioningSettings.java`, `CertTransparencyDownloaderSetting.java`, `CrossProfileClipboardAccessSettings.java`, `AltTouchscreenMode.java` | 17–45 each | domain settings |
| `app/AppSwitch.java` + `app/Asw*.java` (10 files) | 21–178 each | per-app hardening switches (exec spawning, hardened_malloc, memtag, dyn code loading, native debug, Play Integrity) |

**Storage mechanism:**
- Global scope → `android.provider.Settings.Global` (e.g. `settings_reboot_after_timeout`,
  `allow_clipboard_read`, `restrict_memory_dyn_code_exec`, `wifi_off_timeout`).
- Per-user scope → `android.provider.Settings.Secure` (e.g. `screenshot_timestamp_exif`,
  `lockscreen_scramble_pin_layout`, `auto_grant_OTHER_SENSORS_perm`).
- Sysprops for a few defaults (`persist.native_debug`, `persist.security.exec_spawn`).
- No `ExtSettingsProvider`, no multi-user database of its own; multi-user works because PER_USER scope
  uses `getStringForUser`/`putString` against the normal settings provider, and the settings provider
  already handles per-user storage.

**Defaults**: `frameworks/base/core/res/res/values/config_ext.xml` (`setting_default_*` bools/integers/
strings, e.g. `setting_default_allow_clipboard_read=true`,
`setting_default_restrict_memory_dyn_code_loading=false`,
`system_pkgs_allowed_*_by_default` arrays) plus `core/res/res/values/public-ext.xml` for the symbol
export list and `string_ext.xml`.

**Dependents (from grep of their repos):**
- `frameworks/base`: dozens of files under SystemUI/system_server use `ExtSettings.*` (see per-feature
  sections). The comment in `Setting.java` says readability of settings is derived via reflection over
  `Settings`-class members, hence the keys were added to `android.provider.Settings`.
- Settings app: 17 files, incl. a custom XML attribute pipeline:
  `settings:boolSettingField="android.ext.settings.ExtSettings AUTO_REBOOT_TIMEOUT"` parsed by
  `res/values/attrs` → `PreferenceXmlParserUtils` (`R.styleable.Preference_boolSettingField`) →
  `src/com/android/settings/ext/BoolSettingPrefController.java` (reflectively resolves the field).
  Plus per-app screens `AswExploitProtectionFragment`, `AppClipboardRead.kt`, `AppExecSpawning.kt`,
  `AppHardenedMalloc.kt`, `AppMemoryTagging.kt`, `AppNativeDebugging.kt`,
  `AppStorage/Memory/WebViewDynCodeLoading.kt`, `AppManagePlayIntegrityApi.kt`, `AswAdapter.kt`.
- Connectivity module: `networksecurity/service/.../ct/Config.java`, `DownloadHelper.java`,
  `CertificateTransparencyDownloader.java` (certificate transparency downloader toggle),
  `NetworkDiagnostics.java`.

**Port assessment:** The package itself depends only on `android.provider.Settings`, `Context`,
`SystemProperties`, `ContentObserver` — all stable AOSP-16 APIs. Only `Setting.java`'s use of
`Settings.isInSystemServer()` (a GrapheneOS addition to `Settings.java`) is a small dependency; a port can
either bring that helper along (it is ~5 lines) or drop that error-swallowing branch. Porting the *whole*
package costs one frameworks_base patch (~1.6k lines, mostly new files). The Settings-app UI glue is
separate and only needed for screens we choose to ship.
**Recommendation: port the package wholesale now** (it is the cheapest infrastructure win in this
inventory); port only the Setting constants that correspond to features we actually port, to keep the
patch reviewable. Do NOT port their `Settings.java` wholesale — their copy has large unrelated
refactors (caching, validation); add only the new key constants.

---

## 2. Auto reboot (special investigation #2)

**What it does.** Reboots a locked, secure device after N seconds so FBE keys leave RAM (device goes
back to Before First Unlock). Timer starts when keyguard starts showing, is cancelled on unlock. Default
18 h, configurable 10 min – 72 h, or off. Explicitly does NOT apply before first unlock (so a device
that was never unlocked since boot doesn't reboot-loop). Unlocking any profile cancels it.

**GrapheneOS pieces:**

1. Java (their `platform_frameworks_base`):
   - `services/core/java/com/android/server/policy/keyguard/AutoReboot.java` (34 lines): a static
     helper. On keyguard shown: reads `ExtSettings.AUTO_REBOOT_TIMEOUT` (Global key
     `settings_reboot_after_timeout`, ms) and writes `sys.auto_reboot_ctl = <seconds>`. On unlock:
     writes `sys.auto_reboot_ctl = on_device_unlocked`.
   - Caller: `services/core/java/com/android/server/policy/keyguard/KeyguardServiceDelegate.java:227`
     inside `onShowingStateChanged(boolean showing)`, right next to their `UsbPortSecurityHooks` call
     (line 231). The callback comes from the keyguard service
     (`IKeyguardService.onShowingStateChanged`) and fires on lock/unlock and user switches (see their
     comment in AutoReboot).
   - Setting/UI: `Settings/src/com/android/settings/security/AutoRebootPrefController.java` (list of
     durations in values), registered in `exploit_protection_settings.xml` under key `auto_reboot`;
     strings in `strings_ext.xml`.

2. init (`platform_system_core`), the actual enforcement (file `init/property_service.cpp`):
   - Statics at ~line 539: `timer_t auto_reboot_timer; bool device_unlocked_at_least_once;
     bool is_auto_reboot_timer_started;`
   - `auto_reboot_timer_init()` (~551): `timer_create(CLOCK_BOOTTIME_ALARM, SIGEV_THREAD,
     auto_reboot_timer_callback)`. `CLOCK_BOOTTIME_ALARM` ⇒ counts across suspend and can wake the
     device; a plain Java AlarmManager cannot match this in all Doze/idle cases.
   - `auto_reboot_timer_callback` (~543): on expiry `trigger_shutdown("reboot")` — i.e. a **normal
     reboot**, not poweroff (memory zeroing on the normal path + FBE → BFU).
   - `auto_reboot_timer_set(duration_sec)` (~561): enforces a 20 s floor, `timer_settime`.
   - `auto_reboot_handle_property_set(value)` (~580):
     * `"on_device_unlocked"` → `device_unlocked_at_least_once = true`, cancel timer if running;
     * otherwise integer seconds; rejected if ≤0; **ignored if the device was never unlocked since
       boot** (this is the BFU protection — the whole state machine is driven by this one flag);
     * if a timer is already running, the request to restart it is ignored (so re-locking without
       unlocking cannot extend the timer — important: keyguard can show/unshow without an unlock e.g.
       camera launch).
   - Hook: in `HandlePropertySet()` at ~line 657: `if (name == "sys.auto_reboot_ctl") { ... }` —
     placed *after* `CheckPermissions()` and before generic `PropertySet()`, so the prop never really
     lands in the property area and system_server only needs write access to this one property.
   - Init call: `auto_reboot_timer_init()` at ~line 1571, guarded by `if (!IsMicrodroid())`.

3. sepolicy (`platform_system_sepolicy`):
   - `private/property_contexts:29` → `sys.auto_reboot_ctl u:object_r:auto_reboot_ctl_prop:s0`
   - `private/property.te:9` → `system_internal_prop(auto_reboot_ctl_prop)`
   - `private/system_server.te:837` → `set_prop(system_server, auto_reboot_ctl_prop)`

**lenOS status (2026 redo) — DONE.** The faithful port has landed and can be audited directly:

- `system_core/0001-lenos-auto-reboot-init.patch` (134 lines) — same design as GrapheneOS:
  `CLOCK_BOOTTIME_ALARM` `timer_create(SIGEV_THREAD)`, `device_unlocked_at_least_once` BFU guard,
  20 s floor, "ignore restart while running" rule, `sys.auto_reboot_ctl` special-cased in
  `HandlePropertySet()` (after `CheckPermissions()`), `auto_reboot_timer_init()` guarded by
  `!IsMicrodroid()`. Difference: the timer callback calls `HandlePowerctlMessage("reboot")` directly
  (GrapheneOS branch 17 calls `trigger_shutdown("reboot")`; both are normal init reboot paths — equivalent).
- `frameworks_base/0003-lenos-auto-reboot.patch` — `AutoReboot.java` (52-line class writing
  `sys.auto_reboot_ctl`, reading `ExtSettings.AUTO_REBOOT_TIMEOUT`) plus one call added in
  `services/core/java/com/android/server/policy/keyguard/KeyguardServiceDelegate.java`
  `onShowingStateChanged(boolean showing)`. A17 removed `KeyguardStateMonitor`; the delegate now stores
  its `Context` and receives the per-user `IKeyguardStateCallback` event, so the call site matches
  GrapheneOS 17 (lock, unlock, user switch).
- Key: `Settings.Global.settings_reboot_after_timeout` (`frameworks_base/0006`, `Settings.java` hunk;
  `AUTO_REBOOT_TIMEOUT` default `TimeUnit.HOURS.toMillis(18)`). The earlier inventory suggestion to keep
  the lenOS key `lenos_auto_reboot_timeout_ms` was **deliberately not taken**; the GrapheneOS key was
  adopted to keep behaviour/documentation aligned with GrapheneOS. The old `LenosAutoRebootService`
  (AlarmManager), the old settings key, the boot-seed and the RRO were removed.
- Remaining deltas vs GrapheneOS (all deliberate/benign): no call-in-progress deferral (neither has
  GrapheneOS — the old lenOS AlarmManager service's call guard is intentionally gone, matching upstream:
  any lock starts the countdown); the `HandlePowerctlMessage` vs `trigger_shutdown` difference noted
  above; and the SELinux type is now GrapheneOS's dedicated `auto_reboot_ctl_prop`
  (`patches/system_sepolicy/0001`).
- ExtSettings was trimmed to the constants actually needed (here: `AUTO_REBOOT_TIMEOUT`), not the whole
  registry.

**API/version risk:** none — self-contained C++ init code plus AOSP-16-stable Java APIs.

**Verdict: shipped/done in lenOS** (was "port now" when sections 0–3 were first written).
**Size as shipped: S (~190 LOC across 2 repos + 1 settings constant).**

---

## 3. Duress PIN/password + eSIM wipe (special investigation #4) — DONE in lenOS

**What it does.** A second PIN and a second password; entering either at any credential prompt
irrecoverably wipes the device (KeyMint keys → storage keys gone) and powers off, optionally wiping
eSIM profiles too. Set only by the owner credential. The duress PIN is also honoured as the
two-factor fingerprint unlock PIN, but not as the SIM PIN (so far).

**GrapheneOS locksettings pieces** (`frameworks/base/services/core/java/com/android/server/locksettings/`):

| File | LOC | Role |
|---|---|---|
| `DuressCredential.java` | 66 | one duress credential: salt via `SyntheticPasswordManager.PasswordData` + `spm.stretchLskf()`; `validate()` uses `LockPatternUtils.validateDuressCredential()` (no shared-prefix with real credential, min length etc.) |
| `DuressCredentials.java` | 120 | pair (pin+password), serialized hex into `LockSettingsStorage` under key `duress_credentials`, user `USER_SYSTEM` |
| `DuressPasswordHelper.java` | 119 | enrollment (owner cred check), `onVerifyCredentialResult()` hook: on a failed verify, copies the credential to a background HandlerThread and checks it against the duress pair; if matched → `DuressWipe.run()` |
| `DuressWipe.java` | ~74 | thread that calls `EuiccWipe.run(ctx, RESET_FLAG_IS_FOR_DURESS_WIPE)`, then `RecoverySystemService.deleteSecrets()` (deleteAllKeys → storage keys), then `PowerManagerService.lowLevelShutdown(null)` (poweroff, no reboot) |
| `LockSettingsService.java` | hook | calls `DuressPasswordHelper.onVerifyCredentialResult()` on every credential verification failure |
| Settings UI | | `DuressPasswordActivity`, `DuressPasswordMainActivity`, `DuressPasswordSetupActivity` in `Settings/src/com/android/settings/security/` |
| tests | | `frameworks/base/tests/DuressPasswordTest/` |

**Telephony/eSIM pieces (ported in the 2026 redo — kept as the implementation reference):**

| Repo | File | Change |
|---|---|---|
| frameworks/base | `telephony/java/com/android/internal/telephony/euicc/EuiccWipe.java` | new helper (~110 lines): enumerates `TelephonyManager.getUiccSlotsInfo()`, for each `getIsEuicc()` slot calls `EuiccCardManager.resetMemory(cardId, DELETE_OPERATIONAL_PROFILES\|DELETE_FIELD_LOADED_TEST_PROFILES, executor, cb, flags)`, waits for all, returns success (this file is in frameworks_base in branch 17; on 16 it can equally live in `frameworks/opt/telephony`) |
| frameworks/base | `telephony/java/android/telephony/euicc/EuiccCardManager.java` | add `public static final int RESET_FLAG_IS_FOR_DURESS_WIPE = 1;` (**@hide**, not part of the public SDK — safe) + hidden `resetMemory(..., int flags)` overload forwarding to the AIDL |
| frameworks/base | `telephony/java/com/android/internal/telephony/euicc/IEuiccCardController.aidl` | `resetMemory(..., int flags)` — AIDL change, needs the module/impl to be rebuilt together |
| frameworks/opt/telephony | `src/java/com/android/internal/telephony/euicc/EuiccCardController.java` | accept `flags`; throw `SecurityException` if a non-SYSTEM_UID passes flags; **skip `SubscriptionManagerService.updateEmbeddedSubscriptions()`** when `flags & RESET_FLAG_IS_FOR_DURESS_WIPE != 0` (otherwise the LPA sends an eSIM removal notification to the carrier on a duress wipe — exactly what a duress wipe must not do) |
| frameworks/opt/telephony | `EuiccCardController` / `EuiccController` | no other changes needed: `port.resetMemory(options, ...)` exists in LOS 24.0 (`EuiccPort.resetMemory`) |

Verified against LineageOS 24.0 (GitHub `lineage-24.0` branches): the AIDL and `EuiccCardController`
there have **no** `flags` parameter — the GrapheneOS signature is theirs, so all four changes must be
applied. `EuiccCardManager`/`IResetMemoryCallback` are otherwise identical.

**Port surface for lenOS:** `frameworks/base` + `frameworks/opt/telephony` (both already in the lenOS
workspace) + hook `EuiccWipe` into the existing lenOS `DuressWipe.run()` (lenOS already has the
GrapheneOS DuressWipe minus the eSIM thread — see `patches/frameworks_base/0005`).
**API/version risk:** low; only internal AIDL/API changes (hidden). The 3 s wait for the eUICC thread
then poweroff mirrors upstream; if the eSIM wipe takes longer it may be cut short by shutdown — same
trade-off as upstream.
**Verdict: shipped/done in lenOS** (was "port now" at first writing). **Size as shipped: S–M
(~370 LOC across 2 repos).** Value achieved: removes the "carrier still has your number/profile after a
duress wipe" leak — the duress flow is now complete. Caveat: on a physical-SIM device without eSIM the
code paths are inert (asteroids supports eSIM, so it matters).

**lenOS status — DONE (both halves, 2026 redo).**
- Duress backend (`frameworks_base/0005-lenos-duress-credentials.patch`): the same GrapheneOS class set —
  `ILockSettings.aidl`, `LockPatternUtils.java`, `DuressCredential.java`, `DuressCredentials.java`,
  `DuressPasswordHelper.java`, `DuressWipe.java`, `LockSettingsService.java` (verify-result hook),
  `LockSettingsShellCommand.java`, `RecoverySystemService.java`.
- eSIM wipe (`frameworks_base/0007-lenos-esim-duress-wipe.patch` + `frameworks_opt_telephony/0001-lenos-esim-duress-wipe.patch`):
  exactly the four changes tabulated above — `EuiccCardManager` hidden `resetMemory(..., flags)` overload
  + `RESET_FLAG_IS_FOR_DURESS_WIPE`, new `EuiccWipe.java` (~113 lines), `IEuiccCardController.aidl` flags
  parameter, and `EuiccCardController.resetMemory` with the SYSTEM_UID gate and the carrier-notification
  suppression. `DuressWipe` calls `EuiccWipe.run(ctx, RESET_FLAG_IS_FOR_DURESS_WIPE)` before
  `deleteSecrets()` + poweroff.
- `vendor/lenos/docs/features.md` (line 56) now documents the complete flow (3-second eUICC budget,
  system-uid requirement, skipped carrier notification, owner-credential-only enrolment) and references
  the three patches; the earlier "honest limits" claim of an unerased eSIM is gone.

Everything above remains accurate as the porting reference; no open items in this section.

---

## 4. Require unlocking for sensitive quick tiles (special investigation #3) — DONE in lenOS

**What it does.** QS tiles that can change security-relevant state (airplane mode, hotspot, NFC, data,
etc.) cannot be toggled from the lock screen; only a small allow-list of harmless tiles works while
locked. Interacting with a blocked tile instead prompts unlock.

**GrapheneOS implementation** (`packages/SystemUI/src/com/android/systemui/qs/`):
- `QSTileImpl.java` — new default method `public boolean isAllowedWhenLocked(Action action)`
  (default `false`) and the click path in `handleAction()` wraps the action in
  `postQSRunnableDismissingKeyguard()` when the tile is not allowed while locked. All three action kinds
  (click / long-click / secondary click) are gated.
- `QSHost.java` + `QSHostAdapter.kt` — expose
  `com.android.systemui.statusbar.policy.KeyguardStateController` to tiles (append-only interface change).
- 11 tile overrides returning `true` (identical allow-list to what lenOS landed): `BatterySaverTile`,
  `ColorCorrectionTile`, `ColorInversionTile`, `DeviceControlsTile`, `FlashlightTile`,
  `FlashlightTileWithLevel`, `NightDisplayTile`, `QRCodeScannerTile`, `ReduceBrightColorsTile`,
  `RotationLockTile`, `UiModeNightTile`.

**lenOS status — DONE (faithful).** `frameworks_base/0004-lenos-qs-unlock-gating.patch` (287 lines) now
implements exactly this design: `QSTileImpl` hunks (`isAllowedWhenLocked` default + `handleAction` gate,
patch lines ~54/~95), the same 11 tile overrides (patch lines 122–281, incl. the Kotlin
`DeviceControls`/`FlashlightTileWithLevel` overrides) and the `QSHost`/`QSHostAdapter` accessor. The
earlier lenOS mechanism (toast + spec allow-list of {flashlight, camera toggle}) is gone.

**Deviations vs GrapheneOS:** none material found; the tile set matches GrapheneOS's.
`KeyguardStateController` and `postQSRunnableDismissingKeyguard` already exist in LineageOS 24.0's
SystemUI/IActivityStarter. **Size: S** (single module). **API/version risk: none.**
**Verdict: shipped/done.**

---

## 5. Network permission toggle — DONE in lenOS

**What it does.** Turns `INTERNET` into a user-visible runtime permission with a per-profile toggle:
when disabled, the app gets no direct *and no indirect* network access (including access through
same-profile helper apps/OS APIs), `localhost` is also guarded, and the OS *pretends the network is
down* (APIs report a connectivity failure, scheduled jobs avoid running) instead of surfacing
permission errors. Enabled by default; the package installer shows the toggle in the install
confirmation UI.

**GrapheneOS implementation:**
- `core/res/AndroidManifest.xml:2348` — `INTERNET` is `dangerous|instant`
  (LineageOS 24.0 `:2336` still `normal|instant`).
- Kernel/eBPF enforcement: netd's per-UID traffic permission map driven by Connectivity's
  `PermissionMonitor`. **AOSP 17/LineageOS 24.0 already ships this machinery** — verified in
  `packages/modules/Connectivity` on `lineage-24.0`:
  `service/src/com/android/server/connectivity/PermissionMonitor.java:1037-1039`
  (`TRAFFIC_PERMISSION_INTERNET`), `:1290-1296` (`sendAppIdsTrafficPermission`), plus the
  `BpfNetMaps` uid-rule machinery. The stock enforcement is compatibility-gated: the
  `NETWORK_BLOCKED_WITHOUT_INTERNET_PERMISSION` compatibility change (id 333340911) is
  `@EnabledAfter(targetSdkVersion = 36)` in the LineageOS 24.0 tree, while in GrapheneOS branch 17 no
  fwb hit for that change id remains (their release gate has passed — enforcement effectively
  unconditional). GrapheneOS's added value is the *policy* (runtime, user-revocable, enabled by default
  for all apps) plus the UX layers, not a new firewall.
- UI/UX: PermissionController group mapping (`PermissionMapping.kt`, `KotlinUtils.kt:` the NETWORK group
  and per-app toggle), Settings app per-app screen (works automatically once the manifest marks the
  permission dangerous), and the "pretend the network is down" behavior in Connectivity
  (status/callbacks/job scheduling). The first analysis above assumed an install-time toggle inside a
  GrapheneOS PackageInstaller fork; the 2026 port checked their branch-17 `PackageInstaller` and it has
  **no** SRT/INTERNET references — installs auto-grant and app info is the toggle, so no installer work
  was done (same as GrapheneOS).
- Second enforcement layer: GrapheneOS also prevents apps without the permission from proxying network
  access through APIs/components that do have it (the binder/TRAFFIC_PERMISSION_INTERNET mapping — the
  stock `PermissionMonitor` already tracks per-appId traffic permissions, so this converges with AOSP).

**Port surface for lenOS.** 4 projects, heavily pre-built by AOSP 17:
1. `frameworks/base` — 1-line manifest change (INTERNET → `dangerous|instant`).
2. `packages/modules/Connectivity` — enable the enforcement for all target SDKs (drop/overify the
   `@EnabledAfter(36)` gate), ensure the "network down" reporting paths; small–moderate.
3. `packages/modules/Permission` (PermissionController) — group/icon/strings and special-casing;
   small.
4. `packages/apps/PackageInstaller` — install-time toggle (analysis at the time; dropped — GrapheneOS
   itself has no installer change; see below).
netd/eBPF: no work (already in the Android 17 tree). sepolicy: no delta identified in GrapheneOS
branch 17 beyond stock.
**Risks:** shared-UID apps and system components that use INTERNET per UID; instant-permission
semantics; apps that require network for first-run but haven't been granted; jobs/captive portal
testing. Moderate test matrix (Wi-Fi/cellular/tethering, DNS, jobs, installer UI).
**Size: M–L** (multi-repo, but mostly wiring AOSP's existing feature to a visible permission).
**Verdict: port now — top value** alongside the sensors permission (§6); the single most visible
privacy feature after the ones already shipped.

**lenOS status — DONE (2026 redo, three patches).** The port follows GrapheneOS's *"special runtime
permissions"* (SRT) design rather than the older analysis above: `INTERNET` is a `dangerous|instant`
runtime permission whose revocation switches the app into **internet compat mode** instead of exposing
permission errors. `INTERNET` is currently the only SRT member; the sensors permission (§6, Tier 2)
extends the same infrastructure rather than duplicating it.

- `frameworks_base/0025-lenos-network-permission.patch` — the whole SRT framework:
  - `INTERNET` → `dangerous|instant`, `permissionGroup="android.permission-group.UNDEFINED"`, plus a new
    `android.permission-group.NETWORK` group ("Network" / "access the network" strings copied verbatim
    from GrapheneOS; the `perm_group_network` drawable already ships in `frameworks/base`).
  - `SrtPermissions` (`@hide`): per-process flags (`FLAG_INTERNET_COMPAT_ENABLED`), `setFlags()`,
    `shouldSpoofSelfCheck()`.
  - `SpecialRuntimePermAppUtils` (`@SystemApi` — the Connectivity module needs it across the
    boundary): `isInternetCompatEnabled()` / `enableInternetCompat()`.
  - `AppBindArgs` + `IApplicationThread.bindApplication(Bundle extraArgs, …)` + `ActivityThread` /
    `ActivityManagerService` / `NativeApplicationThreadWrapper` plumbing, so the server tells each app
    process at bind time whether it is in internet-compat mode. The GOS `ActivityThreadHooks` indirection
    is inlined (null-guarded) per the deviation rules.
  - Server side: `PackageManagerHooks` (new, `com.android.server.ext`) computes the bind flags from the
    package's *current* permission state via `SpecialRuntimePermUtils` (INTERNET-only): auto-grant
    policy, the "system apps are always granted unless user-set" evaluation path, and GOS's
    `INTERNET.mode=runtime` package-metadata escape hatch for system apps.
  - Self-check spoofing: both `PermissionManager` sites (`checkPermissionUncached`,
    `checkPackageNamePermissionUncached`) return GRANTED for the app's own INTERNET checks while compat
    mode is on; `DownloadManager`'s four internet APIs (`enqueue`, `remove`, `query`,
    `addCompletedDownload`) answer "no network" (invalid id / empty cursor).
  - Permission service (`services/permission/…`, Kotlin): auto-grant **only on a new install** —
    `PermissionManagerServiceInternal.PackageInstalledParams` grew `isNewlyInstalledInUserId()`
    (GrapheneOS has it; LineageOS 24.0 does not. Added by the patch and populated from `InstallPackageHelper`'s new-install and
    install-existing paths) — so an app *update* can never re-grant a revoked INTERNET. Pre-M legacy
    handling and legacy permission review skip SRT; `resetRuntimePermissions` skips SRT;
    implicit-split inheritance forwards SRT grants; system packages get `RUNTIME_GRANTED` on evaluation
    unless user-set.
- `packages_modules_Connectivity/0002-lenos-network-permission.patch` — all 32 `ConnectivityManager`
  gates return the "network is down" answer (`null` / empty / `false`, callbacks suppressed) and
  `NsdManager` swaps in a stubbed `INsdServiceConnector` (registration/discovery/resolve callbacks fail
  with `FAILURE_INTERNAL_ERROR`) so NSD can't be used as an ORB; the stub implements the full A17
  connector interface, including `registerServiceInfoCallbackWithRequest`,
  `injectOffloadEngineResponse`, `checkPermissionForService` and the `packageName` argument of
  `INsdManager#connect`.
- `packages_modules_Permission/0002-lenos-network-permission.patch` — PermissionController: the
  "Network" group presentation (`PermissionMapping`, INTERNET mapped into it), grant/revoke treats SRT
  as runtime for any targetSdk (`KotlinUtils`), `Permission.isGrantedIncludingAppOp` ignores
  `reviewRequired` for SRT, `AppPermissionGroup` grants/revokes SRT for legacy apps, and the
  permission-usage / hibernation / auto-revoke screens never classify SRT as "unused" or revocable.

**Enforcement chain:** the socket-level block is the *already-shipped* AOSP machinery —
`PermissionMonitor` observes runtime permission changes and updates netd's per-UID
`TRAFFIC_PERMISSION_INTERNET` BPF map. The stock `NETWORK_BLOCKED_WITHOUT_INTERNET_PERMISSION`
compatibility gate is `@EnabledAfter(targetSdkVersion = 36)`, i.e. enforcement is already on for every
app on Android 17 / LineageOS 24.0 — no change needed there. The SRT layer adds the *policy* (revocable
runtime permission, auto-grant, compat mode) and the UX.

**Deviations vs GrapheneOS:** none material.
- `MissingSpecialRuntimePermissionNotification` / `PackageManagerNative` /
  `IPackageManagerNative.onDeniedSpecialRuntimePermissionOp` shipped with the sensors permission (§6,
  `fwb/0026` + `frameworks_native/0001`) — their only caller is the sensors path in `frameworks/native`
  `SensorService.cpp`; the framework SRT registry itself (`SpecialRuntimePermUtils`) declares both
  members in `fwb/0025` so the sensors patch never edits a file this one creates.
- `AppPermissionUtils` is SRT-only and `/** @hide */` (GOS makes it `@SystemApi` for other GOS
  components that lenOS doesn't port); the `@SystemApi` surface is exactly
  `SpecialRuntimePermAppUtils.isInternetCompatEnabled()` (`core/api/system-current.txt`).
- No upgrade migration for pre-existing user apps (GrapheneOS has none either — verified in their code
  and release notes); irrelevant for lenOS, where every user app install goes through the auto-grant.
- `AppBindArgs.FLAGS_ARRAY_LEN = 10` and all constants copied from GOS; unused GOS flag slots are left
  in place so the wire format stays comparable.

**Tests:** `vendor/lenos/tests/test_network_permission.py` (20 checks: manifest + group, SRT flag
spoofing, both self-check sites, the four DownloadManager gates, bind plumbing, server flag
computation, auto-grant-on-new-install-only, system-app evaluation, the 32 ConnectivityManager gates,
the NSD stub, XML well-formedness, Java parse, Kotlin balance). Driver markers in
`lenos-1.0-shizuku.sh` verify the applied tree.

---

## 6. Sensors permission — DONE in lenOS

**What it does.** A new `OTHER_SENSORS` runtime permission covering every sensor not already behind an
existing runtime permission (accelerometer, gyroscope, compass, barometer, thermometer, …). Denied →
the app receives **zeroed data** and no events; a dismissible notification informs the user when an app
tries to use blocked sensors. Enabled by default (compat); an ExtSettings default can turn it off for
user-installed apps.

**GrapheneOS implementation:**
- Manifest: `core/res/AndroidManifest.xml:2053-2063` — `OTHER_SENSORS` declared
  `dangerous` with its own permission group.
- Enforcement: `frameworks/native` → `services/sensorservice/SensorService.cpp:2540-2583`
  (`OTHER_SENSORS` check; uids below `AID_APP_START` exempt; apps targeting ≤ P get legacy behavior;
  denied → zeroed values, no events; also hooks `onDeniedSpecialRuntimePermissionOp` into
  `package_native`), `libs/sensor/Sensor.cpp:67` (permission plumbing for the client path).
- Permission plumbing/UI: PermissionController mappings (`PermissionMapping.kt`, `KotlinUtils.kt`) so
  the permission shows up as a runtime toggle in Settings; `MissingSpecialRuntimePermissionNotification.java`
  (`services/core/java/com/android/server/ext/`, 164 lines) posts the "app tried to access sensors" note;
  `AUTO_GRANT_OTHER_SENSORS_PERMISSION` ExtSettings default (already seeded in lenOS `0006`).

**Port surface for lenOS:** `frameworks/native` (SensorService.cpp + Sensor.cpp: ~60 lines of checks),
`frameworks/base` (manifest constant + permission group + `package_native` note path),
`packages/modules/Permission` (mapping/strings/icon), plus Settings strings for group name.
No kernel work; works for all sensors since the gate is in sensor service, not the driver.

**lenOS status — DONE (2026; two framework patches + one native patch).** The network-permission redo
(§5) had already shipped the SRT mechanism this feature plugs into, so adding `OTHER_SENSORS` was:

- `frameworks_base/0025` (extended): the server SRT registry now contains both permissions; the
  `OTHER_SENSORS` auto-grant reads `ExtSettings.AUTO_GRANT_OTHER_SENSORS_PERMISSION` (per user, default
  **on**; a work profile reads the parent profile's value) instead of the unconditional INTERNET
  grant, with GrapheneOS's AMS-null failsafe. The framework manifest declares
  `android.permission-group.OTHER_SENSORS` ("Sensors", `perm_group_location` icon, priority 1000) and
  `android.permission.OTHER_SENSORS` (`dangerous`, group `UNDEFINED`), and `core/api/current.txt`
  carries the new `Manifest.permission`/`Manifest.permission_group` constants (the same file also
  gained the `NETWORK` group entry the network port had missed — without it the API check fails the
  build).
- `frameworks_base/0026` — the notification stack: the `MISSING_PERMISSION` notification channel, the
  proto id (500), `PackageManagerNative.onDeniedSpecialRuntimePermissionOp` (SYSTEM_UID-guarded),
  `MissingSpecialRuntimePermissionNotification` (30 s per-app rate limit, suppressed once the app is
  `USER_SET`, tap opens the grant dialog, "Don't show again" action) plus its `IntentReceiver` /
  `SseUtils` helpers, the strings and the channel string.
- `frameworks_native/0001` — the enforcement: `libs/sensor/Sensor.cpp` tags every HAL sensor without a
  more specific permission with `OTHER_SENSORS`; `SensorService::canAccessSensor` denies app UIDs that
  do not hold it. UIDs below `AID_APP_START` (e.g. the closed-source `gpsd` daemon) keep access; apps
  targeting pre-Q that used the step counter without `ACTIVITY_RECOGNITION` get `OTHER_SENSORS`
  enforced instead of upstream's unconditional allow. On a denial for an `OTHER_SENSORS`-protected
  sensor the service calls the new `IPackageManagerNative.onDeniedSpecialRuntimePermissionOp`
  ("package_native"), which reaches system_server's notification helper. The AIDL lives at
  `native/android/aidl/...` on A17 (the same path as GrapheneOS); the extra method is
  carried by `frameworks_base/0029`.
- `packages_modules_Permission/0002` (extended): the "Sensors" group mapping, so the permission appears
  as an ordinary runtime toggle in app info.

**Deviations:** the notification channel is added inline in `SystemNotificationChannels.createAll`
(GrapheneOS refactored their file around an `extraChannels()` hook); the `<java-symbol>` duplicates
GrapheneOS puts next to the new strings are omitted (the strings are only referenced from
system_server); the 500 proto id is added with a trailing-context-only hunk so the patch applies to
pristine and after `fwb/0023` (400), which inserts at the same place.

**Tests:** `vendor/lenos/tests/test_sensors_permission.py` (16 checks across `frameworks/base`,
`frameworks/native` and the Permission module).
**Risks:** "zeroed data" must also cover `SensorDirectChannel`/batch paths (upstream covers them);
per-SoC differences minimal because the permission gate is Central.
**Size: L** (native service + permission module + framework glue). **API/version risk: low**
(manifest/permission infrastructure is stable; the native patch is a small enforcement delta).
**Verdict: port now — top value** (second to network permission). High user visibility, clean
enforcement point, already half-seeded in lenOS's ExtSettings constants.

---

## 7. Two-factor fingerprint unlock (duress PIN as second-factor PIN)

**What it does.** Optional second factor for biometric unlock: after a successful fingerprint match,
a separate "second factor PIN" (a different credential, not the primary passphrase) must be entered to
complete unlock. Failure counts toward the normal attempt limit. The duress PIN is honoured here too —
entering it as the second factor triggers the duress wipe path (§3). This lets users keep a strong
primary passphrase with convenient fingerprint+PIN unlock.

**GrapheneOS implementation (credential-domain model — the big one):**
- `LockDomain` (PRIMARY/SECONDARY) is a *new abstraction* in the locksettings stack:
  `services/core/java/com/android/server/locksettings/` — `LockSettingsService.java`,
  `SyntheticPasswordManager.java` (per-domain synthetic passwords, separate SPM blobs),
  `LockSettingsStorage.java`, `LockSettingsStateListener.java`, and even the duress code
  (`DuressPasswordHelper.java` references `LockDomain.Secondary` so the duress PIN is a valid
  *secondary* credential). 41 files reference `LockDomain` in the GrapheneOS tree (incl. tests).
- SystemUI: biometric/credential prompt flow for the secondary domain.
- Settings app: `ChooseBiometricSecondFactorPin.java`, `BiometricSecondFactorPinPreferenceController.java`,
  `BiometricSecondFactorSaveAndFinishWorker.java`, `BiometricSecondFactorPinSettings.java`,
  `ChangeBiometricSecondFactorPinPreferenceController.java`, `DeleteBiometricSecondFactorPinPreferenceController.java`,
  plus `ChooseLockGeneric.java`, `FingerprintSettings.java`, `ScreenLockSettings.java` integration.
- **LineageOS 24.0 has no `LockDomain` at all** (single-credential SPM). Backporting the domain model is
  an invasive change to synthetic-password storage, upgrade paths, and every lock-settings caller.
  There is no shortcut that preserves the "duress PIN counts as second factor" property without the
  domain split.
**Size: XL (new subsystem backport; hundreds to >1000 lines across fwb + Settings + SystemUI).**
**API/version risk: high** (credential storage formats, SP upgrade path, Weaver/StrongBox interaction;
GrapheneOS iterated on this over multiple releases).
**Verdict: port later (not now).** Very valuable for PIN-scramble/duress users, but it must be done
after the smaller duress eSIM work and with careful device testing; it is the largest item in the
"port later" bucket together with storage/contact scopes and the Play compatibility layer.

---

## 8. Secure Paste (clipboard read gating)

**What it does.** Apps cannot read clipboard content *set by other apps* unless allowed; they can
always read content they set themselves. Control is per-app with a global default for third-party
apps (`ALLOW_CLIPBOARD_READ_BY_DEFAULT`), integrated into the text-selection toolbar, IME, accessibility
and keyboard-shortcut paths. Android only shows a notice *after* a read; Secure Paste makes it opt-in.

**GrapheneOS implementation:**
- Setting: `core/java/android/ext/settings/ExtSettings.java:103-104` →
  `Settings.Global.ALLOW_CLIPBOARD_READ_BY_DEFAULT` (**the constant is already seeded by lenOS patch
  0006**), per-app switch `android/ext/settings/app/AswAllowClipboardRead.java`.
- Per-app state: `GosPackageStateFlag` bits `ALLOW_CLIPBOARD_READ_NON_DEFAULT`(31), `ALLOW_CLIPBOARD_READ`(32),
  `SUPPRESS_CLIPBOARD_ACCESS_DENIAL_NOTIF`(33) — part of scopes-style per-package state (see §14).
- Enforcement: `services/core/java/com/android/server/clipboard/ClipboardAccess.java` (imports
  `android.content.pm.GosPackageState`, computes a read policy per package/UID) called from
  `clipboard/ClipboardService.java:709-710` (`getClipboardReadPolicyForPackage`); denial notification
  path + suppression bit.
- UI glue: `packages/SystemUI` `SecurePasteSelectionToolbar.kt` (34), `SecurePasteAccessibility.kt` (61),
  `SecurePasteKeyEventHandler.kt` (51), `SecurePasteToolbar.kt` (27) — small classes that keep the
  standard paste affordances working when reads are blocked; `frameworks/base/tests/SecurePasteTests/`.

**Port surface for lenOS — staged:**
1. *Global-only stage (M):* read `ExtSettings.ALLOW_CLIPBOARD_READ_BY_DEFAULT` (or a lenOS key) in
   `ClipboardService`, block cross-app reads for third-party apps, keep same-app reads; add the SystemUI
   toolbar helpers. No new per-package state subsystem.
2. *Full stage (L–XL):* per-app overrides need either GrapheneOS's `GosPackageState` subsystem
   (heavier, shared with scopes/memtag/etc.) **or** reuse the already-present AOSP AppOps op
   `OP_READ_CLIPBOARD` (`AppOpsManager.java:1037` in LineageOS 24.0) as the per-app switch — a
   deliberate deviation that avoids the GOS state machinery.
**API/version risk: low** for stage 1; moderate for stage 2 depending on the path chosen.
**Verdict: port now (stage 1), port later (per-app).** Stage 1 closes the "any focused app reads
clipboard" hole cheaply; the AppOps route looks like the pragmatic lenOS-flavoured implementation.

**Implemented in 1.0** (`frameworks_base/0015-lenos-secure-paste` + the Settings row in
`packages_apps_Settings/0001`): `ClipboardService` reads the GrapheneOS
`ALLOW_CLIPBOARD_READ_BY_DEFAULT` ExtSetting (default `true`, as in GrapheneOS). When the setting is
off, third-party apps may only read content they own; the default IME and system apps keep access;
`getPrimaryClipDescription` returns a label-less description (mime types preserved) and
`hasClipboardText` keeps the presence signal, matching GrapheneOS. Stage 2 (per-app AppOps,
denial notifications, SystemUI paste grants/toolbar) is not ported; the feature is opt-in, so stock
paste keeps working until the user enables it.

**Experimental stage 2 (OPS-4):** `packages_apps_Settings/0004` in `patches-experimental/`
exposes the existing AOSP `OP_READ_CLIPBOARD` AppOp as a per-app switch for user-installed apps.
It adds no framework patch, permission or new AppOp, excludes system apps/enabled keyboards/disabled
packages, and lets the global Secure Paste setting remain authoritative. GrapheneOS's
`GosPackageState` per-app state, denial notification and SystemUI paste-grant toolbar are still
not ported.


---

## 9. Delayed "Allow" action on permission + ADB prompts

**What it does.** The positive/allow button in system permission dialogs and the ADB USB-authorization
prompt is disabled for one second, so neither accidental taps nor tapjacking-style app tricks can
confirm a grant instantly.

**GrapheneOS implementation:**
- Permission dialogs: `packages/modules/Permission/PermissionController/.../GrantPermissionsViewHandlerImpl.kt:411`
  — `button.postDelayed(action, 1000)`.
- ADB prompt: `packages/SystemUI/.../usb/UsbDebuggingActivity.java:110`
  — `getMainThreadHandler().postDelayed(() -> allowButton.setEnabled(true), 1000)`.

**LineageOS 24.0 status:** neither file contains a delay (raw-file check of `lineage-24.0`:
`UsbDebuggingActivity.java` has no `postDelayed`; `GrantPermissionsViewHandlerImpl.kt` only uses
`TransitionManager`). Port = two ~3-line patches.
**Size: S (< 10 LOC total).** **API/version risk: none.** **Verdict: quick win — port now.**
**Done:** `packages_modules_Permission/0001` (all six allow variants, `isAllowButton` helper +
`postDelayed` gate) and `frameworks_base/0014` (ADB prompt); both apply cleanly to LineageOS 24.0.
Adaptation vs GrapheneOS: the permission handler's debug log omits the app package — this branch no
longer passes it into the handheld handler (upstream refactor). Driver markers + `tests/test_delayed_allow.py`.

---

## 10. USB-C port control (USB-C and pogo pins)

**What it does.** Five modes for the USB-C port (and, on devices with pogo pins, those too):
Off, Charging-only, Charging-only when locked (default), Charging-only when locked except before first
unlock, and On. After locking (or immediately, depending on mode), new USB connections are blocked and
existing ones are ended; the data lines are disabled **at the hardware level via the USB controller**,
USB-C alternate modes (DisplayPort) are disabled, plus a kernel/OS-level second layer.

**GrapheneOS implementation:**
- Setting: `core/java/android/ext/settings/UsbPortSecurity.java` (20 lines) — mode constants +
  `IntSysProperty("persist.security.usb_mode", …)`, default `MODE_CHARGING_ONLY_WHEN_LOCKED`
  (`MODE_ALL_PORTS_ENABLED` on debuggable builds). Comment: *"keep in sync with USB HAL implementations
  that check this sysprop during init"* — the HAL/kernel side is where the hardware-level blocking lives.
- OS logic: `services/core/java/com/android/server/policy/keyguard/UsbPortSecurityHooks.java` (424 lines)
  — registers port-change receivers, tracks keyguard state (`onKeyguardShowingStateChanged`,
  `keyguardDismissedAtLeastOnce` for the "-AFU" mode), two-phase handling for new connections
  (`setDenyNewUsb2`), `setSecurityStateForAllPorts`, and the HAL interception
  `onHalEnableUsbDataSignal()`.
- HAL plumbing: `services/usb/java/com/android/server/usb/UsbService.java:429` (`init`) and `:1226`
  (`updateSetting`); `hal/port/UsbPortAidl.java:367` (OS intercepts `IUsb.enableUsbData` and lets the
  hook block/defer) and `:458` (`enableUsbDataWhileDocked` rejected when supported); same in
  `UsbPortHidl.java:277,:325`.
- Feature gate: `core/res/res/values/config.xml:7970` — `config_usbPortSecuritySupported=false`,
  enabled by device overlay where the vendor HAL/kernel implements the contract.

**SM7635 feasibility.** Two layers:
1. *OS side (portable, ~L):* setting + hooks + HAL interception. Works only if Nothing/Qualcomm's USB
   HAL implements AOSP's `IUsb.enableUsbData` (AIDL USB HAL method that AOSP's `UsbManager.setUsbDataSignalingEnabled`
   also uses) and the kernel honors it. That must be prototyped on a device: check the running HAL
   service's interface version and `adb shell dumpsys usb`. If the HAL supports it, we get
   "charging-only"-style data-line blocking while booted (probably not the persisted-ACROSS-boot sysprop
   contract, which requires HAL init support for `persist.security.usb_mode`).
2. *Hardware layer (not feasible):* disabling alternate modes / PD data lines in the controller and
   reading `persist.security.usb_mode` during HAL init are vendor firmware features. Nothing's stock
   firmware controls this; we cannot add it. Pogo pins: the Phone (3a)/3a Pro has none, so that half of
   the feature is N/A.

**Size:** OS-side port L (mostly the 424-line hooks file + HAL plumbing); hardware part infeasible.
**API/version risk:** low for OS side; the risk is entirely vendor-HAL behavior.
**Verdict: not feasible now (full feature); partial prototype possible (see step 1).** Put on the
"research" list; do not promise GrapheneOS-equivalent guarantees.

**Implemented in the opt-in experimental series (not 1.0).** `frameworks_base/0003` +
`packages_apps_Settings/0002` implement the OS-side subset using AOSP 17's existing per-port
`UsbPortManager.enableUsbData` operation rather than the GrapheneOS vendor sysprops. The five
GrapheneOS mode constants and the `persist.security.usb_mode` key are preserved; a controller
applies the mode on boot, keyguard lock/unlock and first unlock, rejects ordinary re-enables while
the policy is blocking, and exposes the setting in Settings. Because the portable operation only
controls data lines, modes 0 (`ALL_PORTS_DISABLED`) and 1 (`CHARGING_ONLY`) are equivalent on this
build; alternate-mode/PD disabling and persisted HAL-init enforcement remain vendor-firmware work.
The `asteroids` USB HAL has not been validated, so this stays out of 1.0 and is marked experimental.

---

## 11. FBE filename padding 16 → 32 bytes

**What it does.** Per-profile file-based-encryption policies use 32-byte (instead of the stock 16-byte)
padding for encrypted filename lengths, reducing the information leaked by the length of directory
entries.

**GrapheneOS implementation** — a genuine one-liner, in `system/extras` (GrapheneOS fork
`platform_system_extras` @ branch 17), file `libfscrypt/fscrypt.cpp:247-248`:

```cpp
// GrapheneOS has always used the maximum 32 byte padding.
options->flags |= FSCRYPT_POLICY_FLAGS_PAD_32;
```

vold calls libfscrypt's `ParseOptions()` when creating the per-profile encryption policies
(`vold/FsCrypt.cpp:330` for `s_data_options`, `:372` for per-storage options), so changing libfscrypt
changes the policy flags of every policy created afterwards.

**Port surface for lenOS:** patch `system/extras` (libfscrypt) — effectively 2 lines + comment (**done**:
`system_extras/0001-lenos-fbe-pad-32`; the pre-R compatibility branch is dropped rather than kept —
`PRODUCT_SHIPPING_API_LEVEL := 35` makes it unreachable — and the stale `fscrypt_test` expectations are
updated to PAD_32, which GrapheneOS's fork left behind). The
device fstab (`device/nothing/asteroids/init/fstab.default:59`,
`fileencryption=aes-256-xts:aes-256-cts:v2+inlinecrypt_optimized+wrappedkey_v0`) does not need changes;
padding is a policy flag, not an fstab option.
**Caveats:** applies to *newly created* encryption policies — on already-installed devices the existing
metadata keys keep 16-byte padding until factory reset/re-encryption, so this is a "new installs and
post-wipe" win (still worth shipping now; it also affects each new user profile created later).
No interaction with Qualcomm ICE (`inlinecrypt_optimized`/`wrappedkey_v0` are orthogonal flags).
**Size: S (~2 LOC + platform repo patch).** **API/version risk: none** (kernel 6.6 supports PAD_32;
AOSP's default is only PAD_16 for compatibility).
**Verdict: quick win — port now.**

---

## 12. Improved VPN leak blocking / always-on VPN hardening

**What it does.** Closes the known classes of "traffic escapes the VPN while 'Block connections without
VPN' is on" holes:
1. System-resolver DNS queries leaking to network DNS when the VPN is down (lockdown race).
2. DNS connections to the VPN's own DNS servers happening outside the tunnel.
3. Processes bypassing the VPN with multicast packets (directly or via kernel IGMP/MLD helper paths).
4. mDNS/"`*`" discovery via the system NSD Manager under VPN lockdown.
5. Multicast leaking into *another profile's* VPN tunnel.
6. A kernel/system-call interface-bind bypass in the eBPF firewall.

**GrapheneOS implementation (evidence from the full-history clones):**
- netd (`GrapheneOS/platform_netd`, branch 17 with history):
  - `82da9204` *"fix DNS leak in VPN lockdown mode when VPN is down"* — `server/NetworkController.cpp`,
    +3/−2 lines: when all VPNs are down, point the system resolver at the *blocked* network instead of
    the default network's DNS, so the resolver can't leak. Small, surgical.
  - `dcef5ccb` *"add multicast firewall"* — `server/MulticastFirewallController.cpp` (135) +
    `.h` (56) + `Controllers.cpp/.h` wiring (+8/+2) + tests (56); ~267 insertions total. Prevents
    sending multicast through a VPN tunnel the process isn't allowed to access (cross-profile leak) and
    is the base for the lockdown multicast filtering.
  - `d57ea8dc` *"stop dropping router advertisements received on VPN interface"* — +5 lines in the
    multicast controller: keep RAs working when the interface is under the lockdown firewall.
  - `40c47da2` *"Fix IPV4/6 privacy leak"* — `server/SockDiag.cpp` +8/−4 (flushes/handles sockets so
    IPv6 privacy addresses can't be used as a cross-network identifier; pairs with Wi-Fi privacy).
- DnsResolver (`GrapheneOS/platform_packages_modules_DnsResolver`, `DnsResolver-h`):
  - `890fe28` *"Exclude VPN and mobile data from .local resolution"* — `.local`/mDNS lookups skip VPN and
    cellular interfaces (backs the NSD behavior).
- NSD Manager: `modules_Connectivity` `service-t/src/com/android/server/NsdService.java:3452-3456` —
  `ConnectivityUtil.isRegularAppWithLockdownVpnEnabled(mContext, uid)` → returns `null`/refuses
  discovery for regular apps while a lockdown VPN is enabled. Helper:
  `frameworks/base/core/java/android/ext/ConnectivityUtil.java:41` (exported as a module-lib API
  `isRegularAppWithLockdownVpnEnabled(Context, int)` — small, easy to port).
- Vpn app-level: a local diff of GrapheneOS's `Vpn.java` against LineageOS 24.0 is mostly version
  drift (Android 17 refactors); the functional delta is that GrapheneOS no longer
  auto-unsets an always-on VPN whose package is currently "unsupported" (so the setting survives safe
  mode / temporary unavailability). Settings screens (`ConfigDialog`, `AppManagementFragment`,
  `VpnUtils`) are identical — the "Always-on VPN"/"Block connections without VPN" toggles are already
  available for all VPN apps by default in AOSP 17, so that part of the feature is *already present* in
  LineageOS 24.0.
- The "eBPF interface-bind bypass" (#6) was **not located** in the netd branch-17 scan; it may be a
  kernel-side fix (their kernel fork). Assume infeasible for us without kernel work.

**Port surface for lenOS:**
1. netd: cherry-pick/port `82da9204` (tiny), `dcef5ccb` + `d57ea8dc` (multicast firewall ~215 core
   LOC + tests), `40c47da2` (tiny) — our netd clone/PoC tree shows these apply against 24.0 with minor
   fuzz.
2. DnsResolver: port `890fe28` (or rely on it already being in mainline AOSP 17 — check current
   `DnsResolver` tree; the commit *is* in AOSP history, so likely present).
3. `frameworks/base` `android.ext.ConnectivityUtil` helper + `modules_Connectivity` `NsdService`
   lockdown check (~30 LOC total, plus strings if we want a user message).
4. `frameworks/base` `Vpn.java` "don't unset unsupported always-on" hunk (~5 LOC).
**Risks:** netd patches touch the firewall/eBPF paths — test tethering, RAs on Wi-Fi, IPv6, multicast
apps (mDNS, discovery); the multicast controller is the largest piece and has upstream tests we can use.
**Size: M** (netd + Connectivity + fwb; 4 small commits + 1 medium). **API/version risk: low**
(netd internal API stable across 16/17 where not renamed — check `Controllers` wiring).
**Verdict: port now.** This is a high-value, well-scoped hardening set; the netd commits are the
authoritative core of "improved VPN leak blocking" and are absent from LineageOS 24.0 (netd there is
stock AOSP).

**Implemented in 1.0** (`system_netd/0001`, `packages_modules_Connectivity/0001`,
`frameworks_base/0017` + `frameworks_base/0018`):
- netd: `82da9204` ported as-is to `getNetworkForDnsLocked()`; `dcef5ccb` + `d57ea8dc` ported as
  `MulticastFirewallController` with the GrapheneOS chain ordering, unit tests and updated
  `ControllersTest` expectations. The new files carry lenOS Apache headers (GrapheneOS's copies had
  none) — no code delta.
- `40c47da2` (SockDiag address logging) is already in LineageOS 24.0, verified in the cloned tree;
  the DnsResolver `.local`/VPN transport filter is AOSP `a17ba5aee1` from 2022 and therefore already
  present upstream. Neither needs a patch.
- `ConnectivityUtil` + the module-lib API declaration are ported verbatim. The NSD check is placed in
  the branch-17 `NsdService.connect()` (three-arg form with `packageName`, matching GrapheneOS),
  immediately after the caller uid is read, and returns `null` for regular apps.
- `Vpn.startAlwaysOnVpn()` drops the auto-unset of an unsupported always-on package. LineageOS 24.0
  already kept the setting in safe mode; the port removes the remaining normal-mode unset so the
  setting survives any temporary package unavailability, as in GrapheneOS.


---

## 13. Vanadium / WebView replacement options

**What it is.** GrapheneOS's hardened Chromium fork ("Vanadium") ships as both the system WebView
provider and the default browser, with MTE for the main allocator, type-based CFI, JIT disabled by
default with per-site toggle, content filtering, WebRTC IP handling policies, reduced UA/client hints,
remote services cut to component-update + DoH connectivity checks, etc. (full feature list on the
features page lines 495-587 of the dump).

**Not source-portable to lenOS in any patch-like way:**
- Building Vanadium = building Chromium with the GrapheneOS patch set (multi-GB, hours-long builds,
  Chromium version churn, their own release pipeline).
- WebView provider integration additionally needs the package/signature allow-listing that AOSP uses
  (`config_webview_packages`-style provider config), a build/update pipeline for the APK, and acceptance
  that the browser and WebView version must track line together.
- The GrapheneOS releases (browser APK, WebView APK, PDF viewer) are signed with the GrapheneOS release
  keys: an official prebuilt can be *installed as a user app* (browser) from their app repository, but
  *cannot legally/reliably become the system WebView* of a lenOS build (WebView provider signature
  trust is per-build; sideloading Vanadium's WebView requires relaxing the provider allow-list and
  accepting out-of-band updates).

**Pragmatic options for lenOS (rough effort, no source port):**
1. **Keep AOSP WebView + vendor a privacy browser** (current path): continue with LineageOS's browser
   stack; optionally recommend/install Cromite (privacy-hardened Chromium fork with its own release
   channel and WebView builds) — *M effort, no OS integration*, still not Vanadium.
2. **Bundle a prebuilt non-Vanadium Chromium WebView** (Cromite WebView or AOSP's Trichrome from
   LineageOS prebuilts — the latter is what ships now): *S–M*, no hardening delta beyond stock.
3. **Build Vanadium from source inside lenOS** — *XL, ongoing maintenance*, unrealistic for this
   project unless adopting GrapheneOS's entire Chromium fork/pipeline.
**Verdict: app-level bundle / port later — not source-portable.** If lenOS wants Vanadium-class
hardening, the realistic recommendation is (3) only as a long-term project, or (1)/(2) with Cromite as
the interim browser while keeping the stock WebView. Nothing in the rest of this inventory depends on
Vanadium.

---

## 14. Smaller ExtSettings-backed items and the remaining feature sweep

This section covers the remaining categories from the features page (ToC coverage is complete: every
heading is mapped here, in §5–§13, in §16–§18 or in the already-written sections). "Seeded" = the
ExtSettings *constant* already exists in lenOS patch 0006 but nothing enforces it yet.

### 14.1 Attack-surface / radio items

| Item | GrapheneOS implementation | lenOS port | Size | Verdict |
|---|---|---|---|---|
| Wi-Fi / Bluetooth / NFC auto-off timers | fwb `services/core/java/com/android/server/ext/WifiAutoOff.java` (141), `BluetoothAutoOff.java` (125), `DelayedConditionalAction.java` (122); keys `Settings.Global.wifi_off_timeout` / `bluetooth_off_timeout` (`Settings.java:14470/:14474`), NFC via the NFC app | **done (Wi-Fi + Bluetooth):** `fwb/0020` ports all three service classes under a trimmed `SystemServerExt` hooked from `SystemServer.java`, plus a driver marker; Settings/0001 adds the two list rows in More security & privacy with the GrapheneOS `AutoOffSetting` choices (0/15 s/30 s/1 m/2 m/5 m/10 m/30 m/1 h/2 h/4 h/8 h, millisecond values). NFC variant not ported (needs the Nfc app side) | S–M | done (NFC later) |
| USB attach attack surface | see §10 | see §10 | L | partial only |
| Native debugging (ptrace) block for bundled apps + per-app toggles + notification | ExtSettings `ASW` switches (`android/ext/settings/app/Asw*`), `GosPackageStateFlag.BLOCK_NATIVE_DEBUGGING*` (6-8), notification helper; enforcement partially via SELinux (GrapheneOS sepolicy) | **Partial experimental ENF-1:** global opt-in `PR_SET_DUMPABLE` block in `frameworks_base/0005` + Settings/0005. The per-app GosPackageState/SELinux policy, denial UI and bundled-app defaults are still unported | M–L | partial (global primitive only) |
| Dynamic code loading toggles (memory/storage/WebView) | `GosPackageStateFlag.RESTRICT_*` (9-16) + `services/.../ext/DynCodeLoadingUtils.java` (116) + notification; enforcement in bionic/seccomp | constants present; **no-op without bionic/ART/seccomp work** | XL | not feasible now (toggles alone useless) |
| Hardened thread stacks (guard gap, separate `pthread_internal_t`, randomized stack top) | bionic `libc/bionic/pthread_create.cpp`; GrapheneOS commits `4aefb578a7a0`, `369305a6632d`, `ff25c271653a`, `b777629641e8` | **Experimental HTS-1:** `bionic/0001` ports the four commits behind the read-only `ro.lenos.hardened_thread_stacks=1` property. It is part of the experimental series (`LENOS_EXPERIMENTAL=1`) and absent from the stable/default build. It only changes new pthread mappings; main thread, existing threads, allocator and MTE/ART are untouched | M | source-only; **not built/booted** |
| Exec spawning / hardened_malloc / MTE / BTI+PAC | bionic + `hardened_malloc` + build/ART/kernel work; toggles in ExtSettings/`GosPackageStateFlag` (17–23, 29–30) | platform-wide runtime replacement | XL+ | not feasible now (see §17) |
| JIT disabled base OS / dynamic code blocked for base OS | ART + seccomp work | none | XL | not feasible now |
| "User-created directories not listable without storage permission" | GrapheneOS `72492da1c` (Storage Scopes): `MediaProvider.getFilesInDirectoryForFuse` suffix + `jni/MediaProviderWrapper.cpp` `skip_add_dirs`; apps with READ_MEDIA_* and `Android/` keep upstream behavior | **Done:** `packages_providers_MediaProvider/0001` (directory-listing part). Storage Scopes themselves (`GosPackageState`, `StorageScope`, scope UI) stay unported; `StorageScopesHooks` keeps GrapheneOS's name/shape for the later scope loop | M | done (scopes later) |
| Screenshot shutter sound toggle | SystemUI `ScreenshotSoundPolicy.kt`/`ScreenshotSoundController.kt`: GOS drops AOSP-16's `screenshotForceShutterSound` aconfig gate and gates the non-forced sound on `Settings.System.SOUND_EFFECTS_ENABLED` (`ScreenshotSoundController.kt:86-89`); forced-shutter regions unchanged (`MediaActionSound.mustPlayShutterSound()` identical) | fwb SystemUI refactor (~40 LOC) | S–M | port later (cosmetic) |
| Location privacy indicator | SystemUI `HeaderPrivacyIconsController.kt` + `PrivacyItemController.locationAvailable`; enables indicator for all location APIs (not just GNSS) | **Done:** `fwb/0027` ports GrapheneOS's four-hunk `AppOpsPrivacyItemMonitor.kt` delta verbatim (`OPS_LOCATION` gains `OP_COARSE_LOCATION`; item filter, privacy-type mapping and display check use the array), so coarse-only location access lights the chip. No enablement plumbing is needed on Android 17: AOSP's `cp1a` release config enables `android.location.flags.location_indicators_enabled`, and `cp2a` (the config LineageOS 24.0 selects) inherits it. The A16-era `vendor/lenos/release/` override was dropped during the port. GrapheneOS's `LocationAccumulatedLogger` and the A17 controller/animation refactors are not part of this port | S–M | done |

### 14.2 Privacy / identifier items

| Item | GrapheneOS implementation | lenOS port | Size | Verdict |
|---|---|---|---|---|
| Private screenshots (EXIF) | Timestamp/timezone tags gated on `ExtSettings.SCREENSHOT_TIMESTAMP_EXIF` (`ImageExporter.java:517`); Software tag removed — LineageOS 24.0 sets `exif.setAttribute(ExifInterface.TAG_SOFTWARE, "Android " + Build.DISPLAY)` (`ImageExporter.java:587`), GrapheneOS tree has no such line | 2 hunks in fwb SystemUI + Settings row; constant seeded | S | quick win — **done** (`fwb/0013` + `packages_apps_Settings/0001`) |
| Sensitive notifications hidden by default / passwords hidden while typing | Confirmed: `packages/SettingsProvider/res/values/defaults.xml:170` — `def_lock_screen_allow_private_notifications` = **false** in GrapheneOS (LineageOS 24.0 same file `:170` = **true**), seeded in `DatabaseHelper.java:1642-1643` (fresh DB) and `:2245-2246` (upgrade); passwords-hidden default already exists in AOSP 17 (`def_text_show_password` empty) | flip our default to false (affects new installs/users; existing user choices kept) | S | quick win |
| Storage Scopes (alternative to storage permissions) | `GosPackageStateFlag.STORAGE_SCOPES_ENABLED = 0`; scope model `core/java/android/app/StorageScope.java`; fake permission grants `services/core/java/com/android/server/pm/GosPackageStatePermissions.java`; MediaProvider enforcement `src/com/android/providers/media/StorageScopesHooks.java` (`callingIdentity.getStorageScopes()`); app hooks `core/java/com/android/internal/app/StorageScopesAppHooks.java`; UI in Permission module `.../permissioncontroller/sscopes/` (Activity/Fragment/Utils + `strings_sscopes.xml`) + Settings `AppStorageScopesPreference.kt` | requires the GosPackageState core first (`GosPackageState*` + `PackageManagerHooks`), then scope model + MediaProvider hooks + Permission/Settings UI | L–XL | port later (after GosPackageState) |
| Contact Scopes (alternative to the Contacts permission) | `CONTACT_SCOPES_ENABLED = 5`; API/storage `core/java/android/ext/cscopes/ContactScopesApi.java` + `ContactScopesStorage.java`, `core/java/com/android/internal/app/ContactScopes.java`; provider filtering `ContactsProvider/src/.../ScopedContactsProvider.java` + `ContactScopesUiHelper.java` (design notes `ContactScopes.md`); UI `.../permissioncontroller/cscopes/ContactScopesActivity.kt` + Settings `AppContactScopesPreference.kt` | same GosPackageState dependency + ContactsProvider fork | L | port later (after GosPackageState) |
| Battery charge limit (80 %) | `core/java/android/ext/power/BatteryChargeLimit.java` — `CHARGE_LEVEL=80`, `Settings.Global.BATTERY_CHARGE_LIMIT`, gated by **`isGoogleDevice()`** (mechanism is Pixel-specific); Settings `BatteryChargingOptimizationPrefController/Fragment` | mechanism would need Nothing charger/kernel support; UI alone does nothing | S (stub), device support = L | not feasible now |
| LTE-only mode | Settings app `EnabledNetworkModePreferenceController.java`, `PreferredNetworkModePreferenceController.java:222`, `NetworkModes.kt:28`; GrapheneOS commits `5310142ccc` (2022, "LTE Only Mode") + `8d37b32db6` (2025, "5G Only / 4G or 5G only") | **Done:** `packages_apps_Settings/0001` adds the "LTE only" entry plus "5G or LTE only"/"5G only" when the carrier/baseband exposes NR (the latter also needs NR standalone), splits the summary switch cases and adds the strings. Deliberate deviation: GrapheneOS also flips the row-availability guard from `== EnabledNetworkMode` to `!= PreferredNetworkMode`, which exposes the row when the carrier hides network settings (type `None`); lenOS keeps the stock guard. GrapheneOS's `NETWORK_MODE_LTE_GSM_WCDMA` summary fallthrough is kept verbatim | S–M | **done** |
| SUPL / PSDS network-assistance toggles | `core/java/android/ext/settings/GnssSettings.java`; `GnssConfiguration.applyConfigOverrides` (applied after carrier/debug properties); `GnssLocationProvider` observers + PSDS gate; Settings `GnssSuplPrefController`/`GnssPsdsPrefController` | **Done:** `frameworks_base/0021` + `packages_apps_Settings/0001`. Setting keys and numeric values match GrapheneOS (`force_disable_supl`, `psds_server`). GrapheneOS defaults both to its own proxies; lenOS has no proxy infrastructure, so only "Off"/"Standard server" are offered and both default to **Off**. The old `device/0003` blank-`gps.supl_host` patch was removed so "Standard server" is functional. Rows live in a "Network assistance" category on the Location screen | S–M | **done** |
| Cross-profile clipboard control | `android/ext/settings/CrossProfileClipboardAccessSettings.java`; read at `ClipboardService.java:1064/:1099` and `DragState.java:517` | class + all three gates + Settings row | S–M | **done** (`fwb/0016` + `packages_apps_Settings/0001`) |
| Alt touchscreen mode | `android/ext/settings/AltTouchscreenMode.java`; used in `PhoneWindowManager.java:5549/:5643` (display state prop) | depends on touch controller/firmware behavior on SM7635 | M | port later / verify hardware |
| Removing auto location grant to system browsers | GrapheneOS `DefaultPermissionGrantPolicy` has no browser block: the stock `PACKAGE_BROWSER` role holder / `CATEGORY_APP_BROWSER` system handler never receives `FOREGROUND_LOCATION_PERMISSIONS` (the `BrowserUtils` helper is unrelated — it backs GrapheneOS SELinux flag handling) | remove the block; browsers need an explicit user grant | S | **done** (`frameworks_base/0019`) |
| PIN scrambling (incl. SIM PIN/PUK) + other SIM/eSIM protections | GrapheneOS base-view `setupPinScrambling` (SecureRandom shuffle + digit→view remap); keyguard reads the primary ExtSettings key, SIM PIN/PUK views read the SIM key; Settings UI via `com.android.settings.ext` controllers | **Done in the fidelity redo:** `frameworks_base/0008` (SystemUI) + `packages_apps_Settings/0001` (Settings: lock-picker switch, SIM-lock switch, controller infra) + primary default flipped ON in `frameworks_base/0006` (documented lenOS deviation — GrapheneOS ships it off). Old Lineage plumbing deleted (`PinScramblePreferenceController`, device/0005, lineage_sdk/0001). Duress is *not* accepted as a SIM PIN in GrapheneOS either (same upstream — nothing to port); duress wipes eSIM profiles (§3, done) | done | — | **done** |
| Prototype/EVT/PVT device warning | AMS `services/core/java/com/android/server/am/ActivityManagerService.java:6047-6081` (`isPrototypeDevice()` + `showPrototypeNotificationIfPrototype()`: Pixel logic checks `ro.revision` for `MP` and `ro.boot.secure_boot` for `PRODUCTION`; the notification uses `SystemMessage.NOTE_PROTOTYPE_DETECTED = 400`) | **Done:** `frameworks_base/0023` — the Pixel branch is ported verbatim (brand gate, `ro.revision`, `ro.boot.secure_boot`); for other OEMs a new `isPrototypeDeviceNonPixel()` treats only an explicit `EVT`/`PVT`/`DVT` marker in `ro.boot.hwlevel`/`ro.boot.hardware.revision`/`ro.boot.device_release` as a prototype, so a retail Nothing unit whose bootloader reports nothing (or a numeric revision) never false-positives. Deliberate deviation: GrapheneOS returns early for every non-Google brand, which would make the warning dead code on Nothing | S | **done** |
| UART debugging warning; bootloader/radio/boot partition version+fingerprint checks | AMS `showConsoleNotificationIfActive()` (`init.svc.console` running) + proto `NOTE_SERIAL_CONSOLE_ENABLED`; the pre-Treble version checks lived in `Build.isBuildConsistent()` (`ro.build.expect.bootloader`/`ro.build.expect.baseband`), which AOSP reduced to the VINTF check in the Treble era and `ActivityTaskManagerService.showSystemReadyErrorDialogsIfNeeded()` still surfaces | **Nothing left to port:** LineageOS 24.0 already ships the console notification unchanged (its check is the accurate `init.svc.console`-based one, so no Pixel-cmdline heuristic is added) and the VINTF build-consistency check + mismatch dialog; the user-visible "version verification" part is the bootloader field (`§14.5`) | — | **done** (no patch needed) |
| Wireless alerts fully optional | `CellBroadcastReceiver` `res/values/config.xml:25` `show_presidential_alerts_settings=true` (LineageOS `false`) making the pref visible; `CellBroadcastChannelManager.java:283` (presidential `mAlwaysOn` commented out) so the pref actually controls delivery; `CellBroadcastAlertService.java:639` reads `KEY_ENABLE_CMAS_PRESIDENTIAL_ALERTS` | patch CellBroadcastReceiver (4 files, ~10 LOC) | S | quick win — **done** (`packages_apps_CellBroadcastReceiver/0001`, 9 files; also ports the 2024 "always allow disabling extreme alerts" commit) |
| CA removal (Chunghwa Telecom, Netlock) | `platform_system_ca-certificates` commit `14ad6bb` deletes `files/53a1b57a.0`, `files/60afe812.0`, `files/9d6523ce.0` | remove the same files; re-apply on each CA update | S | quick win — **done** (`system_ca-certificates/0001`) |
| FLAG_IMMUTABLE log+warp instead of crash | fwb `core/java/android/app/PendingIntent.java:457-467`: logs the error and `return flags \| PendingIntent.FLAG_IMMUTABLE`; LineageOS `:444-465` throws | replace throw with log+warp | S | quick win |
| More precise system clock | fwb `TimeDetectorStrategyImpl.java:90`: drift warning threshold `SYSTEM_CLOCK_PARANOIA_THRESHOLD_MILLIS = 250` (LineageOS = 2000); the features page additionally cites the 2000 ms→50 ms *update* threshold (constant not re-located in this scan beyond the paranoia value) | lower the constants | S | quick win |
| Longer passwords | `DevicePolicyManager.MAX_PASSWORD_LENGTH`: GrapheneOS 128, LineageOS 24.0 = **64** (`DevicePolicyManager.java:3948`) | 1-line constant + audit `PasswordMetrics`/UI assumptions | S | quick win |
| More secure fingerprint unlock (5 attempts) | fwb `services/core/java/com/android/server/biometrics/sensors/fingerprint/hidl/LockoutFrameworkImpl.java`: `MAX_FAILED_ATTEMPTS_LOCKOUT_PERMANENT = 5` (LineageOS = 20 with 30 s timeouts) | 1-line constant | S | **not applicable to `asteroids`**: the device uses an AIDL fingerprint HAL, and the framework only attaches `LockoutFrameworkImpl` to HIDL sensors. The threshold is owned by the vendor HAL |
| Package installer preserves disabled state | GrapheneOS forks `platform_packages_apps_PackageInstaller` and sets `SessionParams#setApplicationEnabledSettingPersistent()` on updates; the API exists in LineageOS 24.0 (`frameworks/base/.../PackageInstaller.java:3951`, honored by the session/installer) | patch the AOSP PackageInstaller app | S | quick win |
| Compressed APEX disabled | build/product config | **Done:** `vendor/lenos/config/lenos.mk` sets `PRODUCT_COMPRESSED_APEX := false`; the lenOS product fragment is inherited after `generic_system.mk` → `updatable_apex.mk`, and LineageOS 24.0's `core/product_config.mk` defaults the flag to true, so the override wins. `core/soong_config.mk` then exports `CompressedApex=false` and the build ships `apexd.config.compressed_apex=false`. No upstream file is patched | S | done |
| "Always-on VPN"/"Block connections without VPN" default | Already the AOSP 17 behavior (toggles available for all VPN apps); GrapheneOS delta is only "don't unset unsupported always-on" — see §12 | 1 hunk | S | port now (with §12) |

### 14.3 User/profile items

| Item | GrapheneOS implementation | lenOS port | Size | Verdict |
|---|---|---|---|---|
| More profiles (32 = 31+guest) | fwb `core/res/res/values/config.xml:3288` (32); LineageOS raw = 1 + Lineage vendor overlay = 4 | device/vendor RRO override `config_multiuserMaximumUsers` | S | quick win |
| End session (logout) without a device manager | AOSP 17 already has `logoutUser`; GrapheneOS enables the UI path and disables the lockscreen logout button (`KeyguardIndicationController` `if (false && …)`); `UserLogoutInteractor.kt` carries `isPolicyManagerLogoutEnabled` on A17 | **Done:** `fwb/0028` ports the lock-screen disable verbatim (`if (false && mUserLogoutInteractor.isPolicyManagerLogoutEnabled().getValue())` plus a lenOS comment), so the end session button never appears on the lock screen where it would need no credentials. The power-menu End session action stays stock, gated by the same `UserLogoutInteractor` | S–M | done |
| Disabling app installation for secondary users | Settings users screens (standard device-management restriction exposed to the owner) | **Done:** `packages_apps_Settings/0003` ports GrapheneOS's per-user "App installs and updates" screen (`UserAppsInstallSettings`: enabled / first-party sources only / disabled) with the trimmed `UserRestrictions` helper, and wires it into user details (`app_installs` row, live summary, launch). The standard `DISALLOW_INSTALL_APPS` / `DISALLOW_INSTALL_UNKNOWN_SOURCES` restrictions are already enforced by A17's framework, so no framework patch. Deltas documented in §18: strings in a new `res/values/strings_lenos_users.xml` instead of extending the lenOS ext-strings file, and the helper's private-space inheritance (separate GrapheneOS feature) omitted | M | done |
| Install available apps | `UserSystemPackageInstaller.java` (fwb) + config **not enabled in AOSP/Pixel** per GrapheneOS; enable + UI | fwb config + Settings UI | M | port later |
| Notification forwarding (cross-profile) | Not located in this fwb scan (verify their Settings/notification service changes) | verify | M–L (est.) | port later (verify) |
| User-installed apps can be disabled | GrapheneOS `AppDisableButton.kt` (Settings SPA app info): the button is offered for every installed app (`!app.installed` gate instead of `!isSystemApp`); `canBeDisabled()` gains a `!isSystemApp -> isAllowUninstallOrArchive(...)` branch, so the uninstall/archive rules (incl. `DISALLOW_APPS_CONTROL`) still apply; clicking Disable on a user app disables it directly while the data-loss confirmation dialog stays for system apps (where disable means downgrade). No framework change: `PackageManagerService.setEnabledSettings` already accepts `DISABLED_USER` for any package and Settings holds `CHANGE_COMPONENT_ENABLED_STATE` | **Done:** `packages_apps_Settings/0002` — line-level port; the framework invariant is pinned by `tests/test_disable_user_apps.py`. The legacy `AppButtonsPreferenceController` screen is unmodified (GrapheneOS leaves it unmodified too; SPA is the default app-info screen) | S | **done** |
| Encrypted backups (Seedvault) | LineageOS 24.0 ships Seedvault (`packages/apps/Seedvault`, via `snippets/lineage.xml`); GrapheneOS's `external/seedvault` fork is *newer upstream* (their tag `2026101600` vs Lineage's `16-5.9`) plus GrapheneOS-specific commits (app-id prefix, and a **prebuilt** `libs/seedvault-chunker-0.1.jar` built from `GrapheneOS/seedvault-chunker`) | **Experimental implementation:** `packages_apps_Seedvault/0001` ports the internal `app.grapheneos` prefix and the GrapheneOS prebuilt chunker while keeping `com.stevesoltys.seedvault` and the legacy `BASE_SPLIT`. Existing old-prefix backups may not restore; migration is unverified. The full GrapheneOS Seedvault rebase is still out of scope | M–L | experimental |
| Log viewer + user-facing crash reporting | fwb `services/core/java/com/android/server/ext/` bundle (17 files, 2722 lines total: `TombstoneHandler.java` 468, `DropBoxMonitor.java` 339, `SystemJournalNotif.java` 103, `SystemErrorNotification.java` 43, `BgDexoptUi.java` 171, `IntentReceiver.java` 103, `PackageManagerHooks.java` 226, `SeInfoOverride.java` 84, `AppCompatConf.java` 195, `AppSwitchNotification.java` 227, …) + Settings log-viewer UI | **Experimental local viewer:** `packages_apps_Settings/0001` reads the existing DropBox crash/ANR/watchdog tags, bounds the list and shares only on an explicit action. No upload, no background reporter, no network permission. GrapheneOS's full reporting service is not ported | M–L | experimental (local only) |

### 14.4 Anti-persistence, App-source and app-level items

| Item | GrapheneOS implementation | lenOS port | Size | Verdict |
|---|---|---|---|---|
| fs-verity enforcement for out-of-band APK updates (`PackageVerityExt`) | install-time + boot-time verified metadata, downgrade prevention, parsing-cache disabled | **Experimental:** `frameworks_base/0001` ports the boot/install checks and signing-capability policy; debug-only escape properties retained. Needs a system-app update test | L | experimental |
| System-app versionCode downgrade loophole | PM install + boot checks | **Experimental:** same `frameworks_base/0001`, including the boot-time rejection of same/older `/data` updates | M–L | experimental |
| Package updates preserve the disabled state | GrapheneOS `bff727d`: removes the three implicit `ps.setEnabled(COMPONENT_ENABLED_STATE_DEFAULT, …)` paths from `InstallPackageHelper.updateSettingsInternalLI`, drops `InstallRequest.isApplicationEnabledSettingPersistent()`, and advertises `grapheneos.package_update_preserves_package_enabled_setting` in `SystemConfig` | **Done:** `frameworks_base/0022`. Exact port of the commit; the `setApplicationEnabledSettingPersistent` session API/flag and `PackageInstallerSession` accessor remain (API/metrics), but updates no longer consult them. An app disabled by the user (or a disabled system app) survives every update | S | **done** |
| MediaProvider directory listing | GrapheneOS `72492da1c` (Storage Scopes): `MediaProvider.getFilesInDirectoryForFuse` returns DB-visible files plus a empty-string separator and the subdirectories that contain visible files; JNI `MediaProviderWrapper.cpp` then skips appending lower-FS directory names. Apps with `READ_MEDIA_AUDIO/IMAGES/VIDEO` and the `Android/` directory keep upstream behavior | **Done (directory-listing part):** `packages_providers_MediaProvider/0001`. A caller with no storage permission now only sees directories containing files it can see, instead of every user-created directory. Storage Scopes themselves (`GosPackageState`, `StorageScope`, scopes UI) are not ported; `StorageScopesHooks` keeps GrapheneOS's name/shape so the rest can be added later | M | **done** (scopes later) |
| Kernel LTS + hardening | their kernel forks + patches | **Started (Tier 3 #32):** `kernel_nothing_sm7635/0001` adds `arch/arm64/configs/vendor/lenos_hardening.config` (zero-on-free, randomized kmalloc caches, kernel-stack offset randomization, dmesg restriction, register zeroing) and `device_nothing_asteroids/0008` merges it last. `INIT_STACK_ALL_ZERO` is already the upstream 6.6 default; `INIT_ON_ALLOC_DEFAULT_ON`, SLUB hardening, CFI/SCS and `LIST_HARDENED` are already on. Not yet: 48-bit VA / 4-level page tables, module signing/lockdown, LTS cadence, custom allocator canaries/MTE. See §19 | M (shipped subset) / XL+ (remaining) | **started** |
| Compressed-APEX / firmware-security reporting items | see 14.2 | verify | S–M | verify |
| Broad carrier support (CarrierConfig2) | their carrier-config conversion scripts + stripped anti-user configs (tethering provisioning, 2G forbidding, OMA-DM) | run their generator on the carrier DBs we can obtain; ship the generated configs; strip anti-user bits | M–L | port later |
| Sandboxed Google Play / Android Auto | GmsCompatConfig + compatibility layer (their own repos; apps sandboxed, no special privileges) | a project of its own; no AOSP-path port | XL | app-level bundle (later) |
| GrapheneOS app repository client | their client + server | alternatives exist (Obtainium/F-Droid); not source-portable | M | app-level bundle |
| Auditor | app + attestation service (attestation.app) | installable APK on any OS; strong value only with their service; not source-portable | S (bundle) | app-level bundle |
| Camera / PDF viewer / Setup Wizard | standalone apps | Camera & PDF viewer are standalone APKs (usable as a bundle); Setup Wizard is tied to their framework UX. **Setup Wizard specifically:** LineageOS 24.0 ships `packages/apps/SetupWizard` (a Kotlin LineageOS wizard under `app/src/main/java/org/lineageos/setupwizard`), and GrapheneOS's fork of it contains **no** bootloader/OEM-unlock warning (no `bootloader`/`oem` references in `GrapheneOS/platform_packages_apps_SetupWizard`). **Experimental lenOS implementation:** `packages_apps_SetupWizard/0001` adds a non-blocking welcome-page warning keyed on `ro.boot.verifiedbootstate`, with wording that does not encourage re-locking an unsigned build | S (bundle) / XL (wizard) | experimental |
| Authenticated NTP + disabling network time | their NTP server with A-E; toggle | lenOS sets NTP server default via 0002; authenticated NTP needs a server (not portable); AOSP supports disabling time sync natively | S | done/not portable |

### 14.5 Other-features sweep (misc ToC items)

| Item | GrapheneOS implementation | lenOS port | Size | Verdict |
|---|---|---|---|---|
| Wi-Fi privacy parity | per-connection MAC randomization (new networks default to `RANDOMIZATION_ALWAYS`), per-network DHCP hostname off by default (`SendDhcpHostname2` tag rename ignores stock-written values), no DHCP lease reuse across connections under per-connection randomization (GrapheneOS `62d70edb46`); EUI64 link-local generation when the MAC is randomized (AOSP `ClientModeImpl`), RFC 7217 stable-privacy addresses for non-randomized networks (netd `InterfaceController`), IPv6 privacy-address kernel support | **Done:** `wifi/0001-privacy-mac-and-dhcp-defaults` ports GrapheneOS's exact 4-file Wi-Fi change set, and `packages_modules_NetworkStack/0001` closes the last gap — GrapheneOS's "avoid reusing DHCP state for full MAC randomization" patch was the one piece LineageOS 24.0 lacked: AOSP renews the `IpMemoryStore` lease for the same L2 network even after the MAC changed, letting the DHCP server correlate connections (GOS still ships the fix on branch 17). The remaining "verify" items are upstream, not GrapheneOS deltas, checked in-tree: the EUI64 path is present in `packages/modules/Wifi/.../ClientModeImpl.java:8417` ("Use EUI64 address generation for link-local IPv6 addresses"), netd keeps the RFC 7217 `stable_secret` handling (`system/netd/server/InterfaceController.cpp:73,203-213,287`), the SockDiag IPv4/6 leak fix (`40c47da2`) is in LineageOS 24.0 (§12), and the stable-privacy kernel commits are upstream mainline (2015, carried by any 6.6 LTS tree). Kernel-adjacent work stays in the kernel workstream (§17) | — | **done** |
| Closed device identifier leaks | restriction tightening for legacy-target apps + exec spawning removes mitigation secrets as identifiers | exec spawning = §17 runtime cluster; legacy-target restrictions not pinned in this scan | M (verify) | port later (verify) |
| Improved sandboxing | SELinux + seccomp-bpf policy hardening, app and WebView renderer sandbox paths | program-level (see §17); no itemized patch surfaced | XL | infeasible now |
| More complete patching | fast kernel LTS point releases + missed-patch backports | operational: kernel workstream (§17) + release cadence, not a patch | n/a | process (not a patch) |
| Seamless automatic updates + rollback | their update client/server; rollback via A/B when first boot fails | LineageOS updater covers the basics; server-side parity is infra, not code | S (policy) | not a code port |
| Hardened build/signing infrastructure | release-engineering practice | adopt independently of the codebase | n/a | out of scope (process) |
| Minimal bundled apps | only essential apps integrated; no bundling partnerships | mechanism already exists (`LENOS_STRIP_PACKAGES`, vendor_lineage/0001); extend the strip list as policy | S | port now (policy step) |
| Keyboard suggestions off by default | "personalized keyboard suggestions based on gathering input history are disabled by default" (privacy-by-default) | seat not pinned (IME/dictionary setting); AOSP exposes the opt-out — flip the default | S (verify) | port later (verify) |
| Dialer call recording | GrapheneOS Dialer: recordings under `Recordings/Call recordings`, no region restrictions or tone | **Already the LineageOS baseline — no port needed.** LineageOS's Dialer records unconditionally (`call_recording_enabled=true`, no carrier/region gate), uses the `VOICE_CALL` source, writes through MediaStore to `Recordings/Call recordings`, plays no tone, and the privileged Dialer holds `CAPTURE_AUDIO_OUTPUT`. Pinned by `tests/test_call_recording.py`. GrapheneOS's additional auto-recording-by-contact subsystem (preferences store, contact modes, stale-contact cleanup jobs) is a larger Dialer fork and is not part of 1.0 | S | **done (baseline)** |
| Firmware security visibility | version/configuration verification reporting inconsistencies + debug features enabled (companion to the bootloader/radio/boot-partition checks row in 14.2) | **Done:** `frameworks_base/0023` (prototype warning, with the EVT/PVT/DVT phase-marker path for non-Pixel devices) + `packages_apps_Settings/0001` (bootloader version field, `BootloaderVersionPreferenceController` reading `ro.bootloader`); the "inconsistencies" reporting is AOSP's VINTF check + mismatch dialog, already shipped in LineageOS | S | **done** |
| Memory hygiene on lock | full compacting GC for SystemUI and system_server when the keyguard starts showing: `KeyguardViewMediator.handleShowInner` (SystemUI, before `mShowKeyguardWakeLock.release()`; line 3297) and `KeyguardServiceDelegate.onShowingStateChanged` (system_server, `if (showing) { System.gc(); System.runFinalization(); System.gc(); }`; line 237) | **Done:** `frameworks_base/0024`. SystemUI hunk is a line-level port. A17 has `IKeyguardStateCallback`, but the port keeps the same three calls on the existing `setLockScreenShown` binder thread, transition-gated (`mKeyguardShown != keyguardShowing` → true) and after the global lock is released — same process, same moment, no WMS lock held | S | **done** |

**Coverage note:** every features-page ToC item is covered somewhere in this document — mapping:
§5 (network), §6 (sensors), §7 (2FA), §8 (secure paste), §9 (delayed allow), §10 (USB-C),
§11 (FBE padding), §12 (VPN), §13 (Vanadium), §2 (auto reboot, done), §3 (duress, done),
§4 (QS gating, done), §15–§18 (rankings + audit), and the tables above for everything else.

---

## 15. Ranked: the next 15 ports (shipped items excluded)

Excluded as already done: ExtSettings infrastructure (`fwb/0006`), auto-reboot (`system_core/0001` +
`fwb/0003`), QS unlock gating (`fwb/0004`), duress backend + eSIM wipe (`fwb/0005`+`0007`,
`frameworks_opt_telephony/0001`). Sizes assume one experienced developer with the device to test on.

| # | Item | Size | Repos touched | One-line value |
|---|---|---|---|---|
| 1 | Network permission | M–L | fwb, Connectivity, Permission, PackageInstaller | user-revocable INTERNET with "network is down" semantics; AOSP 17 already ships the eBPF machinery, so this is mostly policy + UI — **done** (`frameworks_base/0025`, `packages_modules_Connectivity/0002`, `packages_modules_Permission/0002`; no installer change needed — GrapheneOS has none) |
| 2 | Sensors permission | L | fwn, fwb, Permission (+Settings) | zeroed-out accelerometer/gyro/compass/etc. for apps — the largest remaining privacy hole after network — **done** (`frameworks_base/0025`+`0026`, `frameworks_native/0001`, `packages_modules_Permission/0002`) |
| 3 | VPN leak-blocking set | M | netd, Connectivity, fwb | 4 surgical netd fixes (DNS/RA/multicast/SockDiag) + NSD-under-lockdown — hardens the always-on VPN feature we already ship — **done** (`system_netd/0001`, `packages_modules_Connectivity/0001`, `frameworks_base/0017`+`0018`; SockDiag/DnsResolver already upstream) |
| 4 | Secure Paste, stage 1 (global default) | M | fwb (+Permission/Settings UI) | cross-app clipboard reads off by default; staging avoids the GosPackageState backport (per-app later via AppOps) — **done** (`frameworks_base/0015` + Settings row; per-app/toolbar stage 2 pending) |
| 5 | FBE filename padding 32 B | S | system/extras | one-line policy change in libfscrypt; metadata-length privacy (new installs / post-wipe) |
| 6 | Wi-Fi/Bluetooth auto-off timers | S–M | fwb (+Settings; NFC variant in the Nfc app) | radios power down after idle; constants already seeded in `fwb/0006` — **done** (`frameworks_base/0020` + Settings row; NFC variant pending) |
| 7 | Fingerprint lockout after 5 attempts | S | vendor fingerprint HAL | **not applicable via frameworks/base**: `asteroids` uses an AIDL fingerprint HAL, so lockout is HAL-side; the HIDL `LockoutFrameworkImpl` is unused. Verify the vendor HAL before relying on any threshold |
| 8 | MAX_PASSWORD_LENGTH 128 | S | fwb | one-line; supports duress/passphrase users who hit the 64 limit |
| 9 | Package installer preserves disabled state | S | packages/apps/PackageInstaller | disabled apps stay disabled after updates; AOSP API already present in 24.0 |
| 10 | Delayed "Allow" (permission + ADB) | S | Permission, SystemUI | 1-second anti-tapjacking gate, absent from LineageOS 24.0 — **done** (`packages_modules_Permission/0001` + `frameworks_base/0014`) |
| 11 | Wireless alerts fully optional | S | CellBroadcastReceiver | presidential alerts become opt-out (config + channel-manager + alert-service respect the pref) — **done** (`packages_apps_CellBroadcastReceiver/0001`) |
| 12 | FLAG_IMMUTABLE log+warp | S | fwb | mutable PendingIntent logs instead of crashing third-party apps (GrapheneOS behavior) |
| 13 | Screenshot EXIF defaults | S | fwb (SystemUI) | drops timestamp/timezone tags and the Software tag; constant seeded — **done** (`fwb/0013`; Settings toggle in `packages_apps_Settings/0001`) |
| 14 | Clock paranoia threshold 250 ms | S | fwb | GrapheneOS 250 ms vs LineageOS 2000 ms drift warning; cheap precision/privacy parity |
| 15 | More profiles (32) | S | vendor/device overlays | multiuser max 4 → 32; no framework work (fscrypt/quota paths already support it) |

**Runners-up (all small):** removal of Chunghwa Telecom + Netlock CAs (S), prototype-device warning (S),
SIM-PIN scrambling (S–M — **done**), cross-profile clipboard setting (S–M — **done**),
sensitive-notification default (S), "remove auto location
grant to system browsers" (**done**, `frameworks_base/0019`), LTE-only mode UI and GNSS/SUPL/PSDS
toggles (**done**, `packages_apps_Settings/0001` + `frameworks_base/0021`).

**Sequencing suggestion.** Land the §16 quick-win batch first (zero design risk). Then the VPN set
(§12) and Secure Paste stage 1 (§8). Network (§5) and sensors (§6) each deserve their own release and
test pass — **network is done**; sensors is next and reuses the SRT infrastructure `fwb/0025` introduced.
The FBE padding change (§11, **done**: `system_extras/0001`) only affects new encryption
policies, so ship it whenever — but
pair it with a note that existing devices keep 16-byte padding until factory reset.

---

## 16. Quick wins (< ~50 LOC each)

All are GrapheneOS ports unless marked otherwise; each is independently shippable.

| Change | Where | Effort | Reference |
|---|---|---|---|
| Fingerprint permanent lockout 20 → 5 | fwb `biometrics/.../fingerprint/hidl/LockoutFrameworkImpl.java` | 1 line | **Dropped for `asteroids`:** the AIDL fingerprint HAL owns lockout; this HIDL-only tracker is never attached. The ineffective hunk was removed from `fwb/0009` |
| Max password length 64 → 128 | fwb `DevicePolicyManager.MAX_PASSWORD_LENGTH` | 1 line | GOS 128; LOS `DevicePolicyManager.java:3812` = 64 — **done** (`fwb/0009`) |
| Clock drift warning 2000 → 250 ms | fwb `timedetector/TimeDetectorStrategyImpl.java` | 1 line | GOS `:90` = 250; LOS `:89` = 2*1000 — **done** (`fwb/0010`). The features page also advertises a 50 ms system-clock *update* threshold — not pinned to a constant in this scan (search the timedetector/alarm paths when implementing) |
| FBE padding 16 → 32 | `system/extras` `libfscrypt/fscrypt.cpp` | 1–2 lines | GOS branch 17 `:247-248` (`FSCRYPT_POLICY_FLAGS_PAD_32`) — **done** (`system_extras/0001`) |
| Delayed "Allow" buttons | Permission `GrantPermissionsViewHandlerImpl.kt` + SystemUI `usb/UsbDebuggingActivity.java` | 2 hunks (~6 LOC) | GOS `:411` and `:108-110`; LOS has neither — **done** (`packages_modules_Permission/0001` + `frameworks_base/0014`; the permission-handler debug log omits the app package — not a field in this branch) |
| Wireless alerts optional | CellBroadcastReceiver `res/values/config.xml` + `CellBroadcastChannelManager.java` (+ verify `CellBroadcastAlertService` read) | ~5 lines | GOS config `:25` true vs LOS false; GOS channel manager `:283` has the presidential `mAlwaysOn` commented out — **done** (`packages_apps_CellBroadcastReceiver/0001`; also the CDMA category path, the settings-fragment wiring, and the "always allow disabling extreme alerts" mcc-724 commit) |
| Remove Chunghwa Telecom + Netlock CAs | `system/ca-certificates` `files/` | delete 3 files | GOS commit `14ad6bb` deletes `files/53a1b57a.0`, `files/60afe812.0`, `files/9d6523ce.0` — **done** (`system_ca-certificates/0001`) |
| Package installer preserves disabled | `packages/apps/PackageInstaller` | ~5 lines | `SessionParams#setApplicationEnabledSettingPersistent()` exists in LOS 24.0 (`frameworks/base/.../PackageInstaller.java:3951`) |
| Screenshot EXIF cleanup | fwb SystemUI `ImageExporter.java` | ~5 lines + Settings row | GOS gates timestamp on `ExtSettings.SCREENSHOT_TIMESTAMP_EXIF` (`:513`); LOS writes `TAG_SOFTWARE = "Android " + Build.DISPLAY` (`los_ImageExporter.java:520`) — **done** (`fwb/0013`; Settings row in `packages_apps_Settings/0001`) |
| Sensitive notification content hidden by default | fwb `packages/SettingsProvider/res/values/defaults.xml` | 1 line | GOS `def_lock_screen_allow_private_notifications` = false (`:170`) vs LOS 24.0 true; seeded at `DatabaseHelper.java:1642-1643` / `:2245-2246` (new installs/users only) — **done** (`fwb/0012`) |
| More profiles 32 | vendor/device RRO `config_multiuserMaximumUsers` | 1 value | GOS `core/res/res/values/config.xml:3288`; LOS raw 1 + Lineage overlay 4 — **done** (`device/0007`) |
| FLAG_IMMUTABLE log+warp | fwb `core/java/android/app/PendingIntent.java` | ~10 lines | GOS `:457-467` logs + returns `flags \| FLAG_IMMUTABLE`; LOS `:444-465` throws — **done** (`fwb/0011`) |
| Prototype/EVT device warning | fwb AMS + strings (optional; gate on `ro.product.brand` to avoid it firing on every unlockable Nothing device) | ~30 lines | GOS `ActivityManagerService.java:6047-6081` |

---

## 17. Not feasible without kernel, firmware or infrastructure work

| Item | Why it is out of reach now | What we can do instead |
|---|---|---|
| Exploit-mitigation program: `hardened_malloc`, exec spawning, MTE-for-apps defaults, BTI/PAC userspace hardening, JIT-disabled base OS, base-OS dynamic-code-loading block | These are bionic/ART/kernel/toolchain projects, not patch ports; the ExtSettings/ASW toggles registered in `fwb/0006` are config only and stay inert by design. One narrow exception is **experimental HTS-1**: `bionic/0001` ports GrapheneOS's pthread guard-gap/layout change behind an experimental-series runtime property, but it is not a replacement for any of these and is not built or booted | Keep the toggles hidden; HTS-1 requires a full boot, thread-stress and app-compatibility pass before promotion. Revisit the rest only if lenOS adopts a runtime-hardening workstream |
| Kernel LTS + hardening (remaining pieces) | We build `kernel/nothing/sm7635` from LineageOS source, so kernel patches are *possible*, but GrapheneOS-grade kernel hardening targets their supported Pixels and is a project of its own against the vendor baseline | **Started (Tier 3 #32, §19):** the portability-safe config fragment is in (`kernel_nothing_sm7635/0001` + `device_nothing_asteroids/0008`). Still out of reach without a dedicated kernel/firmware effort: 48-bit VA / 4-level page tables, forced module signing + lockdown (vendor modules cannot be re-signed), LTS point-release cadence, GrapheneOS's custom allocator canaries and MTE-for-apps. Boot/performance validation is pending |
| USB-C port control (full semantics) | Hardware data-line disable, alternate-mode (DisplayPort) block and boot-time `persist.security.usb_mode` enforcement live in the vendor USB HAL/kernel/firmware; Nothing controls them | OS-side prototype only if the SM7635 HAL implements AOSP `IUsb.enableUsbData` (verify with VINTF/`dumpsys usb`); see §10 |
| Battery charge limit (80 %) | GrapheneOS's mechanism is gated to Google devices (`BatteryChargeLimit.isGoogleDevice()`) and depends on Pixel charger/kernel support | Nothing's stock firmware has a vendor battery-protection feature, but it is not exposed via an AOSP path we can call; skip unless the kernel exposes a charge-stop node |
| Sandboxed Google Play + Android Auto + GmsCompatConfig | GrapheneOS's compatibility layer (their own repositories and app) — a separate large project; Android Auto support is tied to the sandboxed Play integration | Not applicable to lenOS's current app stack; revisit only if a Play-compat layer is ever adopted |
| Network location service | GrapheneOS runs a network-location proxy on their infrastructure; the OS hooks are portable but the backend is not | Keep GNSS-only location; optionally port the settings toggles (see §14.2) |
| Authenticated NTP | Requires GrapheneOS's NTP service; authentication is server-side | Point the NTP default at a trustworthy server (already a config knob in `fwb/0002`) |
| Auditor / verified attestation workflow | The app can be installed on any device, but the workflow needs their attestation service | Recommend the APK in documentation if desired |
| Verified boot / firmware trust improvements | Locked to Nothing's bootloader, AVB keys and firmware update chain | Document the bootloader-locking trade-offs |
| Vanadium as a source port | Whole-Chromium build + release pipeline (see §13) | App-level bundle decision (Cromite or similar), not a patch |
| UART-debugging warning fix; bootloader/radio/boot-partition version+fingerprint checks | Not located in the branch-17 scan in this pass | Verify before classifying — they may turn out to be small device/settings patches |

---

## 18. Deviations audit: the 53 lenOS patches vs GrapheneOS

Method: all rows read directly from `vendor/lenos/patches/` during this audit; GrapheneOS references are
from the branch-17 clones (`fwb-full`, `system_core`, `sepolicy`, `Settings`, `Permission`,
`PackageInstaller`, …) plus raw
`GrapheneOS/*` fetches. Note: this series now has **53** patches (the fidelity redos; the quick-win
batch `fwb/0009`–`0013` + `device/0007`; `system_ca-certificates/0001`, `system_extras/0001`,
`packages_apps_CellBroadcastReceiver/0001`; the delayed-Allow pair; the clipboard pair `fwb/0015` +
`fwb/0016` + Settings UI; the VPN leak-blocking set `system_netd/0001` +
`packages_modules_Connectivity/0001` + `fwb/0017`/`0018`; the browser-location removal `fwb/0019`; the
radio auto-off set `fwb/0020` + Settings rows; the LTE-only + GNSS batch `fwb/0021` + Settings rows,
which also deleted the superseded `device/0003` so SUPL is controlled by the new framework toggle;
the package-update + MediaProvider batch `fwb/0022` + `packages_providers_MediaProvider/0001`; the
firmware-visibility batch `fwb/0023` + the Settings bootloader field; the memory-hygiene port
`fwb/0024`; the user-app disable support `packages_apps_Settings/0002`; and the network-permission
set `fwb/0025` + `packages_modules_Connectivity/0002` + `packages_modules_Permission/0002`;
and the sensors-permission set `fwb/0026` + `frameworks_native/0001`, whose registry/declaration half
lives in `fwb/0025`; and the location-indicator port `fwb/0027`; and `packages_modules_NetworkStack/0001`,
GrapheneOS's DHCP lease-reuse fix for per-connection MAC randomization; and `fwb/0028`, the
lock-screen end session disable; and `packages_apps_Settings/0003`, the per-user app
installation policy; and the kernel-hardening pair `kernel_nothing_sm7635/0001` +
`device_nothing_asteroids/0008`, a config-only workstream rather than a code port). Verdicts:
**Faithful** (line-level port; deltas only environmental), **Deliberate** (lenOS choice — keep),
**Original** (no GrapheneOS equivalent), **Plumbing** (build/device mechanics).

| Patch(es) | GrapheneOS equivalent | Deviation found | Verdict |
|---|---|---|---|
| `fwb/0001` SSAID rotate-on-reinstall | None (branch-17 SettingsProvider has no install-generation logic; AOSP relies on the SSAID row being dropped on uninstall, which a fast reinstall with uid reuse can miss) | Mixes `PackageInfo.firstInstallTime` into the SSAID HMAC as an install generation; toggle `lenos_ssaid_rotation_enabled` (default 1). Upgrades stay stable because `firstInstallTime` only moves on reinstall | **Original** — keep; document the app-compat effect (new SSAID after reinstall) |
| `fwb/0002` first-boot defaults | GrapheneOS spreads hardened defaults across `config_ext.xml`, module configs and provider seeds | Centralized `def_lenos_*` resources loaded in `DatabaseHelper#loadGlobalSettings`; keys: Private DNS mode/specifier, NTP server, captive-portal mode. The Wi-Fi MAC force-flag seed was removed in the Wi-Fi redo — Wi-Fi privacy defaults are now a GrapheneOS-faithful per-network default in `packages_modules_Wifi/0001`. The stock values in the patch preserve AOSP behaviour; the product overlay supplies hardened values | **Deliberate** — keep; the overlay is the place to review strictness |
| `fwb/0003` + `system_core/0001` auto-reboot | GrapheneOS init-based design (`trigger_shutdown`, dedicated `auto_reboot_ctl_prop`, `KeyguardServiceDelegate` hook) | (a) callback calls `HandlePowerctlMessage("reboot")` vs GOS `trigger_shutdown("reboot")` — both init-internal reboot paths, equivalent; (b) SELinux: GrapheneOS's dedicated `auto_reboot_ctl_prop` type is ported in `system_sepolicy/0001` (`property_contexts`, `property.te`, `system_server.te`), so system_server has an explicit `set_prop` grant and the generic `sys.` → `system_prop` fallback is no longer relied on; (c) hooked in A17's `KeyguardServiceDelegate.onShowingStateChanged`, the same call site GOS uses; (d) no call-in-progress deferral — same as GOS | **Faithful** |
| `fwb/0004` QS unlock gating | GrapheneOS design (`QSTileImpl` gate + 11-tile allow-list + QSHost accessor) | None found | **Faithful** |
| `fwb/0005` duress credentials | GrapheneOS duress | Same class set, same `LockSettingsStorage` key (`duress_credentials`), same verify-result hook, same owner-credential enrolment rules | **Faithful** |
| `fwb/0006` ExtSettings | GrapheneOS `android.ext.settings` registry | Trimmed to the subset used; several constants are seeded but inert (NFC_AUTO_OFF, RESTRICT_*_DYN_CODE_LOADING, FORCE_APP_MEMTAG, ALLOW_DISABLING_HARDENING_VIA_APP_COMPAT_CONFIG). PIN scramble is *not* inert anymore (fwb/0008 + Settings/0001), `ALLOW_CLIPBOARD_READ_BY_DEFAULT` is now enforced by `fwb/0015`, `AUTO_GRANT_OTHER_SENSORS_PERMISSION` by `fwb/0025` (the special-runtime-permission install pass), and `WIFI_AUTO_OFF`/`BLUETOOTH_AUTO_OFF` are enforced by `fwb/0020`; the regenerated patch also adds the GrapheneOS `Settings.Secure.CROSS_PROFILE_CLIPBOARD_ACCESS` constant used by `fwb/0016`. One deliberate default change: `SCRAMBLE_LOCKSCREEN_PIN_LAYOUT_PRIMARY` defaults to `true` (GrapheneOS ships `false`; lenOS hardening choice, commented in the patch; SIM layout inherits it) | **Deliberate** — keep trim + documented scramble default; do not surface UI for the other inert constants before enforcement lands |
| `fwb/0007` + `frameworks_opt_telephony/0001` eSIM duress wipe | GrapheneOS eSIM duress (same flag constant, SYSTEM_UID gate, carrier-notification suppression) | None found; the AIDL change is internal and the public `resetMemory` keeps its signature (hidden overload) | **Faithful** |
| `device/0001` lenOS product | n/a | Adds `lenos_asteroids.mk`; keeps the `LENOS_STRIP_PACKAGES` hook (empty on 24.0 because Gallery2 is no longer shipped) and disables AudioFX | **Plumbing** |
| `device/0002` Wi-Fi privacy hardening | No exact GrapheneOS counterpart | Enterprise Wi-Fi without certificate validation disallowed (stock Nothing overlay sets the AOSP "STRONGLY RECOMMENDED false" value to true); default tether SSID "Nothing Phone (3a)" → "AndroidAP" | **Deliberate** — strict improvements; keep |
| `device/0004` default network without 2G | GrapheneOS exposes an LTE-only setting and strips carrier configs that forbid disabling 2G, but does not change the device default | `ro.telephony.default_network` 26 → 28 (26 = `NETWORK_MODE_NR_LTE_GSM_WCDMA`, includes 2G; 28 = `NETWORK_MODE_NR_LTE_WCDMA`, no 2G — verified against branch-17 `RILConstants.java:226/232/238`) | **Deliberate/stricter** — user-changeable in Settings; keep |
| `device/0005` + `lineage_sdk/0001` PIN scramble default | n/a — superseded by the GrapheneOS port | **Both patches deleted** in the fidelity redo: the Lineage scramble implementation they configured was replaced by GrapheneOS's (`frameworks_base/0008` + `packages_apps_Settings/0001`); the lenOS default-ON now rides `ExtSettings` (`fwb/0006`, commented deviation) | **Removed** — no longer part of the series |
| `device/0006` device name | None | Default `def_device_name` / `def_device_name_simple` → "Android" (Bluetooth / Wi-Fi Direct / hotspot display name) | **Original** — keep |
| `wifi/0001` Wi-Fi privacy defaults | GrapheneOS's `packages/modules/Wifi` change set: `RANDOMIZATION_ALWAYS = 100` as the default for new networks, `shouldUseNonPersistentRandomization` early-true for it, DHCP hostname off by default (`mIsSendDhcpHostnameEnabled` uninitialized), `SendDhcpHostname` → `SendDhcpHostname2` XML rename so stock-written values are ignored after upgrade, no secure-only backfill (their `XmlUtil.java` carries the "disabled by default for all Wi-Fi networks on GrapheneOS" comment) — an earlier inventory note claiming GrapheneOS leaves this stock was wrong | Ported exactly (4 files: `WifiConfiguration`, `WifiConfigManager`, `WifiConfigurationUtil`, `XmlUtil`). The earlier lenOS approximation — a global force-flag clamp (`Settings.Global.non_persistent_mac_randomization_force_enabled` seeding, persistence API, RRO bool) — was **deleted**: it silently overrode explicit per-network user choices | **Faithful (redo)** — keep |
| `fwb/0009` credential hardening | GrapheneOS `DevicePolicyManager.java:3950` (`MAX_PASSWORD_LENGTH = 128`) | Password length ported verbatim. The `LockoutFrameworkImpl` hunk was **removed**: the device uses an AIDL fingerprint HAL, so the HIDL-only tracker is unused and the change was a no-op | **Partial (password length only)** — keep |
| `fwb/0010` clock-drift warning | GrapheneOS `TimeDetectorStrategyImpl.java:90` (`SYSTEM_CLOCK_PARANOIA_THRESHOLD_MILLIS = 250`) | Value ported verbatim (AOSP `2 * 1000`) | **Faithful** — keep |
| `fwb/0011` PendingIntent immutability warp | GrapheneOS `PendingIntent.checkPendingIntent2`: on a missing mutability flag under the enforced S+ compat change, log `Log.e(TAG, msg)` and return `flags \| FLAG_IMMUTABLE` instead of throwing; all four creation paths (`getActivity`, `getActivities` loop, `getBroadcast`, `getService`/foreground service) assign the returned flags | Ported verbatim, including the both-flags-still-throws behaviour. The lenOS comment in the patch notes the intent; no functional delta | **Faithful** — keep |
| `fwb/0012` lockscreen notification privacy | GrapheneOS `packages/SettingsProvider/res/values/defaults.xml:170` (`def_lock_screen_allow_private_notifications` `false`) | One line flipped in place (AOSP `true`); seeded through `DatabaseHelper` for new installs/users exactly as GrapheneOS does — no RRO or seed indirection | **Faithful** — keep |
| `fwb/0013` + `packages_apps_Settings/0001` screenshot metadata | GrapheneOS `ImageExporter.java:513` gate on `ExtSettings.SCREENSHOT_TIMESTAMP_EXIF` (`writeExif` nulls `captureTime`; `updateExifAttributes` is nullable and early-returns before the date/timezone tags) and the Settings row `privacy_screenshot_timestamp_exif` (`more_security_privacy_settings.xml:108`) | SystemUI side is line-level faithful plus the removal of LineageOS's `TAG_SOFTWARE = "Android " + Build.DISPLAY` line (GrapheneOS/AOSP never write it; commented in the patch). Settings side: same row, strings and keys; GrapheneOS wires it via the `settings:boolSettingField` XML attribute, which lenOS does not port — the controller is registered explicitly in `MoreSecurityPrivacyFragment` (documented mechanism substitution, same UX). `packages_apps_Settings/0001` was renamed to `0001-lenos-ext-settings-ui` because it already carried the ext-controller infrastructure | **Faithful** (mechanism substitution documented) — keep |
| `system_ca-certificates/0001` distrusted CA removal | GrapheneOS commit `14ad6bb` on `platform_system_ca-certificates` ("remove Chunghwa Telecom and Netlock CAs", June 2025) | Same three files deleted: `files/53a1b57a.0` (HiPKI Root CA - G1), `files/60afe812.0` (NetLock Arany (Class Gold)), `files/9d6523ce.0` (ePKI Root CA). The LineageOS 24.0 tree still ships all three files, so this is a real removal; `Android.bp` globs `files/*`, so no build-file edit is needed | **Faithful** — keep |
| `system_extras/0001` FBE filename padding | GrapheneOS `libfscrypt/fscrypt.cpp:248` (`FSCRYPT_POLICY_FLAGS_PAD_32`, commit "pad filenames to 32 bytes instead of 16 or 4 bytes", Sep 2020) | Same one-line behavior for every new policy; the pre-R PAD_4 branch is dropped exactly as GrapheneOS did it (unreachable here: `PRODUCT_SHIPPING_API_LEVEL := 35`, and no shipped lenOS installs to stay compatible with). lenOS additionally updates the stale in-tree `fscrypt_test` expectations to PAD_32 — GrapheneOS's fork changed only the code, so its copy of the test contradicts it; behavior delta vs GrapheneOS: none | **Faithful** (test fix documented) — keep |
| `packages_apps_CellBroadcastReceiver/0001` wireless alerts optional | GrapheneOS commits "allow toggling presidential alerts" (`11e3a8c`, 8 files) and "always allow disabling extreme alerts" (`59d96c7`, `res/values-mcc724/config.xml`) | Both are ported file-for-file: default `show_presidential_alerts_settings=true`, the override summary string, the presidential preference un-disabled in both preferences XMLs, the alert path reading `KEY_ENABLE_CMAS_PRESIDENTIAL_ALERTS` (default true), the `mAlwaysOn` parse commented out exactly as GrapheneOS writes it, the CDMA category set/clear mapping, the settings-fragment wiring, and Brazil's forced-on extreme override removed. lenOS deltas: the stale "the user is never allowed to change the preference" comment GrapheneOS left behind is dropped (and replaced with a short note), plus a lenOS marker comment on the config bool. The legacy `CellBroadcastSettingsOldFragment` (pre-S/watch path, unreachable here: `hideToolbar = !SdkLevel.isAtLeastS() || isWatch`) is left untouched, same as GrapheneOS. All alert types stay on by default | **Faithful** (comment deltas documented) — keep |
| `packages_modules_Permission/0001` delayed Allow (permission dialogs) | GrapheneOS commit "delay activation of Allow button(s) in runtime permission dialog" (`f51d118d6`, Dec 2024) | `GrantPermissionsActivity.isAllowButton()` recognises the same six allow button IDs as GrapheneOS (matching is by constant, so upstream's `NEXT_BUTTON` drift is irrelevant), and `GrantPermissionsViewHandlerImpl.kt` disables the button whenever it is visible and an allow variant, then re-enables it via `postDelayed(action, 1000)`. lenOS delta: the debug log suffix drops the app package (`mAppPackageName`), which this branch no longer passes into the handheld handler — GrapheneOS logs it. Deny/Cancel paths untouched | **Faithful** (log suffix delta documented) — keep |
| `frameworks_base/0014` delayed Allow (USB ADB prompt) | GrapheneOS commit "delay activation of the Allow button in USB ADB confirmation dialog" (`f9fc573b1`, Dec 2024) | The same five lines in `UsbDebuggingActivity.onCreate`: disable the dialog's positive button after `setupAlert()` and re-enable it via `getMainThreadHandler().postDelayed(…, 1000)`; the `android.widget.Button` import is added. No lenOS deltas | **Faithful** — keep |
| `fwb/0015` Secure Paste stage 1 | GrapheneOS `ClipboardAccess.java` + `AswAllowClipboardRead` (per-app `GosPackageState` state, denial notifications, paste grants) integrated with the SystemUI paste toolbars | Framework part that does not need `GosPackageState`: `ClipboardService` reads `ExtSettings.ALLOW_CLIPBOARD_READ_BY_DEFAULT`, exempts the default IME and system apps, lets the clip owner always read, strips the label from denied `getPrimaryClipDescription` calls while keeping mime types, and keeps the `hasClipboardText` presence signal — all matching GrapheneOS. Not ported in 1.0: per-app overrides, the denial notification/`SUPPRESS_CLIPBOARD_ACCESS_DENIAL_NOTIF`, paste grants and the SystemUI toolbar. The experimental OPS-4 screen adds per-app `OP_READ_CLIPBOARD` AppOps control for user-installed apps (§8); GrapheneOS's `GosPackageState` state, denial notification and toolbar remain unported. The global default stays `true`, so stock paste is unchanged unless the user opts in; when enabled without stage 2, cross-app paste is blocked by design (documented in features.md). Settings row uses explicit-controller registration instead of GOS's `boolSettingField` auto-wiring | **Deliberate (staged)** — stage 2 experimental; keep |
| `fwb/0016` cross-profile clipboard | GrapheneOS `CrossProfileClipboardAccessSettings` (`FOLLOW_DEFAULT`/import-only/export-only/block) read at `ClipboardService.java:1064` (export) and `:1099` (import), plus `DragState.java:517` | Class ported verbatim (same `Settings.Secure` key and four values); both `ClipboardService` gates match GOS — export returns before the related-profile loop and import skips per related profile — and the drag gate clears `mCrossProfileCopyAllowed` as in GOS. `Settings.Secure.CROSS_PROFILE_CLIPBOARD_ACCESS` is added through the regenerated `fwb/0006`. Settings UI is a plain `ListPreference` with an explicit controller (GOS uses `RadioButtonPickerFragment2`/`IntSettingPrefController`), same four policies and strings, editing the current profile's per-user value. Default follows stock Android | **Faithful** (UI mechanism substitution) — keep |
| `system_netd/0001` VPN leak blocking | GrapheneOS netd `82da9204` (DNS lockdown), `dcef5ccb` (multicast firewall) and `d57ea8dc` (keep inbound RAs), plus `40c47da2` (SockDiag logging) | `NetworkController::getNetworkForDnsLocked` derives the fwmark from `canProtectLocked()`/`getPermissionForUserLocked()` instead of the unconditional VPN-protected/system mark. The multicast firewall is ported as `MulticastFirewallController` with the exact rules, GrapheneOS chain ordering, the RA RETURN rule and the router-solicitation compatibility rule; unit tests and `ControllersTest` expectations included. lenOS deltas: Apache headers on the new files (GrapheneOS copies have none) — no code change. `40c47da2` is already in LineageOS 24.0 (verified in-tree), so it is not duplicated | **Faithful** — keep; exercise tethering, IPv6 and multicast apps on first flash |
| `packages_modules_Connectivity/0001` NSD lockdown | GrapheneOS `NsdService.java:3452-3456` calling `ConnectivityUtil.isRegularAppWithLockdownVpnEnabled` and returning null for regular apps | The branch-16 `connect()` has no package-name argument, so the check sits immediately after `mDeps.getCallingUid()` instead of after `enforcePackageNameMatchesUid`; same uid predicate, same null return, same system-app exemption through the shared helper. `connect()` is the single NSD client entry point in this branch | **Faithful** (API drift documented) — keep |
| `fwb/0017` ConnectivityUtil | GrapheneOS `core/java/android/ext/ConnectivityUtil.java` (`isSystem`, `isRegularAppWithLockdownVpnEnabled`) and its module-lib API declaration | Class and methods ported verbatim; `core/api/module-lib-current.txt` gains the same `package android.ext` block so the module-lib API check passes. Consumed by the Connectivity NSD gate | **Faithful** — keep |
| `fwb/0018` always-on VPN survival | GrapheneOS `Vpn.startAlwaysOnVpn()`: log and `return false` for an unsupported always-on package without clearing the setting | Same log message and control flow; LineageOS 24.0's safe-mode-only `setAlwaysOnPackage(null, false, null)` guard is removed together with the normal-mode unset, so the always-on + lockdown configuration survives any temporary package unavailability and resumes when the package returns | **Faithful** — keep |
| `fwb/0019` no browser location grant | GrapheneOS `DefaultPermissionGrantPolicy` has no browser location block | The stock block (browser role holder or `CATEGORY_APP_BROWSER` system handler → `FOREGROUND_LOCATION_PERMISSIONS`) is deleted; one lenOS comment marks the spot (GrapheneOS's tree has no comment). Every other default grant is untouched | **Faithful** — keep |
| `fwb/0020` radio auto-off timers | GrapheneOS `DelayedConditionalAction` (122), `WifiAutoOff` (141), `BluetoothAutoOff` (125), wired from `SystemServerExt.init` in `SystemServer#startOtherServices` just before `mActivityManagerService.systemReady` returns | The three service classes are line-level ports (same alarm semantics, same Wi-Fi/GATT-connected predicates, same `adapter.disable(true)` and `setWifiEnabled(false)` calls, same extras logging). Deviations: `SystemServerExt` is a trimmed lenOS version that keeps the same `context`/`bgHandler`/`packageManager` shape and wiring point but only calls the auto-off `maybeInit`s (GrapheneOS's class also bootstraps AppCompatConf and dev-build diagnostics, neither ported); Apache headers on the new files. The Settings rows use GrapheneOS's `AutoOffSetting` choices and millisecond values with a plain `ListPreference` instead of a `RadioButtonPickerFragment2` sub-screen (UI mechanism substitution, §14.1). `WIFI_AUTO_OFF`/`BLUETOOTH_AUTO_OFF` were already seeded by `fwb/0006` | **Faithful** (wiring trim + UI mechanism documented) — keep |
| `fwb/0021` GNSS SUPL/PSDS privacy | GrapheneOS `android/ext/settings/GnssSettings.java` (keys `force_disable_supl` / `psds_server`, values 0/1/2), `GnssConfiguration.applyConfigOverrides` applied after carrier + debug properties, and `GnssLocationProvider` SUPL/PSDS observers plus the `isPsdsEnabled()` download gate | Ported file-for-file with the proxy modes omitted: GrapheneOS defaults to its own SUPL/PSDS proxies and offers them in the UI; lenOS has no proxy infrastructure, so only `STANDARD`/`DISABLED` are valid and both settings default to `DISABLED` (documented deviation, privacy-max). The enforcement order, property names, SUPL mode 0 + host/port removal, PSDS server clearing and `ENABLE_PSDS_PERIODIC_DOWNLOAD=0` match GrapheneOS. `device/0003` (empty `gps.supl_host`) was deleted because it made the new "Standard server" choice a no-op | **Faithful** (proxy modes/defaults documented; stricter defaults) — keep |
| `fwb/0022` package updates preserve enabled state | GrapheneOS `bff727d` ("always preserve package enabled setting after package update", 2026-07-29): removes the three implicit re-enable blocks in `InstallPackageHelper.updateSettingsInternalLI`, removes `InstallRequest.isApplicationEnabledSettingPersistent()`, and advertises `grapheneos.package_update_preserves_package_enabled_setting` from `SystemConfig` | Exact port of all three parts (verified against the commit diff). The `setApplicationEnabledSettingPersistent` session flag, `InstallingSession`/`InstallArgs` plumbing and `PackageInstallerSession` accessor stay (API + metrics), matching GrapheneOS; only the update path stops re-enabling. Feature name kept verbatim | **Faithful** — keep |
| `packages_providers_MediaProvider/0001` directory listing | GrapheneOS `72492da1c` (Storage Scopes): Java returns a `["" , <dirs>]` suffix and JNI stops appending lower-FS dirs; apps with READ_MEDIA_* and `Android/` keep upstream behavior | The Java branch, native `skip_add_dirs` plumbing and the directory-name computation are line-level ports. Deviation: Storage Scopes (`GosPackageState`, `StorageScope`, scope UI, `LocalCallingIdentity` scope hooks) are **not ported**; `StorageScopesHooks.obtainDirContents` omits the scope loop and keeps the same name/shape for later. The app-created-file visibility query is unchanged | **Faithful** (subset: directory-listing hook only) — keep |
| `fwb/0023` prototype-device warning + Settings bootloader field | AMS `isPrototypeDevice()`/`showPrototypeNotificationIfPrototype()` (Pixel: `ro.revision` contains `MP`, `ro.boot.secure_boot` is `PRODUCTION`; otherwise notify) with strings `prototype_device_notification_{title,message}` and proto `SystemMessage.NOTE_PROTOTYPE_DETECTED = 400`; Settings `BootloaderVersionPreferenceController` + row + string (`ro.bootloader`) | The Pixel branch, notification builder (same `SystemNotificationChannels.DEVELOPER` channel, `stat_sys_adb` icon, ongoing/public), proto id and call site (after `showMteOverrideNotificationIfActive()` in `finishBooting()`'s boot-complete path) are line-level ports; the Settings controller is a file-level port and the row/string match GrapheneOS. Documented deviation: GrapheneOS returns early for every non-Google brand; lenOS adds `isPrototypeDeviceNonPixel()`, which treats only an explicit EVT/PVT/DVT marker in `ro.boot.hwlevel` / `ro.boot.hardware.revision` / `ro.boot.device_release` as a prototype — without it the warning would be dead code on Nothing hardware. AOSP's serial-console notification already exists in LineageOS and is untouched (no Pixel `console=null` cmdline heuristic is added) | **Faithful** (non-Pixel detection extension documented) — keep; verify the phase properties on first boot |
| `fwb/0024` memory hygiene on lock | SystemUI `KeyguardViewMediator.handleShowInner` (`System.gc(); System.runFinalization(); System.gc();` before `mShowKeyguardWakeLock.release()`) and system_server `KeyguardServiceDelegate.onShowingStateChanged` (`if (showing) { … }`, binder thread) | SystemUI hunk is a line-level port (same position, same three calls). A17 has `IKeyguardStateCallback`, but the port keeps the existing `IActivityTaskManager.setLockScreenShown` hook instead of adding keyguard plumbing: the same three calls run on that binder thread, gated on the false→true transition (`mKeyguardShown != keyguardShowing`) and placed after the `mGlobalLock` block, so no WMS lock is held — same process, same moment as GrapheneOS's callback | **Faithful** (callback-path choice documented) — keep |
| `packages_apps_Settings/0002` disable user-installed apps | SPA app info `AppDisableButton.kt`: offered for every installed app (`!app.installed`), `canBeDisabled()` `!isSystemApp -> isAllowUninstallOrArchive(...)`, and the disable click skips the data-loss dialog for user apps | The three hunks are exact ports of the GrapheneOS logic (`!app.installed` gate, the `isAllowUninstallOrArchive` branch placed before the system-app checks, and the `if (app.isSystemApp) dialog else disable()` click). Documented deviations: the classic `AppButtonsPreferenceController` screen is unmodified (GrapheneOS leaves it unmodified as well; `settings_enable_spa` defaults to true, so the SPA screen is the one users see) and the HSU dialog title/message is kept (user apps skip the dialog) | **Faithful** — keep |
| `packages_apps_Settings/0001` LTE/5G-only entries | GrapheneOS commits `5310142ccc` ("LTE Only Mode") and `8d37b32db6` ("5G Only / 4G or 5G only") | Entries, `lteOnlyUnsupported` cases, NR-standalone detection, summary switch and strings are line-level ports (the atomic `is5GSupported` flag included, as GrapheneOS writes it). Deliberate deviation: GrapheneOS's commit also flips `getAvailabilityStatus` from `== EnabledNetworkMode` to `!= PreferredNetworkMode`, exposing the row when the carrier hides network settings (`None`); lenOS keeps the stock guard. GrapheneOS's non-world-mode `NETWORK_MODE_LTE_GSM_WCDMA` summary fallthrough is preserved verbatim | **Faithful** (availability guard deviation documented) — keep |
| `device/0007` multiuser limit | GrapheneOS `core/res/res/values/config.xml:3288` (`config_multiuserMaximumUsers = 32`) | Same value, carried in the vendor overlay the device already uses (framework raw default is 1; the Lineage device overlay pinned 4). `config_enableMultiUserUI` is already `true` in that overlay, so both knobs the AOSP deprecation note asks for are set | **Faithful** — keep |
| `fwb/0025` special-runtime-permission framework (INTERNET + OTHER_SENSORS) | GrapheneOS "special runtime permissions" (SRT): `SrtPermissions`, `SpecialRuntimePermAppUtils`, `AppPermissionUtils`, `AppBindArgs`, `PackageManagerHooks`, server `SpecialRuntimePermUtils`, `PermissionManager` self-check spoofing, `DownloadManager` gates, `ActivityThread`/AMS bind plumbing, and the permission-service Kotlin policy (auto-grant, evaluation, review skip, reset skip, inheritance) | Line-level port of the whole SRT mechanism, with `INTERNET` and `OTHER_SENSORS` as the members up front (the sensors patch `fwb/0026` only adds the enforcement, so it never edits files this patch creates): the manifest carries both permission declarations and groups, `core/api/current.txt` the matching `Manifest.permission`/`Manifest.permission_group` constants (also fixing the `NETWORK` group entry the first network landing missed), and `shouldAutoGrant` carries GrapheneOS's `ExtSettings.AUTO_GRANT_OTHER_SENSORS_PERMISSION` path (parent profile for work users) alongside the unconditional INTERNET grant. Documented deviations: the `ActivityThreadHooks` indirection is inlined (null-guarded); `AppPermissionUtils` is `@hide`/SRT-only instead of GOS's `@SystemApi` (the `@SystemApi` surface is exactly `SpecialRuntimePermAppUtils.isInternetCompatEnabled()`); `PackageInstalledParams.isNewlyInstalledInUserId()` is *added* to LineageOS 24.0 (GrapheneOS field, same name and semantics) and populated at both install paths so an update can never re-grant; no pre-existing-install migration (GrapheneOS has none either — checked code + release notes) | **Faithful** — keep |
| `packages_modules_Connectivity/0002` network-permission gates | GrapheneOS's 32 `ConnectivityManager` internet-compat gates plus the `NsdManager` stub connector | All 32 gates verbatim (same `null`/empty/`false` "network down" answers, callbacks suppressed). The NSD stub implements the full A17 connector AIDL (`registerServiceInfoCallbackWithRequest`, `injectOffloadEngineResponse`, `checkPermissionForService`) and `connect()`'s `packageName` argument; the failure callbacks are identical | **Faithful** — keep |
| `packages_modules_Permission/0002` network permission UI | GrapheneOS PermissionController SRT integration: `PermissionMapping` (NETWORK group), `KotlinUtils`, `Permission.isGrantedIncludingAppOp`, `AppPermissionGroup`, `PermissionUsageControlPreferenceUtils`, `HibernationSettingStateLiveData`, `AutoRevokePermissions` | Seven files, line-level ports; the only non-behavioral delta is one GrapheneOS line over 100 columns wrapped to AOSP style in `AppPermissionGroup`. The install-time toggle assumed by the original §5 analysis does not exist in GrapheneOS either — their branch-17 `PackageInstaller` has no SRT/INTERNET references (checked), so installs auto-grant and app info is the toggle | **Faithful** — keep |
| `fwb/0026` sensors-permission notification stack | GrapheneOS `MissingSpecialRuntimePermissionNotification` + `IntentReceiver` + `SseUtils`, the `MISSING_PERMISSION` notification channel, the `NOTE_MISSING_PERMISSION_OTHER_SENSORS = 500` proto id and `PackageManagerNative.onDeniedSpecialRuntimePermissionOp` (+ the AIDL method in `fwb/0029`) | Verbatim port; deviations are mechanism-only: the channel is created inline in `SystemNotificationChannels.createAll` (GrapheneOS refactored around an `extraChannels()` hook), the `<java-symbol>` duplicates next to the strings are omitted (framework-internal references only), the notification builder resolves the app context as `mPm.mContext` (A17 `PackageManagerService` has no `getContext()`), and the 500 proto id is inserted with a trailing-context-only hunk so it co-applies with `fwb/0023`'s 400 at the same spot | **Faithful** (mechanism deltas documented) — keep |
| `frameworks_native/0001` sensors permission enforcement | GrapheneOS `libs/sensor/Sensor.cpp:67` (`mRequiredPermission = OTHER_SENSORS` for every sensor without a more specific permission) and `services/sensorservice/SensorService.cpp:2540-2583` (`canAccessSensor`: `OTHER_SENSORS` check, `AID_APP_START` exemption for system daemons, pre-Q step-counter fallback to `OTHER_SENSORS`, denial → `package_native.onDeniedSpecialRuntimePermissionOp`) + the AIDL method carried by `fwb/0029` | Line-level port. The pre-Q step-sensor branch (which upstream allowed unconditionally) moves into the non-permission branch and enforces `OTHER_SENSORS` exactly like GrapheneOS; the AIDL lives in `frameworks/base` at `native/android/aidl/` (the A17 location, same as GrapheneOS) | **Faithful** — keep |
| `fwb/0027` location-indicator coverage | GrapheneOS `AppOpsPrivacyItemMonitor.kt`: `OPS_LOCATION = intArrayOf(OP_FINE_LOCATION, OP_COARSE_LOCATION)` (:82-83), `.filter { item.code in OPS_LOCATION }` (:272), `OP_FINE_LOCATION, OP_COARSE_LOCATION -> PrivacyType.TYPE_LOCATION` (:387-388) and `if (item.code in OPS_LOCATION)` (:429) | Line-level port of the four-hunk delta (plus one lenOS comment); the other deltas in that file (`LocationAccumulatedLogger`, the `getUidImportance` refactor) are separate GrapheneOS features and are untouched. No enablement plumbing is needed on A17: AOSP's `cp1a` release config enables `android.location.flags.location_indicators_enabled`, and `cp2a` (the config LineageOS selects through `vendor/lineage/vars/aosp_target_release`) inherits it. The A16-era `vendor/lenos/release/` map + value set was removed during the port. No AOSP or LineageOS file is patched for it | **Faithful** — keep |
| `packages_modules_NetworkStack/0001` DHCP lease reuse | GrapheneOS `platform_packages_modules_NetworkStack` `62d70edb46` "avoid reusing DHCP state for full MAC randomization" (2021-05-20): `DhcpClient` checks the connected network's `WifiConfiguration.macRandomizationSetting` when a non-expired lease comes back from `IpMemoryStore`, and transitions to `mDhcpInitState` (fresh DISCOVER) instead of `mDhcpInitRebootState` (renew) for `RANDOMIZATION_ALWAYS` (GOS still ships the hunks on branch 17, `DhcpClient.java:1309`/`:1342-1366`) | Line-level port; the only delta is a lenOS comment above the method. A17 adaptation: none needed — the `EVENT_CONFIGURATION_OBTAINED`/`IpMemoryStore` path is identical and the `NETWORK_STACK` UID passes Wi-Fi's `enforceCanAccessScanResults` bypass (checked in `WifiPermissionsUtil.java:572-577`), so the configured-network lookup works without location permission; any lookup failure returns `true` (avoid reuse), GrapheneOS's own fail-safe | **Faithful** — keep |
| `fwb/0028` lock-screen end session | GrapheneOS `KeyguardIndicationController.updateLockScreenLogoutView()`: `if (false && mUserLogoutInteractor.isPolicyManagerLogoutEnabled().getValue())` (branch 17; the only difference from AOSP in that method — the surrounding logout wiring is unchanged) | Line-level port using A17's `isPolicyManagerLogoutEnabled()` plus a lenOS comment. The power-menu End session action stays stock, gated by the same interactor | **Faithful** — keep |
| `packages_apps_Settings/0003` per-user app installation policy | GrapheneOS `packages/apps/Settings/src/com/android/settings/users/UserAppsInstallSettings.java` (three-way radio picker writing `DISALLOW_INSTALL_APPS` / `DISALLOW_INSTALL_UNKNOWN_SOURCES`; guests cannot select "enabled"), the `UserRestrictions` helper (restriction reads/writes with guest-default handling), the `app_installs` row in `user_details_settings.xml`, and the `UserDetailsSettings` wiring (summary + launch) | Line-level port. The metrics category is GrapheneOS's `Instrumentable.METRICS_CATEGORY_UNKNOWN` (defined on A17), the strings live in a new `strings_lenos_users.xml` instead of extending the lenOS ext-strings file, and the helper is trimmed to the install path — GrapheneOS's private-space restriction inheritance (`INHERITED_PRIVATE_SPACE_RESTRICTIONS`, sync/fixup) is a separate feature and is omitted. No framework patch: `PackageInstallerService`/`InstallPackageHelper` already enforce both restrictions on A17 | **Faithful** (UI deltas documented) — keep |
| `kernel_nothing_sm7635/0001` + `device_nothing_asteroids/0008` kernel hardening (#32) | No GrapheneOS patch equivalent — their kernel hardening is a config/allocator/bionic project, not a portable diff (§17). lenOS ships the portability-safe Kconfig subset and merges it last | Additive 6.6 GKI fragment (`arch/arm64/configs/vendor/lenos_hardening.config`): `INIT_ON_FREE_DEFAULT_ON`, `RANDOM_KMALLOC_CACHES`, `RANDOMIZE_KSTACK_OFFSET_DEFAULT`, `SECURITY_DMESG_RESTRICT`, `ZERO_CALL_USED_REGS`. It disables no vendor/GKI option. `INIT_STACK_ALL_ZERO` is already the upstream 6.6 default when Clang supports auto-var-init, and `INIT_ON_ALLOC_DEFAULT_ON`, SLUB freelist hardening, page-allocator shuffling, CFI/SCS and `LIST_HARDENED` are already on. Not attempted: 48-bit VA/4-level page tables, forced module signing/lockdown, LTS point-release cadence, custom allocator canaries/MTE-for-apps (§19) | **Original** (config-only workstream) + **Plumbing** (BoardConfig merge) — keep; boot/perf validation pending |
| `vendor_lineage/0001` strip packages | GrapheneOS edits its product app lists directly | Parameterized `LENOS_STRIP_PACKAGES` filter applied in three `vendor/lineage/config/*.mk` files | **Plumbing** — equivalent intent, cleaner mechanism |

**Conclusion.** No accidental behavioral deviations were found, and the approximations surfaced by the
redo audit have been replaced by faithful ports (auto-reboot init, QS gating, Wi-Fi privacy defaults,
PIN scrambling). Of the 53 patches: **42 are faithful GrapheneOS ports** — auto-reboot pair, QS gating,
duress, eSIM wipe pair, Wi-Fi privacy defaults (`wifi/0001`), SystemUI PIN scramble (`fwb/0008`), the
Settings ext-UI (`packages_apps_Settings/0001`: scramble controls + screenshot toggle + LTE/5G-only
entries + firmware-visibility bootloader field, single-credential-domain adaptation, explicit controller
registration instead of GrapheneOS's
XML auto-wiring), the quick-win batch (`fwb/0009`–`0013`, `device/0007`, all value/line-level), the
cross-profile clipboard policy (`fwb/0016`), the VPN leak-blocking set
(`system_netd/0001`, `packages_modules_Connectivity/0001`, `fwb/0017`–`0018`), the
browser-location removal (`fwb/0019`), the radio auto-off set (`fwb/0020`), the GNSS SUPL/PSDS
set (`fwb/0021`), the package-update enabled-state port (`fwb/0022`), the MediaProvider
directory-listing hook (`packages_providers_MediaProvider/0001`), the firmware-visibility
batch (`fwb/0023`, non-Pixel detection extension documented), the memory hygiene on lock
(`fwb/0024`, callback-path choice documented), the user-installed app disabling
(`packages_apps_Settings/0002`, SPA-only like GrapheneOS), the network-permission set
(`fwb/0025` + `packages_modules_Connectivity/0002` + `packages_modules_Permission/0002`, the
added `isNewlyInstalledInUserId` field documented), the sensors-permission set (`fwb/0026` + `frameworks_native/0001`, notification-stack mechanism deltas documented), the
location-indicator port (`fwb/0027`), the
DHCP lease-reuse fix (`packages_modules_NetworkStack/0001`, faithful on A17), the
lock-screen end session disable (`fwb/0028`), the per-user app installation policy
(`packages_apps_Settings/0003`, string-placement delta documented), the
distrusted-CA removal (`ca-certificates/0001`), the FBE padding (`system_extras/0001`),
the wireless-alerts optionalization (`packages_apps_CellBroadcastReceiver/0001`) and the delayed-Allow
pair (`packages_modules_Permission/0001` + `fwb/0014`) — the
auto-reboot pair carries the two benign environment
deltas listed above, the Settings port the LockDomain removal + registration mechanism; **5 are
deliberate lenOS choices** (first-boot defaults, ExtSettings trim + PIN
scramble default ON, Secure Paste stage 1, Wi-Fi enterprise hardening, no-2G default) — several
stricter than anything GrapheneOS ships (enterprise Wi-Fi, SUPL/PSDS-off defaults, scramble default); **3 are
lenOS-original** (SSAID rotation, device name, kernel-hardening fragment); **3 are build/device plumbing**
(product, package strip, kernel-config merge). The re-done ports are
line-level faithful; earlier inventory text that called them (or the Wi-Fi privacy defaults) deviations
is superseded by this audit.

**Watch list (revisit conditions):**
1. Auto-reboot SELinux context — the dedicated `auto_reboot_ctl_prop` type is now ported
   (`system_sepolicy/0001`); re-check it if LineageOS reworks `private/property_contexts`.
2. SUPL/PSDS defaults — if first-fix UX complaints appear, keep the defaults off and point users at the
   Location → Network assistance toggles (standard server); do not reintroduce a device-level blank
   `gps.supl_host`, which defeats the toggle.
3. Seeded-but-inert ExtSettings constants — do not expose UI for the sensors auto-grant,
   NFC auto-off, memtag/DCL toggles until their enforcement lands (§14). PIN scramble, the clipboard
   default, screenshot EXIF and the Wi-Fi/Bluetooth auto-off timers are the exceptions (wired, UI
   shipped).
4. PIN scramble default-ON — the one lenOS hardening deviation with a plausible accessibility
   trade-off (the keypad relayouts on every setup). The per-user switch exists; if feedback is bad,
   flip the `ExtSettings` default back to GrapheneOS's `false` instead of patching SystemUI.
5. Keep `vendor/lenos/docs/features.md` synced as the §16 quick wins land (each adds a patch; features.md
   currently references the right files for duress/eSIM/scramble).
6. SSAID rotation — the only lenOS-original behavior with plausible app-compat fallout; keep it
   documented and easily switchable (the toggle already exists).
7. Storage Scopes — `packages_providers_MediaProvider/0001` ships only the directory-listing hook.
   When scopes are ported, add `GosPackageState`/`StorageScope` support inside `StorageScopesHooks`
   (the scope loop was intentionally left out) and wire `LocalCallingIdentity.getStorageScopes()`.
8. Non-Pixel prototype detection — `fwb/0023`'s EVT/PVT/DVT phase-property list
   (`ro.boot.hwlevel`, `ro.boot.hardware.revision`, `ro.boot.device_release`) is best-effort: Nothing
   bootloader documentation is not public. On the first flash, check which (if any) of those properties
   the asteroids bootloader reports (`getprop ro.boot.hwlevel`, etc.); if the real unit type lives under
   another `ro.boot.*` name, extend `PROTOTYPE_PHASE_PROPS` in the same patch (the check only fires on
   an explicit EVT/PVT/DVT marker, so unknown names stay silent — no false positives).

---

## 19. Kernel hardening workstream (Tier 3 #32) — started

Tier 3 #32 is a workstream, not a GrapheneOS patch port: GrapheneOS's kernel
hardening is spread across their kernel forks, bionic/ART and custom allocator
code, none of which is a portable `git diff`. lenOS starts with the subset that
is expressible as an additive 6.6 GKI config fragment and needs no vendor
firmware or module re-signing:

* `kernel_nothing_sm7635/0001` creates
  `arch/arm64/configs/vendor/lenos_hardening.config`.
* `device_nothing_asteroids/0008` appends it to `TARGET_KERNEL_CONFIG` **last**,
  after `gki_defconfig` and the two vendor fragments, so it can only override
  with `=y` (the fragment contains no `# CONFIG_... is not set` line).

### Enabled by the fragment

| Option | Effect | Expected cost |
|---|---|---|
| `CONFIG_INIT_ON_FREE_DEFAULT_ON` | zero page-allocator and SLUB memory when freed, not only when allocated; reduces sensitive-data lifetime and use-after-free usefulness | 3–5% typical (up to 8% synthetic); can be disabled at boot with `init_on_free=0` |
| `CONFIG_RANDOM_KMALLOC_CACHES` | 16 randomized `kmalloc` caches; makes heap spraying harder | small memory/CPU overhead |
| `CONFIG_RANDOMIZE_KSTACK_OFFSET_DEFAULT` | 5 bits of per-syscall kernel-stack offset randomization on by default | negligible; `randomize_kstack_offset=off` at boot |
| `CONFIG_SECURITY_DMESG_RESTRICT` | unprivileged reads of the kernel log denied by default (Android already gates `dmesg` to root/SELinux; this is the kernel-side default) | none |
| `CONFIG_ZERO_CALL_USED_REGS` | zero caller-used registers on function exit; reduces register-content leaks and ROP gadgets | <1% runtime; ~5% arm64 image growth |

### Already on in the pinned baseline (not claimed by the fragment)

`INIT_ON_ALLOC_DEFAULT_ON`, `SLAB_FREELIST_RANDOM`, `SLAB_FREELIST_HARDENED`,
`SHUFFLE_PAGE_ALLOCATOR`, `HARDENED_USERCOPY`, `FORTIFY_SOURCE`,
`CFI_CLANG`, `SHADOW_CALL_STACK`, `BUG_ON_DATA_CORRUPTION` (which selects
`LIST_HARDENED`), `KFENCE`, `RANDOMIZE_BASE`, `STRICT_KERNEL_RWX`/
`STRICT_MODULE_RWX` (arch defaults) and `VMAP_STACK` (arch default).
`INIT_STACK_ALL_ZERO` is the upstream 6.6 choice default when the compiler
supports `-ftrivial-auto-var-init=zero`, which the GKI Clang does, so it is
already in effect and is not listed as a lenOS delta.

### Deliberately not attempted

* **48-bit VA / 4-level page tables** (`CONFIG_ARM64_VA_BITS_48`; GrapheneOS's
  higher-entropy ASLR). 4 KB-page kernels default to 39-bit VA; changing the
  memory map has to be validated against the vendor kernel/modules and the
  bootloader, and a bad change can prevent boot.
* **Forced module signing + lockdown**: the vendor DLKM/module set is prebuilt
  and signed by Nothing/Qualcomm; lenOS cannot re-sign it, and
  `MODULE_SIG_FORCE` would refuse to load those modules.
* **Kernel LTS point-release cadence**: operational work (fetch/merge/test the
  6.6 LTS stable queue), not a config patch.
* **GrapheneOS's custom allocator canaries and MTE-for-apps**: kernel/bionic
  work, not a Kconfig switch. The pinned `gki_defconfig`'s `KASAN_HW_TAGS` is
  a debug/testing feature, not the production app-hardening MTE policy.

### Baseline caveat

The pinned `gki_defconfig` is debug-heavy (`KASAN`, `UBSAN`, `KFENCE`,
`PAGE_OWNER`, etc.). This workstream does not change those options: it is
additive only. Any production debug-option review (and the resulting
performance win) is a separate decision that needs a build and on-device
measurement.

### Verification (after the first build)

```bash
adb shell 'zcat /proc/config.gz | grep -E "CONFIG_(INIT_ON_FREE_DEFAULT_ON|RANDOM_KMALLOC_CACHES|RANDOMIZE_KSTACK_OFFSET_DEFAULT|SECURITY_DMESG_RESTRICT|ZERO_CALL_USED_REGS)=y"'
adb shell cat /proc/sys/kernel/dmesg_restrict     # 1
adb shell dmesg | head                            # permission denied for shell
```

`CONFIG_IKCONFIG_PROC=y` in the pinned config makes `/proc/config.gz`
available. Also record boot time, idle memory and a few real workloads before
and after the fragment, because `init_on_free` is the only option with a
material cost. Until this runs on the device, #32 is **source-complete**, not
verified.

## 20. Experimental series (opt-in)

Implementations that are source-complete but have not been built or
device-validated are kept out of the default 1.0 build. They live under
`patches-experimental/` and `experimental/`, but remain a second series applied
**after** the stable 1.0 series. `tools/lenos-patch.py --experimental` selects
them; the build driver does so only when `LENOS_EXPERIMENTAL=1`, and installs
`experimental/app/LenosOpsec` only in that mode. The default build never applies
or compiles them. See `docs/experimental.md`.

Current experimental batches:

* **#20/#21 — system-app update verification.** `frameworks_base/0001` ports
  GrapheneOS's `PackageVerityExt`: immutable packages are recorded during the
  boot scan before `/data` updates are considered; an update is rejected when
  its versionCode is not greater (or is equal for static shared libraries),
  when any split lacks fs-verity, or when its signing certificate lacks the
  required capability. The install path also fails before committing for
  fs-verity and same-versionCode cases. Debuggable-only recovery properties
  are retained. GrapheneOS's original-package exception for Vanadium/PDF
  viewer is not ported (lenOS ships neither).
* **#25 — screenshot sound.** `frameworks_base/0002` removes the
  `screenshotForceShutterSound` aconfig guard from the non-forced screenshot
  sound and gates it on `Settings.System.SOUND_EFFECTS_ENABLED`; the forced
  shutter path is unchanged. lenOS evaluates the forced path first so a
  mandatory shutter sound is not silenced by the touch-sounds setting (a
  deliberate deviation from GrapheneOS branch 17's early return; see the
  experimental provenance doc).
* **#22 — USB-C data-line control.** `frameworks_base/0003` +
  `packages_apps_Settings/0002` implement the portable OS-side subset with
  AOSP's per-port `enableUsbData` HAL operation. Modes, keyguard transitions,
  the `persist.security.usb_mode` key and the Settings UI are present; the
  `asteroids` HAL and modes 0/1 are documented limitations (§10).
* **#17 — crash/ANR viewer.** `packages_apps_Settings/0001` adds a local
  DropBox reader with bounded entries and explicit sharing; no upload path.
* **#28 — Setup Wizard warning.** `packages_apps_SetupWizard/0001` shows a
  non-blocking warning on the welcome page when verified boot is not green.
* **#23 partial / ENF-1 — native-debugging block.** `frameworks_base/0005` +
  `packages_apps_Settings/0005` add an opt-in global `PR_SET_DUMPABLE` block for
  newly started non-system, non-debuggable, non-profileable app processes. This
  is explicitly **not** GrapheneOS's per-app `GosPackageState`/SELinux policy;
  there is no per-app toggle or denial UI, and root remains exempt.
* **HTS-1 / #33 partial — hardened thread stacks.** `bionic/0001` ports the
  four GrapheneOS pthread layout commits behind the runtime
  `ro.lenos.hardened_thread_stacks` property: randomized `PROT_NONE`
  guard gap, separate `pthread_internal_t` page, and randomized stack top.
  The property is part of the experimental series and the stock mapping
  remains the property-absent path. It is not
  `hardened_malloc`, MTE/BTI, exec spawning or a sandbox, and it is not built
  or booted.
* **#27 — Seedvault prefix.** `packages_apps_Seedvault/0001` ports the
  GrapheneOS internal `app.grapheneos` prefix and prebuilt chunker while
  keeping `com.stevesoltys.seedvault`; backup migration is unverified.
* **OPS-1/OPS-2/OPS-3 — original lenOS OPSEC tools.**
  `experimental/app/LenosOpsec` builds a metadata-scrubbing share target and
  Offline radio tile; `frameworks_base/0004` + `packages_apps_Settings/0003`
  add the opt-in screen-off clipboard wipe. These are not GrapheneOS ports;
  the threat model and limits are in `experimental/docs/opsec.md`.
* **OPS-4 / #8 stage 2 — per-app clipboard access.**
  `packages_apps_Settings/0004` exposes the existing AOSP
  `OP_READ_CLIPBOARD` AppOp for user-installed apps. No framework patch, new
  permission or new AppOp; the global Secure Paste setting still wins.
* **OPS-5 — tracking-parameter scrubber.**
  `experimental/app/LenosOpsec` adds a `text/plain` share target that removes
  known tracking fields from links while preserving functional query
  parameters and fragments. It never opens, resolves or uploads the links.

The experimental series carries 13 patches, 87 source-level tests in
`experimental/tests/` (each sandbox rebuilds the stable base first), 16 build-gate
tests in the main suite, provenance and a post-build verification checklist. The
remaining workstreams (full per-app #23, #30/#31 scopes/2FA, the rest of #33,
#34–#35 runtime/SELinux/browser) are listed with their concrete blockers in
`experimental/STATUS.md`; they are not implemented and are not claimed as
shipped. `experimental/docs/security-review.md` carries the source-level review,
deliberate non-goals and the findings from the patch-order/reset audit.
