/* File-host adapter table and URL/filename helpers (fork). */
#include "hosts.h"
#include "orbit.h"
#include <curl/curl.h>
#include <string.h>
#include <strings.h>

static const char *const viking_domains[] = {"vikingfile.com", "vik1ngfile.site", "vikingf1le.us.to", NULL};
static const char *const akira_domains[] = {"akirabox.com", "akirabox.to", NULL};
static const char *const data_domains[] = {"datanodes.to", NULL};
/* Every domain below serves the same 1fichier file ids (api.1fichier.com domain list). */
static const char *const fichier_domains[] = {"1fichier.com", "alterupload.com", "cjoint.net", "desfichiers.com",
    "dfichiers.com", "megadl.fr", "mesfichiers.org", "piecejointe.net", "pjointe.com", "tenvoi.com", "dl4free.com", NULL};
static const char *const archive_domains[] = {"archive.org", NULL};
static const char *const gofile_domains[] = {"gofile.io", NULL};
static const char *const ditch_domains[] = {"fileditch.com", NULL};
static const char *const fast_domains[] = {"fuckingfast.co", NULL};
static const char *const rootz_domains[] = {"rootz.so", NULL};
static const char *const no_domains[] = {NULL};

/* Existing providers keep their own page and route validation (providers.c);
 * this table only identifies them. Aliases are search hints from user-supplied labels. */
static const HostAdapter hosts[] = {
    {"vikingfile", "Vikingfile", "viki vikingfile1", viking_domains, HOST_BROWSER, ORBIT_SOURCE_VIKINGFILE, ""},
    {"akirabox", "AkiraBox", "akia akira", akira_domains, HOST_BROWSER, ORBIT_SOURCE_AKIRABOX, ""},
    {"datanodes", "DataNodes", "data", data_domains, HOST_BROWSER, ORBIT_SOURCE_DATANODES, ""},
    {"1fichier", "1Fichier", "1fichier", fichier_domains, HOST_BROWSER, ORBIT_SOURCE_ONEFICHIER, ""},
    {"archive", "Archive.org", "archive", archive_domains, HOST_DISABLED, ORBIT_SOURCE_ARCHIVE,
     "Archive.org links are added from the catalogue. Paste other direct links instead."},
    {"gofile", "Gofile", "gofile1", gofile_domains, HOST_DISABLED, ORBIT_SOURCE_GOFILE,
     "Gofile is recognised, but its download flow is not verified in this build."},
    {"fileditch", "FileDitch", "dith fileditch1 ditch", ditch_domains, HOST_DIRECT, ORBIT_SOURCE_FILEDITCH, ""},
    {"fuckingfast", "FuckingFast", "fuckingfast1 fast", fast_domains, HOST_DISABLED, 0,
     "FuckingFast needs Cloudflare verification and its download flow is not verified in this build."},
    {"rootz", "Rootz", "rootz1", rootz_domains, HOST_DISABLED, 0,
     "Rootz is recognised, but no verifiable public download flow exists for it yet."},
    {"web", "Direct link", "http https direct", no_domains, HOST_WEB, ORBIT_SOURCE_WEB, ""},
};

size_t host_count(void) { return sizeof hosts / sizeof hosts[0]; }
const HostAdapter *host_at(size_t i) { return i < host_count() ? &hosts[i] : NULL; }
const HostAdapter *host_by_id(const char *id) {
    for (size_t i = 0; id && i < host_count(); i++)
        if (!strcmp(hosts[i].id, id)) return &hosts[i];
    return NULL;
}
bool host_domain_match(const HostAdapter *h, const char *name) {
    size_t n = name ? strlen(name) : 0;
    for (const char *const *d = h ? h->domains : NULL; d && *d; d++) {
        size_t k = strlen(*d);
        if (n == k && !strcasecmp(name, *d)) return true;
        if (n > k + 1 && name[n - k - 1] == '.' && !strcasecmp(name + n - k, *d)) return true;
    }
    return false;
}

static bool ascii_alnum(unsigned char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
}
bool host_name_ok(const char *n) {
    size_t len = n ? strlen(n) : 0, label = 0;
    unsigned dots = 0;
    if (len < 3 || len > 253) return false;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)n[i];
        if (c == '.') {
            if (!label || n[i - 1] == '-') return false;
            dots++; label = 0;
            continue;
        }
        if (!ascii_alnum(c) && c != '-') return false;
        if ((!label && c == '-') || ++label > 63) return false;
    }
    if (!label || n[len - 1] == '-' || !dots) return false;
    /* A numeric last label would be an IPv4 literal, including 127.1 and decimal forms. */
    bool letter = false;
    for (const char *p = strrchr(n, '.') + 1; *p; p++)
        if (!ascii_alnum((unsigned char)*p) || (*p > '9')) letter = true;
    return letter;
}

