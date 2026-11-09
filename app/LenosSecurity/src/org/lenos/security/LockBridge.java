package org.lenos.security;

import android.content.Context;

import java.lang.reflect.Constructor;
import java.lang.reflect.Method;

/**
 * Reflection wrapper over the hidden
 * {@code com.android.internal.widget.LockPatternUtils} and
 * {@code com.android.internal.widget.LockscreenCredential}, so the app source
 * does not link against hidden framework classes at compile time. The module
 * still uses the platform API surface to build as a privileged system app.
 *
 * Backed by the lenOS 1.0 framework patch
 * (frameworks/base/0005-lenos-duress-credentials), which adds:
 *   setDuressCredentials(LockscreenCredential, LockscreenCredential, LockscreenCredential)
 *   hasDuressCredentials(LockscreenCredential) -> boolean
 *   deleteDuressCredentials(LockscreenCredential)
 */
final class LockBridge {
    private static final String LPU = "com.android.internal.widget.LockPatternUtils";
    private static final String LC = "com.android.internal.widget.LockscreenCredential";

    private final Object lpu;

    LockBridge(Context ctx) throws Exception {
        Class<?> c = Class.forName(LPU);
        Constructor<?> ctor = c.getConstructor(Context.class);
        lpu = ctor.newInstance(ctx);
    }

    boolean isSecure() {
        try {
            Method m = lpu.getClass().getMethod("isSecure", int.class);
            return (Boolean) m.invoke(lpu, 0);
        } catch (Exception e) {
            return false;
        }
    }

    Object createPin(String pin) throws Exception {
        Class<?> c = Class.forName(LC);
        Method m = c.getMethod("createPin", CharSequence.class);
        return m.invoke(null, pin);
    }

    Object createPassword(String pass) throws Exception {
        Class<?> c = Class.forName(LC);
        Method m = c.getMethod("createPassword", CharSequence.class);
        return m.invoke(null, pass);
    }

    void setDuress(Object owner, Object pin, Object pass) throws Exception {
        Class<?> lc = Class.forName(LC);
        Method m = lpu.getClass().getMethod("setDuressCredentials", lc, lc, lc);
        m.invoke(lpu, owner, pin, pass);
    }

    boolean hasDuress(Object owner) throws Exception {
        Class<?> lc = Class.forName(LC);
        Method m = lpu.getClass().getMethod("hasDuressCredentials", lc);
        return (Boolean) m.invoke(lpu, owner);
    }

    void deleteDuress(Object owner) throws Exception {
        Class<?> lc = Class.forName(LC);
        Method m = lpu.getClass().getMethod("deleteDuressCredentials", lc);
        m.invoke(lpu, owner);
    }

    void zeroize(Object cred) {
        if (cred == null) {
            return;
        }
        try {
            Method m = cred.getClass().getMethod("zeroize");
            m.invoke(cred);
        } catch (Exception ignored) {
        }
    }
}
