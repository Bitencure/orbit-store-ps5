/* Unit tests for the fork's host table, URL checks and filename handling.
 * Built WITHOUT ORBIT_TEST so the production allowlists and the socket guard are what run. */
#include "hosts.h"
#include "orbit.h"
#include "provider_network.h"
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static int failures, checks;
#define CHECK(cond) do { checks++; if (!(cond)) { failures++; fprintf(stderr, "FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define CHECK_STR(actual, expected) do { checks++; const char *a_ = (actual), *e_ = (expected); \
    if (!a_ || strcmp(a_, e_)) { failures++; fprintf(stderr, "FAIL %s:%d  got \"%s\" want \"%s\"\n", __FILE__, __LINE__, a_ ? a_ : "(null)", e_); } } while (0)

static const char *id_of(const char *url) { const HostAdapter *h = host_for_url(url); return h ? h->id : NULL; }
static bool allowed(const char *source, bool local, const char *url) {
    Release r = {0};
    r.local = local;
    strcpy(r.source, source);
    return provider_transfer_allowed(&r, url);
}
static bool socket_allowed(const char *ip) {
    struct curl_sockaddr a = {.family = AF_INET, .socktype = SOCK_STREAM, .addrlen = sizeof(struct sockaddr_in)};
    struct sockaddr_in *in = (struct sockaddr_in *)&a.addr;
    in->sin_family = AF_INET;
    inet_pton(AF_INET, ip, &in->sin_addr);
    curl_socket_t s = provider_open_socket(NULL, CURLSOCKTYPE_IPCXN, &a);
    if (s != CURL_SOCKET_BAD) close(s);
    return s != CURL_SOCKET_BAD;
}
static bool socket6_allowed(const char *ip) {
    struct curl_sockaddr a = {.family = AF_INET6, .socktype = SOCK_STREAM, .addrlen = sizeof(struct sockaddr_in6)};
    struct sockaddr_in6 *in = (struct sockaddr_in6 *)&a.addr;
    in->sin6_family = AF_INET6;
    inet_pton(AF_INET6, ip, &in->sin6_addr);
    curl_socket_t s = provider_open_socket(NULL, CURLSOCKTYPE_IPCXN, &a);
    if (s != CURL_SOCKET_BAD) close(s);
    return s != CURL_SOCKET_BAD;
}
static const char *clean(const char *in) {
    static char out[160];
    return filename_sanitize(in, out, sizeof out) ? out : NULL;
}