bool host_url_ok(const char *url, char *name, size_t cap) {
    if (!url || strlen(url) > 2047) return false;
    for (const unsigned char *p = (const void *)url; *p; p++)
        if (*p <= 32 || *p >= 127 || *p == '\\') return false;
    CURLU *u = curl_url();
    if (!u) return false;
    char *scheme = NULL, *host = NULL, *port = NULL, *user = NULL, *password = NULL, *fragment = NULL;
    bool ok = !curl_url_set(u, CURLUPART_URL, url, 0) &&
              !curl_url_get(u, CURLUPART_SCHEME, &scheme, 0) &&
              !curl_url_get(u, CURLUPART_HOST, &host, 0);
    curl_url_get(u, CURLUPART_PORT, &port, 0);
    curl_url_get(u, CURLUPART_USER, &user, 0);
    curl_url_get(u, CURLUPART_PASSWORD, &password, 0);
    curl_url_get(u, CURLUPART_FRAGMENT, &fragment, 0);
    ok = ok && !user && !password && !fragment;
#ifdef ORBIT_TEST
    ok = ok && !strcmp(scheme, "http") && !strcmp(host, "127.0.0.1");
#else
    ok = ok && !strcmp(scheme, "https") && (!port || !strcmp(port, "443")) && host_name_ok(host);
#endif
    if (ok && name) {
        if (strlen(host) >= cap) ok = false;
        else for (size_t i = 0; (name[i] = (char)((host[i] >= 'A' && host[i] <= 'Z') ? host[i] + 32 : host[i])); i++) {}
    }
    curl_free(scheme); curl_free(host); curl_free(port); curl_free(user); curl_free(password);
    curl_free(fragment); curl_url_cleanup(u);
    return ok;
}

const HostAdapter *host_for_url(const char *url) {
    char name[256];
    if (!host_url_ok(url, name, sizeof name)) return NULL;
    for (size_t i = 0; i < host_count(); i++)
        if (host_domain_match(&hosts[i], name)) return &hosts[i];
    return host_by_id("web");
}

bool host_canonical_url(const char *url, char *out, size_t cap) {
    char name[256];
    const HostAdapter *h = host_by_id("1fichier");
    if (!host_url_ok(url, name, sizeof name) || !host_domain_match(h, name)) return false;
    CURLU *u = curl_url();
    char *query = NULL;
    bool ok = u && !curl_url_set(u, CURLUPART_URL, url, 0) && !curl_url_get(u, CURLUPART_QUERY, &query, 0);
    char id[24] = {0};
    if (ok) {
        size_t n = strcspn(query, "&");
        ok = n >= 5 && n <= 20;
        for (size_t i = 0; ok && i < n; i++)
            ok = (query[i] >= 'a' && query[i] <= 'z') || (query[i] >= '0' && query[i] <= '9');
        if (ok) memcpy(id, query, n);
    }
    curl_free(query);
    curl_url_cleanup(u);
    if (!ok) return false;
    return snprintf(out, cap, "https://1fichier.com/?%s", id) < (int)cap;
}

