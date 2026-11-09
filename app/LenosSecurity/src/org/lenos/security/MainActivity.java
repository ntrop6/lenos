package org.lenos.security;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Stand-in Settings page for lenOS 1.0 where the stock Settings APK never
 * grew the "lenOS security" category. Backed by the hardening backend that IS
 * in this build (auto-BFU timer in init, duress in LockSettingsService,
 * etc.).
 *
 * Every privileged write goes through the platform Settings/LockPatternUtils
 * APIs. The app is platform-signed, privileged, and holds
 * WRITE_SECURE_SETTINGS and ACCESS_KEYGUARD_SECURE_STORAGE, so there is no
 * root/su fallback.
 */
public class MainActivity extends Activity {
    static final String BFU_SETTING = "settings_reboot_after_timeout";
    static final int BFU_DEFAULT_MS = 64_800_000; // 18h, matches init default
    static final int BFU_12H_MS = 43_200_000;
    // Settings.Secure key read by the SystemUI and Settings scramble readers
    // (android.ext.settings.ExtSettings, GrapheneOS port). lenOS default: on.
    static final String SCRAMBLE_KEY = "lockscreen_scramble_pin_layout";

    private static final int BG = Color.parseColor("#111318");
    private static final int CARD = Color.parseColor("#1C1F26");
    private static final int TEXT = Color.parseColor("#E8EAED");
    private static final int MUTED = Color.parseColor("#9AA0A6");
    private static final int ACCENT = Color.parseColor("#8AB4F8");
    private static final int DANGER = Color.parseColor("#F28B82");
    private static final int STROKE = Color.parseColor("#3C4043");

    private static final LinkedHashMap<Integer, String> BFU_CHOICES = new LinkedHashMap<Integer, String>();
    static {
        BFU_CHOICES.put(0, "Off");
        BFU_CHOICES.put(600_000, "10 minutes");
        BFU_CHOICES.put(1_800_000, "30 minutes");
        BFU_CHOICES.put(3_600_000, "1 hour");
        BFU_CHOICES.put(7_200_000, "2 hours");
        BFU_CHOICES.put(14_400_000, "4 hours");
        BFU_CHOICES.put(28_800_000, "8 hours");
        BFU_CHOICES.put(43_200_000, "12 hours");
        BFU_CHOICES.put(64_800_000, "18 hours (ROM default)");
        BFU_CHOICES.put(86_400_000, "1 day");
        BFU_CHOICES.put(129_600_000, "36 hours");
        BFU_CHOICES.put(172_800_000, "2 days");
        BFU_CHOICES.put(259_200_000, "3 days");
    }

    private LockBridge lock;
    private TextView statusBody;
    private TextView bfuSummary;
    private TextView duressStatus;
    private Switch scrambleSwitch;
    private Spinner bfuSpinner;

    // Last-committed values, used to ignore programmatic UI sync.
    // (A plain boolean suppress flag is racy for Spinner: setSelection()
    //  posts onItemSelected to the next looper tick, so the flag is already
    //  reset by the time the listener runs.)
    private int currentBfu = Integer.MIN_VALUE;
    private int currentScramble = Integer.MIN_VALUE;

