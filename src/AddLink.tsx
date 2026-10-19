// Fork: paste a link, let the service check it, then queue it like any other download.
// Self-contained like the TorBox and Archive.org panels: it talks to the API itself, so the
// Store dialog, the other looks' Settings page and a stopped download's "new link" prompt all use it.
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "./api";
import { Select } from "./Select";
import {
  bytes,
  type Job,
  type LinkReply,
  type SavedLink,
  type SourceId,
  type SourceSettings,
  type Storage,
} from "./types";
import { formatNumber, placeName, t } from "./i18n";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// The service checks a link on its own thread; start it, then poll until it answers.
function useChecker() {
  const [reply, setReply] = useState<LinkReply | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const alive = useRef(true),
    turn = useRef(0);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const run = useCallback(async (body: Record<string, unknown>) => {
    const mine = ++turn.current;
    const current = () => alive.current && turn.current === mine;
    setBusy(true);
    setError("");
    setReply(null);
    try {
      let status = await api<LinkReply>("/custom/resolve", body);
      const deadline = Date.now() + 60_000;
      while (current() && status.state === "resolving" && Date.now() < deadline) {
        await sleep(500);
        status = await api<LinkReply>("/custom/resolve");
      }
      if (!current()) return null;
      if (status.state === "resolving") throw new Error(t("Checking took too long. Try again."));
      setReply(status);
      return status;
    } catch (e) {
      if (current()) setError((e as Error).message);
      return null;
    } finally {
      if (current()) setBusy(false);
    }
  }, []);
  const cancel = useCallback(async () => {
    turn.current++;
    setBusy(false);
    setReply(null);
    try {
      await api("/custom/resolve", { action: "cancel" });
    } catch {
      /* Already finished. */
    }
  }, []);
  const clear = useCallback(() => {
    turn.current++;
    setReply(null);
    setError("");
  }, []);
  return { reply, busy, error, run, cancel, clear };
}

function Facts({ reply }: { reply: LinkReply }) {
  return (
    <ul className="add-link-facts">
      <li>{reply.providerLabel}</li>
      <li>
        {reply.sizePending ? t("Size comes from TorBox") : bytes(reply.sizeBytes || 0)}
      </li>
      {reply.state === "ready" && !reply.sizePending && (
        <li>{reply.resumable ? t("Can resume if interrupted") : t("Starts over if interrupted")}</li>
      )}
      {reply.archive && <li>{t("Archive: extracted after download")}</li>}
    </ul>
  );
}

