#pragma once
#include "Sha256.h"
#include "Identity.h"
static BOOL w101_nt_verified_game(const WCHAR *key) {
 WCHAR *env=NtCurrentTeb()->Peb->ProcessParameters->Environment;
 BOOL enabled=FALSE;for(WCHAR *p=env;p && *p;p+=wcslen(p)+1)if(!wcscmp(p,key))enabled=TRUE;
 if(!enabled)return FALSE;
 WCHAR *name=NtCurrentTeb()->Peb->ProcessParameters->ImagePathName.Buffer;
 WCHAR *base=name;for(WCHAR *p=name;*p;p++)if(*p=='\\'||*p=='/')base=p+1;
#ifndef W101_TEST_HASH
 if(wcsicmp(base,L"WizardGraphicalClient.exe"))return FALSE;
#endif
 UNICODE_STRING path;OBJECT_ATTRIBUTES attr;IO_STATUS_BLOCK io;HANDLE file;BOOL ok=FALSE;
 if(RtlDosPathNameToNtPathName_U_WithStatus(name,&path,NULL,NULL))return FALSE;
 InitializeObjectAttributes(&attr,&path,OBJ_CASE_INSENSITIVE,NULL,NULL);
 NTSTATUS status=NtOpenFile(&file,FILE_READ_DATA|SYNCHRONIZE,&attr,&io,FILE_SHARE_READ,FILE_SYNCHRONOUS_IO_NONALERT|FILE_NON_DIRECTORY_FILE);
 RtlFreeUnicodeString(&path);if(status)return FALSE;
 w101_sha hash;w101_sha_init(&hash);unsigned char block[16384];LARGE_INTEGER offset;offset.QuadPart=0;
 while(!(status=NtReadFile(file,NULL,NULL,NULL,&io,block,sizeof(block),&offset,NULL)) && io.Information){w101_sha_update(&hash,block,io.Information);offset.QuadPart+=io.Information;}
 if(status==STATUS_END_OF_FILE || (!status&&!io.Information)){
  char hex[65];w101_sha_hex(&hash,hex);
#ifdef W101_TEST_HASH
  ok=!strcmp(hex,W101_TEST_HASH);
#else
  ok=!strcmp(hex,W101_GAME_SHA256);
#endif
 }
 NtClose(file);return ok;
}
