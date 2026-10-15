// Keep allocation-failure exceptions on the game's original return address.
// The fallback is a tail jump after undoing this frame. Windows unwind metadata
// covers the helper call and both epilogues. No GNU C++ exception boundary.
.text
.globl w101_scene_allocate
.def w101_scene_allocate; .scl 2; .type 32; .endef
.seh_proc w101_scene_allocate
w101_scene_allocate:
    subq $40, %rsp
    .seh_stackalloc 40
    .seh_endprologue
    movq %rcx, 32(%rsp)
    call w101_scene_try_allocate
    testq %rax, %rax
    jz .Lfallback
    addq $40, %rsp
    ret
.Lfallback:
    movq 32(%rsp), %rcx
    addq $40, %rsp
    jmp *w101_scene_original_alloc(%rip)
.seh_endproc
