/* Match the production call and tail-jump RVAs in a hash-bound test executable. */
.section .wad,"xr"
.org 0x320
.global W101WadUncompress
W101WadUncompress:
  subq $0xb8, %rsp
  movq %rdi, 0xa8(%rsp)
  movq %rdx, 0xa0(%rsp)
  movq %rcx, %rdi
  movl (%rdx), %eax
  movl %eax, 0x90(%rsp)
.org 0x34a,0x90
  leaq 0x90(%rsp), %rdx
  .byte 0x48,0x8b,0xcf /* exact production mov rcx,rdi encoding */
  call W101WadThunk
  movl 0x90(%rsp), %r10d
  movq 0xa0(%rsp), %rdx
  movl %r10d, (%rdx)
  movq 0xa8(%rsp), %rdi
  addq $0xb8, %rsp
  ret

.section .wthunk,"xr"
.org 0x328
W101WadThunk:
  jmp *__imp_uncompress(%rip)
