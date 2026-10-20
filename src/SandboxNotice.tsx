import { useState } from "react";
import { api } from "./api";
import { t } from "./i18n";

// Shown only by the first-test (sandbox) build. It has no updater, so this is its way to stop.
export function SandboxNotice() {
  const [step, setStep] = useState<"idle" | "confirm" | "stopped">("idle"),
    [error, setError] = useState("");
  async function stop() {
    try {
      await api("/updates", { action: "stop", confirmed: true });
      setStep("stopped");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <div className="connection-error" role="status">
      {step === "stopped"
        ? t("Test build stopped. Your installed Orbit was not touched.")
        : t(
            "Test build: separate queue and settings, no updates or icon changes. Your installed Orbit is untouched.",
          )}
      {error && <b> {error}</b>}
      {step === "idle" && (
        <button onClick={() => setStep("confirm")}>{t("Stop test build")}</button>
      )}
      {step === "confirm" && (
        <button onClick={() => void stop()}>
          {t("Pause downloads and stop")}
        </button>
      )}
    </div>
  );
}
