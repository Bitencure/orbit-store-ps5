/* Guarded link probe for user-added downloads (fork). One bounded request learns the
 * file's name, size, validators and Range support. HTML, errors and redirects to
 * hosts Orbit will not use are refused with a message that says what to do. */
#include "resolve.h"
#include "ca.h"
#include "provider_network.h"
#include <ctype.h>
#include <curl/curl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#define MAX_FILE_SIZE (1LL << 50)

typedef struct {
    Release gate;  /* Local release carrying only the provider, to reuse the transfer allowlist. */
    atomic_bool *cancel;
    CURL *handle;
    long status;
    int64_t length, start, end, total;
    char etag[256], modified[128], type[128], disposition[512], error[256];
    bool done, challenge;
} Probe;

static void trim_copy(char *out, size_t cap, const char *s, size_t n) {
    while (n && (*s == ' ' || *s == '\t')) { s++; n--; }
    while (n && (s[n - 1] == '\r' || s[n - 1] == '\n' || s[n - 1] == ' ')) n--;
    if (n >= cap) n = cap - 1;
    memcpy(out, s, n);
    out[n] = 0;
}
static bool lower_contains(const char *haystack, const char *needle) {
    size_t n = strlen(needle);
    for (; *haystack; haystack++)
        if (!strncasecmp(haystack, needle, n)) return true;
    return false;
}

static size_t probe_header(char *s, size_t a, size_t b, void *arg) {
    Probe *p = arg;
    size_t n = a * b;
    if (n > 5 && !strncmp(s, "HTTP/", 5)) {
        char line[100];
        trim_copy(line, sizeof line, s, n);
        const char *space = strchr(line, ' ');
        p->status = space ? strtol(space + 1, NULL, 10) : 0;
        /* libcurl reports every response of a redirect chain; none describes the next. */
        p->length = p->start = p->end = p->total = -1;
        p->etag[0] = p->modified[0] = p->type[0] = p->disposition[0] = p->error[0] = 0;
        p->challenge = false;
    } else if (n > 13 && !strncasecmp(s, "cf-mitigated:", 13)) {
        char value[32];
        trim_copy(value, sizeof value, s + 13, n - 13);
        p->challenge = lower_contains(value, "challenge");
    } else if (n > 15 && !strncasecmp(s, "Content-Length:", 15)) {
        p->length = strtoll(s + 15, NULL, 10);
    } else if (n > 14 && !strncasecmp(s, "Content-Range:", 14)) {
        long long x, y, z;
        if (sscanf(s + 14, " bytes %lld-%lld/%lld", &x, &y, &z) == 3) { p->start = x; p->end = y; p->total = z; }
    } else if (n > 5 && !strncasecmp(s, "ETag:", 5)) {
        trim_copy(p->etag, sizeof p->etag, s + 5, n - 5);
    } else if (n > 14 && !strncasecmp(s, "Last-Modified:", 14)) {
        trim_copy(p->modified, sizeof p->modified, s + 14, n - 14);
    } else if (n > 13 && !strncasecmp(s, "Content-Type:", 13)) {
        trim_copy(p->type, sizeof p->type, s + 13, n - 13);
    } else if (n > 20 && !strncasecmp(s, "Content-Disposition:", 20)) {
        trim_copy(p->disposition, sizeof p->disposition, s + 20, n - 20);
    } else if (n > 9 && !strncasecmp(s, "Location:", 9)) {
        char location[2100], *base = NULL, *resolved = NULL;
        if (n - 9 >= sizeof location) return 0;
        trim_copy(location, sizeof location, s + 9, n - 9);
        CURLU *u = curl_url();
        curl_easy_getinfo(p->handle, CURLINFO_EFFECTIVE_URL, &base);
        bool allowed = u && base && !curl_url_set(u, CURLUPART_URL, base, 0) &&
                       !curl_url_set(u, CURLUPART_URL, location, 0) &&
                       !curl_url_get(u, CURLUPART_URL, &resolved, 0) &&
                       provider_transfer_allowed(&p->gate, resolved);
        curl_free(resolved);
        curl_url_cleanup(u);
        if (!allowed) {
            copy_text(p->error, sizeof p->error, "The link redirects to a host Orbit will not download from.");
            return 0;
        }
    } else if ((n == 2 && s[0] == '\r') || (n == 1 && s[0] == '\n')) {
        if ((p->status >= 100 && p->status < 200) || (p->status >= 300 && p->status < 400)) return n;
        p->done = true;
        return 0; /* Headers are enough; never read the body. */
    }
    return n;
}
static size_t probe_body(char *d, size_t a, size_t b, void *arg) {
    (void)d; (void)a; (void)b; (void)arg;
    return 0;
}
static int probe_progress(void *arg, curl_off_t a, curl_off_t b, curl_off_t c, curl_off_t d) {
    (void)a; (void)b; (void)c; (void)d;
    Probe *p = arg;
    return p->cancel && atomic_load(p->cancel);
}
static int probe_prereq(void *arg, char *remote, char *local, int remote_port, int local_port) {
    (void)remote; (void)local; (void)remote_port; (void)local_port;
    Probe *p = arg;
    char *url = NULL;
    curl_easy_getinfo(p->handle, CURLINFO_EFFECTIVE_URL, &url);
    if (provider_transfer_allowed(&p->gate, url)) return CURL_PREREQFUNC_OK;
    copy_text(p->error, sizeof p->error, "The link redirects to a host Orbit will not download from.");
    return CURL_PREREQFUNC_ABORT;
}

