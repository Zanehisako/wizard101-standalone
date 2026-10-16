"""Exercise the real dynamic Steam bridge against a disposable flat-API library."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOCK = r'''
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef struct { int user, callback; uint8_t *data; int size; } Callback;
typedef struct { uint32_t handle; int result, length; uint8_t bytes[2560]; } Ticket;
static int mode, delivered, frees, cancels, shutdowns, requests, accepted;
static Ticket ticket;
void test_mode(int value) { mode=value; delivered=frees=cancels=shutdowns=requests=accepted=0; }
int test_count(int which) { return which==0 ? frees : which==1 ? cancels : which==2 ? shutdowns : requests; }
int SteamAPI_InitFlat(char *error) { return mode==1 ? 1 : 0; }
void SteamAPI_Shutdown(void) { ++shutdowns; }
void SteamAPI_ManualDispatch_Init(void) {}
int SteamAPI_GetHSteamPipe(void) { return 1; }
void *SteamAPI_SteamUser_v023(void) { return (void *)1; }
void *SteamAPI_SteamApps_v008(void) { return (void *)1; }
void *SteamAPI_SteamUtils_v010(void) { return (void *)1; }
uint32_t SteamAPI_ISteamUtils_GetAppID(void *self) { return mode==4 ? 480 : 799960; }
bool SteamAPI_ISteamApps_BIsSubscribedApp(void *self, uint32_t app) { return app==799960 && mode!=3; }
bool SteamAPI_ISteamUser_BLoggedOn(void *self) { return mode!=2; }
uint64_t SteamAPI_ISteamUser_GetSteamID(void *self) { return 76561198000000001ULL; }
uint32_t SteamAPI_ISteamUser_GetAuthTicketForWebApi(void *self, const char *identity) {
    ++requests;
    if (mode==5 || (mode==12 && requests==1) || strcmp(identity,"Wizard101")) return 0;
    accepted=1; return 42;
}
void SteamAPI_ISteamUser_CancelAuthTicket(void *self, uint32_t handle) { if(handle==42) ++cancels; }
void SteamAPI_ManualDispatch_RunFrame(int pipe) {}
bool SteamAPI_ManualDispatch_GetNextCallback(int pipe, Callback *out) {
    if(!accepted || mode==6 || delivered++) return false;
    memset(&ticket,0,sizeof(ticket)); ticket.handle=mode==7 ? 99 : 42;
    ticket.result=mode==8 ? 2 : 1; ticket.length=mode==9 ? 2561 : 4;
    ticket.bytes[0]=0; ticket.bytes[1]=255; ticket.bytes[2]=128; ticket.bytes[3]=65;
    out->user=1; out->callback=mode==10 ? 101 : 168; out->data=(uint8_t *)&ticket;
    out->size=mode==11 ? 8 : sizeof(ticket); return true;
}
void SteamAPI_ManualDispatch_FreeLastCallback(int pipe) { ++frees; }
'''


@unittest.skipUnless(shutil.which('xcrun'), 'macOS C compiler required')
class SteamBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='w101-steam-bridge-')
        cls.root = Path(cls.temp.name)
        source = cls.root / 'mock.c'; source.write_text(MOCK)
        cls.mock_path = cls.root / 'mock.dylib'
        bridge_path = cls.root / 'bridge.dylib'
        for files, output in [([source], cls.mock_path), ([ROOT / 'launcher/Vendor/SteamBridge.c'], bridge_path)]:
            subprocess.run(['xcrun', 'clang', '-dynamiclib', '-O2', '-Wall', '-Wextra',
                            '-Wno-unused-parameter', *map(str, files), '-o', str(output)], check=True, capture_output=True)
        cls.mock = ctypes.CDLL(str(cls.mock_path)); cls.bridge = ctypes.CDLL(str(bridge_path))
        cls.bridge.w101_steam_open.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        cls.bridge.w101_steam_poll.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64),
                                             ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        cls.bridge.w101_steam_close.argtypes = [ctypes.c_void_p]

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.context = ctypes.c_void_p()
        self.mock.test_mode(0)

    def tearDown(self):
        if self.context.value: self.bridge.w101_steam_close(self.context)

    def open(self, mode=0):
        self.mock.test_mode(mode)
        return self.bridge.w101_steam_open(os.fsencode(self.mock_path), ctypes.byref(self.context))

    def poll(self, capacity=2560):
        user = ctypes.c_uint64(); length = ctypes.c_size_t(); data = ctypes.create_string_buffer(capacity)
        status = self.bridge.w101_steam_poll(self.context, ctypes.byref(user), data, capacity, ctypes.byref(length))
        return status, user.value, data.raw[:length.value]

    def test_binary_web_ticket_and_cleanup(self):
        self.assertEqual(self.open(), 0)
        self.assertEqual(self.poll(), (1, 76561198000000001, b'\0\xff\x80A'))
        self.assertEqual(self.mock.test_count(0), 1)
        self.bridge.w101_steam_close(self.context); self.context.value = None
        self.assertEqual(self.mock.test_count(1), 1)
        self.assertEqual(self.mock.test_count(2), 1)

    def test_availability_login_ownership_and_request_failures(self):
        for mode, expected in [(1,-2),(2,-3),(3,-4),(4,-2)]:
            with self.subTest(mode=mode):
                self.assertEqual(self.open(mode), expected)
                self.assertIsNone(self.context.value)
        self.assertEqual(self.open(), 0)  # failures release the bridge lock

    def test_connecting_client_is_pumped_without_rejecting_signin(self):
        self.assertEqual(self.open(12), 0)
        self.assertEqual(self.mock.test_count(3), 0)  # no request before pumping
        self.assertEqual(self.poll()[0], 0)  # running/logged-in client is not ready
        self.assertEqual(self.poll()[0], 0)
        self.assertEqual(self.mock.test_count(3), 1)  # throttle unaccepted requests
        time.sleep(1.02)
        self.assertEqual(self.poll(), (1, 76561198000000001, b'\0\xff\x80A'))
        self.assertEqual(self.mock.test_count(3), 2)
        self.poll()
        self.assertEqual(self.mock.test_count(3), 2)  # accepted tickets are not retried

    def test_unavailable_ticket_remains_cancellable_and_closes_cleanly(self):
        self.assertEqual(self.open(5), 0)
        self.assertEqual(self.poll()[0], 0)
        self.bridge.w101_steam_close(self.context); self.context.value = None
        self.assertEqual(self.mock.test_count(1), 0)  # no issued ticket to cancel
        self.assertEqual(self.mock.test_count(2), 1)
        self.assertEqual(self.open(), 0)

    def test_current_client_interface_versions(self):
        # The installed Mac Steam library exports Apps009 / Utils011 only.
        source = self.root / 'current.c'
        source.write_text(MOCK.replace('SteamApps_v008', 'SteamApps_v009').replace('SteamUtils_v010', 'SteamUtils_v011'))
        current = self.root / 'current.dylib'
        subprocess.run(['xcrun', 'clang', '-dynamiclib', str(source), '-o', str(current)],
                       check=True, capture_output=True)
        self.assertEqual(self.bridge.w101_steam_open(os.fsencode(current), ctypes.byref(self.context)), 0)
        self.assertEqual(self.poll(), (1, 76561198000000001, b'\0\xff\x80A'))

    def test_bad_or_incompatible_library(self):
        self.assertEqual(self.bridge.w101_steam_open(b'/missing/steam.dylib', ctypes.byref(self.context)), -1)
        empty = self.root / 'incompatible.dylib'
        subprocess.run(['xcrun', 'clang', '-dynamiclib', '-x', 'c', '-', '-o', str(empty)],
                       input=b'int unrelated(void) { return 0; }\n', check=True, capture_output=True)
        self.assertEqual(self.bridge.w101_steam_open(os.fsencode(empty), ctypes.byref(self.context)), -1)
        self.assertEqual(self.open(), 0)

    def test_pending_wrong_handle_and_unrelated_callbacks(self):
        for mode in [6,7,10]:
            with self.subTest(mode=mode):
                self.assertEqual(self.open(mode), 0)
                self.assertEqual(self.poll()[0], 0)
                self.assertEqual(self.mock.test_count(0), 0 if mode==6 else 1)
                self.bridge.w101_steam_close(self.context); self.context.value = None

    def test_rejected_oversized_truncated_and_undersized_buffer(self):
        for mode, capacity in [(8,2560),(9,2560),(11,2560),(0,2)]:
            with self.subTest(mode=mode):
                self.assertEqual(self.open(mode), 0)
                self.assertEqual(self.poll(capacity)[0], -5)
                self.assertEqual(self.mock.test_count(0), 1)
                self.bridge.w101_steam_close(self.context); self.context.value = None

    def test_signout_during_ticket_wait(self):
        self.assertEqual(self.open(), 0)
        self.mock.test_mode(2)
        self.assertEqual(self.poll()[0], -3)

    def test_only_one_request_can_change_steam_environment(self):
        self.assertEqual(self.open(), 0)
        another = ctypes.c_void_p()
        self.assertEqual(self.bridge.w101_steam_open(os.fsencode(self.mock_path), ctypes.byref(another)), -6)
        self.assertIsNone(another.value)
        self.assertEqual(self.poll()[0], 1)

    def test_environment_restored_after_success_and_failure(self):
        # Check libc's environment, since C setenv does not refresh os.environ.
        libc = ctypes.CDLL(None); libc.getenv.argtypes=[ctypes.c_char_p]; libc.getenv.restype=ctypes.c_char_p
        original = {key: os.environ.get(key) for key in ['SteamAppId', 'SteamGameId']}
        try:
            for key in original: os.environ[key] = 'prior-value'
            for mode in [0,1,2,5]:
                self.open(mode)
                if self.context.value:
                    self.assertEqual(libc.getenv(b'SteamAppId'), b'799960')
                    self.bridge.w101_steam_close(self.context); self.context.value=None
                for key in original: self.assertEqual(libc.getenv(key.encode()), b'prior-value')
        finally:
            for key, value in original.items():
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value


if __name__ == '__main__': unittest.main()
