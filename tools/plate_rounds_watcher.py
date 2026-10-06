"""Orchestrate the 3-candidate plate pool.

Phase 1: wait for the legacy round-A process (plain s0NN.png output) to exit;
         if it died before BATCH DONE, re-run round A once to top up (resume-safe).
Phase 2: rename s0NN.png -> s0NN-a.png (never overwrites an existing -a file).
Phase 3: round B (seed base 5200) then round C (seed base 6200), serially.
Phase 4: build per-section 3-up review contact sheets.

Log: plates/rounds_watcher.log
"""
import argparse
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLATES = ROOT / 'plates'
GEN = ROOT / 'tools' / 'gen_plates.py'
SHEETS = ROOT / 'tools' / 'build_review_sheets.py'
GEN_LOG = PLATES / 'gen_plates.log'
LEGACY_RE = re.compile(r'^s\d{3}\.png$')
EXPECTED = 54  # 55 shots minus s005 (pure code card)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler(PLATES / 'rounds_watcher.log', encoding='utf-8'),
              logging.StreamHandler()],
)
log = logging.getLogger('rounds_watcher')


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OverflowError):
        return False


def run(cmd):
    log.info('exec: %s', ' '.join(cmd))
    r = subprocess.run(cmd, cwd=ROOT)
    log.info('exit=%d: %s', r.returncode, ' '.join(cmd))
    return r.returncode


def wait_round_a(aid, poll=30):
    while pid_alive(aid):
        time.sleep(poll)
    log.info('round-A process %d exited', aid)
    # top-up guard: if A died early (no BATCH DONE), resume it once
    if GEN_LOG.exists() and 'BATCH DONE' not in GEN_LOG.read_text(encoding='utf-8', errors='replace'):
        log.warning('no BATCH DONE in gen_plates.log; resuming round A to top up')
        run([sys.executable, str(GEN)])


def normalize_names():
    n = 0
    for p in sorted(PLATES.iterdir()):
        if LEGACY_RE.match(p.name):
            dst = p.with_name(p.stem + '-a.png')
            if dst.exists():
                log.warning('skip rename %s (target %s exists)', p.name, dst.name)
                continue
            p.rename(dst)
            n += 1
    log.info('renamed %d legacy plates to -a', n)


def count_candidates(cand):
    return sum(1 for p in PLATES.iterdir() if re.match(rf'^s\d{{3}}-{cand}\.png$', p.name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--aid', type=int, default=520077, help='PID of the running round-A process')
    ap.add_argument('--skip-wait', action='store_true', help='skip phase 1 (round A already done)')
    a = ap.parse_args()

    log.info('watcher started, round-A pid=%d', a.aid)
    if not a.skip_wait:
        wait_round_a(a.aid)
    normalize_names()
    log.info('candidate a count: %d/%d', count_candidates('a'), EXPECTED)

    for cand, seed_base in (('b', 5200), ('c', 6200)):
        log.info('=== round %s (seed base %d) start ===', cand.upper(), seed_base)
        run([sys.executable, str(GEN), '--candidate', cand, '--seed-base', str(seed_base)])
        log.info('candidate %s count: %d/%d', cand, count_candidates(cand), EXPECTED)

    log.info('=== building review contact sheets ===')
    run([sys.executable, str(SHEETS)])
    log.info('ALL ROUNDS DONE')


if __name__ == '__main__':
    main()