static void http_message(long status, char *error, size_t cap) {
    copy_text(error, cap,
        status == 404 || status == 410 ? "The file was not found. It may have been removed, or the link has expired."
        : status == 401 || status == 403 ? "The host refused access. The link may have expired, or it needs a login or human verification."
        : status == 429 || status == 503 ? "The host is rate limiting or temporarily unavailable. Try again later."
        : status >= 500 ? "The host reported a server error. Try again later."
        : "The host did not return the file.");
}

int resolve_direct(const HostAdapter *host, const char *url, const char *wanted_name,
                   atomic_bool *cancel, Resolved *out, char *error, size_t cap) {
    memset(out, 0, sizeof *out);
    out->host = host;
    if (!host || (host->kind != HOST_WEB && host->kind != HOST_DIRECT) || !host_url_ok(url, NULL, 0)) {
        copy_text(error, cap, "Paste a complete https:// link to a file.");
        return -1;
    }
    Probe p = {.cancel = cancel};
    p.gate.local = true;
    copy_text(p.gate.source, sizeof p.gate.source, host->id);
    CURL *c = curl_easy_init();
    if (!c) { copy_text(error, cap, "Could not initialise HTTPS."); return -1; }
    p.handle = c;
    struct curl_blob ca = {(void *)orbit_ca, sizeof orbit_ca - 1, CURL_BLOB_COPY};
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_CAINFO_BLOB, &ca);
    curl_easy_setopt(c, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(c, CURLOPT_SSL_VERIFYHOST, 2L);
#ifdef ORBIT_TEST
    curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, "http,https");
    curl_easy_setopt(c, CURLOPT_REDIR_PROTOCOLS_STR, "http,https");
#else
    curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, "https");
    curl_easy_setopt(c, CURLOPT_REDIR_PROTOCOLS_STR, "https");
