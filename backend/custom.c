/* SPDX-License-Identifier: GPL-3.0-or-later */
/* User-added links (fork): paste a URL, resolve it with a guarded probe, then queue it
 * through the normal download pipeline. Also holds the user's own link catalogue.
 * Nothing here is generated or fetched from a catalogue feed. */
#include "orbit.h"
#include "debrid.h"
#include "hosts.h"
#include "resolve.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

#define PENDING_MAX 16
#define LINK_MAX 256
#define LINK_FILE "custom-catalogue.json"
#define LINK_FILE_LIMIT (512 * 1024)

typedef struct {
    char id[24], title[128], title_id[16], platform[8], format[12], filename[160], url[2048];
    int64_t size;
} Link;

/* Resolved-but-unqueued releases live in memory only; a queued job carries its own copy. */
static Release pending[PENDING_MAX];
static size_t pending_next;
static Link links[LINK_MAX];
static size_t link_count;

typedef struct {
    bool refresh;
    char url[2048], filename[160], job_id[24];
    int64_t size;
} Request;
static struct {
    pthread_t thread;
    pthread_cond_t changed;
    bool started, stop, pending, busy;
    atomic_bool cancel;
    char id[17], state[20], message[256];
    Request request;
    cJSON *result;
} worker = {.changed = PTHREAD_COND_INITIALIZER};

Release *custom_release_find(const char *id) {
    for (size_t i = 0; i < PENDING_MAX; i++)
        if (pending[i].id[0] && !strcmp(pending[i].id, id)) return &pending[i];
    return NULL;
}

static cJSON *state_json(const char *state, const char *message) {
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "state", state);
    cJSON_AddStringToObject(o, "message", message);
    return o;
}
static void describe(cJSON *o, const Release *r, bool ranges, bool direct) {
    const HostAdapter *h = host_by_id(r->source);
    cJSON_AddStringToObject(o, "provider", r->source);
    cJSON_AddStringToObject(o, "providerLabel", h ? h->label : r->source);
    cJSON_AddStringToObject(o, "releaseId", r->id);
    cJSON_AddStringToObject(o, "filename", r->filename);
    cJSON_AddNumberToObject(o, "sizeBytes", (double)r->size);
    cJSON_AddBoolToObject(o, "sizePending", r->size_pending);
    cJSON_AddBoolToObject(o, "resumable", ranges);
    cJSON_AddBoolToObject(o, "archive", r->compression[0] != 0);
    cJSON_AddBoolToObject(o, "viaBrowser", h && h->kind == HOST_BROWSER);
    char why[200] = {0};
    cJSON *delivery = cJSON_AddObjectToObject(o, "delivery");
    bool torbox = debrid_release_supported(r, why, sizeof why);
    cJSON_AddBoolToObject(delivery, "direct", direct);
    cJSON_AddBoolToObject(delivery, "torbox", torbox);
    cJSON_AddStringToObject(delivery, "torboxReason", torbox ? "" : why);
}
/* A link whose name and size only TorBox can tell us; it can be delivered no other way. */
static void torbox_release(Release *r, const HostAdapter *host, const char *url) {
    char segment[512] = {0}, name[sizeof r->filename];
    memset(r, 0, sizeof *r);
    r->local = r->size_pending = true;
    random_hex(r->id + snprintf(r->id, sizeof r->id, "custom-"), 6);
    if (!url_last_segment(url, segment, sizeof segment) || !filename_sanitize(segment, name, sizeof name))
        snprintf(name, sizeof name, "%s-download", host->id);
    copy_text(r->filename, sizeof r->filename, name);
    copy_text(r->title, sizeof r->title, name);
    copy_text(r->game_id, sizeof r->game_id, "custom");
    copy_text(r->source, sizeof r->source, host->id);
    copy_text(r->url, sizeof r->url, url);
    release_classify_local(r);
}
static void remember_locked(const Release *r) {
    pending[pending_next] = *r;
    pending_next = (pending_next + 1) % PENDING_MAX;
}
static void provider_fields(cJSON *o, const HostAdapter *host) {
    cJSON_AddStringToObject(o, "provider", host->id);
    cJSON_AddStringToObject(o, "providerLabel", host->label);
}

