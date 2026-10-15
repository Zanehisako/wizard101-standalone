#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
typedef int NTSTATUS;
#include "WineLockNative.h"
int main(int argc,char **argv)
{
    struct w101_lock_params p={0};
    int size=argc>1 && !strcmp(argv[1],"size"), i;
    for(i=0;i<(size?50000:2);++i) {
        errno=EDOM;
        w101_lock_begin_native(&p);
        if(errno!=EDOM)return 1;
        if(p.begin) {p.begin-=1500;p.windows_tid=36;p.owner_tid=40;p.section=0x12345678;p.identified=1;p.caller_rva=4096;}
        w101_lock_end_native(&p);
        if(errno!=EDOM)return 2;
    }
    w101_lock_close();
    printf("PASS native contention writer, errno preserved, cap/finalization mode=%s\n",argc>1?argv[1]:"disabled");
    return 0;
}
