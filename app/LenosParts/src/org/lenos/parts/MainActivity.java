/*
 * SPDX-FileCopyrightText: 2026 lenOS
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lenos.parts;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.om.OverlayInfo;
import android.content.om.OverlayManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Process;
import android.provider.Settings;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

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
    private static final String[] THEME_NAMES = {
            "Ember",
            "Mint",
            "Mono",
    };
    private static final String[] THEME_DESCRIPTIONS = {
            "Warm amber accents and softer corners.",
            "Cool green accents and compact corners.",
            "Neutral graphite with sharper corners.",
    };

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

    private static final int BG = Color.parseColor("#111318");
    private static final int CARD = Color.parseColor("#1C1F26");
    private static final int TEXT = Color.parseColor("#E8EAED");
    private static final int MUTED = Color.parseColor("#9AA0A6");
    private static final int ACCENT = Color.parseColor("#FFB26A");
    private static final int STROKE = Color.parseColor("#3C4043");

    private RadioGroup themeGroup;
    private Spinner motionSpinner;
    private boolean suppressTheme;
    private boolean suppressMotion;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshThemeSelection();
        refreshMotionSelection();
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
                "These packs change SystemUI colors, notification corners and Quick "
                        + "Settings spacing. Android's wallpaper-based accent may take "
                        + "precedence when dynamic color is enabled.",
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
                "Sets the standard Android animator, transition and window scales. "
                        + "0x disables animations; accessibility and battery saver can "
                        + "still override them.",
                12, MUTED, false));
        motionSpinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item, MOTION_LABELS);
        motionSpinner.setAdapter(adapter);
        motionSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view,
                    int position, long id) {
                if (suppressMotion) {
                    return;
                }
                applyMotion(MOTION_VALUES[position]);
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
        LinearLayout motionCard = new LinearLayout(this);
        motionCard.setOrientation(LinearLayout.VERTICAL);
        motionCard.addView(motionSpinner);
        root.addView(card(motionCard));

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
            java.util.HashSet<String> installed = new java.util.HashSet<>();
            for (OverlayInfo info : manager.getOverlayInfosForTarget(
                    SYSTEMUI_PACKAGE, Process.myUserHandle())) {
                installed.add(info.getPackageName());
            }
            for (String pkg : THEME_PACKAGES) {
                if (!installed.contains(pkg)) {
                    continue;
                }
                manager.setEnabled(pkg, pkg.equals(selected),
                        Process.myUserHandle());
            }
            Toast.makeText(this,
                    selected == null ? "Stock appearance restored"
                            : "Theme pack applied",
                    Toast.LENGTH_SHORT).show();
            refreshThemeSelection();
        } catch (Throwable t) {
            Toast.makeText(this, "Could not apply theme: " + t.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private void refreshMotionSelection() {
        float current = Settings.Global.getFloat(getContentResolver(),
                Settings.Global.ANIMATOR_DURATION_SCALE, 1.0f);
        int index = 0;
        for (int i = 0; i < MOTION_VALUES.length; i++) {
            if (Math.abs(MOTION_VALUES[i] - current) < 0.01f) {
                index = i;
                break;
            }
        }
        suppressMotion = true;
        motionSpinner.setSelection(index);
        suppressMotion = false;
    }

    private void applyMotion(float scale) {
        try {
            Settings.Global.putFloat(getContentResolver(),
                    Settings.Global.ANIMATOR_DURATION_SCALE, scale);
            Settings.Global.putFloat(getContentResolver(),
                    Settings.Global.TRANSITION_ANIMATION_SCALE, scale);
            Settings.Global.putFloat(getContentResolver(),
                    Settings.Global.WINDOW_ANIMATION_SCALE, scale);
            Toast.makeText(this, "Motion scale set to " + scale + "x",
                    Toast.LENGTH_SHORT).show();
        } catch (Throwable t) {
            Toast.makeText(this,
                    "Could not change animation scale: " + t.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
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