static cJSON *run_resolve(const Request *q) {
    char error[256] = {0}, canonical[2048];
    const char *url = q->url;
    if (host_canonical_url(url, canonical, sizeof canonical)) url = canonical;
    const HostAdapter *host = host_for_url(url);
    if (!host) return state_json("error", "Paste a complete https:// link to a file.");
    if (host->kind == HOST_DISABLED) {
        cJSON *o = state_json("unsupported", host->note);
        cJSON_AddStringToObject(o, "provider", host->id);
        cJSON_AddStringToObject(o, "providerLabel", host->label);
        return o;
    }
    pthread_mutex_lock(&orbit.mutex);
    bool enabled = source_id_enabled_locked(host->id);
    pthread_mutex_unlock(&orbit.mutex);
    if (!enabled) {
        cJSON *o = state_json("source-disabled", "Enable this provider in Sources, then paste the link again.");
        cJSON_AddStringToObject(o, "provider", host->id);
        cJSON_AddStringToObject(o, "providerLabel", host->label);
        return o;
    }
    Resolved res = {0};
    bool browser = host->kind == HOST_BROWSER;
    if (host->kind == HOST_TORBOX) {
        Release t;
        char why[200] = {0};
        torbox_release(&t, host, url);
        pthread_mutex_lock(&orbit.mutex);
        bool ok = debrid_release_supported(&t, why, sizeof why);
        cJSON *o;
        if (ok) {
            remember_locked(&t);
            o = state_json("ready", "Ready to download through TorBox. TorBox supplies the file name and size.");
            describe(o, &t, false, false);
        } else {
            char message[400];
            snprintf(message, sizeof message, "%s %s", host->note, why);
            o = state_json("unsupported", message);
            provider_fields(o, host);
            cJSON_AddBoolToObject(o, "torboxSetup", !debrid_connected_locked());
        }
        pthread_mutex_unlock(&orbit.mutex);
        return o;
    }
    if (browser && !strcmp(host->id, "vikingfile")) {
        if (resolve_viking(url, &worker.cancel, &res, error, sizeof error)) return state_json("error", error);
    } else if (browser) {
        /* These pages show the name and size only to a person; Orbit verifies both when it
         * captures the link, so a wrong entry fails safely instead of downloading the wrong file. */
        char clean[sizeof res.filename];
        if (!q->filename[0] || q->size < 1) {
            Release t;
            char why[200] = {0};
            torbox_release(&t, host, url);
            pthread_mutex_lock(&orbit.mutex);
            bool tb = debrid_release_supported(&t, why, sizeof why);
            if (tb) remember_locked(&t);
            cJSON *o = state_json("needs-details", tb
                ? "Download through TorBox now, or enter the exact file name and size shown on the provider page to use the PS5 browser."
                : "Enter the exact file name and size in bytes shown on the provider page.");
            provider_fields(o, host);
            if (!tb) cJSON_AddBoolToObject(o, "torboxSetup", !debrid_connected_locked());
            cJSON *delivery = cJSON_AddObjectToObject(o, "delivery");
            cJSON_AddBoolToObject(delivery, "direct", false);
            cJSON_AddBoolToObject(delivery, "torbox", tb);
            cJSON_AddStringToObject(delivery, "torboxReason", tb ? "" : why);
            if (tb) cJSON_AddStringToObject(o, "torboxReleaseId", t.id);
            pthread_mutex_unlock(&orbit.mutex);
            return o;
        }
        if (!filename_sanitize(q->filename, clean, sizeof clean) || strcmp(clean, q->filename))
            return state_json("error", "That file name has characters Orbit cannot save safely.");
        res.host = host;
        copy_text(res.filename, sizeof res.filename, clean);
        copy_text(res.url, sizeof res.url, url);
        res.size = q->size;
    } else if (resolve_direct(host, url, q->filename, &worker.cancel, &res, error, sizeof error)) {
        return state_json("error", error);
    }
    Release r = {0};
    r.local = true;
    random_hex(r.id + snprintf(r.id, sizeof r.id, "custom-"), 6);
    copy_text(r.title, sizeof r.title, res.filename);
    copy_text(r.game_id, sizeof r.game_id, "custom");
    copy_text(r.source, sizeof r.source, host->id);
    copy_text(r.filename, sizeof r.filename, res.filename);
    copy_text(r.url, sizeof r.url, res.url);
    if (browser) copy_text(r.browser_url, sizeof r.browser_url, res.url);
    r.size = res.size;
    release_classify_local(&r);
    if (!provider_url_supported(&r) && !provider_browser_supported(&r))
        return state_json("error", "Orbit cannot download this link safely. Check the address and try again.");
    pthread_mutex_lock(&orbit.mutex);
    remember_locked(&r);
    cJSON *o = state_json(browser ? "needs-browser" : "ready",
        browser ? "Open the provider page on your PS5 and complete any verification."
                : "Ready to download.");
    describe(o, &r, res.ranges, true);
    pthread_mutex_unlock(&orbit.mutex);
    return o;
}

