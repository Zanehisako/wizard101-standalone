#include "CryptoBridge.h"
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <zlib.h>

// Bound decompressed output and verify gzip framing/trailer before returning.
// Caller still requires the manifest's full-file or bootstrap-header CRC.
int w101_gunzip_file(const char *input, const char *output, uint64_t expected,
                    int (*cancelled)(void *), void *context) {
    int source_fd = open(input, O_RDONLY | O_NOFOLLOW);
    if (source_fd < 0) return -2;
    gzFile source = gzdopen(source_fd, "rb");
    if (!source) { close(source_fd); return -2; }
    if (!gzdirect(source)) {
        int target_fd = open(output, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0600);
        if (target_fd < 0) { gzclose(source); return -3; }
        FILE *target = fdopen(target_fd, "wb");
        if (!target) { close(target_fd); gzclose(source); return -3; }
        unsigned char buffer[65536]; uint64_t written = 0; int status = 0;
        while (1) {
            if (cancelled && cancelled(context)) { status = -1; break; }
            int count = gzread(source, buffer, sizeof(buffer));
            if (count < 0) { status = -2; break; }
            if (!count) break;
            if ((uint64_t)count > expected - written) { status = -2; break; }
            if (fwrite(buffer, 1, count, target) != (size_t)count) { status = -3; break; }
            written += count;
        }
        int zstatus = Z_OK; gzerror(source, &zstatus);
        if (written != expected || (zstatus != Z_OK && zstatus != Z_STREAM_END)) status = -2;
        if (gzclose(source) != Z_OK && !status) status = -2;
        if (fclose(target) != 0 && !status) status = -3;
        return status;
    }
    gzclose(source); return -2; // do not accept zlib's transparent raw mode
}