int main(void) {
    /* Provider identification is by real domain, never by label or substring. */
    CHECK_STR(id_of("https://vikingfile.com/f/abcdefghij"), "vikingfile");
    CHECK_STR(id_of("https://vik1ngfile.site/f/abcdefghij"), "vikingfile");
    CHECK_STR(id_of("https://akirabox.to/abcdefghijkl/file"), "akirabox");
    CHECK_STR(id_of("https://datanodes.to/abcdefghijkl"), "datanodes");
    CHECK_STR(id_of("https://1fichier.com/?abcdefghij0123456789"), "1fichier");
    CHECK_STR(id_of("https://alterupload.com/?abcdefghij0123456789"), "1fichier");
    CHECK_STR(id_of("https://store1.gofile.io/download/web/x/y.bin"), "gofile");
    CHECK_STR(id_of("https://gofile.io/d/AbCdEf"), "gofile");
    CHECK_STR(id_of("https://fileditch.com/abc/file.bin"), "fileditch");
    CHECK_STR(id_of("https://new.fileditch.com/x"), "fileditch");
    CHECK_STR(id_of("https://itsfileditchfiles.st/balpha34/abc/x.bin"), "fileditch");
    CHECK_STR(id_of("https://fileditchvids.st/a/b/c.mp4"), "fileditch");
    CHECK_STR(id_of("https://fuckingfast.co/abc"), "fuckingfast");
    CHECK_STR(id_of("https://rootz.so/file/abc"), "rootz");
    CHECK_STR(id_of("https://downloads.example.org/a.bin"), "web");
    /* Public archive.org files are ordinary direct links; the catalogue keeps its own login-aware source. */
    CHECK_STR(id_of("https://archive.org/download/some-item/file.bin"), "web");
    /* Look-alikes must not inherit a named host's rules or toggle. */
    CHECK_STR(id_of("https://vikingfile.com.evil.example/f/abcdefghij"), "web");
    CHECK_STR(id_of("https://notvikingfile.com/f/abc"), "web");
    CHECK_STR(id_of("https://evil.example/gofile.io"), "web");
    CHECK_STR(id_of("https://gofile.io.attacker.test/d/x"), "web");
    /* Unacceptable URLs. */
    CHECK(!host_for_url("http://downloads.example.org/a.bin"));
    CHECK(!host_for_url("ftp://downloads.example.org/a.bin"));
    CHECK(!host_for_url("file:///etc/passwd"));
    CHECK(!host_for_url("https://user:pw@downloads.example.org/a.bin"));
    CHECK(!host_for_url("https://downloads.example.org:8443/a.bin"));
    CHECK_STR(id_of("https://downloads.example.org:443/a.bin"), "web");
    CHECK(!host_for_url("https://downloads.example.org/a.bin#frag"));
    CHECK(!host_for_url("https://127.0.0.1/a.bin"));
    CHECK(!host_for_url("https://10.0.0.5/a.bin"));
    CHECK(!host_for_url("https://[::1]/a.bin"));
    CHECK(!host_for_url("https://2130706433/a.bin"));
    CHECK(!host_for_url("https://localhost/a.bin"));
    CHECK(!host_for_url("https://intranet/a.bin"));
    CHECK(!host_for_url("https://exa mple.com/a.bin"));
    CHECK(!host_for_url("https://example.com/a b"));
    CHECK(!host_for_url("https://example.com/\\evil"));
    CHECK(!host_for_url(""));
    CHECK(!host_for_url("not a url"));
    char longurl[2200] = "https://example.com/";
    memset(longurl + 20, 'a', 2100);
    longurl[2120] = 0;
    CHECK(!host_for_url(longurl));
    /* Host name syntax. */
    CHECK(host_name_ok("example.com") && host_name_ok("a-b.example.co.uk") && host_name_ok("xn--bcher-kva.example"));
    CHECK(!host_name_ok("-bad.example.com") && !host_name_ok("bad-.example.com") && !host_name_ok("a..b.com"));
    CHECK(!host_name_ok("1.2.3.4") && !host_name_ok("127.1") && !host_name_ok("localhost"));
    /* Which kinds are downloadable. */
    CHECK(host_by_id("web")->kind == HOST_WEB);
    CHECK(host_by_id("fileditch")->kind == HOST_DISABLED && *host_by_id("fileditch")->note);
    CHECK(host_by_id("rootz")->kind == HOST_DISABLED && *host_by_id("rootz")->note);
    CHECK(host_by_id("fuckingfast")->kind == HOST_TORBOX && host_by_id("gofile")->kind == HOST_TORBOX);
    CHECK(host_by_id("vikingfile")->kind == HOST_BROWSER);
    CHECK(!host_by_id("nonsense") && !host_by_id(NULL));
    CHECK(!provider_direct_source("vikingfile") && provider_direct_source("web"));
    CHECK(!provider_direct_source("fileditch") && !provider_direct_source("rootz") && !provider_direct_source("gofile") && !provider_direct_source("fuckingfast"));

    /* 1fichier alias canonicalisation. */
    char out[256];
    CHECK(host_canonical_url("https://alterupload.com/?abcdefghij0123456789", out, sizeof out));
    CHECK_STR(out, "https://1fichier.com/?abcdefghij0123456789");
    CHECK(host_canonical_url("https://1fichier.com/?abcdefghij0123456789&lg=en", out, sizeof out));
    CHECK_STR(out, "https://1fichier.com/?abcdefghij0123456789");
    CHECK(!host_canonical_url("https://1fichier.com/?AB", out, sizeof out));
    CHECK(!host_canonical_url("https://example.com/?abcdefghij0123456789", out, sizeof out));

    /* Transfer allowlist: named direct hosts stay on their domains; web accepts any public name. */
    CHECK(allowed("web", true, "https://cdn.example.org/a.bin"));
    CHECK(!allowed("web", true, "http://cdn.example.org/a.bin"));
    CHECK(!allowed("web", true, "https://203.0.113.9/a.bin"));
    CHECK(!allowed("web", true, "https://u:p@cdn.example.org/a.bin"));
    CHECK(!allowed("fileditch", true, "https://new.fileditch.com/a.bin"));
    CHECK(!allowed("fileditch", true, "https://cdn.example.org/a.bin"));
    CHECK(!allowed("fileditch", true, "https://vikingfile.com/d/abcdefghij/a.bin"));
    CHECK(!allowed("rootz", true, "https://rootz.so/a.bin"));
    CHECK(!allowed("gofile", true, "https://store1.gofile.io/a.bin"));
    /* A catalogue (non-local) release keeps the original fixed list only. */
    CHECK(!allowed("vikingfile", false, "https://cdn.example.org/a.bin"));
    CHECK(allowed("vikingfile", false, "https://vikingfile.com/d/abcdefghij/a.bin"));
    CHECK(!allowed("archive", false, "https://cdn.example.org/a.bin"));

    /* The connect-time guard refuses private, loopback and special ranges (DNS rebinding included). */
    CHECK(socket_allowed("93.184.216.34") && socket_allowed("8.8.8.8"));
    const char *blocked[] = {"127.0.0.1", "10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.1.1", "169.254.1.1",
                             "100.64.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255", "192.0.0.1", "192.0.2.1",
                             "198.18.0.1", "198.51.100.1", "203.0.113.1"};
    for (size_t i = 0; i < sizeof blocked / sizeof blocked[0]; i++) {
        checks++;
        if (socket_allowed(blocked[i])) { failures++; fprintf(stderr, "FAIL socket allowed %s\n", blocked[i]); }
    }
    CHECK(socket6_allowed("2606:4700:4700::1111"));
    CHECK(!socket6_allowed("::1") && !socket6_allowed("fe80::1") && !socket6_allowed("fc00::1") &&
          !socket6_allowed("::ffff:127.0.0.1") && !socket6_allowed("2001:db8::1") && !socket6_allowed("2002::1"));

    /* Filename sanitising. */
    CHECK_STR(clean("game.exfat"), "game.exfat");
    CHECK_STR(clean("dir/sub/game.exfat"), "game.exfat");
    CHECK_STR(clean("..\\..\\win\\game.pkg"), "game.pkg");
    CHECK_STR(clean("../../etc/passwd"), "passwd");
    CHECK(!clean("..") && !clean(".") && !clean("") && !clean("   ") && !clean("/") && !clean("./"));
    CHECK_STR(clean("a:b*c?.bin"), "a_b_c_.bin");
    CHECK_STR(clean("a\x01z.bin"), "a_z.bin");
    CHECK_STR(clean(" lead and trail. "), "lead and trail");
    CHECK_STR(clean("a..b...c.bin"), "a.b.c.bin");
    CHECK_STR(clean("x.PART"), "x_PART");
    CHECK_STR(clean("caf\xc3\xa9.bin"), "caf\xc3\xa9.bin");
    CHECK_STR(clean("bad\xff.bin"), "bad_.bin");
    char lng[400];
    memset(lng, 'a', 300);
    strcpy(lng + 300, ".exfat");
    const char *cut = clean(lng);
    CHECK(cut && strlen(cut) == 159 && !strcmp(cut + strlen(cut) - 6, ".exfat"));

    /* Percent-decoding and Content-Disposition. */
    char dec[64];
    CHECK(pct_decode("a%20b", 5, dec, sizeof dec) && !strcmp(dec, "a b"));
    CHECK(!pct_decode("a%2", 3, dec, sizeof dec) && !pct_decode("a%zz", 4, dec, sizeof dec) && !pct_decode("a%00b", 5, dec, sizeof dec));
    CHECK(!pct_decode("abcdef", 6, dec, 4));
    CHECK(disposition_filename("attachment; filename=\"My File.bin\"", dec, sizeof dec) && !strcmp(dec, "My File.bin"));
    CHECK(disposition_filename("attachment; filename=plain.bin", dec, sizeof dec) && !strcmp(dec, "plain.bin"));
    CHECK(disposition_filename("attachment; filename=\"fallback.bin\"; filename*=UTF-8''%E2%82%AC.bin", dec, sizeof dec) &&
          !strcmp(dec, "\xe2\x82\xac.bin"));
    CHECK(disposition_filename("attachment; filename=\"a\\\"b.bin\"", dec, sizeof dec) && !strcmp(dec, "a\"b.bin"));
    CHECK(!disposition_filename("inline", dec, sizeof dec) && !disposition_filename("", dec, sizeof dec));
    CHECK(!disposition_filename("attachment; filename*=ISO-8859-1''x.bin", dec, sizeof dec));
    CHECK(url_last_segment("https://h.example/a/b%20c.bin?x=1", dec, sizeof dec) && !strcmp(dec, "b c.bin"));
    CHECK(!url_last_segment("https://h.example/", dec, sizeof dec));

    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
