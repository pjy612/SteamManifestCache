import os
import vdf
import time
import shutil
import winreg
import sqlite3
import argparse
import requests
import traceback
from pathlib import Path
from multiprocessing.pool import ThreadPool
from multiprocessing.dummy import Pool, Lock

lock = Lock()


def get(sha, path):
    url_list = [f'https://cdn.jsdelivr.net/gh/{repo}@{sha}/{path}',
                f'https://ghproxy.com/https://raw.githubusercontent.com/{repo}/{sha}/{path}']
    retry = 3
    while True:
        for url in url_list:
            try:
                r = requests.get(url)
                if r.status_code == 200:
                    return r.content
            except requests.exceptions.ConnectionError:
                print(f'获取失败: {path}')
                retry -= 1
                if not retry:
                    print(f'超过最大重试次数: {path}')
                    raise


def get_manifest(sha, path, steam_path: Path, app_id=None):
    try:
        if path.endswith('.manifest'):
            depot_cache_path = steam_path / 'depotcache'
            with lock:
                if not depot_cache_path.exists():
                    depot_cache_path.mkdir(exist_ok=True)
            save_path = depot_cache_path / path
            if save_path.exists():
                with lock:
                    print(f'已存在清单: {path}')
                return
            content = get(sha, path)
            with lock:
                print(f'清单下载成功: {path}')
            with save_path.open('wb') as f:
                f.write(content)
        elif path == 'config.vdf':
            content = get(sha, path)
            with lock:
                print(f'密钥下载成功: {path}')
            depots_config = vdf.loads(content.decode(encoding='utf-8'))
            if depotkey_merge(steam_path / 'config' / path, depots_config):
                print('合并config.vdf成功')
            if stool_add(
                    [(depot_id, '1', depots_config['depots'][depot_id]['DecryptionKey'])
                     for depot_id in depots_config['depots']]):
                print('导入steamtools成功')
    except KeyboardInterrupt:
        raise
    except:
        traceback.print_exc()
        raise
    return True


def depotkey_merge(config_path, depots_config):
    if not config_path.exists():
        with lock:
            print('config.vdf不存在')
        return
    with open(config_path, encoding='utf-8') as f:
        config = vdf.load(f)
    software = config['InstallConfigStore']['Software']
    valve = software.get('Valve') or software.get('valve')
    steam = valve.get('Steam') or valve.get('steam')
    if 'depots' not in steam:
        steam['depots'] = {}
    steam['depots'].update(depots_config['depots'])
    with open(config_path, 'w', encoding='utf-8') as f:
        vdf.dump(config, f, pretty=True)
    return True


def stool_add(depot_list):
    info_path = Path('~/AppData/Roaming/Stool/info.pak').expanduser()
    conn = sqlite3.connect(info_path)
    c = conn.cursor()
    for depot_id, type_, depot_key in depot_list:
        if depot_key:
            depot_key = f'"{depot_key}"'
        columns = dict(filter(lambda x: x[1], zip(['appid', 'type', 'DecryptionKey'], [depot_id, type_, depot_key])))
        sql = 'insert or replace into Appinfo ({}) values ({})'.format(','.join(columns), ','.join(columns.values()))
        c.execute(sql)
    conn.commit()
    return True


def get_steam_path():
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam')
    steam_path = Path(winreg.QueryValueEx(key, 'SteamPath')[0])
    return steam_path


def main(app_id):
    url = f'https://api.github.com/repos/{repo}/branches/{app_id}'
    r = requests.get(url)
    if 'commit' in r.json():
        sha = r.json()['commit']['sha']
        url = r.json()['commit']['commit']['tree']['url']
        r = requests.get(url)
        if 'tree' in r.json():
            stool_add([(app_id, '1', None)])
            result_list = []
            with Pool(32) as pool:
                pool: ThreadPool
                for i in r.json()['tree']:
                    result_list.append(pool.apply_async(get_manifest, (sha, i['path'], get_steam_path(), app_id)))
                try:
                    while pool._state == 'RUN':
                        if all([result.ready() for result in result_list]):
                            break
                        time.sleep(0.1)
                except KeyboardInterrupt:
                    with lock:
                        pool.terminate()
                    raise
            if all([result.successful() for result in result_list]):
                print(f'入库成功: {app_id}')
                print('重启steam生效')
                return True
    print(f'入库失败: {app_id}')
    return False


def app(app_path):
    app_path = Path(app_path)
    if not app_path.is_dir():
        raise NotADirectoryError(app_path)
    steam_path = get_steam_path()
    app_id_list = list(filter(str.isdecimal, app_path.name.strip().split('-')))
    if app_id_list:
        app_id = app_id_list[0]
        stool_add([(app_id, '1', None)])
    else:
        raise Exception('目录名称不是app_id')
    for file in app_path.iterdir():
        if file.is_file():
            if file.suffix == '.manifest':
                depot_cache_path = steam_path / 'depotcache'
                shutil.copy(file, depot_cache_path)
                print(f'导入清单成功: {file.name}')
            elif file.name == 'config.vdf':
                with file.open('r', encoding='utf-8') as f:
                    depots_config = vdf.loads(f.read())
                if depotkey_merge(steam_path / 'config' / 'config.vdf', depots_config):
                    print('合并config.vdf成功')
                if stool_add([(depot_id, '1',
                               depots_config['depots'][depot_id]['DecryptionKey']) for depot_id in
                              depots_config['depots']]):
                    print('导入steamtools成功')


parser = argparse.ArgumentParser()
parser.add_argument('-r', '--repo', default='wxy1343/ManifestAutoUpdate')
parser.add_argument('-a', '--app-id')
parser.add_argument('-p', '--app-path')
args = parser.parse_args()
repo = args.repo
if __name__ == '__main__':
    try:
        if args.app_path:
            app(args.app_path)
        else:
            main(args.app_id or input('appid: '))
    except KeyboardInterrupt:
        exit()
    except:
        traceback.print_exc()
    if not args.app_id and not args.app_path:
        os.system('pause')
