#include "CryptoBridge.h"
#include "Twofish/twofish.h"
#include <pthread.h>
#include <string.h>
#include <zlib.h>
#include <libproc.h>
#include <sys/proc_info.h>
#include <unistd.h>
#include <stdlib.h>
#include <limits.h>
#include <strings.h>
#include <signal.h>
#include <errno.h>

// Scope a name-only process observation to its current directory. A process
// outside this prefix is never selected, and no argv/environment is inspected.
int w101_pid_in_prefix(int pid, const char *prefix) {
    char root[PATH_MAX], cwd[PATH_MAX];
    if (!realpath(prefix, root)) return -1;
    struct proc_bsdinfo bsd;
    if (proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &bsd, sizeof bsd) != sizeof bsd) return 0;
    if (bsd.pbi_uid != getuid()) return 0;
    struct proc_vnodepathinfo vnode;
    if (proc_pidinfo(pid, PROC_PIDVNODEPATHINFO, 0, &vnode, sizeof vnode) != sizeof vnode) {
        // A process that exited between ps and this call is already closed.
        if (kill(pid, 0) != 0 && errno == ESRCH) return 0;
        return -1;
    }
    if (!realpath(vnode.pvi_cdir.vip_path, cwd)) return -1;
    size_t length = strlen(root);
    return !strncmp(cwd, root, length) && (cwd[length] == '/' || cwd[length] == 0);
}
static void wipe(void *data, size_t length) { volatile uint8_t *p = data; while (length--) *p++ = 0; }
void w101_wipe(void *data, size_t length) { wipe(data, length); }
static pthread_once_t once = PTHREAD_ONCE_INIT;
static void initialize(void) { Twofish_initialise(); }
int w101_twofish_ofb(const uint8_t *key, const uint8_t *iv, const uint8_t *input,
                     size_t length, uint8_t *output) {
    pthread_once(&once, initialize);
    Twofish_key schedule;
    uint8_t material[32], feedback[16], next[16];
    memcpy(material, key, 32);
    memcpy(feedback, iv, 16);
    Twofish_prepare_key(material, 32, &schedule);
    for (size_t i = 0; i < length; i++) {
        if (i % 16 == 0) {
            Twofish_encrypt(&schedule, feedback, next);
            memcpy(feedback, next, 16);
        }
        output[i] = input[i] ^ feedback[i % 16];
    }
    wipe(material, sizeof material);
    wipe(feedback, sizeof feedback);
    wipe(next, sizeof next);
    wipe(&schedule, sizeof schedule);
    return 0;
}
uint32_t w101_crc(uint32_t previous, const uint8_t *input, size_t length) {
    // zlib complements both ends; KingsIsle starts at zero and never complements.
    return (uint32_t)crc32(previous ^ 0xffffffffU, input, (uInt)length) ^ 0xffffffffU;
}
