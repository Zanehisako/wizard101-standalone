#include "SteamBridge.h"
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <stdatomic.h>
#include <time.h>

/* Steam's public flat C ABI. CallbackMsg_t uses native pointer alignment. */
typedef struct { int user, callback; uint8_t *data; int size; } Callback;
typedef struct { uint32_t handle; int result, length; uint8_t bytes[2560]; } WebTicket;
struct W101Steam {
    void *library, *user;
    int pipe;
    uint32_t ticket;
    uint32_t (*request)(void *, const char *);
    double next_request;
    bool initialized;
    char *previous_app, *previous_game;
    void (*shutdown)(void);
    void (*run)(int);
    bool (*next)(int, Callback *);
    void (*free_callback)(int);
    bool (*logged_on)(void *);
    uint64_t (*steam_id)(void *);
    void (*cancel)(void *, uint32_t);
};
static atomic_flag lock = ATOMIC_FLAG_INIT;
static double monotonic_time(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (double)now.tv_sec + (double)now.tv_nsec / 1000000000.0;
}
static void wipe(void *memory, size_t size) {
    volatile uint8_t *bytes = memory;
    while (size--) *bytes++ = 0;
}

void w101_steam_close(W101Steam *s) {
    if (!s) return;
    if (s->initialized) {
        if (s->ticket && s->user && s->cancel) s->cancel(s->user, s->ticket);
        if (s->shutdown) s->shutdown();
    }
    if (s->previous_app) { setenv("SteamAppId", s->previous_app, 1); free(s->previous_app); }
    else unsetenv("SteamAppId");
    if (s->previous_game) { setenv("SteamGameId", s->previous_game, 1); free(s->previous_game); }
    else unsetenv("SteamGameId");
    if (s->library) dlclose(s->library);
    wipe(s, sizeof(*s)); free(s);
    atomic_flag_clear(&lock);
}

int w101_steam_open(const char *library, W101Steam **out) {
    if (!out || !library) return -1;
    *out = NULL;
    if (atomic_flag_test_and_set(&lock)) return -6;
    W101Steam *s = calloc(1, sizeof(*s));
    if (!s) { atomic_flag_clear(&lock); return -1; }
    const char *previous = getenv("SteamAppId"); s->previous_app = previous ? strdup(previous) : NULL;
    previous = getenv("SteamGameId"); s->previous_game = previous ? strdup(previous) : NULL;
    s->library = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!s->library) { w101_steam_close(s); return -1; }
    int (*init)(char *) = dlsym(s->library, "SteamAPI_InitFlat");
    void (*manual_init)(void) = dlsym(s->library, "SteamAPI_ManualDispatch_Init");
    int (*get_pipe)(void) = dlsym(s->library, "SteamAPI_GetHSteamPipe");
    void *(*get_user)(void) = dlsym(s->library, "SteamAPI_SteamUser_v023");
    void *(*get_apps)(void) = dlsym(s->library, "SteamAPI_SteamApps_v009");
    if (!get_apps) get_apps = dlsym(s->library, "SteamAPI_SteamApps_v008");
    void *(*get_utils)(void) = dlsym(s->library, "SteamAPI_SteamUtils_v011");
    if (!get_utils) get_utils = dlsym(s->library, "SteamAPI_SteamUtils_v010");
    uint32_t (*app_id)(void *) = dlsym(s->library, "SteamAPI_ISteamUtils_GetAppID");
    bool (*owns)(void *, uint32_t) = dlsym(s->library, "SteamAPI_ISteamApps_BIsSubscribedApp");
    s->request = dlsym(s->library, "SteamAPI_ISteamUser_GetAuthTicketForWebApi");
    s->shutdown = dlsym(s->library, "SteamAPI_Shutdown");
    s->run = dlsym(s->library, "SteamAPI_ManualDispatch_RunFrame");
    s->next = dlsym(s->library, "SteamAPI_ManualDispatch_GetNextCallback");
    s->free_callback = dlsym(s->library, "SteamAPI_ManualDispatch_FreeLastCallback");
    s->logged_on = dlsym(s->library, "SteamAPI_ISteamUser_BLoggedOn");
    s->steam_id = dlsym(s->library, "SteamAPI_ISteamUser_GetSteamID");
    s->cancel = dlsym(s->library, "SteamAPI_ISteamUser_CancelAuthTicket");
    if (!init || !manual_init || !get_pipe || !get_user || !get_apps || !get_utils || !app_id || !owns || !s->request ||
        !s->shutdown || !s->run || !s->next || !s->free_callback || !s->logged_on || !s->steam_id || !s->cancel) {
        w101_steam_close(s); return -1;
    }
    setenv("SteamAppId", "799960", 1); setenv("SteamGameId", "799960", 1);
    char message[1024] = {0};
    int result = init(message); wipe(message, sizeof(message));
    if (result != 0) { w101_steam_close(s); return -2; }
    s->initialized = true;
    s->user = get_user(); s->pipe = get_pipe();
    void *utils = get_utils(), *apps = get_apps();
    if (!s->user || !utils || !apps || s->pipe == 0 || app_id(utils) != 799960) { w101_steam_close(s); return -2; }
    if (!s->logged_on(s->user)) { w101_steam_close(s); return -3; }
    if (!owns(apps, 799960)) { w101_steam_close(s); return -4; }
    manual_init();
    *out = s; return 0;
}

int w101_steam_poll(W101Steam *s, uint64_t *user, uint8_t *ticket, size_t capacity, size_t *length) {
    if (!s || !user || !ticket || !length) return -5;
    *length = 0;
    if (!s->logged_on(s->user)) return -3;
    s->run(s->pipe);
    /* A running, logged-in Mac client can initially return an invalid handle
       while this app's Steam connection starts. Pump callbacks and retry only
       this preparation step, leaving the caller's cancellation/deadline active.
       Never request another ticket once Steam has accepted one. */
    double now = monotonic_time();
    if (!s->ticket && now >= s->next_request) {
        /* Verified in the official r806919 client: Web API ticket for "Wizard101". */
        s->ticket = s->request(s->user, "Wizard101");
        s->next_request = now + 1.0;
    }
    Callback callback;
    /* Bound callback work so cancellation is checked even under a busy client. */
    for (int count = 0; count < 64 && s->next(s->pipe, &callback); ++count) {
        int result = 0;
        if (s->ticket && callback.callback == 168) { /* GetTicketForWebApiResponse_t */
            if (!callback.data || callback.size < (int)sizeof(WebTicket)) result = -5;
            else {
                WebTicket response;
                memcpy(&response, callback.data, sizeof(response));
                if (response.handle == s->ticket) {
                    if (response.result != 1 || response.length <= 0 || response.length > 2560 || (size_t)response.length > capacity) result = -5;
                    else {
                        *user = s->steam_id(s->user);
                        if (!*user) result = -3;
                        else { *length = (size_t)response.length; memcpy(ticket, response.bytes, *length); result = 1; }
                    }
                }
                wipe(&response, sizeof(response));
            }
        }
        s->free_callback(s->pipe);
        if (result) return result;
    }
    return 0;
}