#endif
    curl_easy_setopt(c, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(c, CURLOPT_MAXREDIRS, 5L);
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(c, CURLOPT_CONNECTTIMEOUT, 15L);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(c, CURLOPT_USERAGENT, "OrbitStore/" ORBIT_VERSION);
    curl_easy_setopt(c, CURLOPT_PROXY, "");
    curl_easy_setopt(c, CURLOPT_RANGE, "0-0");
    curl_easy_setopt(c, CURLOPT_OPENSOCKETFUNCTION, provider_open_socket);
    curl_easy_setopt(c, CURLOPT_PREREQFUNCTION, probe_prereq);
    curl_easy_setopt(c, CURLOPT_PREREQDATA, &p);
    curl_easy_setopt(c, CURLOPT_HEADERFUNCTION, probe_header);
    curl_easy_setopt(c, CURLOPT_HEADERDATA, &p);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, probe_body);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &p);
    curl_easy_setopt(c, CURLOPT_NOPROGRESS, 0L);
    curl_easy_setopt(c, CURLOPT_XFERINFOFUNCTION, probe_progress);
    curl_easy_setopt(c, CURLOPT_XFERINFODATA, &p);
    CURLcode rc = curl_easy_perform(c);
    char *effective = NULL;
    curl_easy_getinfo(c, CURLINFO_EFFECTIVE_URL, &effective);
    char final_url[2048] = {0};
    if (effective) copy_text(final_url, sizeof final_url, effective);
    curl_easy_cleanup(c);

    if (p.error[0]) { copy_text(error, cap, p.error); return -1; }
    if (cancel && atomic_load(cancel)) { copy_text(error, cap, "Cancelled."); return -1; }
    if (!p.done) {
        snprintf(error, cap, "Could not reach the host (%s).", curl_easy_strerror(rc));
        return -1;
    }
    if (p.challenge) {
        /* Cloudflare is asking a person to prove they are one. Orbit does not try to answer that. */
        copy_text(error, cap, "This host is asking for human verification (Cloudflare), which Orbit cannot complete. Open the link in a browser instead, or use TorBox if it supports this host.");
        return -1;
    }
    if (p.status != 200 && p.status != 206) { http_message(p.status, error, cap); return -1; }
    if (lower_contains(p.type, "text/") || lower_contains(p.type, "json") || lower_contains(p.type, "xml")) {
        copy_text(error, cap, "This link opens a web page, not a file. Open it in a browser and copy the real download link.");
        return -1;
    }
    if (p.status == 206) {
        if (p.start != 0 || p.total < 1) { copy_text(error, cap, "The host returned an invalid byte range."); return -1; }
        out->size = p.total;
        out->ranges = true;
    } else {
        out->size = p.length;
    }
    if (out->size < 1) {
        copy_text(error, cap, "The host did not report the file size, so Orbit cannot queue it safely.");
        return -1;
    }
    if (out->size > MAX_FILE_SIZE) { copy_text(error, cap, "The file size is not valid."); return -1; }
    /* Take the first name that can be made safe: the user's, the host's, then the URL's own. */
    char candidates[4][512] = {{0}};
    if (wanted_name) copy_text(candidates[0], sizeof candidates[0], wanted_name);
    if (!wanted_name || !*wanted_name) {
        disposition_filename(p.disposition, candidates[1], sizeof candidates[1]);
        url_last_segment(final_url, candidates[2], sizeof candidates[2]);
        url_last_segment(url, candidates[3], sizeof candidates[3]);
    }
    bool named = false;
    for (size_t i = 0; i < 4 && !named; i++)
        named = candidates[i][0] && filename_sanitize(candidates[i], out->filename, sizeof out->filename);
    if (!named) {
        copy_text(error, cap, "Orbit could not work out a safe file name. Enter one below.");
        return -1;
    }
    bool strong = p.etag[0] == '"' && p.etag[strlen(p.etag) - 1] == '"' && !strstr(p.etag, "W/");
    copy_text(out->etag, sizeof out->etag, strong ? p.etag : "");
    copy_text(out->modified, sizeof out->modified, p.modified);
    copy_text(out->url, sizeof out->url, url);
    return 0;
}

static int cancel_progress(void *arg, curl_off_t a, curl_off_t b, curl_off_t c, curl_off_t d) {
    (void)a; (void)b; (void)c; (void)d;
    atomic_bool *cancel = arg;
    return cancel && atomic_load(cancel);
}
typedef struct { char *data; size_t length; } Body;
static size_t collect(char *d, size_t a, size_t b, void *arg) {
    Body *body = arg;
    size_t n = a * b;
    if (n > 100000 - body->length) return 0;
    char *next = realloc(body->data, body->length + n + 1);
    if (!next) return 0;
    body->data = next;
    memcpy(next + body->length, d, n);
    body->length += n;
    next[body->length] = 0;
    return n;
}

