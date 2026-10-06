"""Batch-generate the 55 storyboard plates via Qwen-Image 2.1 (ComfyUI-5090).

Usage:
    python3 tools/gen_plates.py                 # full batch, resume-safe
    python3 tools/gen_plates.py --only s001,s002,s018

- Resume: skips plates/<id>.png that already exist.
- Character shots -> edit mode against char_3view_1344x768.png (identity anchor).
- Non-character shots -> t2i at 1344x768.
- Serial discipline (manual section 10): checks /queue before every submit,
  never calls /interrupt, per-job timeout 15 min, changed-seed single retry.
- Log: plates/gen_plates.log ; persistent error list: plates/errors.json
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENT_DIR = ROOT / 'qwen21-api-templates'
sys.path.insert(0, str(CLIENT_DIR))
import client  # noqa: E402  (qwen21-api-templates/client.py)

PLATES = ROOT / 'plates'
MANIFEST = PLATES / 'manifest.json'
ERRORS = PLATES / 'errors.json'
LOG = PLATES / 'gen_plates.log'
CHAR_IMG = PLATES / 'char_3view_1344x768.png'

CANON = '年轻女性，黑色凌乱狼尾中长发（后颈发尾较长），苍白肤色，淡妆冷脸，黑色无袖上衣'
SIZE = (1344, 768)
JOB_TIMEOUT = 900  # 15 min per manual section 8/10
RETRY_SEED_OFFSET = 100000

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler(LOG, encoding='utf-8'), logging.StreamHandler()],
)
log = logging.getLogger('gen_plates')


def wait_for_idle(poll=10, server_grace=1800):
    """Manual section 10: never submit while the queue is non-empty.

    Server-unreachable tolerant: keeps waiting up to server_grace seconds so a
    ComfyUI restart (watchdog-driven) does not burn the whole round as errors.
    """
    server_down_since = None
    while True:
        try:
            q = client.post(f'{client.API}/queue', timeout=30)
        except Exception as e:  # noqa: BLE001 - server may be mid-restart
            server_down_since = server_down_since or time.time()
            if time.time() - server_down_since > server_grace:
                raise
            log.warning('server unreachable (%s), retrying in %ss', e, poll * 3)
            time.sleep(poll * 3)
            continue
        server_down_since = None
        if not q.get('queue_running') and not q.get('queue_pending'):
            return
        log.info('queue busy (running=%d pending=%d), waiting %ss',
                 len(q['queue_running']), len(q['queue_pending']), poll)
        time.sleep(poll)


def split_scene_style(prompt):
    """Split expanded prompt into (scene part, style suffix) at the style marker."""
    idx = prompt.find('，冷峻电影感')
    if idx == -1:
        return prompt, ''
    return prompt[:idx], prompt[idx + 1:]


def edit_instruction(prompt):
    scene, style = split_scene_style(prompt)
    scene = scene.replace(CANON, '主角')
    # lip-sync / coverline shots need an explicit frontal face, not a 3/4 turn
    scene = scene.replace('面对镜头', '面对镜头，正脸朝向观众，双眼看向镜头')
    return (
        f'这张图是一个动漫风格角色的三视图设定图：{CANON}。'
        f'图中还包含正视图、侧视图、背视图、面部特写小图和一圈文字标注。'
        f'以这个角色为唯一主角，把整张画面完全替换为以下写实电影场景：{scene}。'
        f'保持这个角色的发型、发色、脸型、肤色和黑色无袖上衣完全一致，写实电影质感，'
        f'原设定图上的三视图分格、特写小图和所有文字标注全部消失，不得残留。'
        f'{style}'
    )


def submit(entry, char_img_name, seed):
    if entry['has_character']:
        patch = {
            '11': {'value': edit_instruction(entry['prompt'])},
            '41': {'image': char_img_name},
            '44': {'noise_seed': seed},
            '45': {'noise_seed': seed},
        }
        return 'edit', client.queue('aio_edit.json', patch)
    patch = {
        '11': {'value': entry['prompt']},
        '32': {'width': SIZE[0], 'height': SIZE[1]},
        '34': {'noise_seed': seed},
        '35': {'noise_seed': seed},
    }
    return 't2i', client.queue('aio_t2i.json', patch)


def run_one(entry, char_img_name, seed_base=4200, candidate=''):
    sid = entry['id']
    stem = f'{sid}-{candidate}' if candidate else sid
    out = PLATES / f'{stem}.png'
    base_seed = seed_base + int(sid[1:])
    last_err = None
    for attempt, seed in enumerate((base_seed, base_seed + RETRY_SEED_OFFSET), 1):
        try:
            wait_for_idle()
            mode, pid = submit(entry, char_img_name, seed)
            log.info('%s submitted (%s, seed=%d, attempt=%d) pid=%s', stem, mode, seed, attempt, pid)
            t0 = time.time()
            outputs = client.wait(pid, timeout=JOB_TIMEOUT)
            saved = client.fetch(outputs)
            if not saved:
                raise RuntimeError(f'no image in outputs: {list(outputs)}')
            Path(saved[0]).rename(out)
            log.info('%s OK in %.0fs -> %s', stem, time.time() - t0, out)
            return True
        except Exception as e:  # noqa: BLE001 - log, maybe retry, never crash the batch
            last_err = f'attempt={attempt} seed={seed}: {e}'
            log.error('%s FAILED %s', stem, last_err)
            try:
                h = client.post(f'{client.API}/queue', timeout=30)
                log.info('post-failure queue state: running=%d pending=%d',
                         len(h.get('queue_running', [])), len(h.get('queue_pending', [])))
            except Exception as qe:  # noqa: BLE001
                log.error('queue check after failure also failed: %s', qe)
    errs = json.loads(ERRORS.read_text()) if ERRORS.exists() else {}
    errs[stem] = {'error': last_err, 'ts': time.strftime('%Y-%m-%d %H:%M:%S')}
    ERRORS.write_text(json.dumps(errs, ensure_ascii=False, indent=2))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='', help='comma-separated shot ids, e.g. s001,s002')
    ap.add_argument('--candidate', default='', help="candidate tag appended to filename, e.g. 'b' -> s001-b.png")
    ap.add_argument('--seed-base', type=int, default=4200, help='seed = seed_base + shot number')
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(',') if x.strip()}

    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    char_img_name = None
    done = skipped = failed = 0
    for entry in manifest:
        sid = entry['id']
        if only and sid not in only:
            continue
        if entry['prompt'] is None:
            log.info('%s skipped (no plate: %s)', sid, entry.get('note', ''))
            continue
        stem = f'{sid}-{a.candidate}' if a.candidate else sid
        if (PLATES / f'{stem}.png').exists():
            skipped += 1
            log.info('%s skipped (already exists)', stem)
            continue
        if entry['has_character'] and char_img_name is None:
            char_img_name = client.upload_image(CHAR_IMG)
            log.info('uploaded character reference as %s', char_img_name)
        if run_one(entry, char_img_name, seed_base=a.seed_base, candidate=a.candidate):
            done += 1
        else:
            failed += 1
    log.info('BATCH DONE candidate=%r: generated=%d skipped=%d failed=%d', a.candidate, done, skipped, failed)


if __name__ == '__main__':
    main()