static cJSON *run_refresh(const Request *q) {
    char error[256] = {0};
    pthread_mutex_lock(&orbit.mutex);
    Job *j = job_find(q->job_id);
    bool eligible = job_can_refresh_url(j);
    char source[sizeof j->release.source] = {0}, status[sizeof j->status] = {0};
    int64_t received = 0;
    unsigned attempts = 0;
    if (eligible) {
        copy_text(source, sizeof source, j->release.source);
        copy_text(status, sizeof status, j->status);
        received = j->received;
        attempts = j->attempts;
    }
    pthread_mutex_unlock(&orbit.mutex);
    if (!eligible) return state_json("error", "Pause the download first, then give it a new link.");
    const HostAdapter *host = host_for_url(q->url);
    if (!host || strcmp(host->id, source))
        return state_json("error", "The new link must be on the same host as the original download.");
    Resolved res = {0};
    if (resolve_direct(host, q->url, NULL, &worker.cancel, &res, error, sizeof error)) return state_json("error", error);
    pthread_mutex_lock(&orbit.mutex);
    j = job_find(q->job_id);
    int code = 409;
    if (j && job_can_refresh_url(j) && !strcmp(j->status, status) && j->received == received && j->attempts == attempts)
        code = job_refresh_url_locked(j, res.url, res.size, res.etag, res.modified, error, sizeof error);
    else copy_text(error, sizeof error, "The download changed while the new link was being checked. Try again.");
    pthread_mutex_unlock(&orbit.mutex);
    return code == 200 ? state_json("refreshed", "The download has the new link and is queued to resume.")
                       : state_json("error", error);
}

static void *worker_main(void *unused) {
    (void)unused;
    pthread_mutex_lock(&orbit.mutex);
    while (!worker.stop) {
        while (!worker.pending && !worker.stop) pthread_cond_wait(&worker.changed, &orbit.mutex);
        if (worker.stop) break;
        worker.pending = false;
        Request q = worker.request;
        pthread_mutex_unlock(&orbit.mutex);
        cJSON *reply = q.refresh ? run_refresh(&q) : run_resolve(&q);
        pthread_mutex_lock(&orbit.mutex);
        cJSON_Delete(worker.result);
        worker.result = reply;
        copy_text(worker.state, sizeof worker.state, json_text(reply, "state"));
        copy_text(worker.message, sizeof worker.message, json_text(reply, "message"));
        if (atomic_load(&worker.cancel)) {
            copy_text(worker.state, sizeof worker.state, "cancelled");
            copy_text(worker.message, sizeof worker.message, "Cancelled.");
        }
        worker.busy = false;
    }
    pthread_mutex_unlock(&orbit.mutex);
    return NULL;
}

static int text_input(const cJSON *input, const char *key, char *out, size_t cap, bool required) {
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(input, key);
    if (!v || cJSON_IsNull(v)) { out[0] = 0; return required ? -1 : 0; }
    if (!cJSON_IsString(v) || strlen(v->valuestring) >= cap || (required && !*v->valuestring)) return -1;
    for (const unsigned char *p = (const void *)v->valuestring; *p; p++)
        if (*p < 32 || *p == 127) return -1;
    copy_text(out, cap, v->valuestring);
    return 0;
}

