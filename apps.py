import git
import json
import time
import logging
import argparse
import requests
import traceback
from tqdm import tqdm
from pathlib import Path
from openpyxl import Workbook
from steam.client import SteamClient
from multiprocessing.pool import ThreadPool
from multiprocessing.dummy import Lock, Pool
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.utils.exceptions import IllegalCharacterError

lock = Lock()


class MyJson(dict):

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.load()

    def load(self):
        if not self.path.exists():
            self.dump()
            return
        with self.path.open() as f:
            self.update(json.load(f))

    def dump(self):
        with self.path.open('w') as f:
            json.dump(self, f)


class XiaoHeiHe:
    def __init__(self):
        self.app_info = MyJson('apps.json')
        self.pbar = tqdm(delay=1)
        self.pbar.delay = 0
        self.xiao_hei_he = MyJson('xiaoheihe.json')

    def __del__(self):
        self.pbar.delay = 1

    def get_game_detail(self, app_id):
        url = f'https://api.xiaoheihe.cn/game/web/get_game_detail/?appid={app_id}'
        while True:
            try:
                r = requests.get(url, headers={'User-Agent': ''}, timeout=5)
                if r.status_code != 200:
                    with lock:
                        self.pbar.clear()
                        logging.info(r.status_code)
                        logging.info(r.headers)
                        logging.info(r.text)
                        logging.info('Wait 300 seconds!')
                        time.sleep(300)
                    continue
                break
            except requests.exceptions.ConnectionError:
                pass
            except requests.exceptions.ReadTimeout:
                pass
        return r.json()

    def task(self, app_id, app_info):
        try:
            name = None
            type_ = None
            if 'common' in app_info:
                name = app_info['common']['name']
                type_ = app_info['common']['type'].replace('g', 'G')
            cname = None
            about = None
            score = None
            release_date = None
            tags = []
            if detail := self.get_game_detail(app_id):
                if 'name' in detail['result']:
                    cname = detail['result']['name']
                if 'genres' in detail['result']:
                    tags = detail['result']['genres']
                if 'about_the_game' in detail['result']:
                    about = detail['result']['about_the_game']
                if 'score' in detail['result']:
                    score = detail['result']['score']
                if 'release_date' in detail['result']:
                    release_date = detail['result']['release_date']
            info = {'type': type_, 'name': name, 'cname': cname, 'tags': tags,
                    'score': score, 'release_date': release_date}
            wait = 60
            with lock:
                self.xiao_hei_he[int(app_id)] = {**info, 'about': about}
                self.pbar.set_postfix(**{str(i): str(j) for i, j in info.items()})
                self.pbar.update()
                if self.pbar.n and self.pbar.n % 150 == 0:
                    self.pbar.clear()
                    logging.info(f'Wait {wait} seconds!')
                    time.sleep(wait)
        except:
            traceback.print_exc()

    def run(self):
        with Pool(32) as pool:
            pool: ThreadPool
            result_list = []
            self.pbar.total = 0
            for i, j in sorted(self.app_info.items(), key=lambda x: int(x[0])):
                if i in self.xiao_hei_he:
                    continue
                self.pbar.total += 1
                result_list.append(pool.apply_async(self.task, (i, j)))
            try:
                while pool._state == 'RUN':
                    if all([result.ready() for result in result_list]):
                        break
                    time.sleep(0.5)
                    with lock:
                        self.xiao_hei_he.dump()
            except KeyboardInterrupt:
                pass


def get_app_info(repo):
    app = MyJson('apps.json')
    steam = SteamClient()
    steam.anonymous_login()
    app_id_list = []
    for i in git.cmd.Git().ls_remote('--head', repo).split('\n'):
        sha, head = i.split()
        app_id = head.split('/')[-1]
        if app_id.isdecimal() and app_id not in app:
            app_id_list.append(int(app_id))
    logging.info('Waiting to get all app info!')
    app_info_dict = {}
    count = 0
    while app_id_list[count:count + 300]:
        fresh_resp = steam.get_product_info(app_id_list[count:count + 300], timeout=60)
        count += 300
        if fresh_resp:
            for app_id, info in fresh_resp['apps'].items():
                app_info_dict[int(app_id)] = info
            logging.info(f'Acquired {len(app_info_dict)} app info!')
    if app_info_dict:
        app.update(app_info_dict)
        app.dump()


def export_xlsx(save_path='.'):
    save_path = Path(save_path).absolute()
    workbook = Workbook()
    workbook.remove(workbook.worksheets[0])
    ws = workbook.create_sheet('游戏')
    ws.append(['app id', '游戏名', '中文名', '标签', '类型', '评分', '发行日期', '简介'])
    for i, info in sorted(MyJson('xiaoheihe.json').items(), key=lambda x: int(x[0])):
        try:
            ws.append([i, info['name'], info['cname'], ','.join(info['tags']), info['type'], info['score'],
                       info['release_date'], info['about']])
        except IllegalCharacterError:
            ws.append([i, info['name'], info['cname'], ','.join(info['tags']), info['type'], info['score'],
                       info['release_date'], ILLEGAL_CHARACTERS_RE.sub('', info['about'])])
    if save_path.is_dir():
        save_path = save_path / 'apps.xlsx'
    workbook.save(save_path)


parser = argparse.ArgumentParser()
parser.add_argument('-r', '--repo', default='https://github.com/wxy1343/ManifestAutoUpdate')
parser.add_argument('-o', '--output', default='.')
logging.basicConfig(format='%(asctime)s - %(pathname)s[line:%(lineno)d] - %(levelname)s: %(message)s',
                    level=logging.INFO)
if __name__ == '__main__':
    args = parser.parse_args()
    get_app_info(args.repo)
    XiaoHeiHe().run()
    export_xlsx(args.output)
