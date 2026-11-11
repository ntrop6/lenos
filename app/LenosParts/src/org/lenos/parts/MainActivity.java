/*
 * SPDX-FileCopyrightText: 2026 lenOS
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lenos.parts;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.om.OverlayInfo;
import android.content.om.OverlayManager;
import android.database.Cursor;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Process;
import android.provider.Settings;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * lenOS personalization shell.
 *
 * <p>Everything here is applied on-device: preinstalled SystemUI resource
 * overlays are toggled through {@link OverlayManager}, and motion presets write
 * the standard Android animation-scale settings. The app has no network
 * permission and no account or cloud code path.</p>
 */
public class MainActivity extends Activity {
    private static final String SYSTEMUI_PACKAGE = "com.android.systemui";
    private static final String STATUS_BAR_ACTION =
            "org.lineageos.lineageparts.STATUS_BAR_SETTINGS";

    private static final String[] THEME_PACKAGES = {
            "org.lenos.theme.ember.systemui",
            "org.lenos.theme.mint.systemui",
            "org.lenos.theme.mono.systemui",
    };
    private static final String[] FRAMEWORK_PACKAGES = {
            "org.lenos.theme.ember.frameworks",
            "org.lenos.theme.mint.frameworks",
            "org.lenos.theme.mono.frameworks",
    };
    private static final String[] THEME_NAMES = {
            "Ember",
            "Mint",
            "Mono",
    };
    private static final String[] THEME_DESCRIPTIONS = {
            "Warm amber accents for notifications and Quick Settings.",
            "Cool green accents for notifications and Quick Settings.",
            "Neutral graphite accents for notifications and Quick Settings.",
    };

    // Monet reads these keys from Settings.Secure and builds its own fabricated
    // framework overlays from the seed. Seeding a theme is therefore more
    // reliable than relying on manifest priority alone, which is advisory for
    // unconfigured overlays on Android 17.
    private static final String THEME_OVERLAY_SETTING =
            Settings.Secure.THEME_CUSTOMIZATION_OVERLAY_PACKAGES;
    private static final String CATEGORY_SYSTEM_PALETTE =
            "android.theme.customization.system_palette";
    private static final String CATEGORY_THEME_STYLE =
            "android.theme.customization.theme_style";
    private static final String CATEGORY_COLOR_SOURCE =
            "android.theme.customization.color_source";
    private static final String COLOR_SOURCE_PRESET = "preset";
    private static final String[] THEME_SEEDS = {
            "C96A1E",
            "2FA37C",
            "6B6F76",
    };
    private static final String[] THEME_STYLES = {
            "VIBRANT",
            "TONAL_SPOT",
            "MONOCHROMATIC",
    };
    private static final String PREFS = "lenos_parts";
    private static final String PREF_OWNED_PALETTE = "monet_owned_palette";
    private static final String PREF_OWNED_STYLE = "monet_owned_style";
    private static final String PREF_OWNED_SOURCE = "monet_owned_source";
    private static final String PREF_BACKUP_PALETTE = "monet_backup_palette";
    private static final String PREF_BACKUP_STYLE = "monet_backup_style";
    private static final String PREF_BACKUP_SOURCE = "monet_backup_source";
    private static final String PREF_BACKUP_PRESENT = "monet_backup_present";

    private static final String[] MOTION_LABELS = {
            "System default (1.0x)",
            "Relaxed (1.25x)",
            "Fast (0.75x)",
            "Very fast (0.5x)",
            "Off (0x)",
    };
    private static final float[] MOTION_VALUES = {
            1.0f, 1.25f, 0.75f, 0.5f, 0.0f,
    };

    private static final String[] QS_COLUMNS_LABELS = {
            "4 columns (default)",
            "3 columns",
            "5 columns",
    };
    private static final String[] QS_COLUMNS_PACKAGES = {
            null,
            "org.lenos.qs.columns3",
            "org.lenos.qs.columns5",
    };
    private static final String[] QS_ROWS_LABELS = {
            "4 rows (default)",
            "3 rows",
            "5 rows",
    };
    private static final String[] QS_ROWS_PACKAGES = {
            null,
            "org.lenos.qs.rows3",
            "org.lenos.qs.rows5",
    };

    // Notification styling is independent of the theme packs: the packs no
    // longer override the notification radii, so these overlays are the only
    // writers and cannot race them for the same resource on Android 17.
    private static final String[] NOTIFY_CORNER_LABELS = {
            "System default (28 dp)",
            "Round (24 dp)",
            "Compact (16 dp)",
            "Square (6 dp)",
    };
    private static final String[] NOTIFY_CORNER_PACKAGES = {
            null,
            "org.lenos.notify.corners.round",
            "org.lenos.notify.corners.compact",
            "org.lenos.notify.corners.square",
    };
    private static final String NOTIFY_DIVIDERS_PACKAGE =
            "org.lenos.notify.dividers.hidden";

    // LineageOS 24.0 ships the Launcher3 fork as com.android.launcher3. Its
    // exported grid-control provider is guarded by the signature-level
    // GRID_CONTROL permission, not BIND_WALLPAPER. LenosParts is platform
    // signed, so it can use the narrow launcher permission instead.
    private static final String LAUNCHER_PACKAGE = "com.android.launcher3";
    private static final String LAUNCHER_GRID_AUTHORITY =
            "com.android.launcher3.grid_control";
    private static final String LAUNCHER_LIST_OPTIONS = "/list_options";
    private static final String LAUNCHER_DEFAULT_GRID = "/default_grid";
    private static final String LAUNCHER_SHAPE_OPTIONS = "/shape_options";
    private static final String LAUNCHER_SET_SHAPE = "/shape";
    private static final String LAUNCHER_GET_ICON_THEMED = "/get_icon_themed";
    private static final String LAUNCHER_SET_ICON_THEMED = "/set_icon_themed";