int custom_action(const cJSON *input, char *error, size_t cap) {
    const char *action = json_text(input, "action");
    pthread_mutex_lock(&orbit.mutex);
    int code = 202;
    if (!strcmp(action, "cancel")) {
        if (!worker.busy) { copy_text(error, cap, "No link is being checked."); code = 409; }
        else atomic_store(&worker.cancel, true);
    } else if (strcmp(action, "resolve") && strcmp(action, "refresh")) {
        copy_text(error, cap, "Unknown action."); code = 400;
    } else if (orbit.stop || worker.stop) {
        copy_text(error, cap, "Orbit is stopping."); code = 503;
    } else if (worker.busy) {
        copy_text(error, cap, "Another link is still being checked."); code = 409;
    } else {
        Request q = {.refresh = !strcmp(action, "refresh")};
        const cJSON *size = cJSON_GetObjectItemCaseSensitive(input, "sizeBytes");
        if (text_input(input, "url", q.url, sizeof q.url, true) ||
            text_input(input, "filename", q.filename, sizeof q.filename, false) ||
            text_input(input, "jobId", q.job_id, sizeof q.job_id, q.refresh) ||
            (size && !cJSON_IsNull(size) && (!cJSON_IsNumber(size) || size->valuedouble < 1 ||
                                             size->valuedouble > 1125899906842624.0 ||
                                             size->valuedouble != (double)(int64_t)size->valuedouble))) {
            copy_text(error, cap, "Paste a link of up to 2000 characters."); code = 400;
        } else {
            if (size && cJSON_IsNumber(size)) q.size = (int64_t)size->valuedouble;
            if (!worker.started) {
                pthread_attr_t attr;
                int rc = pthread_attr_init(&attr);
                if (!rc) rc = pthread_attr_setstacksize(&attr, ORBIT_THREAD_STACK);
                if (!rc) rc = pthread_create(&worker.thread, &attr, worker_main, NULL);
                if (!rc) pthread_attr_destroy(&attr);
                worker.started = rc == 0;
            }
            if (!worker.started) { copy_text(error, cap, "Could not start the link check. Try again."); code = 503; }
            else {
                worker.request = q;
                worker.pending = worker.busy = true;
                atomic_store(&worker.cancel, false);
                random_hex(worker.id, 8);
                copy_text(worker.state, sizeof worker.state, "resolving");
                copy_text(worker.message, sizeof worker.message, q.refresh ? "Checking the new link…" : "Checking the link…");
                cJSON_Delete(worker.result);
                worker.result = NULL;
                pthread_cond_signal(&worker.changed);
            }
        }
    }
    pthread_mutex_unlock(&orbit.mutex);
    return code;
}

cJSON *custom_status(void) {
    pthread_mutex_lock(&orbit.mutex);
    cJSON *o = worker.result && !worker.busy ? cJSON_Duplicate(worker.result, true) : cJSON_CreateObject();
    cJSON_DeleteItemFromObjectCaseSensitive(o, "state");
    cJSON_AddStringToObject(o, "state", worker.state[0] ? worker.state : "idle");
    if (!cJSON_HasObjectItem(o, "message")) cJSON_AddStringToObject(o, "message", worker.message);
    cJSON_AddStringToObject(o, "id", worker.id);
    cJSON_AddBoolToObject(o, "busy", worker.busy);
    pthread_mutex_unlock(&orbit.mutex);
    return o;
}

/* ---- The user's own link catalogue ------------------------------------------------- */