int resolve_viking(const char *page_url, atomic_bool *cancel, Resolved *out, char *error, size_t cap) {
    memset(out, 0, sizeof *out);
    out->host = host_by_id("vikingfile");
    const char *hash = strrchr(page_url, '/');
    char form[32];
    if (!hash || strlen(hash + 1) != 10 || snprintf(form, sizeof form, "hash=%s", hash + 1) < 0) {
        copy_text(error, cap, "Paste a Vikingfile link that looks like vikingfile.com/f/…");
        return -1;
    }
    for (const char *h = hash + 1; *h; h++)
        if (!isalnum((unsigned char)*h)) { copy_text(error, cap, "That Vikingfile link is not valid."); return -1; }
    const char *endpoint = "https://vikingfile.com/api/check-file";
#ifdef ORBIT_TEST
    const char *override = getenv("ORBIT_TEST_VIKING_API");
    if (override && !strncmp(override, "http://127.0.0.1:", 17)) endpoint = override;
#endif
    Body body = {0};
    CURL *c = curl_easy_init();
    if (!c) { copy_text(error, cap, "Could not initialise HTTPS."); return -1; }
    struct curl_blob ca = {(void *)orbit_ca, sizeof orbit_ca - 1, CURL_BLOB_COPY};
    curl_easy_setopt(c, CURLOPT_URL, endpoint);
    curl_easy_setopt(c, CURLOPT_CAINFO_BLOB, &ca);
    curl_easy_setopt(c, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(c, CURLOPT_SSL_VERIFYHOST, 2L);
#ifdef ORBIT_TEST
    curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, "http,https");
#else
    curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, "https");
#endif
    curl_easy_setopt(c, CURLOPT_FOLLOWLOCATION, 0L);
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(c, CURLOPT_CONNECTTIMEOUT, 15L);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 20L);
    curl_easy_setopt(c, CURLOPT_USERAGENT, "OrbitStore/" ORBIT_VERSION);
    curl_easy_setopt(c, CURLOPT_PROXY, "");
    curl_easy_setopt(c, CURLOPT_OPENSOCKETFUNCTION, provider_open_socket);
    curl_easy_setopt(c, CURLOPT_POSTFIELDS, form);
    curl_easy_setopt(c, CURLOPT_NOPROGRESS, 0L);
    curl_easy_setopt(c, CURLOPT_XFERINFOFUNCTION, cancel_progress);
    curl_easy_setopt(c, CURLOPT_XFERINFODATA, cancel);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, collect);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &body);
    CURLcode rc = curl_easy_perform(c);
    long status = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(c);
    int result = -1;
    if (cancel && atomic_load(cancel)) {
        copy_text(error, cap, "Cancelled.");
    } else if (rc != CURLE_OK || status != 200 || !body.data) {
        copy_text(error, cap, "Vikingfile did not answer. Try again later.");
    } else {
        cJSON *root = cJSON_Parse(body.data);
        const cJSON *json = root;
        if (cJSON_IsArray(root) && cJSON_GetArraySize(root) == 1) json = cJSON_GetArrayItem(root, 0);
        const cJSON *exist = cJSON_GetObjectItemCaseSensitive(json, "exist");
        const cJSON *name = cJSON_GetObjectItemCaseSensitive(json, "name");
        const cJSON *size = cJSON_GetObjectItemCaseSensitive(json, "size");
        char clean[sizeof out->filename];
        if (!cJSON_IsTrue(exist)) {
            copy_text(error, cap, "Vikingfile says this file no longer exists.");
        } else if (!cJSON_IsString(name) || !cJSON_IsNumber(size) || size->valuedouble < 1 ||
                   size->valuedouble > (double)MAX_FILE_SIZE ||
                   !filename_sanitize(name->valuestring, clean, sizeof clean)) {
            copy_text(error, cap, "Vikingfile returned an unusable file listing.");
        } else if (strcmp(clean, name->valuestring)) {
            /* The generated /d/ link carries the exact name; a changed name could never match it. */
            copy_text(error, cap, "This file's name has characters Orbit cannot save safely.");
        } else {
            copy_text(out->filename, sizeof out->filename, clean);
            out->size = (int64_t)size->valuedouble;
            copy_text(out->url, sizeof out->url, page_url);
            result = 0;
        }
        cJSON_Delete(root);
    }
    free(body.data);
    return result;
}
