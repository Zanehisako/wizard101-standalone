#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <pthread.h>
#include <assert.h>
#include "WineThreadIdentity.h"
int main(void) {
    errno=EDOM; w101_thread_identity(1,1); assert(errno==EDOM);
    for(unsigned i=0;i<20000;i++) { errno=ERANGE; w101_thread_identity(2,0); assert(errno==ERANGE); }
    puts("PASS bounded thread identities and errno transparency");
    return 0;
}