    private EditText ownerPin;
    private EditText duressPin;
    private EditText duressPin2;
    private EditText duressPass;
    private EditText duressPass2;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
            buildUi();
        } catch (Throwable t) {
            Log.e("lenOS-security", "onCreate failed", t);
            try {
                setContentView(errorScreen(stack(t)));
            } catch (Throwable ignored) {
            }
        }
    }

    private void buildUi() {
        try {
            lock = new LockBridge(this);
        } catch (Throwable t) {
            Log.w("lenOS-security", "LockBridge deferred", t);
            lock = null;
        }

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BG);

        LinearLayout root = column();
        root.setPadding(dp(16), dp(20), dp(16), dp(32));
        scroll.addView(root);

        // Logo (branding/logo.png) — decorative header.
        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.logo);
        logo.setAdjustViewBounds(true);
        logo.setMaxWidth(dp(120));
        logo.setMaxHeight(dp(130));
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        LinearLayout.LayoutParams logoLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        logoLp.topMargin = dp(8);
        logo.setLayoutParams(logoLp);
        root.addView(logo);

        root.addView(text("lenOS security", 26, TEXT, true));
        root.addView(text(getString(R.string.lenos_header_subtitle), 13, MUTED, false));
        root.addView(text("Hardening controls missing from Settings on this image.", 13, MUTED, false));

        statusBody = text("", 13, MUTED, false);
        root.addView(card("Status", statusBody));

        bfuSummary = text("", 13, MUTED, false);
        bfuSpinner = new Spinner(this);
        String[] labels = BFU_CHOICES.values().toArray(new String[0]);
        bfuSpinner.setAdapter(new ArrayAdapter<String>(this,
                android.R.layout.simple_spinner_dropdown_item, labels));
        LinearLayout bfuCol = column();
        bfuCol.addView(bfuSummary);
        bfuCol.addView(text("Reboots after the phone stays locked (Before First Unlock). Lock once after changing so the timer arms.", 13, MUTED, false));
        bfuCol.addView(bfuSpinner);
        root.addView(card("Automatic BFU reboot", bfuCol));

        scrambleSwitch = new Switch(this);
        scrambleSwitch.setText("Scramble PIN layout");
        scrambleSwitch.setTextColor(TEXT);
        LinearLayout pinCol = column();
        pinCol.addView(text("Randomizes the lock-screen PIN pad after a PIN lock is set.", 13, MUTED, false));
        pinCol.addView(scrambleSwitch);
        root.addView(card("PIN scramble", pinCol));

        LinearLayout wifiCol = column();
        wifiCol.addView(text("Off by default for every network (GrapheneOS-faithful): DHCP "
                + "requests carry no hostname, so the local network and its router logs "
                + "never see this phone's name. Override per network in the Wi-Fi network "
                + "details (Advanced).", 13, MUTED, false));
        root.addView(card("Wi-Fi DHCP hostname", wifiCol));

        duressStatus = text("Enter your current screen-lock PIN to check or change duress credentials.", 13, MUTED, false);
        ownerPin = passwordField("Current screen-lock PIN", true);
        duressPin = passwordField("Duress PIN (min 4 digits)", true);
        duressPin2 = passwordField("Confirm duress PIN", true);
        duressPass = passwordField("Duress password (min 4 characters)", false);
        duressPass2 = passwordField("Confirm duress password", false);

        Button check = accentButton("Check duress status");
        Button save = dangerButton("Save duress PIN + password");
        Button delete = outlineButton("Delete duress credentials");
        check.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { checkDuress(); }
        });
        save.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { confirmSaveDuress(); }
        });
        delete.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { confirmDeleteDuress(); }
        });

        LinearLayout duressCol = column();
        duressCol.addView(text("Entering either duress credential anywhere Android asks for your lock deletes the keystore secrets protecting storage, erases stored eSIM profiles and powers the device off. Storage is gone. Do not test on this phone.", 13, DANGER, false));
        duressCol.addView(duressStatus);
        duressCol.addView(ownerPin);
        duressCol.addView(check);
        duressCol.addView(duressPin);
        duressCol.addView(duressPin2);
        duressCol.addView(duressPass);
        duressCol.addView(duressPass2);
        duressCol.addView(save);
        duressCol.addView(delete);
        root.addView(card("Duress PIN and password", duressCol));

        LinearLayout extra = column();
        extra.addView(text("Wi-Fi MAC + DHCP hostname: per network in Settings \u2192 Network & internet \u2192 Internet.", 13, MUTED, false));
        extra.addView(text("Other sensors: Settings \u2192 Apps \u2192 [app] \u2192 Permissions.", 13, MUTED, false));
        extra.addView(text("Per-app network block: app data-usage screen (Lineage POLICY_REJECT_ALL).", 13, MUTED, false));
        extra.addView(text("Do not lock the bootloader from this helper.", 13, DANGER, false));
        root.addView(card("Also on this build", extra));

        setContentView(scroll);
        wireBfu();
        wireScramble();
        refreshStatus();
        refreshBfu();
        refreshScramble();
    }

    private void wireBfu() {
        bfuSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> p, View v, int pos, long id) {
                int value = bfuValueAt(pos);
                if (value == currentBfu) {
                    return; // programmatic re-sync, not a user change
                }
                if (!writeBfu(value)) {
                    toast("Could not write BFU. Check the platform signature/privileged allowlist.");
                    refreshBfu();
                    return;
                }
                currentBfu = value;
                refreshBfu();
                toast(value == 0 ? "Automatic BFU is off" : "BFU set. Lock the phone once to arm.");
            }
            @Override public void onNothingSelected(AdapterView<?> p) {}
        });
    }

    private void wireScramble() {
        scrambleSwitch.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override public void onCheckedChanged(CompoundButton buttonView, boolean isChecked) {
                int value = isChecked ? 1 : 0;
                if (value == currentScramble) {
                    return;
                }
                if (!writeScramble(value)) {
                    toast("Could not write PIN scramble");
                    refreshScramble();
                    return;
                }
                currentScramble = value;
                toast(isChecked ? "PIN scramble on" : "PIN scramble off");
            }
        });
    }

    private void refreshStatus() {
        String secure;
        try {
            secure = lock == null ? "lock API deferred" : (lock.isSecure() ? "yes" : "no");
        } catch (Exception e) {
            secure = "error: " + e.getMessage();
        }
        statusBody.setText(
                "profile " + sysProp("ro.lenos.hardening.profile", "?") + "\n"
                        + "auto-BFU backend " + sysProp("ro.lenos.security.auto_bfu", "?") + "\n"
                        + "duress backend " + sysProp("ro.lenos.security.duress", "?") + "\n"
                        + "wifi MAC + DHCP hostname privacy defaults (per-network)\n"
                        + "owner screen lock " + secure);
    }

    private boolean writeBfu(int value) {
        try {
            return Settings.Global.putInt(getContentResolver(), BFU_SETTING, value);
        } catch (Throwable ignored) {
            // The app is platform-signed and holds WRITE_SECURE_SETTINGS.
            // Do not fall back to a root shell.
            return false;
        }
    }

    private void refreshBfu() {
        int value = Settings.Global.getInt(getContentResolver(), BFU_SETTING, BFU_DEFAULT_MS);
        if (!BFU_CHOICES.containsKey(value)) {
            value = BFU_DEFAULT_MS;
        }
        currentBfu = value;
        int index = 0;
        int i = 0;
        for (Integer key : BFU_CHOICES.keySet()) {
            if (key == value) {
                index = i;
                break;
            }
            i++;
        }
        bfuSpinner.setSelection(index);
        bfuSummary.setText(value == 0
                ? "Automatic BFU reboot is off"
                : "Reboot after the device remains locked for " + BFU_CHOICES.get(value));
    }

    private void refreshScramble() {
        int value = readScramble();
        currentScramble = value;
        scrambleSwitch.setChecked(value != 0);
    }

    private int readScramble() {
        // Settings.Secure key, the same one ExtSettings.
        // SCRAMBLE_LOCKSCREEN_PIN_LAYOUT_PRIMARY drives in SystemUI/Settings.
        return Settings.Secure.getInt(getContentResolver(), SCRAMBLE_KEY, 1);
    }

    private boolean writeScramble(int value) {
        try {
            return Settings.Secure.putInt(getContentResolver(), SCRAMBLE_KEY, value);
        } catch (Throwable ignored) {
            // The app is platform-signed and holds WRITE_SECURE_SETTINGS.
            // Do not fall back to a root shell.
            return false;
        }
    }

    private void checkDuress() {
        Object owner = null;
        try {
            requireLock();
            owner = ownerCredential();
            boolean has = lock.hasDuress(owner);
            duressStatus.setText(has
                    ? "Duress credentials are set. You can update or delete them."
                    : "No duress credentials are set.");
            duressStatus.setTextColor(has ? ACCENT : MUTED);
        } catch (Exception e) {
            duressStatus.setText(friendly(e));
            duressStatus.setTextColor(DANGER);
        } finally {
            zero(owner);
        }
    }

    private void confirmSaveDuress() {
        final String pin = textOf(duressPin);
        final String pin2 = textOf(duressPin2);
        final String pass = textOf(duressPass);
        final String pass2 = textOf(duressPass2);
        if (pin.length() < 4 || !pin.equals(pin2)) {
            toast("Duress PIN must match and be at least 4 digits");
            return;
        }
        if (pass.length() < 4 || !pass.equals(pass2)) {
            toast("Duress password must match and be at least 4 characters");
            return;
        }
        if (pin.equals(textOf(ownerPin))) {
            toast("Duress PIN must be different from your real PIN");
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("Destructive credential warning")
                .setMessage("Entering either duress credential will immediately and irreversibly make storage inaccessible, erase stored eSIM profiles and power off. Do not test on this phone.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Proceed", new android.content.DialogInterface.OnClickListener() {
                    @Override public void onClick(android.content.DialogInterface d, int w) {
                        saveDuress(pin, pass);
                    }
                })
                .show();
    }

    private void saveDuress(String pin, String pass) {
        Object owner = null;
        Object dPin = null;
        Object dPass = null;
        try {
            requireLock();
            owner = ownerCredential();
            dPin = lock.createPin(pin);
            dPass = lock.createPassword(pass);
            lock.setDuress(owner, dPin, dPass);
            duressStatus.setText("Duress credentials saved.");
            duressStatus.setTextColor(ACCENT);
            duressPin.setText("");
            duressPin2.setText("");
            duressPass.setText("");
            duressPass2.setText("");
            toast("Duress PIN and password saved");
        } catch (Exception e) {
            duressStatus.setText(friendly(e));
            duressStatus.setTextColor(DANGER);
            toast("Save failed");
        } finally {
            zero(owner);
            zero(dPin);
            zero(dPass);
        }
    }

    private void confirmDeleteDuress() {
        new AlertDialog.Builder(this)
                .setTitle("Delete duress credentials?")
                .setMessage("This only removes the wipe credentials. It does not wipe the phone.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Delete", new android.content.DialogInterface.OnClickListener() {
                    @Override public void onClick(android.content.DialogInterface d, int w) {
                        deleteDuress();
                    }
                })
                .show();
    }

    private void deleteDuress() {
        Object owner = null;
        try {
            requireLock();
            owner = ownerCredential();
            lock.deleteDuress(owner);
            duressStatus.setText("Duress credentials deleted.");
            duressStatus.setTextColor(MUTED);
            toast("Duress credentials deleted");
        } catch (Exception e) {
            duressStatus.setText(friendly(e));
            duressStatus.setTextColor(DANGER);
        } finally {
            zero(owner);
        }
    }

    private void requireLock() throws Exception {
        if (lock == null) {
            try {
                lock = new LockBridge(this);
            } catch (Throwable t) {
                throw new IllegalStateException(
                        "Lock APIs blocked. This app must be built with the platform "
                                + "certificate and the privileged allowlist. "
                                + t.getClass().getSimpleName() + ": " + t.getMessage());
            }
        }
    }

    private void zero(Object cred) {
        if (lock != null) {
            lock.zeroize(cred);
        }
    }

    private Object ownerCredential() throws Exception {
        String pin = textOf(ownerPin);
        if (pin.isEmpty()) {
            throw new IllegalArgumentException("Enter your current screen-lock PIN first");
        }
        return lock.createPin(pin);
    }

    private static int bfuValueAt(int pos) {
        int i = 0;
        for (Map.Entry<Integer, String> e : BFU_CHOICES.entrySet()) {
            if (i == pos) {
                return e.getKey();
            }
            i++;
        }
        return BFU_12H_MS;
    }

    private static String friendly(Exception e) {
        String msg = e.getMessage();
        if (msg == null || msg.isEmpty()) {
            msg = e.getClass().getSimpleName();
        }
        if (msg.contains("owner credential")) {
            return "Current PIN is wrong.";
        }
        if (msg.contains("factory reset protection") || msg.contains("FRP")) {
            return "FRP is still active.";
        }
        if (isPrivError(e)) {
            return "lenOS security lacks ACCESS_KEYGUARD_SECURE_STORAGE. "
                    + "Check the platform signature and the privileged allowlist.";
        }
        return msg;
    }

    private static boolean isPrivError(Exception e) {
        String msg = String.valueOf(e.getMessage()) + " " + e.getClass().getName();
        if (msg.contains("owner credential")) {
            return false;
        }
        return msg.contains("ACCESS_KEYGUARD")
                || msg.contains("LockSettingsWrite")
                || msg.contains("Permission Denial")
                || e instanceof SecurityException;
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }

    private static String sysProp(String key, String fallback) {
        try {
            Class<?> c = Class.forName("android.os.SystemProperties");
            return (String) c.getMethod("get", String.class, String.class).invoke(null, key, fallback);
        } catch (Exception e) {
            return fallback;
        }
    }

    private static String textOf(EditText e) {
        return e.getText() == null ? "" : e.getText().toString();
    }

    private static String stack(Throwable t) {
        StringWriter sw = new StringWriter();
        t.printStackTrace(new PrintWriter(sw));
        return sw.toString();
    }

    private LinearLayout card(String heading, View body) {
        LinearLayout card = column();
        card.setPadding(dp(16), dp(16), dp(16), dp(16));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(CARD);
        bg.setCornerRadius(dp(16));
        bg.setStroke(dp(1), STROKE);
        card.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(14);
        card.setLayoutParams(lp);
        card.addView(text(heading, 16, TEXT, true));
        if (body.getParent() == null) {
            card.addView(body);
        }
        return card;
    }

    private LinearLayout column() {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        return col;
    }

    private TextView text(String value, int sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(value);
        t.setTextColor(color);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTypeface(Typeface.create("sans-serif", bold ? Typeface.BOLD : Typeface.NORMAL));
        t.setPadding(0, 0, 0, dp(4));
        t.setTextIsSelectable(true);
        return t;
    }

    private EditText passwordField(String hint, boolean numeric) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setHintTextColor(MUTED);
        e.setTextColor(TEXT);
        e.setSingleLine(true);
        e.setInputType(numeric
                ? InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_PASSWORD
                : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        e.setPadding(dp(12), dp(12), dp(12), dp(12));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor("#0E1116"));
        bg.setCornerRadius(dp(10));
        bg.setStroke(dp(1), STROKE);
        e.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(4);
        e.setLayoutParams(lp);
        return e;
    }

    private Button accentButton(String label) {
        return button(label, ACCENT, Color.parseColor("#0B1B33"));
    }

    private Button dangerButton(String label) {
        return button(label, DANGER, Color.parseColor("#2A1210"));
    }

    private Button outlineButton(String label) {
        return button(label, STROKE, Color.TRANSPARENT);
    }

    private Button button(String label, int stroke, int fill) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setTextColor(TEXT);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(fill);
        bg.setCornerRadius(dp(12));
        bg.setStroke(dp(1), stroke);
        b.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(4);
        b.setLayoutParams(lp);
        return b;
    }

    private View errorScreen(String msg) {
        TextView t = text(msg, 13, DANGER, false);
        t.setPadding(dp(24), dp(48), dp(24), dp(24));
        t.setBackgroundColor(BG);
        t.setGravity(Gravity.START);
        ScrollView sc = new ScrollView(this);
        sc.setBackgroundColor(BG);
        sc.addView(t);
        return sc;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
