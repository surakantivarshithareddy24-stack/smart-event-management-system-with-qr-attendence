/**
 * Clean QR text from scanner (spaces, line breaks, BOM).
 * Keeps first number:number pattern like 3:1
 */
function normalizeQrToken(raw) {
    if (raw == null) return "";
    var t = String(raw).replace(/\uFEFF/g, "").replace(/\s+/g, "").trim();
    var m = t.match(/^(\d+):(\d+)/);
    if (m) {
        return m[1] + ":" + m[2];
    }
    return t;
}

/**
 * Mark attendance from scanned QR text (format: "user_id:event_id").
 */
function markAttendance(qrToken, onDone) {
    var token = normalizeQrToken(qrToken);
    fetch("/mark_attendance", {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            Accept: "application/json"
        },
        body: JSON.stringify({ qr_token: token })
    })
        .then(async function (response) {
            var data;
            try {
                data = await response.json();
            } catch (e) {
                var text = await response.text();
                data = {
                    status: "error",
                    message:
                        (response.status === 401
                            ? "Login as Admin on this site, then try again."
                            : "Server: ") + text.substring(0, 180)
                };
            }
            if (!response.ok && data && !data.message) {
                data.status = "error";
                data.message = "Error " + response.status;
            }
            return data;
        })
        .then(function (data) {
            if (typeof onDone === "function") {
                onDone(data);
                return;
            }
            document.dispatchEvent(
                new CustomEvent("mark-attendance-done", { detail: data })
            );
            var result = document.getElementById("scan-result");
            if (result) {
                result.innerText = data.message || "Done.";
            }
            if (data && data.status === "ok") {
                setTimeout(function () {
                    window.location.reload();
                }, 3000);
            }
        })
        .catch(function (error) {
            console.error("Error marking attendance:", error);
            var err = { status: "error", message: "Network error — check you are logged in as Admin." };
            if (typeof onDone === "function") {
                onDone(err);
            } else {
                var result = document.getElementById("scan-result");
                if (result) {
                    result.innerText = err.message;
                }
            }
        });
}
