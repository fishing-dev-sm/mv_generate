"""Night-shift orchestrator: extend the plate pool until morning cutoff.

Phases (serial, one generator at a time):
  0. wait for the legacy rounds watcher (A->B->C chain) to exit
  1. rounds D (seed base 7200), E (8200), F (9200) — best effort until CUTOFF
  2. mop-up: top-up any candidate letter (a-f) with < 54 plates, time permitting
  3. rebuild review contact sheets (a-f grid)

Watchdog thread (every 10 min):
  - no new plate for 25 min while work should be running ->
    a) GET /system_stats dead      -> ssh restart ComfyUI (start_comfyui.sh),
                                      wait for 200, resume (scripts are resume-safe)
    b) stats OK but server log shows cuInit -> ssh sudo -n reboot the host
       (authorized), wait for it to come back, start ComfyUI, resume
    c) stats OK, no cuInit         -> kill the hung generator; the orchestrator
                                      relaunches the same round (resume-safe)
  - restart attempted but stats never recover, and log shows cuInit -> reboot path
  All actions logged to plates/rounds_watcher.log.

Never calls /interrupt. Does not touch {{H3_HOST}}.
"""
import argparse
import glob
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLATES = ROOT / 'plates'
GEN = ROOT / 'tools' / 'gen_plates.py'
SHEETS = ROOT / 'tools' / 'build_review_sheets.py'
API = os.environ.get('QWEN21_API', 'http://{{IMAGE_HOST}}:8189')
HOST = '{{SSH_USER}}@{{IMAGE_HOST}}'
EXPECTED = 54
CHECK_INTERVAL = 600       # 10 min
STALL_AFTER = 1500         # 25 min without a new plate
CUTOFF_HHMM = (10, 30)     # local time hard stop
SSH_OPTS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']

EXTRA_ROUNDS = [('d', 7200), ('e', 8200), ('f', 9200)]
ALL_ROUNDS = [('a', 4200), ('b', 5200), ('c', 6200)] + EXTRA_ROUNDS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler(PLATES / 'rounds_watcher.log', encoding='utf-8'),
              logging.StreamHandler()],
)
log = logging.getLogger('night_watcher')

stop_event = threading.Event()
state = {'phase': 'waiting', 'generator_running': False}


def cutoff_ts():
    now = time.localtime()
    return time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                        CUTOFF_HHMM[0], CUTOFF_HHMM[1], 0, 0, 0, -1))


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OverflowError):
        return False