static bool pattern_title_id(const char *s) {
    if (strlen(s) != 9 || (strncmp(s, "PPSA", 4) && strncmp(s, "CUSA", 4))) return false;
    for (int i = 4; i < 9; i++) if (!isdigit((unsigned char)s[i])) return false;
    return true;
}
/* Strict, never rewriting: an entry either describes a link Orbit can handle, or it is refused. */
static bool link_parse(const cJSON *e, Link *l, char *why, size_t cap) {
    memset(l, 0, sizeof *l);
    char url[sizeof l->url], clean[sizeof l->filename];
    if (!cJSON_IsObject(e)) { copy_text(why, cap, "Entry is not an object."); return false; }
    if (text_input(e, "title", l->title, sizeof l->title, true)) { copy_text(why, cap, "Missing or invalid title."); return false; }
    if (text_input(e, "url", url, sizeof url, true)) { copy_text(why, cap, "Missing or invalid url."); return false; }
    char canonical[2048];
    if (host_canonical_url(url, canonical, sizeof canonical)) copy_text(url, sizeof url, canonical);
    const HostAdapter *h = host_for_url(url);
    if (!h) { copy_text(why, cap, "The url must be a complete https:// link."); return false; }
    if (h->kind == HOST_DISABLED) { copy_text(why, cap, h->note); return false; }
    copy_text(l->url, sizeof l->url, url);
    if (text_input(e, "titleId", l->title_id, sizeof l->title_id, false) || (l->title_id[0] && !pattern_title_id(l->title_id))) {
        copy_text(why, cap, "titleId must look like PPSA01234 or CUSA01234."); return false;
    }
    if (text_input(e, "platform", l->platform, sizeof l->platform, false) ||
        (l->platform[0] && strcmp(l->platform, "ps4") && strcmp(l->platform, "ps5"))) {
        copy_text(why, cap, "platform must be ps4 or ps5."); return false;
    }
    if (text_input(e, "format", l->format, sizeof l->format, false)) { copy_text(why, cap, "Invalid format."); return false; }
    if (text_input(e, "filename", l->filename, sizeof l->filename, false) ||
        (l->filename[0] && (!filename_sanitize(l->filename, clean, sizeof clean) || strcmp(clean, l->filename)))) {
        copy_text(why, cap, "filename cannot be saved safely."); return false;
    }
    const cJSON *size = cJSON_GetObjectItemCaseSensitive(e, "sizeBytes");
    if (size && !cJSON_IsNull(size)) {
        if (!cJSON_IsNumber(size) || size->valuedouble < 1 || size->valuedouble > 1125899906842624.0 ||
            size->valuedouble != (double)(int64_t)size->valuedouble) { copy_text(why, cap, "sizeBytes must be a whole number."); return false; }
        l->size = (int64_t)size->valuedouble;
    }
    return true;
}
static cJSON *link_json(const Link *l) {
    const HostAdapter *h = host_for_url(l->url);
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "id", l->id);
    cJSON_AddStringToObject(o, "title", l->title);
    cJSON_AddStringToObject(o, "titleId", l->title_id);
    cJSON_AddStringToObject(o, "platform", l->platform);
    cJSON_AddStringToObject(o, "format", l->format);
    cJSON_AddStringToObject(o, "filename", l->filename);
    cJSON_AddStringToObject(o, "url", l->url);
    cJSON_AddStringToObject(o, "provider", h ? h->id : "");
    cJSON_AddStringToObject(o, "providerLabel", h ? h->label : "");
    if (l->size) cJSON_AddNumberToObject(o, "sizeBytes", (double)l->size);
    return o;
}
cJSON *custom_catalog_json(void) {
    cJSON *o = cJSON_CreateObject(), *a = cJSON_AddArrayToObject(o, "links");
    pthread_mutex_lock(&orbit.mutex);
    for (size_t i = 0; i < link_count; i++) cJSON_AddItemToArray(a, link_json(&links[i]));
    pthread_mutex_unlock(&orbit.mutex);
    return o;
}
static int save_links(const Link *items, size_t count) {
    cJSON *o = cJSON_CreateObject(), *a = cJSON_AddArrayToObject(o, "entries");
    cJSON_AddStringToObject(o, "format", "orbit-custom-catalogue");
    cJSON_AddNumberToObject(o, "version", 1);
    for (size_t i = 0; i < count; i++) cJSON_AddItemToArray(a, link_json(&items[i]));
    char *s = cJSON_PrintUnformatted(o);
    cJSON_Delete(o);
    if (!s) return -1;
    int fd = openat(orbit.state_fd, "custom-catalogue.tmp", O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0600), rc = -1;
    if (fd >= 0) {
        size_t n = strlen(s), p = 0;
        while (p < n) {
            ssize_t w = write(fd, s + p, n - p);
            if (w < 0 && errno == EINTR) continue;
            if (w <= 0) break;
            p += (size_t)w;
        }
        if (p == n && !fsync(fd)) rc = 0;
        if (close(fd)) rc = -1;
    }
    free(s);
    if (!rc) rc = renameat(orbit.state_fd, "custom-catalogue.tmp", orbit.state_fd, LINK_FILE);
    if (!rc) rc = fsync(orbit.state_fd);
    return rc;
}
/* Insert or update by url; a re-imported link keeps its id. Returns the new count. */
static size_t upsert(Link *items, size_t count, const Link *l, const char *wanted_id) {
    for (size_t i = 0; i < count; i++)
        if (!strcmp(items[i].url, l->url)) {
            char id[sizeof l->id];
            copy_text(id, sizeof id, items[i].id);
            items[i] = *l;
            copy_text(items[i].id, sizeof items[i].id, id);
            return count;
        }
    if (count >= LINK_MAX) return count;
    items[count] = *l;
    bool reuse = wanted_id && !strncmp(wanted_id, "link-", 5) && strlen(wanted_id) < sizeof l->id;
    for (const char *c = reuse ? wanted_id : ""; *c; c++) reuse = reuse && (isalnum((unsigned char)*c) || *c == '-');
    if (reuse) copy_text(items[count].id, sizeof items[count].id, wanted_id);
    else random_hex(items[count].id + snprintf(items[count].id, sizeof items[count].id, "link-"), 6);
    return count + 1;
}
int custom_catalog_action(const cJSON *input, cJSON **reply, char *error, size_t cap) {
    const char *action = json_text(input, "action");
    *reply = NULL;
    int code = 200;
    Link *next = calloc(LINK_MAX, sizeof *next); /* Heap: 600 KB would crowd a 1 MB thread stack. */
    if (!next) { copy_text(error, cap, "Out of memory."); return 503; }
    pthread_mutex_lock(&orbit.mutex);
    size_t count = 0;
    if (!strcmp(action, "clear") || !strcmp(action, "remove")) {
        const char *id = json_text(input, "id");
        for (size_t i = 0; i < link_count; i++)
            if (strcmp(action, "clear") && strcmp(links[i].id, id)) next[count++] = links[i];
        if (!strcmp(action, "remove") && count == link_count) { copy_text(error, cap, "No such link."); code = 404; }
    } else if (!strcmp(action, "import")) {
        const cJSON *doc = cJSON_GetObjectItemCaseSensitive(input, "catalogue");
        const cJSON *entries = cJSON_GetObjectItemCaseSensitive(doc ? doc : input, "entries");
        const char *format = json_text(doc ? doc : input, "format");
        if (!cJSON_IsArray(entries) || (*format && strcmp(format, "orbit-custom-catalogue")) ||
            cJSON_GetArraySize(entries) < 1 || cJSON_GetArraySize(entries) > LINK_MAX) {
            copy_text(error, cap, "Provide a catalogue with 1 to 256 entries."); code = 400;
        } else {
            if (!strcmp(json_text(input, "mode"), "merge")) { memcpy(next, links, link_count * sizeof *next); count = link_count; }
            cJSON *out = cJSON_CreateObject(), *rejected = cJSON_AddArrayToObject(out, "rejected");
            unsigned imported = 0;
            size_t index = 0;
            const cJSON *e;
            cJSON_ArrayForEach(e, entries) {
                Link l;
                char why[160] = {0};
                bool ok = link_parse(e, &l, why, sizeof why);
                bool known = false;
                for (size_t i = 0; ok && i < count; i++) known = known || !strcmp(next[i].url, l.url);
                if (ok && !known && count >= LINK_MAX) { copy_text(why, sizeof why, "Too many saved links."); ok = false; }
                if (ok) count = upsert(next, count, &l, NULL);
                if (ok) imported++;
                else {
                    cJSON *r = cJSON_CreateObject();
                    cJSON_AddNumberToObject(r, "index", (double)index);
                    cJSON_AddStringToObject(r, "reason", why);
                    cJSON_AddItemToArray(rejected, r);
                }
                index++;
            }
            cJSON_AddNumberToObject(out, "imported", imported);
            *reply = out;
        }
    } else { copy_text(error, cap, "Unknown action."); code = 400; }
    if (code == 200 && save_links(next, count)) {
        copy_text(error, cap, "Could not save your links."); code = 503;
        cJSON_Delete(*reply);
        *reply = NULL;
    } else if (code == 200) {
        memcpy(links, next, count * sizeof *links);
        link_count = count;
    }
    pthread_mutex_unlock(&orbit.mutex);
    free(next);
    return code;
}

