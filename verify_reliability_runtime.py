#!/usr/bin/env python3
"""Exercise recovery with two disposable, real Wine prefixes and sleeping fixtures."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def verify(app, seed, output):
    app, seed = Path(app).resolve(), Path(seed).resolve()
    executable = app / 'Contents/MacOS/Wizard101Native'
    runtime = app / 'Contents/Resources/Runtime'
    report = {'real_accounts_used': False, 'real_gameplay_verified': False,
              'component_sha256': {name: hashlib.sha256(file.read_bytes()).hexdigest() for name, file in
                  [('launcher', executable), ('wine', runtime / 'bin/wine'), ('wineserver', runtime / 'bin/wineserver')]}}
    with tempfile.TemporaryDirectory(prefix='w101-recovery-') as folder:
        root = Path(folder)
        source = root / 'fixture.c'
        source.write_text('#include <windows.h>\nint main(void) { Sleep(180000); return 0; }\n')
        fixture = root / 'WizardGraphicalClient.exe'
        subprocess.run(['x86_64-w64-mingw32-gcc', '-Os', str(source), '-o', str(fixture)], check=True)
        clients, environments = [], []
        try:
            for name in ('Selected', 'Other'):
                data = root / name; data.mkdir()
                prefix = data / 'Prefix'
                subprocess.run(['cp', '-cR', str(seed / 'Prefix'), str(prefix)], check=True)
                cwd = prefix / 'drive_c/RecoveryFixture'; cwd.mkdir()
                shutil.copy2(fixture, cwd / fixture.name)
                env = {k:v for k,v in os.environ.items() if not k.startswith(('WINE', 'CX_', 'CROSSOVER', 'DYLD_', 'VK_', 'DXVK_'))}
                env.update(W101_DATA_ROOT=str(data), W101_RUNTIME_ROOT=str(runtime), WINEPREFIX=str(prefix), WINEDEBUG='-all', WINEARCH='win64',
                           WINEDLLPATH=str(runtime / 'lib/wine'), WINEDLLOVERRIDES='winemenubuilder.exe=d', WINEMSYNC='1',
                           DYLD_FALLBACK_LIBRARY_PATH=str(runtime / 'lib') + ':/usr/lib')
                client = subprocess.Popen([str(runtime / 'bin/wine'), str(cwd / fixture.name)], cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                clients.append(client); environments.append(env)
            def status(index):
                return subprocess.check_output([str(executable), '--game-status'], env=environments[index], text=True).strip()
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and (status(0), status(1)) != ('game', 'game'):
                if any(c.poll() is not None for c in clients):
                    raise ValueError('A sleeping Wine fixture exited before recovery')
                time.sleep(0.2)
            if (status(0), status(1)) != ('game', 'game'):
                raise ValueError('Prefix-scoped detection did not recognize both real Wine fixtures')
            report['both_prefixes_detected'] = True
            lockfile = Path(environments[0]['W101_DATA_ROOT']) / 'State/operation.lock'
            lockfile.parent.mkdir(exist_ok=True)
            with lockfile.open('w') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                blocked = subprocess.run([str(executable), '--force-quit-game'], env=environments[0], text=True, capture_output=True, timeout=15)
                if blocked.returncode == 0 or status(0) != 'game':
                    raise ValueError('An active update lock did not prevent shutdown')
            report['update_lock_blocks_recovery'] = True
            start = time.monotonic()
            subprocess.run([str(executable), '--force-quit-game'], env=environments[0], check=True, text=True, capture_output=True, timeout=16)
            report['shutdown_seconds'] = round(time.monotonic() - start, 3)
            if status(0) != 'idle' or status(1) != 'game' or clients[1].poll() is not None:
                raise ValueError('Recovery did not isolate the selected Wine prefix')
            report.update(selected_prefix_closed=True, other_prefix_still_running=True)
            # A new process in the same prefix must be detected and recoverable.
            cwd = Path(environments[0]['WINEPREFIX']) / 'drive_c/RecoveryFixture'
            retry = subprocess.Popen([str(runtime / 'bin/wine'), str(cwd / fixture.name)], cwd=cwd, env=environments[0], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            clients.append(retry)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and status(0) != 'game': time.sleep(0.1)
            if status(0) != 'game': raise ValueError('Relaunch after forced shutdown was not detected')
            report['relaunch_after_recovery_detected'] = True
            subprocess.run([str(executable), '--force-quit-game'], env=environments[0], check=True, capture_output=True, timeout=16)
            if status(1) != 'game': raise ValueError('Repeated recovery affected the other prefix')
            report['repeat_recovery_isolated'] = True
        finally:
            for env in environments:
                subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env, capture_output=True, timeout=8)
            for child in clients:
                try: child.wait(timeout=8)
                except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=2)
    Path(output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--seed-data-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify(args.app, args.seed_data_root, args.output)