    private static final int BG = Color.parseColor("#111318");
    private static final int CARD = Color.parseColor("#1C1F26");
    private static final int TEXT = Color.parseColor("#E8EAED");
    private static final int MUTED = Color.parseColor("#9AA0A6");
    private static final int ACCENT = Color.parseColor("#FFB26A");
    private static final int STROKE = Color.parseColor("#3C4043");

    private RadioGroup themeGroup;
    private Spinner animatorSpinner;
    private Spinner transitionSpinner;
    private Spinner windowSpinner;
    private Spinner qsColumnsSpinner;
    private Spinner qsRowsSpinner;
    private Spinner notifyCornersSpinner;
    private CheckBox notifyDividersCheck;
    private Spinner launcherGridSpinner;
    private TextView launcherGridNote;
    private Spinner launcherShapeSpinner;
    private TextView launcherShapeNote;
    private CheckBox launcherThemedIcons;
    private final List<String> launcherGridNames = new ArrayList<>();
    private final List<String> launcherShapeKeys = new ArrayList<>();
    private String launcherGridCurrent;
    private String launcherShapeCurrent;
    private int launcherGridRequest;
    private int launcherShapeRequest;
    private int launcherThemedRequest;
    private boolean suppressTheme;
    private boolean suppressMotion;
    private boolean suppressQs;
    private boolean suppressNotify;
    private boolean suppressLauncher;
    private boolean suppressLauncherShape;
    private boolean suppressLauncherThemed;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshThemeSelection();
        // Motion spinners are initialized from the current scales once. Do
        // not re-select them on every resume: a non-preset value set through
        // Developer Options would display as 1.0x, and a queued selection
        // callback could then overwrite it.
        refreshQsSelection();
        refreshNotifySelection();
        refreshLauncherGrid();
        refreshLauncherShapes();
        refreshLauncherThemedIcons();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BG);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(24), dp(18), dp(36));
        scroll.addView(root);

        root.addView(text("lenOS personalization", 28, TEXT, true));
        root.addView(text(
                "Local-only appearance controls. No network, no account, no telemetry.",
                13, MUTED, false));

        root.addView(section("Theme packs"));
        root.addView(text(
                "These packs change system accent colors, SystemUI notification "
                        + "and Quick Settings colors, Quick Settings corners and "
                        + "spacing. Notification corners are controlled "
                        + "separately below. The selected pack overrides the "
                        + "wallpaper-generated accent while it is enabled.",
                12, MUTED, false));

        themeGroup = new RadioGroup(this);
        themeGroup.setOrientation(RadioGroup.VERTICAL);
        addThemeChoice(themeGroup, null, "Stock",
                "Keep the LineageOS defaults.");
        for (int i = 0; i < THEME_PACKAGES.length; i++) {
            addThemeChoice(themeGroup, THEME_PACKAGES[i],
                    THEME_NAMES[i], THEME_DESCRIPTIONS[i]);
        }
        themeGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressTheme || checkedId == View.NO_ID) {
                return;
            }
            View checked = group.findViewById(checkedId);
            Object tag = checked == null ? null : checked.getTag();
            applyTheme(tag instanceof String ? (String) tag : null);
        });
        root.addView(card(themeGroup));

        root.addView(section("Motion"));
        root.addView(text(
                "Each animation surface has its own scale. 1.0x is the system "
                        + "default; 0x disables that surface. Accessibility and "
                        + "battery saver can still override the scales.",
                12, MUTED, false));
        LinearLayout motionCard = new LinearLayout(this);
        motionCard.setOrientation(LinearLayout.VERTICAL);
        animatorSpinner = motionSpinner("System animations",
                Settings.Global.ANIMATOR_DURATION_SCALE, motionCard);
        transitionSpinner = motionSpinner("Transition animations",
                Settings.Global.TRANSITION_ANIMATION_SCALE, motionCard);
        windowSpinner = motionSpinner("Window animations",
                Settings.Global.WINDOW_ANIMATION_SCALE, motionCard);
        root.addView(card(motionCard));

        Button resetButton = button("Reset all to 1.0x");
        resetButton.setOnClickListener(v -> resetMotion());
        root.addView(resetButton);

        root.addView(section("Quick Settings layout"));
        root.addView(text(
                "Changes the number of tiles per row and the rows in the expanded "
                        + "paginated grid. The stock layout is four columns and four "
                        + "rows; SystemUI may restart or need a reboot to pick up the "
                        + "new grid. A dual-shade infinite grid scrolls instead and "
                        + "ignores the row choice.",
                12, MUTED, false));
        LinearLayout qsCard = new LinearLayout(this);
        qsCard.setOrientation(LinearLayout.VERTICAL);
        suppressQs = true;
        qsColumnsSpinner = qsSpinner(QS_COLUMNS_LABELS, true);
        qsRowsSpinner = qsSpinner(QS_ROWS_LABELS, false);
        qsCard.addView(qsColumnsSpinner);
        qsCard.addView(qsRowsSpinner);
        root.addView(card(qsCard));
        suppressQs = false;

        root.addView(section("Notifications"));
        root.addView(text(
                "The corner choice applies to notifications in the shade. "
                        + "\"Hide dividers\" makes the lines between grouped "
                        + "notifications transparent without changing their "
                        + "layout or spacing. Both choices are independent of "
                        + "the selected theme pack.",
                12, MUTED, false));
        LinearLayout notifyCard = new LinearLayout(this);
        notifyCard.setOrientation(LinearLayout.VERTICAL);
        notifyCornersSpinner = new Spinner(this);
        ArrayAdapter<String> notifyAdapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item,
                NOTIFY_CORNER_LABELS);
        notifyCornersSpinner.setAdapter(notifyAdapter);
        // Pick the current state before attaching the listener so the first
        // layout pass cannot mistake the default position for a user choice.
        suppressNotify = true;
        notifyCornersSpinner.setSelection(
                enabledOption(NOTIFY_CORNER_PACKAGES, 0));
        notifyCornersSpinner.setOnItemSelectedListener(
                new AdapterView.OnItemSelectedListener() {
                    @Override
                    public void onItemSelected(AdapterView<?> parent, View view,
                            int position, long id) {
                        if (suppressNotify) {
                            return;
                        }
                        applyNotifyCorners(position);
                    }

                    @Override
                    public void onNothingSelected(AdapterView<?> parent) {
                    }
                });
        notifyCard.addView(notifyCornersSpinner);
        notifyDividersCheck = new CheckBox(this);
        notifyDividersCheck.setText(
                "Hide dividers between grouped notifications");
        notifyDividersCheck.setTextColor(TEXT);
        notifyDividersCheck.setTextSize(14);
        notifyDividersCheck.setPadding(0, dp(10), 0, 0);
        notifyDividersCheck.setOnCheckedChangeListener(
                (buttonView, isChecked) -> {
                    if (suppressNotify) {
                        return;
                    }
                    applyNotifyDividers(isChecked);
                });
        notifyCard.addView(notifyDividersCheck);
        root.addView(card(notifyCard));
        suppressNotify = false;

        root.addView(section("Launcher"));
        root.addView(text(
                "The Home screen and All apps grid, icon shape and themed "
                        + "icons are read from the launcher's own provider. "
                        + "Grid and shape changes apply immediately; "
                        + "notification dots and the remaining Home options "
                        + "stay in launcher settings.",
                12, MUTED, false));
        launcherGridSpinner = new Spinner(this);
        launcherGridSpinner.setEnabled(false);
        launcherGridSpinner.setOnItemSelectedListener(
                new AdapterView.OnItemSelectedListener() {
                    @Override
                    public void onItemSelected(AdapterView<?> parent, View view,
                            int position, long id) {
                        if (suppressLauncher) {
                            return;
                        }
                        applyLauncherGrid(position);
                    }

                    @Override
                    public void onNothingSelected(AdapterView<?> parent) {
                    }
                });
        launcherGridNote = text("Reading launcher grid options\u2026",
                12, MUTED, false);
        LinearLayout launcherCard = new LinearLayout(this);
        launcherCard.setOrientation(LinearLayout.VERTICAL);
        launcherCard.addView(launcherGridSpinner);
        launcherCard.addView(launcherGridNote);

        TextView shapeTitle = text("Icon shape", 14, TEXT, true);
        shapeTitle.setPadding(0, dp(18), 0, 0);
        launcherCard.addView(shapeTitle);
        launcherShapeSpinner = new Spinner(this);
        launcherShapeSpinner.setEnabled(false);
        launcherShapeSpinner.setOnItemSelectedListener(
                new AdapterView.OnItemSelectedListener() {
                    @Override
                    public void onItemSelected(AdapterView<?> parent, View view,
                            int position, long id) {
                        if (suppressLauncherShape) {
                            return;
                        }
                        applyLauncherShape(position);
                    }

                    @Override
                    public void onNothingSelected(AdapterView<?> parent) {
                    }
                });
        launcherShapeNote = text("Reading icon shapes\u2026", 12, MUTED, false);
        launcherCard.addView(launcherShapeSpinner);
        launcherCard.addView(launcherShapeNote);

        launcherThemedIcons = new CheckBox(this);
        launcherThemedIcons.setText("Themed icons");
        launcherThemedIcons.setTextColor(TEXT);
        launcherThemedIcons.setTextSize(14);
        launcherThemedIcons.setEnabled(false);
        launcherThemedIcons.setPadding(0, dp(12), 0, 0);
        launcherThemedIcons.setOnCheckedChangeListener(
                (buttonView, isChecked) -> {
                    if (suppressLauncherThemed) {
                        return;
                    }
                    applyLauncherThemedIcons(isChecked);
                });
        launcherCard.addView(launcherThemedIcons);
        root.addView(card(launcherCard));

        Button launcherSettings = button("Open launcher settings");
        launcherSettings.setOnClickListener(v -> openLauncherSettings());
        root.addView(launcherSettings);

        root.addView(section("Status bar and Quick Settings"));
        root.addView(text(
                "LineageOS already provides clock position, seconds, battery style, "
                        + "network traffic and brightness slider controls. Open the "
                        + "stock panel to change them; lenOS does not duplicate those "
                        + "settings.",
                12, MUTED, false));
        Button statusBar = button("Open status bar settings");
        statusBar.setOnClickListener(v -> openStatusBarSettings());
        root.addView(statusBar);

        root.addView(section("About this build"));
        root.addView(text(
                "lenOS personalization is a local-only layer. It has no INTERNET "
                        + "permission, no Google services and no analytics. Theme packs "
                        + "are preinstalled on the product partition; nothing is "
                        + "downloaded.",
                12, MUTED, false));
        root.addView(text("Source-complete, not yet device-validated.",
                12, ACCENT, true));

        setContentView(scroll);
    }

    private void addThemeChoice(RadioGroup group, String pkg, String name,
            String description) {
        RadioButton button = new RadioButton(this);
        button.setText(name + " \u2014 " + description);
        button.setTextColor(TEXT);
        button.setTextSize(14);
        button.setTag(pkg);
        button.setPadding(0, dp(8), 0, dp(8));
        group.addView(button, new RadioGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
    }

    private void refreshThemeSelection() {
        String current = currentTheme();
        suppressTheme = true;
        for (int i = 0; i < themeGroup.getChildCount(); i++) {
            View child = themeGroup.getChildAt(i);
            Object tag = child.getTag();
            boolean checked = current == null ? tag == null : current.equals(tag);
            ((RadioButton) child).setChecked(checked);
        }
        suppressTheme = false;
    }

    private String currentTheme() {
        try {
            OverlayManager manager = getSystemService(OverlayManager.class);
            if (manager == null) {
                return null;
            }
            // The two-argument overload talks to the system OverlayManager
            // service. Same-user reads need no cross-user permission; the
            // @RequiresPermission annotation only covers the cross-user case.
            for (OverlayInfo info : manager.getOverlayInfosForTarget(
                    SYSTEMUI_PACKAGE, Process.myUserHandle())) {
                if (info.isEnabled() && isKnownTheme(info.getPackageName())) {
                    return info.getPackageName();
                }
            }
        } catch (Throwable ignored) {
            // A missing OverlayManager or an uninstalled pack is not fatal; the
            // stock selection stays visible.
        }
        return null;
    }

    private static boolean isKnownTheme(String pkg) {
        for (String known : THEME_PACKAGES) {
            if (known.equals(pkg)) {
                return true;
            }
        }
        return false;
    }

    private void applyTheme(String selected) {
        try {
            OverlayManager manager = getSystemService(OverlayManager.class);
            if (manager == null) {
                throw new IllegalStateException("OverlayManager unavailable");
            }
            int selectedIndex = themeIndex(selected);
            Set<String> systemUiInstalled = installedPackages(manager, SYSTEMUI_PACKAGE);
            Set<String> frameworkInstalled = installedPackages(manager, "android");
            for (int i = 0; i < THEME_PACKAGES.length; i++) {
                boolean enable = i == selectedIndex;
                if (systemUiInstalled.contains(THEME_PACKAGES[i])) {
                    manager.setEnabled(THEME_PACKAGES[i], enable,
                            Process.myUserHandle());
                }
            }
            boolean frameworkFailure = false;
            for (int i = 0; i < FRAMEWORK_PACKAGES.length; i++) {
                if (!frameworkInstalled.contains(FRAMEWORK_PACKAGES[i])) {
                    frameworkFailure |= i == selectedIndex;
                    continue;
                }
                try {
                    manager.setEnabled(FRAMEWORK_PACKAGES[i], i == selectedIndex,
                            Process.myUserHandle());
                } catch (Throwable t) {
                    frameworkFailure = true;
                }
            }
            boolean seedApplied = applyMonetSeed(selectedIndex);
            if (frameworkFailure && !seedApplied) {
                Toast.makeText(this,
                        "SystemUI theme applied; the system accent could not be changed",
                        Toast.LENGTH_LONG).show();
            } else {
                Toast.makeText(this,
                        selected == null ? "Stock appearance restored"
                                : "Theme pack applied",
                        Toast.LENGTH_SHORT).show();
            }
            refreshThemeSelection();
        } catch (Throwable t) {
            Toast.makeText(this, "Could not apply theme: " + t.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    /**
     * Seeds Monet with the pack's accent and style through the secure theme
     * setting. This is the reliable path on Android 17: the controller builds
     * fabricated overlays after boot, so an unconfigured preinstalled RRO
     * cannot outrank them through manifest priority alone.
     *
     * @return true when the setting was written (or when stock needed no
     *         restore), false when the setting could not be changed.
     */
    private boolean applyMonetSeed(int selectedIndex) {
        try {
            if (selectedIndex < 0) {
                return restoreMonetSeed();
            }
            SharedPreferences prefs = prefs();
            String current = Settings.Secure.getString(getContentResolver(),
                    THEME_OVERLAY_SETTING);
            JSONObject object = current == null || current.isEmpty()
                    ? new JSONObject() : new JSONObject(current);
            backupMonetValue(object, CATEGORY_SYSTEM_PALETTE,
                    PREF_OWNED_PALETTE, PREF_BACKUP_PALETTE);
            backupMonetValue(object, CATEGORY_THEME_STYLE,
                    PREF_OWNED_STYLE, PREF_BACKUP_STYLE);
            backupMonetValue(object, CATEGORY_COLOR_SOURCE,
                    PREF_OWNED_SOURCE, PREF_BACKUP_SOURCE);
            object.put(CATEGORY_SYSTEM_PALETTE, THEME_SEEDS[selectedIndex]);
            object.put(CATEGORY_THEME_STYLE, THEME_STYLES[selectedIndex]);
            object.put(CATEGORY_COLOR_SOURCE, COLOR_SOURCE_PRESET);
            Settings.Secure.putString(getContentResolver(),
                    THEME_OVERLAY_SETTING, object.toString());
            prefs.edit()
                    .putString(PREF_OWNED_PALETTE, THEME_SEEDS[selectedIndex])
                    .putString(PREF_OWNED_STYLE, THEME_STYLES[selectedIndex])
                    .putString(PREF_OWNED_SOURCE, COLOR_SOURCE_PRESET)
                    .putBoolean(PREF_BACKUP_PRESENT, true)
                    .apply();
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    /**
     * Restores whatever values Monet had before the first pack was applied.
     * A key is only restored while it still holds the value this app wrote, so
     * a later wallpaper/preset choice is never overwritten.
     */
    private boolean restoreMonetSeed() {
        try {
            SharedPreferences prefs = prefs();
            if (!prefs.getBoolean(PREF_BACKUP_PRESENT, false)) {
                return true;
            }
            String current = Settings.Secure.getString(getContentResolver(),
                    THEME_OVERLAY_SETTING);
            JSONObject object = current == null || current.isEmpty()
                    ? new JSONObject() : new JSONObject(current);
            restoreMonetValue(object, CATEGORY_SYSTEM_PALETTE,
                    PREF_OWNED_PALETTE, PREF_BACKUP_PALETTE);
            restoreMonetValue(object, CATEGORY_THEME_STYLE,
                    PREF_OWNED_STYLE, PREF_BACKUP_STYLE);
            restoreMonetValue(object, CATEGORY_COLOR_SOURCE,
                    PREF_OWNED_SOURCE, PREF_BACKUP_SOURCE);
            Settings.Secure.putString(getContentResolver(),
                    THEME_OVERLAY_SETTING, object.toString());
            prefs.edit()
                    .remove(PREF_OWNED_PALETTE)
                    .remove(PREF_OWNED_STYLE)
                    .remove(PREF_OWNED_SOURCE)
                    .remove(PREF_BACKUP_PALETTE)
                    .remove(PREF_BACKUP_STYLE)
                    .remove(PREF_BACKUP_SOURCE)
                    .remove(PREF_BACKUP_PRESENT)
                    .apply();
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    private void backupMonetValue(JSONObject object, String category,
            String ownedKey, String backupKey) {
        SharedPreferences prefs = prefs();
        String current = object.has(category)
                ? object.optString(category, null) : null;
        String owned = prefs.getString(ownedKey, null);
        if (owned != null && owned.equals(current)) {
            // This is still the value we wrote; keep the original backup.
            return;
        }
        SharedPreferences.Editor editor = prefs.edit();
        if (current == null) {
            editor.remove(backupKey);
        } else {
            editor.putString(backupKey, current);
        }
        editor.apply();
    }

    private void restoreMonetValue(JSONObject object, String category,
            String ownedKey, String backupKey) {
        SharedPreferences prefs = prefs();
        String current = object.has(category)
                ? object.optString(category, null) : null;
        String owned = prefs.getString(ownedKey, null);
        if (owned == null || !owned.equals(current)) {
            // The user or the system changed this value after we wrote it.
            return;
        }
        String backup = prefs.getString(backupKey, null);
        try {
            if (backup == null) {
                object.remove(category);
            } else {
                object.put(category, backup);
            }
        } catch (Throwable ignored) {
            // A malformed key must not abort restoring the remaining keys.
        }
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private static int themeIndex(String pkg) {
        if (pkg == null) {
            return -1;
        }
        for (int i = 0; i < THEME_PACKAGES.length; i++) {
            if (THEME_PACKAGES[i].equals(pkg)) {
                return i;
            }
        }
        return -1;
    }

    private static Set<String> installedPackages(OverlayManager manager,
            String targetPackage) {
        Set<String> installed = new HashSet<>();
        for (OverlayInfo info : manager.getOverlayInfosForTarget(
                targetPackage, Process.myUserHandle())) {
            installed.add(info.getPackageName());
        }
        return installed;
    }

    private Spinner motionSpinner(String label, String key,
            LinearLayout card) {
        TextView title = text(label, 14, TEXT, true);
        title.setPadding(0, dp(14), 0, 0);
        card.addView(title);
        Spinner spinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item, MOTION_LABELS);
        spinner.setAdapter(adapter);
        // Match the existing scale before attaching the listener; otherwise
        // the first layout pass could overwrite the user's current choice.
        spinner.setSelection(currentMotionIndex(key));
        spinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view,
                    int position, long id) {
                if (suppressMotion) {
                    return;
                }
                applyMotion(key, MOTION_VALUES[position]);
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
        card.addView(spinner);
        return spinner;
    }

    private void refreshMotionSelection() {
        suppressMotion = true;
        animatorSpinner.setSelection(currentMotionIndex(
                Settings.Global.ANIMATOR_DURATION_SCALE));
        transitionSpinner.setSelection(currentMotionIndex(
                Settings.Global.TRANSITION_ANIMATION_SCALE));
        windowSpinner.setSelection(currentMotionIndex(
                Settings.Global.WINDOW_ANIMATION_SCALE));
        suppressMotion = false;
    }

    private int currentMotionIndex(String key) {
        float current = Settings.Global.getFloat(getContentResolver(), key,
                1.0f);
        for (int i = 0; i < MOTION_VALUES.length; i++) {
            if (Math.abs(MOTION_VALUES[i] - current) < 0.01f) {
                return i;
            }
        }
        return 0;
    }

    private void applyMotion(String key, float scale) {
        try {
            float current = Settings.Global.getFloat(getContentResolver(), key,
                    1.0f);
            if (Math.abs(current - scale) < 0.01f) {
                // Already at this value; do not rewrite the setting or toast.
                return;
            }
            Settings.Global.putFloat(getContentResolver(), key, scale);
            Toast.makeText(this,
                    motionLabel(key) + " set to " + scale + "x",
                    Toast.LENGTH_SHORT).show();
        } catch (Throwable t) {
            Toast.makeText(this,
                    "Could not change animation scale: " + t.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private void resetMotion() {
        try {
            Settings.Global.putFloat(getContentResolver(),
                    Settings.Global.ANIMATOR_DURATION_SCALE, 1.0f);
            Settings.Global.putFloat(getContentResolver(),
                    Settings.Global.TRANSITION_ANIMATION_SCALE, 1.0f);
            Settings.Global.putFloat(getContentResolver(),
                    Settings.Global.WINDOW_ANIMATION_SCALE, 1.0f);
            Toast.makeText(this, "Animation scales reset to 1.0x",
                    Toast.LENGTH_SHORT).show();
            refreshMotionSelection();
        } catch (Throwable t) {
            Toast.makeText(this,
                    "Could not reset animation scales: " + t.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private static String motionLabel(String key) {
        if (Settings.Global.ANIMATOR_DURATION_SCALE.equals(key)) {
            return "System animations";
        }
        if (Settings.Global.TRANSITION_ANIMATION_SCALE.equals(key)) {
            return "Transition animations";
        }
        return "Window animations";
    }

    private Spinner qsSpinner(String[] labels, boolean columns) {
        Spinner spinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item, labels);
        spinner.setAdapter(adapter);
        // Pick the current state before attaching the listener so the first
        // layout pass cannot mistake the default position for a user choice.
        spinner.setSelection(enabledOption(
                columns ? QS_COLUMNS_PACKAGES : QS_ROWS_PACKAGES, 0));
        spinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view,
                    int position, long id) {
                if (suppressQs) {
                    return;
                }
                applyQsLayout(columns, position);
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
        return spinner;
    }

    private void refreshQsSelection() {
        suppressQs = true;
        qsColumnsSpinner.setSelection(
                enabledOption(QS_COLUMNS_PACKAGES, 0));
        qsRowsSpinner.setSelection(enabledOption(QS_ROWS_PACKAGES, 0));
        suppressQs = false;
    }

    private int enabledOption(String[] packages, int defaultIndex) {
        try {
            OverlayManager manager = getSystemService(OverlayManager.class);
            if (manager == null) {
                return defaultIndex;
            }
            Set<String> enabled = new HashSet<>();
            for (OverlayInfo info : manager.getOverlayInfosForTarget(
                    SYSTEMUI_PACKAGE, Process.myUserHandle())) {
                if (info.isEnabled()) {
                    enabled.add(info.getPackageName());
                }
            }
            for (int i = 0; i < packages.length; i++) {
                if (packages[i] != null && enabled.contains(packages[i])) {
                    return i;
                }
            }
        } catch (Throwable ignored) {
            // Keep the default visible if the overlay service is unavailable.
        }
        return defaultIndex;
    }

    private void applyQsLayout(boolean columns, int selectedIndex) {
        try {
            OverlayManager manager = getSystemService(OverlayManager.class);
            if (manager == null) {
                throw new IllegalStateException("OverlayManager unavailable");
            }
            String[] packages = columns ? QS_COLUMNS_PACKAGES : QS_ROWS_PACKAGES;
            if (selectedIndex == enabledOption(packages, 0)) {
                // The first layout pass can report the already-current
                // selection; it must not toggle an overlay.
                return;
            }
            Set<String> installed = installedPackages(manager, SYSTEMUI_PACKAGE);
            for (int i = 0; i < packages.length; i++) {
                if (packages[i] == null || !installed.contains(packages[i])) {
                    continue;
                }
                manager.setEnabled(packages[i], i == selectedIndex,
                        Process.myUserHandle());
            }
            Toast.makeText(this,
                    "Quick Settings layout updated",
                    Toast.LENGTH_SHORT).show();
            refreshQsSelection();
        } catch (Throwable t) {
            Toast.makeText(this,
                    "Could not change the Quick Settings layout: " + t.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private void refreshNotifySelection() {
        suppressNotify = true;
        notifyCornersSpinner.setSelection(
                enabledOption(NOTIFY_CORNER_PACKAGES, 0));
        notifyDividersCheck.setChecked(
                enabledOption(new String[]{NOTIFY_DIVIDERS_PACKAGE}, -1) >= 0);
        suppressNotify = false;
    }

    private void applyNotifyCorners(int selectedIndex) {
        try {
            OverlayManager manager = getSystemService(OverlayManager.class);
            if (manager == null) {
                throw new IllegalStateException("OverlayManager unavailable");
            }
            if (selectedIndex == enabledOption(NOTIFY_CORNER_PACKAGES, 0)) {
                // The first layout pass can report the already-current
                // selection; it must not toggle an overlay.
                return;
            }
            Set<String> installed = installedPackages(manager, SYSTEMUI_PACKAGE);
            for (int i = 0; i < NOTIFY_CORNER_PACKAGES.length; i++) {
                String pkg = NOTIFY_CORNER_PACKAGES[i];
                if (pkg == null || !installed.contains(pkg)) {
                    continue;
                }
                manager.setEnabled(pkg, i == selectedIndex,
                        Process.myUserHandle());
            }
            Toast.makeText(this, "Notification corners updated",
                    Toast.LENGTH_SHORT).show();
            refreshNotifySelection();
        } catch (Throwable t) {
            Toast.makeText(this,
                    "Could not change notification corners: " + t.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private void applyNotifyDividers(boolean enabled) {
        try {
            OverlayManager manager = getSystemService(OverlayManager.class);
            if (manager == null) {
                throw new IllegalStateException("OverlayManager unavailable");
            }
            if (!installedPackages(manager, SYSTEMUI_PACKAGE)
                    .contains(NOTIFY_DIVIDERS_PACKAGE)) {
                throw new IllegalStateException("overlay not installed");
            }
            if (enabled == (enabledOption(
                    new String[]{NOTIFY_DIVIDERS_PACKAGE}, -1) >= 0)) {
                return;
            }
            manager.setEnabled(NOTIFY_DIVIDERS_PACKAGE, enabled,
                    Process.myUserHandle());
            Toast.makeText(this,
                    enabled ? "Notification dividers hidden"
                            : "Notification dividers restored",
                    Toast.LENGTH_SHORT).show();
            refreshNotifySelection();
        } catch (Throwable t) {
            Toast.makeText(this,
                    "Could not change notification dividers: "
                            + t.getMessage(),
                    Toast.LENGTH_LONG).show();
            refreshNotifySelection();
        }
    }

    /**
     * Reads the launcher's grid choices off the UI thread. The provider may
     * start the launcher process, so a synchronous query could block the
     * dashboard on first open.
     */
    private void refreshLauncherGrid() {
        if (launcherGridSpinner == null) {
            return;
        }
        launcherGridSpinner.setEnabled(false);
        final int request = ++launcherGridRequest;
        new Thread(() -> {
            List<String> names = new ArrayList<>();
            List<String> labels = new ArrayList<>();
            int selected = -1;
            try (Cursor cursor = getContentResolver().query(
                    launcherProviderUri(LAUNCHER_LIST_OPTIONS),
                    new String[]{"name", "grid_title", "rows", "cols",
                            "is_default"},
                    null, null, null)) {
                if (cursor != null) {
                    int nameIndex = cursor.getColumnIndexOrThrow("name");
                    int titleIndex = cursor.getColumnIndex("grid_title");
                    int rowsIndex = cursor.getColumnIndexOrThrow("rows");
                    int columnsIndex = cursor.getColumnIndexOrThrow("cols");
                    int defaultIndex =
                            cursor.getColumnIndexOrThrow("is_default");
                    while (cursor.moveToNext()) {
                        String name = cursor.getString(nameIndex);
                        if (name == null || name.isEmpty()) {
                            continue;
                        }
                        String title = titleIndex >= 0
                                ? cursor.getString(titleIndex) : null;
                        int rows = cursor.getInt(rowsIndex);
                        int columns = cursor.getInt(columnsIndex);
                        boolean current = cursor.getInt(defaultIndex) != 0;
                        names.add(name);
                        labels.add(launcherGridLabel(title, columns, rows));
                        if (current) {
                            selected = names.size() - 1;
                        }
                    }
                }
            } catch (Throwable ignored) {
                // A missing provider, a denied permission or a launcher
                // without grid support all fall back to the settings entry.
            }
            final List<String> resultNames = names;
            final List<String> resultLabels = labels;
            final int resultSelected = selected;
            runOnUiThread(() -> {
                if (request != launcherGridRequest || isFinishing()
                        || isDestroyed()) {
                    return;
                }
                showLauncherGrid(resultNames, resultLabels, resultSelected);
            });
        }, "lenos-launcher-grid-query").start();
    }

    private void showLauncherGrid(List<String> names, List<String> labels,
            int selected) {
        launcherGridNames.clear();
        launcherGridNames.addAll(names);
        suppressLauncher = true;
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item,
                labels.isEmpty()
                        ? Collections.singletonList(
                                "Grid control not available")
                        : labels);
        launcherGridSpinner.setAdapter(adapter);
        int shown = selected >= 0 && selected < names.size() ? selected : 0;
        launcherGridSpinner.setSelection(shown);
        // Treat the visible option as current so the initial selection
        // callback cannot write a grid the user did not choose.
        launcherGridCurrent = names.isEmpty() ? null : names.get(shown);
        launcherGridSpinner.setEnabled(!names.isEmpty());
        suppressLauncher = false;
        if (names.isEmpty()) {
            launcherGridNote.setText(
                    "This launcher build does not expose grid control to "
                            + "lenOS. Use launcher settings below; it still "
                            + "contains the launcher's own grid picker.");
        } else {
            launcherGridNote.setText(
                    "Choosing a grid applies it immediately. Launcher settings "
                            + "below also covers icon shape, themed icons and "
                            + "notification dots.");
        }
    }

    private void applyLauncherGrid(int position) {
        if (position < 0 || position >= launcherGridNames.size()) {
            return;
        }
        String name = launcherGridNames.get(position);
        if (name.equals(launcherGridCurrent)) {
            return;
        }
        launcherGridSpinner.setEnabled(false);
        new Thread(() -> {
            int updated = 0;
            String failure = null;
            try {
                ContentValues values = new ContentValues();
                values.put("name", name);
                updated = getContentResolver().update(
                        launcherProviderUri(LAUNCHER_DEFAULT_GRID), values,
                        null, null);
            } catch (Throwable t) {
                failure = t.getMessage();
            }
            final int result = updated;
            final String message = failure;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                if (result > 0) {
                    launcherGridCurrent = name;
                    Toast.makeText(this, "Launcher grid updated",
                            Toast.LENGTH_SHORT).show();
                    refreshLauncherGrid();
                } else {
                    Toast.makeText(this,
                            message == null
                                    ? "This launcher did not accept the grid "
                                            + "change"
                                    : "Could not change the launcher grid: "
                                            + message,
                            Toast.LENGTH_LONG).show();
                    // Put the spinner back on the grid the launcher actually
                    // reports instead of leaving the rejected choice visible.
                    refreshLauncherGrid();
                }
            });
        }, "lenos-launcher-grid-apply").start();
    }

    private static String launcherGridLabel(String title, int columns,
            int rows) {
        String size = columns + " \u00d7 " + rows;
        if (title == null || title.trim().isEmpty()) {
            return size;
        }
        return title.trim();
    }

    /**
     * Reads the launcher's icon-shape choices off the UI thread. The provider
     * exposes the same list the stock launcher settings screen uses.
     */
    private void refreshLauncherShapes() {
        if (launcherShapeSpinner == null) {
            return;
        }
        launcherShapeSpinner.setEnabled(false);
        final int request = ++launcherShapeRequest;
        new Thread(() -> {
            List<String> keys = new ArrayList<>();
            List<String> labels = new ArrayList<>();
            int selected = -1;
            try (Cursor cursor = getContentResolver().query(
                    launcherProviderUri(LAUNCHER_SHAPE_OPTIONS),
                    new String[]{"shape_key", "shape_title", "is_default"},
                    null, null, null)) {
                if (cursor != null) {
                    int keyIndex = cursor.getColumnIndexOrThrow("shape_key");
                    int titleIndex = cursor.getColumnIndex("shape_title");
                    int defaultIndex =
                            cursor.getColumnIndexOrThrow("is_default");
                    while (cursor.moveToNext()) {
                        String key = cursor.getString(keyIndex);
                        if (key == null || key.isEmpty()) {
                            continue;
                        }
                        String title = titleIndex >= 0
                                ? cursor.getString(titleIndex) : null;
                        boolean current = cursor.getInt(defaultIndex) != 0;
                        keys.add(key);
                        labels.add(launcherShapeLabel(title, key));
                        if (current) {
                            selected = keys.size() - 1;
                        }
                    }
                }
            } catch (Throwable ignored) {
                // Fall back to the stock launcher settings screen.
            }
            final List<String> resultKeys = keys;
            final List<String> resultLabels = labels;
            final int resultSelected = selected;
            runOnUiThread(() -> {
                if (request != launcherShapeRequest || isFinishing()
                        || isDestroyed()) {
                    return;
                }
                showLauncherShapes(resultKeys, resultLabels, resultSelected);
            });
        }, "lenos-launcher-shape-query").start();
    }

    private void showLauncherShapes(List<String> keys, List<String> labels,
            int selected) {
        launcherShapeKeys.clear();
        launcherShapeKeys.addAll(keys);
        suppressLauncherShape = true;
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item,
                labels.isEmpty()
                        ? Collections.singletonList(
                                "Icon shape control not available")
                        : labels);
        launcherShapeSpinner.setAdapter(adapter);
        int shown = selected >= 0 && selected < keys.size() ? selected : 0;
        launcherShapeSpinner.setSelection(shown);
        // Treat the visible option as current so the initial selection
        // callback cannot write a shape the user did not choose.
        launcherShapeCurrent = keys.isEmpty() ? null : keys.get(shown);
        launcherShapeSpinner.setEnabled(!keys.isEmpty());
        suppressLauncherShape = false;
        if (keys.isEmpty()) {
            launcherShapeNote.setText(
                    "This launcher build does not expose icon shapes to "
                            + "lenOS. Use launcher settings below.");
        } else {
            launcherShapeNote.setText(
                    "Changes the mask applied to launcher icons.");
        }
    }

    private void applyLauncherShape(int position) {
        if (position < 0 || position >= launcherShapeKeys.size()) {
            return;
        }
        String key = launcherShapeKeys.get(position);
        if (key.equals(launcherShapeCurrent)) {
            return;
        }
        launcherShapeSpinner.setEnabled(false);
        new Thread(() -> {
            int updated = 0;
            String failure = null;
            try {
                ContentValues values = new ContentValues();
                values.put("shape_key", key);
                updated = getContentResolver().update(
                        launcherProviderUri(LAUNCHER_SET_SHAPE), values,
                        null, null);
            } catch (Throwable t) {
                failure = t.getMessage();
            }
            final int result = updated;
            final String message = failure;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                if (result > 0) {
                    launcherShapeCurrent = key;
                    Toast.makeText(this, "Icon shape updated",
                            Toast.LENGTH_SHORT).show();
                } else {
                    Toast.makeText(this,
                            message == null
                                    ? "This launcher did not accept the icon "
                                            + "shape"
                                    : "Could not change the icon shape: "
                                            + message,
                            Toast.LENGTH_LONG).show();
                }
                refreshLauncherShapes();
            });
        }, "lenos-launcher-shape-apply").start();
    }

    private static String launcherShapeLabel(String title, String key) {
        if (title == null || title.trim().isEmpty()) {
            return key;
        }
        return title.trim();
    }

    /**
     * Reads the monochrome/themed-icon preference from the launcher provider.
     */
    private void refreshLauncherThemedIcons() {
        if (launcherThemedIcons == null) {
            return;
        }
        launcherThemedIcons.setEnabled(false);
        final int request = ++launcherThemedRequest;
        new Thread(() -> {
            Boolean enabled = null;
            try (Cursor cursor = getContentResolver().query(
                    launcherProviderUri(LAUNCHER_GET_ICON_THEMED),
                    new String[]{"boolean_value"},
                    null, null, null)) {
                if (cursor != null && cursor.moveToFirst()) {
                    int index = cursor.getColumnIndexOrThrow("boolean_value");
                    enabled = cursor.getInt(index) != 0;
                }
            } catch (Throwable ignored) {
                // Fall back to the stock launcher settings screen.
            }
            final Boolean result = enabled;
            runOnUiThread(() -> {
                if (request != launcherThemedRequest || isFinishing()
                        || isDestroyed()) {
                    return;
                }
                suppressLauncherThemed = true;
                launcherThemedIcons.setChecked(Boolean.TRUE.equals(result));
                launcherThemedIcons.setEnabled(result != null);
                launcherThemedIcons.setText(result == null
                        ? "Themed icons (not available)" : "Themed icons");
                suppressLauncherThemed = false;
            });
        }, "lenos-launcher-themed-query").start();
    }

    private void applyLauncherThemedIcons(boolean enabled) {
        launcherThemedIcons.setEnabled(false);
        new Thread(() -> {
            int updated = 0;
            String failure = null;
            try {
                ContentValues values = new ContentValues();
                values.put("boolean_value", enabled);
                updated = getContentResolver().update(
                        launcherProviderUri(LAUNCHER_SET_ICON_THEMED), values,
                        null, null);
            } catch (Throwable t) {
                failure = t.getMessage();
            }
            final int result = updated;
            final String message = failure;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                if (result > 0) {
                    Toast.makeText(this,
                            enabled ? "Themed icons enabled"
                                    : "Themed icons disabled",
                            Toast.LENGTH_SHORT).show();
                } else {
                    Toast.makeText(this,
                            message == null
                                    ? "This launcher did not accept the "
                                            + "themed-icon change"
                                    : "Could not change themed icons: "
                                            + message,
                            Toast.LENGTH_LONG).show();
                }
                refreshLauncherThemedIcons();
            });
        }, "lenos-launcher-themed-apply").start();
    }

    private void openLauncherSettings() {
        Intent preferences = new Intent(Intent.ACTION_APPLICATION_PREFERENCES);
        preferences.setPackage(LAUNCHER_PACKAGE);
        preferences.addCategory(Intent.CATEGORY_DEFAULT);
        if (tryStartActivity(preferences)) {
            return;
        }
        if (tryStartActivity(new Intent(Settings.ACTION_HOME_SETTINGS))) {
            return;
        }
        Toast.makeText(this,
                "Launcher settings are not available on this build",
                Toast.LENGTH_LONG).show();
    }

    private boolean tryStartActivity(Intent intent) {
        try {
            startActivity(intent);
            return true;
        } catch (ActivityNotFoundException | SecurityException e) {
            return false;
        }
    }

    private static Uri launcherProviderUri(String path) {
        return Uri.parse("content://" + LAUNCHER_GRID_AUTHORITY + path);
    }

    private void openStatusBarSettings() {
        Intent intent = new Intent(STATUS_BAR_ACTION);
        intent.addCategory(Intent.CATEGORY_DEFAULT);
        try {
            startActivity(intent);
        } catch (ActivityNotFoundException e) {
            try {
                startActivity(new Intent(Settings.ACTION_DISPLAY_SETTINGS));
            } catch (ActivityNotFoundException ignored) {
                Toast.makeText(this,
                        "Status bar settings are not available on this build",
                        Toast.LENGTH_LONG).show();
            }
        }
    }

    private TextView section(String value) {
        TextView view = text(value, 18, TEXT, true);
        view.setPadding(0, dp(26), 0, dp(8));
        return view;
    }

    private TextView text(String value, int size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        if (bold) {
            view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        }
        view.setLineSpacing(dp(2), 1.0f);
        return view;
    }

    private LinearLayout card(View content) {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(16), dp(14), dp(16), dp(14));
        GradientDrawable background = new GradientDrawable();
        background.setColor(CARD);
        background.setCornerRadius(dp(20));
        background.setStroke(dp(1), STROKE);
        layout.setBackground(background);
        layout.addView(content);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(10);
        layout.setLayoutParams(lp);
        return layout;
    }

    private Button button(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(10);
        button.setLayoutParams(lp);
        return button;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