static int utf8_length(const unsigned char *p) {
    if (*p < 0x80) return 1;
    int n = (*p & 0xe0) == 0xc0 ? 2 : (*p & 0xf0) == 0xe0 ? 3 : (*p & 0xf8) == 0xf0 ? 4 : 0;
    if (!n || (*p == 0xc0) || (*p == 0xc1) || *p > 0xf4) return 0;
    for (int i = 1; i < n; i++)
        if ((p[i] & 0xc0) != 0x80) return 0;
    return n;
}
bool filename_sanitize(const char *in, char *out, size_t cap) {
    if (!in || cap < 2) return false;
    const char *base = in;
    for (const char *p = in; *p; p++)
        if (*p == '/' || *p == '\\') base = p + 1;
    char tmp[1024];
    size_t n = 0;
    for (const unsigned char *p = (const void *)base; *p && n + 5 < sizeof tmp;) {
        int len = utf8_length(p);
        if (!len) { tmp[n++] = '_'; p++; continue; }
        if (len == 1) {
            tmp[n++] = (*p < 32 || *p == 127 || strchr("<>:\"|?*", *p)) ? '_' : (char)*p;
            p++;
        } else { memcpy(tmp + n, p, (size_t)len); n += (size_t)len; p += len; }
    }
    tmp[n] = 0;
    for (char *d; (d = strstr(tmp, "..")); ) memmove(d + 1, d + 2, strlen(d + 2) + 1);
    char *start = tmp;
    while (*start == ' ' || *start == '.') start++;
    size_t end = strlen(start);
    while (end && (start[end - 1] == ' ' || start[end - 1] == '.')) end--;
    if (!end) return false;
    start[end] = 0;
    if (end > cap - 1) {
        const char *dot = strrchr(start, '.');
        size_t ext = dot && (size_t)(start + end - dot) <= 16 ? (size_t)(start + end - dot) : 0;
        size_t stem = cap - 1 - ext;
        while (stem && (start[stem] & 0xc0) == 0x80) stem--;
        if (!stem) return false;
        memmove(start + stem, start + end - ext, ext + 1);
        end = stem + ext;
    }
    /* A name ending in .part would collide with Orbit's own partial file. */
    if (end > 5 && !strcasecmp(start + end - 5, ".part")) start[end - 5] = '_';
    memcpy(out, start, end + 1);
    return true;
}

bool pct_decode(const char *in, size_t length, char *out, size_t cap) {
    size_t n = 0;
    for (size_t i = 0; i < length; i++) {
        unsigned char c = (unsigned char)in[i];
        if (c == '%') {
            if (i + 2 >= length) return false;
            int a = in[i + 1], b = in[i + 2];
            a = a >= '0' && a <= '9' ? a - '0' : a >= 'a' && a <= 'f' ? a - 'a' + 10 : a >= 'A' && a <= 'F' ? a - 'A' + 10 : -1;
            b = b >= '0' && b <= '9' ? b - '0' : b >= 'a' && b <= 'f' ? b - 'a' + 10 : b >= 'A' && b <= 'F' ? b - 'A' + 10 : -1;
            if (a < 0 || b < 0 || (!a && !b)) return false;
            c = (unsigned char)(a * 16 + b);
            i += 2;
        }
        if (n + 1 >= cap) return false;
        out[n++] = (char)c;
    }
    out[n] = 0;
    return true;
}

bool disposition_filename(const char *header, char *out, size_t cap) {
    char plain[512] = {0}, extended[512] = {0};
    const char *p = strchr(header ? header : "", ';');
    while (p && *p) {
        p++;
        while (*p == ' ' || *p == '\t') p++;
        bool star = !strncasecmp(p, "filename*=", 10), name = star || !strncasecmp(p, "filename=", 9);
        if (!name) { p = strchr(p, ';'); continue; }
        p += star ? 10 : 9;
        while (*p == ' ' || *p == '\t') p++;
        bool quoted = *p == '"';
        char value[512];
        size_t n = 0;
        if (quoted) p++;
        while (*p && (quoted ? *p != '"' : *p != ';')) {
            if (quoted && *p == '\\' && p[1]) p++;
            if (n + 1 >= sizeof value) return false;
            value[n++] = *p++;
        }
        while (!quoted && n && (value[n - 1] == ' ' || value[n - 1] == '\t')) n--;
        value[n] = 0;
        if (star) {
            const char *tick = !strncasecmp(value, "UTF-8'", 6) ? strchr(value + 6, '\'') : NULL;
            if (!tick || !pct_decode(tick + 1, strlen(tick + 1), extended, sizeof extended)) extended[0] = 0;
        } else memcpy(plain, value, n + 1);
        if (quoted && *p == '"') p++;
        p = strchr(p, ';');
    }
    const char *chosen = extended[0] ? extended : plain;
    if (!*chosen || strlen(chosen) >= cap) return false;
    memcpy(out, chosen, strlen(chosen) + 1);
    return true;
}

bool url_last_segment(const char *url, char *out, size_t cap) {
    CURLU *u = curl_url();
    char *path = NULL;
    bool ok = u && !curl_url_set(u, CURLUPART_URL, url, 0) && !curl_url_get(u, CURLUPART_PATH, &path, 0);
    if (ok) {
        const char *last = strrchr(path, '/');
        last = last ? last + 1 : path;
        ok = *last && pct_decode(last, strlen(last), out, cap);
    }
    curl_free(path);
    curl_url_cleanup(u);
    return ok;
}