def api_ok(timeout=10):
    try:
        with urllib.request.urlopen(f'{API}/system_stats', timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def ssh(cmd, timeout=60):
    log.info('ssh %s %s', HOST, cmd)
    r = subprocess.run(['ssh', *SSH_OPTS, HOST, cmd],
                       capture_output=True, text=True, timeout=timeout)
    out = (r.stdout + r.stderr).strip()
    log.info('ssh exit=%d out=%s', r.returncode, out[:400])
    return r.returncode, out


def server_log_has_cuinit():
    try:
        rc, out = ssh("tail -300 ~/comfyui/comfyui.log | grep -iE 'cuInit|CUDA error|Xid' | tail -5",
                      timeout=30)
        return bool(out.strip())
    except Exception as e:  # noqa: BLE001
        log.error('cuInit check failed: %s', e)
        return False


def newest_plate_mtime():
    files = glob.glob(str(PLATES / 's???-?.png')) + glob.glob(str(PLATES / 's???.png'))
    return max((os.path.getmtime(f) for f in files), default=0)


def generator_pids():
    r = subprocess.run(['pgrep', '-f', 'tools/gen_plates.py'],
                       capture_output=True, text=True)
    return [int(x) for x in r.stdout.split() if x.strip().isdigit()]


def kill_generator():
    pids = generator_pids()
    if not pids:
        return
    log.warning('watchdog: terminating hung generator pids=%s (resume-safe)', pids)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(8)
    for pid in pids:
        if pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def wait_api_up(deadline_s=900, poll=15):
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        if api_ok():
            return True
        time.sleep(poll)
    return False


def restart_comfyui():
    log.warning('watchdog: restarting ComfyUI on %s', HOST)
    ssh('nohup ~/comfyui/start_comfyui.sh >> ~/comfyui/comfyui.log 2>&1 &', timeout=30)
    if wait_api_up():
        log.warning('watchdog: ComfyUI back up after restart')
        return True
    return False


def reboot_host():
    log.warning('watchdog: cuInit-level failure; REBOOTING %s (authorized)', HOST)
    ssh('sudo -n reboot', timeout=30)
    time.sleep(60)  # let it go down
    if not wait_api_up(deadline_s=900, poll=20):
        # host may be back but ComfyUI not started yet
        pass
    if not api_ok():
        log.warning('watchdog: host rebooted, starting ComfyUI')
        restart_comfyui()


def recover():
    """Stall recovery ladder. Returns True if generation should resume."""
    log.warning('watchdog: STALL detected (no new plate for >%ds), phase=%s',
                STALL_AFTER, state['phase'])
    if not api_ok():
        log.warning('watchdog: /system_stats unresponsive')
        if restart_comfyui():
            kill_generator()  # old client is stuck on the dead job; relaunch resumes
            return
        log.error('watchdog: ComfyUI restart did not restore /system_stats')
        if server_log_has_cuinit():
            reboot_host()
            kill_generator()
        else:
            log.error('watchdog: no cuInit signature; giving up this cycle, will retry')
        return
    # server answers but no progress: poisoned CUDA context or hung client
    if server_log_has_cuinit():
        reboot_host()
        kill_generator()
        return
    log.warning('watchdog: server alive, no cuInit; assuming hung client/job')
    kill_generator()


def watchdog():
    while not stop_event.is_set():
        stop_event.wait(CHECK_INTERVAL)
        if stop_event.is_set():
            break
        if time.time() >= cutoff_ts():
            continue
        idle = time.time() - newest_plate_mtime()
        if idle < STALL_AFTER:
            continue
        if not state['generator_running'] and not generator_pids():
            log.info('watchdog: idle %ds but no generator expected right now', idle)
            continue
        try:
            recover()
        except Exception as e:  # noqa: BLE001 - watchdog must never die
            log.error('watchdog: recover() raised: %s', e)


def run(cmd):
    log.info('exec: %s', ' '.join(str(c) for c in cmd))
    state['generator_running'] = True
    try:
        r = subprocess.run(cmd, cwd=ROOT)
        log.info('exit=%d: %s', r.returncode, ' '.join(str(c) for c in cmd))
        return r.returncode
    finally:
        state['generator_running'] = False


def count_candidates(cand):
    return len(glob.glob(str(PLATES / f's???-{cand}.png')))


def run_round(cand, seed_base, max_relaunch=3):
    """Run one candidate round; relaunch on abnormal exit (watchdog kills, etc)."""
    for attempt in range(1, max_relaunch + 1):
        if time.time() >= cutoff_ts():
            log.warning('cutoff reached, not (re)launching round %s', cand.upper())
            return
        rc = run([sys.executable, str(GEN), '--candidate', cand, '--seed-base', str(seed_base)])
        log.info('round %s count: %d/%d (rc=%d, attempt=%d)',
                 cand.upper(), count_candidates(cand), EXPECTED, rc, attempt)
        if rc == 0:
            return
        log.warning('round %s exited abnormally (rc=%d); resume-safe relaunch', cand.upper(), rc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--old-watcher', type=int, default=575839,
                    help='PID of the legacy A/B/C rounds watcher')
    ap.add_argument('--skip-wait', action='store_true')
    a = ap.parse_args()

    log.info('night watcher started; cutoff=%s; old watcher pid=%d',
             time.strftime('%H:%M', time.localtime(cutoff_ts())), a.old_watcher)
    wd = threading.Thread(target=watchdog, daemon=True)
    wd.start()

    state['phase'] = 'wait-legacy-abc'
    if not a.skip_wait:
        while pid_alive(a.old_watcher):
            time.sleep(30)
    log.info('legacy A/B/C chain done; b=%d c=%d', count_candidates('b'), count_candidates('c'))

    # soft-stop generator at cutoff so the morning state is clean
    def cutoff_guard():
        while not stop_event.is_set():
            stop_event.wait(60)
            if not stop_event.is_set() and time.time() >= cutoff_ts():
                log.warning('cutoff %s reached; stopping generation',
                            time.strftime('%H:%M', time.localtime(cutoff_ts())))
                kill_generator()
                return
    threading.Thread(target=cutoff_guard, daemon=True).start()

    for cand, base in EXTRA_ROUNDS:
        state['phase'] = f'round-{cand}'
        log.info('=== round %s (seed base %d) start ===', cand.upper(), base)
        run_round(cand, base)

    state['phase'] = 'mop-up'
    for cand, base in ALL_ROUNDS:
        if time.time() >= cutoff_ts():
            break
        if count_candidates(cand) < EXPECTED:
            log.info('mop-up: candidate %s at %d/%d, topping up', cand, count_candidates(cand), EXPECTED)
            run_round(cand, base, max_relaunch=2)

    state['phase'] = 'sheets'
    log.info('=== building final review contact sheets (a-f) ===')
    run([sys.executable, str(SHEETS)])
    counts = {c: count_candidates(c) for c, _ in ALL_ROUNDS}
    log.info('NIGHT DONE. pool=%s total=%d', counts, sum(counts.values()))
    stop_event.set()


if __name__ == '__main__':
    main()