int custom_start(void) {
    int fd = openat(orbit.state_fd, LINK_FILE, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return 0;
    struct stat st;
    char *s = NULL;
    if (!fstat(fd, &st) && S_ISREG(st.st_mode) && st.st_size > 0 && st.st_size <= LINK_FILE_LIMIT &&
        (s = calloc((size_t)st.st_size + 1, 1))) {
        size_t p = 0;
        while (p < (size_t)st.st_size) {
            ssize_t got = read(fd, s + p, (size_t)st.st_size - p);
            if (got <= 0) break;
            p += (size_t)got;
        }
        cJSON *doc = p == (size_t)st.st_size ? cJSON_Parse(s) : NULL;
        const cJSON *e;
        pthread_mutex_lock(&orbit.mutex);
        cJSON_ArrayForEach(e, cJSON_GetObjectItemCaseSensitive(doc, "entries")) {
            Link l;
            char why[160];
            if (link_parse(e, &l, why, sizeof why)) link_count = upsert(links, link_count, &l, json_text(e, "id"));
        }
        pthread_mutex_unlock(&orbit.mutex);
        cJSON_Delete(doc);
    }
    free(s);
    close(fd);
    return 0;
}

void custom_stop(void) {
    pthread_mutex_lock(&orbit.mutex);
    bool join = worker.started;
    worker.stop = true;
    atomic_store(&worker.cancel, true);
    pthread_cond_signal(&worker.changed);
    pthread_mutex_unlock(&orbit.mutex);
    if (join) pthread_join(worker.thread, NULL);
    cJSON_Delete(worker.result);
    worker.result = NULL;
}