export function AddLink({
  onQueued,
  openSources,
  openTorbox,
  initialUrl = "",
}: {
  // The new job opens highlighted in Downloads; a browser-assisted link has no job yet.
  onQueued?: (jobId?: string) => void;
  openSources?: () => void;
  openTorbox?: () => void;
  initialUrl?: string;
}) {
  const check = useChecker();
  const [url, setUrl] = useState(initialUrl),
    [name, setName] = useState(""),
    [size, setSize] = useState(""),
    [drives, setDrives] = useState<Storage[]>([]),
    [drive, setDrive] = useState(""),
    [delivery, setDelivery] = useState<"direct" | "torbox">("direct"),
    [sources, setSources] = useState<SourceSettings | null>(null),
    [saved, setSaved] = useState<SavedLink[]>([]),
    [working, setWorking] = useState(false),
    [error, setError] = useState("");
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const load = useCallback(async () => {
    try {
      const [storage, source, links] = await Promise.all([
        api<Storage[]>("/storage"),
        api<SourceSettings>("/sources"),
        api<{ links: SavedLink[] }>("/custom/catalog"),
      ]);
      if (!alive.current) return;
      setDrives(storage);
      setSources(source);
      setSaved(links.links);
      setDrive((current) => current || storage[0]?.id || "");
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const reply = check.reply;
  const wantsTorbox = delivery === "torbox" && !!reply?.delivery?.torbox;
  useEffect(() => {
    // A link TorBox must fetch has no direct option; keep the choice valid.
    if (reply?.delivery && !reply.delivery.direct && reply.delivery.torbox) setDelivery("torbox");
    else if (reply?.delivery && !reply.delivery.torbox) setDelivery("direct");
  }, [reply]);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    setError("");
    const body: Record<string, unknown> = { action: "resolve", url: url.trim() };
    if (name.trim()) body.filename = name.trim();
    const parsed = Number(size.replace(/[\s,_]/g, ""));
    if (size.trim() && Number.isSafeInteger(parsed) && parsed > 0) body.sizeBytes = parsed;
    void check.run(body);
  }
  async function enableSource(id: string) {
    if (!sources) return;
    setWorking(true);
    setError("");
    try {
      await api("/sources", {
        enabled: [...sources.enabled, id as SourceId],
        acknowledged: true,
        noticeVersion: sources.noticeVersion,
      });
      await load();
      submit();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      if (alive.current) setWorking(false);
    }
  }
  async function queue() {
    if (!reply?.releaseId || !drive) return;
    setWorking(true);
    setError("");
    try {
      let id: string | undefined;
      if (wantsTorbox)
        id = (await api<{ id: string }>("/downloads", { releaseId: reply.torboxReleaseId || reply.releaseId, storageId: drive, delivery: "torbox" })).id;
      else if (reply.state === "needs-browser")
        await api("/browser", { action: "start", returnToOrbit: true, releaseId: reply.releaseId, storageId: drive });
      else id = (await api<{ id: string }>("/downloads", { releaseId: reply.releaseId, storageId: drive, delivery: "direct" })).id;
      onQueued?.(id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      if (alive.current) setWorking(false);
    }
  }
  async function manageSaved(body: Record<string, unknown>) {
    setError("");
    try {
      const result = await api<{ links: SavedLink[] }>("/custom/catalog", body);
      setSaved(result.links);
      return result as { links: SavedLink[]; result?: { imported: number; rejected: { index: number; reason: string }[] } };
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }

  const needTorboxDrive = wantsTorbox || reply?.state === "ready" || reply?.state === "needs-browser";
  const size_ = reply?.sizeBytes || 0;
  const options = drives.map((d) => ({
    value: d.id,
    label: `${placeName(d.label)} · ${t("{size} free", { size: bytes(d.freeBytes) })}`,
    disabled: size_ > 0 && d.projectedFreeBytes < size_,
  }));
  const queueLabel = wantsTorbox
    ? t("Download via TorBox")
    : reply?.state === "needs-browser"
      ? t("Open {provider} on PS5", { provider: reply.providerLabel || "" })
      : t("Add to Downloads");

  return (
    <div className="add-link">
      <h1>{t("Add a download link")}</h1>
      <p className="source-intro">
        {t("Paste a link to a file you are allowed to download. Orbit checks it before anything is queued.")}
      </p>
      <form className="add-link-form" onSubmit={submit}>
        <label>
          {t("Link")}
          <input
            type="text"
            inputMode="url"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            maxLength={2000}
            placeholder="https://"
            data-initial-focus
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              if (reply || check.error) check.clear();
            }}
            disabled={check.busy || working}
          />
        </label>
        <div className="actions">
          <button className="primary" type="submit" disabled={check.busy || working || !url.trim()}>
            {t("Check link")}
          </button>
          {check.busy && (
            <button type="button" onClick={() => void check.cancel()}>
              {t("Cancel")}
            </button>
          )}
        </div>
      </form>
      {check.busy && (
        <p role="status" className="fine">
          {t("Checking the link…")}
        </p>
      )}
      {(check.error || error) && (
        <p className="form-error" role="alert">
          {check.error || error}
        </p>
      )}

      {reply && reply.state === "error" && (
        <p className="form-error" role="alert">
          {t(reply.message)}
        </p>
      )}
      {reply && reply.state === "cancelled" && <p className="fine">{t("Cancelled.")}</p>}

      {reply && reply.state === "unsupported" && (
        <div className="notice" role="status">
          {t(reply.message)}
          {reply.torboxSetup && openTorbox && (
            <button type="button" onClick={openTorbox}>
              {t("Set up TorBox")}
            </button>
          )}
        </div>
      )}

      {reply && reply.state === "source-disabled" && (
        <div className="notice" role="status">
          {t("{provider} is turned off in your download sources.", { provider: reply.providerLabel || "" })}
          {sources?.acknowledged ? (
            <button type="button" disabled={working} onClick={() => void enableSource(reply.provider || "")}>
              {t("Turn on {provider}", { provider: reply.providerLabel || "" })}
            </button>
          ) : (
            openSources && (
              <button type="button" onClick={openSources}>
                {t("Open download sources")}
              </button>
            )
          )}
        </div>
      )}

      {reply && reply.state === "needs-details" && (
        <div className="add-link-card">
          <h2>{reply.providerLabel}</h2>
          <p>{t(reply.message)}</p>
          {reply.delivery?.torbox && (
            <Select label={t("Save to")} value={drive} options={options} onChange={setDrive} disabled={working || !options.length} />
          )}
          {reply.delivery?.torbox && (
            <div className="actions">
              <button
                className="primary"
                disabled={working || !drive}
                onClick={() => {
                  setDelivery("torbox");
                  void (async () => {
                    setWorking(true);
                    setError("");
                    try {
                      const created = await api<{ id: string }>("/downloads", { releaseId: reply.torboxReleaseId, storageId: drive, delivery: "torbox" });
                      onQueued?.(created.id);
                    } catch (e) {
                      setError((e as Error).message);
                    } finally {
                      if (alive.current) setWorking(false);
                    }
                  })();
                }}
              >
                {t("Download via TorBox")}
              </button>
            </div>
          )}
          <div className="add-link-form">
            <label>
              {t("File name")}
              <input type="text" maxLength={159} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              {t("Size in bytes")}
              <input type="text" inputMode="numeric" value={size} onChange={(e) => setSize(e.target.value)} />
            </label>
            <div className="actions">
              <button type="button" disabled={check.busy || !name.trim() || !size.trim()} onClick={() => submit()}>
                {t("Use the PS5 browser")}
              </button>
              {reply.delivery?.torboxReason && !reply.delivery.torbox && openTorbox && reply.torboxSetup && (
                <button type="button" onClick={openTorbox}>
                  {t("Set up TorBox")}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {reply && (reply.state === "ready" || reply.state === "needs-browser") && (
        <div className="add-link-card">
          <h2>{reply.filename}</h2>
          <Facts reply={reply} />
          {reply.delivery && reply.delivery.direct && reply.delivery.torbox && (
            <div className="add-link-delivery" role="radiogroup" aria-label={t("Download using")}>
              {(["direct", "torbox"] as const).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  role="radio"
                  aria-checked={delivery === kind}
                  className={`source-card ${delivery === kind ? "selected" : ""}`}
                  onClick={() => setDelivery(kind)}
                >
                  {kind === "direct" ? (reply.state === "needs-browser" ? t("PS5 browser") : t("Download to PS5")) : "TorBox"}
                </button>
              ))}
            </div>
          )}
          {reply.delivery && !reply.delivery.torbox && reply.delivery.torboxReason && (
            <p className="fine">{t("TorBox: {reason}", { reason: t(reply.delivery.torboxReason) })}</p>
          )}
          {reply.state === "ready" && !reply.sizePending && !wantsTorbox && (
            <label className="add-link-rename">
              {t("Save as")}
              <input
                type="text"
                maxLength={159}
                value={name || reply.filename || ""}
                onChange={(e) => setName(e.target.value)}
                onBlur={() => name && name !== reply.filename && submit()}
              />
            </label>
          )}
          {reply.state === "needs-browser" && (
            <p className="fine">
              {t("Complete any verification on the page that opens, then wait. Orbit adds the file when its link is ready.")}
            </p>
          )}
          {needTorboxDrive && (
            <Select label={t("Save to")} value={drive} options={options} onChange={setDrive} disabled={working || !options.length} />
          )}
          {!drives.length && <p className="fine">{t("No writable storage connected")}</p>}
          <div className="actions">
            <button className="primary" disabled={working || !drive || !reply.releaseId} onClick={() => void queue()}>
              {queueLabel}
            </button>
          </div>
        </div>
      )}

      <details className="add-link-saved">
        <summary>{t("Saved links")} ({formatNumber(saved.length)})</summary>
        {saved.length === 0 && <p className="fine">{t("Links you save or import appear here.")}</p>}
        <ul>
          {saved.map((link) => (
            <li key={link.id}>
              <span>
                <strong>{link.title}</strong>
                <small>
                  {link.providerLabel}
                  {link.titleId ? ` · ${link.titleId}` : ""}
                </small>
              </span>
              <button
                type="button"
                onClick={() => {
                  setUrl(link.url);
                  setName(link.filename);
                  setSize(link.sizeBytes ? String(link.sizeBytes) : "");
                  void check.run({ action: "resolve", url: link.url, ...(link.filename ? { filename: link.filename } : {}),
                    ...(link.sizeBytes ? { sizeBytes: link.sizeBytes } : {}) });
                }}
              >
                {t("Use")}
              </button>
              <button type="button" onClick={() => void manageSaved({ action: "remove", id: link.id })}>
                {t("Remove")}
              </button>
            </li>
          ))}
        </ul>
        <ImportLinks onImport={(catalogue, mode) => manageSaved({ action: "import", catalogue, mode })} onClear={() => void manageSaved({ action: "clear" })} hasLinks={saved.length > 0} />
      </details>
    </div>
  );
}

// A catalogue is plain JSON: { "format": "orbit-custom-catalogue", "version": 1, "entries": [ … ] }.
function ImportLinks({
  onImport,
  onClear,
  hasLinks,
}: {
  onImport: (catalogue: unknown, mode: "merge" | "replace") => Promise<{ result?: { imported: number; rejected: { index: number; reason: string }[] } } | null>;
  onClear: () => void;
  hasLinks: boolean;
}) {
  const [text, setText] = useState(""),
    [message, setMessage] = useState(""),
    [problems, setProblems] = useState<string[]>([]);
  async function run(mode: "merge" | "replace") {
    setMessage("");
    setProblems([]);
    let catalogue: unknown;
    try {
      catalogue = JSON.parse(text);
    } catch {
      setMessage(t("That is not valid JSON."));
      return;
    }
    const done = await onImport(catalogue, mode);
    if (done?.result) {
      setMessage(t("Imported {imported}, skipped {skipped}.", { imported: done.result.imported, skipped: done.result.rejected.length }));
      setProblems(done.result.rejected.slice(0, 20).map((r) => t("Entry {number}: {reason}", { number: r.index + 1, reason: r.reason })));
      if (!done.result.rejected.length) setText("");
    }
  }
  return (
    <div className="add-link-import">
      <label>
        {t("Import a link catalogue (JSON)")}
        <textarea
          rows={5}
          spellCheck={false}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder='{"format":"orbit-custom-catalogue","version":1,"entries":[{"title":"…","url":"https://…"}]}'
        />
      </label>
      <input
        type="file"
        accept="application/json,.json"
        aria-label={t("Choose a catalogue file")}
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (file && file.size <= 256 * 1024) setText(await file.text());
        }}
      />
      <div className="actions">
        <button type="button" disabled={!text.trim()} onClick={() => void run("merge")}>
          {t("Add to saved links")}
        </button>
        <button type="button" disabled={!text.trim()} onClick={() => void run("replace")}>
          {t("Replace saved links")}
        </button>
        {hasLinks && (
          <button type="button" className="danger" onClick={onClear}>
            {t("Clear saved links")}
          </button>
        )}
      </div>
      {message && <p role="status">{message}</p>}
      {problems.length > 0 && (
        <ul className="add-link-problems">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// A stopped pasted-link download whose address expired: give the same file a new one.
export function RefreshLink({ job, close, done }: { job: Job; close: () => void; done: () => void }) {
  const check = useChecker();
  const [url, setUrl] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    void check.run({ action: "refresh", jobId: job.id, url: url.trim() }).then((reply) => {
      if (reply?.state === "refreshed") done();
    });
  }
  return (
    <form className="add-link-form" onSubmit={submit}>
      <h2>{t("Give this download a new link")}</h2>
      <p>
        {t("Paste a new link for {name}. Orbit continues only if it is the same file; your partial download is kept.", {
          name: job.filename,
        })}
      </p>
      <label>
        {t("New link")}
        <input
          type="text"
          inputMode="url"
          autoCapitalize="off"
          spellCheck={false}
          maxLength={2000}
          placeholder="https://"
          data-initial-focus
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={check.busy}
        />
      </label>
      {check.busy && (
        <p role="status" className="fine">
          {t("Checking the new link…")}
        </p>
      )}
      {(check.error || check.reply?.state === "error") && (
        <p className="form-error" role="alert">
          {check.error || t(check.reply?.message || "")}
        </p>
      )}
      <div className="actions">
        <button className="primary" type="submit" disabled={check.busy || !url.trim()}>
          {t("Use new link")}
        </button>
        <button type="button" onClick={check.busy ? () => void check.cancel() : close}>
          {t("Cancel")}
        </button>
      </div>
    </form>
  );
}
