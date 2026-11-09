package org.lenos.security;

import android.content.Context;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/**
 * Best-effort BakaSU / KernelSU / Magisk su. Secrets go on stdin only,
 * never on argv (argv is visible to other processes via /proc).
 */
final class RootShell {
    private static final String[] SU = {
            "su",
            "/debug_ramdisk/su",
            "/system/xbin/su",
            "/system/bin/su",
            "/data/adb/ksu/bin/ksu"
    };

    static final class Result {
        final int code;
        final String out;
        final String err;

        Result(int code, String out, String err) {
            this.code = code;
            this.out = out;
            this.err = err;
        }

        boolean ok() {
            return code == 0;
        }
    }

    static Result run(String shellCommand) {
        return run(shellCommand, null);
    }

    static Result run(String shellCommand, String stdin) {
        Exception last = null;
        for (String su : SU) {
            try {
                Process p = new ProcessBuilder(su, "-c", shellCommand)
                        .redirectErrorStream(false)
                        .start();
                if (stdin != null) {
                    OutputStream os = p.getOutputStream();
                    os.write(stdin.getBytes(StandardCharsets.UTF_8));
                    os.flush();
                    os.close();
                } else {
                    p.getOutputStream().close();
                }
                String out = readAll(p.getInputStream());
                String err = readAll(p.getErrorStream());
                int code = p.waitFor();
                return new Result(code, out, err);
            } catch (Exception e) {
                last = e;
            }
        }
        return new Result(127, "", last == null ? "su not found" : last.getMessage());
    }

    /** Run DuressCli via app_process so the Binder call originates from uid 0. */
    static Result duress(Context ctx, String stdin) {
        String apk = ctx.getPackageCodePath().replace("'", "'\\''");
        String cmd = "CLASSPATH='" + apk + "' app_process /system/bin org.lenos.security.DuressCli";
        return run(cmd, stdin);
    }

    static Result settingsPutGlobal(String key, String value) {
        return run("settings put global " + key + " " + value);
    }

    static Result settingsPutSecure(String key, String value) {
        return run("settings put secure " + key + " " + value);
    }

    private static String readAll(InputStream in) {
        try {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) >= 0) {
                bos.write(buf, 0, n);
            }
            return bos.toString("UTF-8").trim();
        } catch (Exception e) {
            return "";
        }
    }
}
