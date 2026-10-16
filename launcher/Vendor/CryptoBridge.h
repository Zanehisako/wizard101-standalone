#include <stddef.h>
#include "SteamBridge.h"
#include <stdint.h>
int w101_twofish_ofb(const uint8_t *key, const uint8_t *iv, const uint8_t *input,
                     size_t length, uint8_t *output);
uint32_t w101_crc(uint32_t previous, const uint8_t *input, size_t length);
void w101_wipe(void *data, size_t length);
#include <stdint.h>
int w101_gunzip_file(const char *input, const char *output, uint64_t expected,
                    int (*cancelled)(void *), void *context);
